from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import jieba
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Chunk, Document
from app.services.embedding import Embedder, get_embedder
from app.services.rerank import Reranker
from app.services.vectorstore import get_vector_store
from app.services.vectorstore.base import VectorStore

RRF_K = 60
_STOP = set("的了和是在有为与及或等这那其中以及对于关于我们你们他们它其什么怎么为什么如何")


@dataclass
class Evidence:
    chunk_id: str
    doc_id: str
    doc_name: str
    text: str
    score: float
    source: str = "vector"
    page: int = 0
    section: str = ""
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "doc_name": self.doc_name,
            "text": self.text,
            "score": round(self.score, 4),
            "source": self.source,
            "page": self.page,
            "section": self.section,
        }


@dataclass
class RetrievalOutcome:
    items: list[Evidence]
    stats: dict
    degraded: list[str] = field(default_factory=list)


def build_embed_text(doc_name: str, section: str, text: str) -> str:
    prefix = " / ".join(x for x in (doc_name, section) if x)
    return f"{prefix}\n{text}" if prefix else text


def extract_terms(query: str, limit: int = 6) -> list[str]:
    terms: list[str] = []
    for tok in jieba.lcut(query):
        tok = tok.strip()
        if len(tok) < 2 or tok in _STOP:
            continue
        if tok not in terms:
            terms.append(tok)
    for m in re.findall(r"[A-Za-z]{2,}[A-Za-z0-9\-_]*|\d+[A-Za-z\-]+\d*", query):
        if m.lower() not in {t.lower() for t in terms}:
            terms.append(m)
    return terms[:limit]


class Retriever:
    def __init__(
        self,
        session: AsyncSession,
        store: VectorStore | None = None,
        embedder: Embedder | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self.session = session
        self.store = store or get_vector_store()
        self.embedder = embedder or get_embedder()
        self.settings = get_settings()
        self.reranker = reranker or (Reranker() if self.settings.rerank_enabled else None)

    async def search(
        self,
        query: str,
        tenant_id: str,
        kb_ids: list[str],
        top_k: int | None = None,
    ) -> RetrievalOutcome:
        t0 = time.perf_counter()
        degrade: list[str] = []
        stats: dict = {"query": query, "kb_ids": kb_ids}
        if not kb_ids:
            return RetrievalOutcome(items=[], stats=stats)

        vector_hits = []
        try:
            vec = (await self.embedder.embed([query]))[0]
            vector_hits = await self.store.search(
                tenant_id, kb_ids, vec, top_k=self.settings.retrieval_top_k
            )
        except Exception as exc:  # noqa: BLE001
            degrade.append(f"vector_error:{type(exc).__name__}")
        stats["vector_hits"] = len(vector_hits)

        keyword_hits: list[tuple[str, float]] = []
        try:
            keyword_hits = await self._keyword_search(query, tenant_id, kb_ids)
        except Exception as exc:  # noqa: BLE001
            degrade.append(f"keyword_error:{type(exc).__name__}")
        stats["keyword_hits"] = len(keyword_hits)

        fused: dict[str, float] = {}
        sources: dict[str, set[str]] = {}
        for rank, hit in enumerate(vector_hits):
            fused[hit.chunk_id] = fused.get(hit.chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
            sources.setdefault(hit.chunk_id, set()).add("vector")
        for rank, (chunk_id, _) in enumerate(keyword_hits):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank + 1)
            sources.setdefault(chunk_id, set()).add("keyword")
        stats["fused"] = len(fused)
        if not fused:
            stats["latency_ms"] = int((time.perf_counter() - t0) * 1000)
            return RetrievalOutcome(items=[], stats=stats, degraded=degrade)

        candidate_ids = sorted(fused, key=lambda cid: fused[cid], reverse=True)[: max(40, self.settings.rerank_top_k)]
        rows = await self._fetch_rows(candidate_ids)
        texts = [build_embed_text(name, ch.section, ch.text) for ch, name in rows]

        final_scores = {ch.id: fused[ch.id] for ch, _ in rows}
        if self.reranker is not None and texts:
            try:
                rerank_scores = await self.reranker.rerank(query, texts)
                if rerank_scores:
                    lo, hi = min(rerank_scores), max(rerank_scores)
                    span = (hi - lo) or 1.0
                    for (ch, _), rs in zip(rows, rerank_scores):
                        norm = (rs - lo) / span
                        final_scores[ch.id] = 0.5 * final_scores.get(ch.id, 0.0) + 0.5 * norm
                    stats["reranked"] = True
            except Exception as exc:  # noqa: BLE001
                degrade.append(f"rerank_error:{type(exc).__name__}")

        rows.sort(key=lambda pair: final_scores.get(pair[0].id, 0.0), reverse=True)
        limit = top_k or self.settings.rerank_top_k
        selected = rows[:limit]

        items: list[Evidence] = []
        for ch, doc_name in selected:
            src = "+".join(sorted(sources.get(ch.id, {"vector"})))
            items.append(
                Evidence(
                    chunk_id=ch.id,
                    doc_id=ch.doc_id,
                    doc_name=doc_name,
                    text=ch.text,
                    score=float(final_scores.get(ch.id, 0.0)),
                    source=src,
                    page=ch.page,
                    section=ch.section,
                    meta={"type": ch.type, **(ch.meta or {})},
                )
            )
        stats["returned"] = len(items)
        stats["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        return RetrievalOutcome(items=items, stats=stats, degraded=degrade)

    async def _keyword_search(self, query: str, tenant_id: str, kb_ids: list[str]) -> list[tuple[str, float]]:
        terms = extract_terms(query)
        if not terms:
            return []
        like = or_(*[Chunk.text.ilike(f"%{t}%") for t in terms], *[Chunk.section.ilike(f"%{t}%") for t in terms])
        stmt = (
            select(Chunk.id, Chunk.text, Chunk.section)
            .where(
                Chunk.tenant_id == tenant_id,
                Chunk.kb_id.in_(kb_ids),
                like,
            )
            .limit(200)
        )
        result = await self.session.execute(stmt)
        scored: list[tuple[str, float]] = []
        for chunk_id, text, section in result.all():
            blob = f"{section}\n{text}"
            hits = sum(1 for t in terms if t in blob)
            if hits:
                scored.append((chunk_id, hits / len(terms)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[: self.settings.retrieval_bm25_k]

    async def _fetch_rows(self, ids: list[str]) -> list[tuple[Chunk, str]]:
        if not ids:
            return []
        stmt = (
            select(Chunk, Document.name)
            .join(Document, Chunk.doc_id == Document.id)
            .where(Chunk.id.in_(ids))
        )
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]