from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol


@dataclass
class ChunkVector:
    chunk_id: str
    tenant_id: str
    kb_id: str
    doc_id: str
    vector: list[float]


@dataclass
class VectorHit:
    chunk_id: str
    score: float


class VectorStore(Protocol):
    async def upsert(self, items: list[ChunkVector]) -> None: ...
    async def delete_by_doc(self, doc_id: str) -> None: ...
    async def search(self, tenant_id: str, kb_ids: list[str], vector: list[float],
                     top_k: int) -> list[VectorHit]: ...
    async def health(self) -> bool: ...


class MemoryVectorStore:
    """In-process store: used for tests and for running the slice without Milvus."""

    def __init__(self) -> None:
        self._data: dict[str, ChunkVector] = {}

    async def upsert(self, items: list[ChunkVector]) -> None:
        for item in items:
            self._data[item.chunk_id] = item

    async def delete_by_doc(self, doc_id: str) -> None:
        for key in [k for k, v in self._data.items() if v.doc_id == doc_id]:
            self._data.pop(key, None)

    async def search(self, tenant_id: str, kb_ids: list[str], vector: list[float],
                     top_k: int) -> list[VectorHit]:
        hits: list[VectorHit] = []
        for item in self._data.values():
            if item.tenant_id != tenant_id or item.kb_id not in kb_ids:
                continue
            sim = _cosine(vector, item.vector)
            hits.append(VectorHit(chunk_id=item.chunk_id, score=sim))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    async def health(self) -> bool:
        return True

    def clear(self) -> None:
        self._data.clear()


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)