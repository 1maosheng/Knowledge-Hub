from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings
from app.services.embedding import get_embedder
from app.services.llm import get_llm
from app.services.vectorstore import get_vector_store

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    s = get_settings()
    vector_ok = False
    try:
        vector_ok = await get_vector_store().health()
    except Exception:  # noqa: BLE001
        vector_ok = False
    return {
        "status": "ok",
        "llm": {"mode": "mock" if s.mock_llm else "vllm", "model": None if s.mock_llm else s.llm_model},
        "embedding": {
            "mode": "mock" if s.mock_embedding else "remote",
            "model": None if s.mock_embedding else s.embedding_model,
            "dim": s.embedding_dim,
        },
        "vector_backend": s.vector_backend,
        "vector_ok": vector_ok,
        "rerank": s.rerank_enabled,
        "embedder": type(get_embedder()).__name__,
        "llm_client": type(get_llm()).__name__,
    }