from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.services.vectorstore.base import ChunkVector, MemoryVectorStore, VectorHit, VectorStore

__all__ = ["ChunkVector", "MemoryVectorStore", "VectorHit", "VectorStore", "get_vector_store", "reset_vector_store"]


@lru_cache
def get_vector_store() -> VectorStore:
    if get_settings().vector_backend == "milvus":
        from app.services.vectorstore.milvus_store import MilvusVectorStore

        return MilvusVectorStore()
    return MemoryVectorStore()


def reset_vector_store() -> None:
    get_vector_store.cache_clear()