from __future__ import annotations

import hashlib
import logging

from sqlalchemy import delete

from app.config import get_settings
from app.db.models import Chunk, Document
from app.db.session import session_factory
from app.services.chunking import chunk_blocks
from app.services.embedding import get_embedder
from app.services.parsing import parse_bytes
from app.services.storage import get_storage
from app.services.vectorstore import get_vector_store
from app.services.vectorstore.base import ChunkVector

logger = logging.getLogger(__name__)


def _chunk_id(doc_id: str, seq: int, chunk_hash: str) -> str:
    return hashlib.sha256(f"{doc_id}:{seq}:{chunk_hash}".encode()).hexdigest()[:32]


async def _update(session, doc: Document, *, status: str | None = None, stage: str | None = None,
                  progress: int | None = None, error: str | None = None, **extra) -> None:
    if status is not None:
        doc.status = status
    if stage is not None:
        doc.stage = stage
    if progress is not None:
        doc.progress = progress
    if error is not None:
        doc.error = error[:2000]
    for key, value in extra.items():
        setattr(doc, key, value)
    await session.commit()


async def ingest_document(doc_id: str) -> None:
    storage = get_storage()
    embedder = get_embedder()
    store = get_vector_store()

    async with session_factory() as session:
        doc = await session.get(Document, doc_id)
        if doc is None:
            logger.warning("ingest: document %s not found", doc_id)
            return
        try:
            await _update(session, doc, status="processing", stage="downloading", progress=5, error="")
            data = await storage.get(doc.object_key)

            await _update(session, doc, stage="parsing", progress=20)
            parsed = parse_bytes(doc.filename, data)
            if not parsed.blocks:
                raise ValueError("未能从文档中提取到文本（可能是扫描件，需要 OCR）")

            await _update(session, doc, stage="chunking", progress=35)
            settings = get_settings()
            drafts = chunk_blocks(
                parsed.blocks,
                chunk_size=settings.chunk_size,
                overlap=settings.chunk_overlap,
            )

            await store.delete_by_doc(doc.id)
            await session.execute(delete(Chunk).where(Chunk.doc_id == doc.id))

            rows: list[Chunk] = []
            for draft in drafts:
                rows.append(
                    Chunk(
                        id=_chunk_id(doc.id, draft.seq, draft.chunk_hash),
                        tenant_id=doc.tenant_id,
                        kb_id=doc.kb_id,
                        doc_id=doc.id,
                        seq=draft.seq,
                        type=draft.type,
                        text=draft.text,
                        page=draft.page,
                        section=draft.section,
                        chunk_hash=draft.chunk_hash,
                        meta={"doc_name": doc.name},
                    )
                )
            session.add_all(rows)
            await session.commit()

            await _update(session, doc, stage="embedding", progress=55)
            batch = 32
            for start in range(0, len(rows), batch):
                part = rows[start : start + batch]
                vectors = await embedder.embed([f"{r.section}\n{r.text}" for r in part])
                await store.upsert(
                    [
                        ChunkVector(
                            chunk_id=r.id,
                            tenant_id=r.tenant_id,
                            kb_id=r.kb_id,
                            doc_id=r.doc_id,
                            vector=v,
                        )
                        for r, v in zip(part, vectors)
                    ]
                )
                pct = 55 + int(40 * min(1.0, (start + len(part)) / max(1, len(rows))))
                await _update(session, doc, progress=pct)

            await _update(
                session,
                doc,
                status="ready",
                stage="done",
                progress=100,
                error="",
                page_count=parsed.page_count,
                chunk_count=len(rows),
                meta={**(doc.meta or {}), "parse": parsed.meta},
            )
        except Exception as exc:
            logger.exception("ingest failed for %s", doc_id)
            await session.rollback()
            doc = await session.get(Document, doc_id)
            if doc is not None:
                await _update(session, doc, status="failed", stage="failed", error=f"{type(exc).__name__}: {exc}")