from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.config import get_settings
from app.db.session import dispose_db, init_db
from app.services.storage import get_storage
from app.services.vectorstore import get_vector_store

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await init_db()
    try:
        await get_storage().ensure_ready()
    except Exception as exc:  # noqa: BLE001
        logger.warning("object storage not ready: %s", exc)
    try:
        ok = await get_vector_store().health()
        logger.info("vector backend=%s healthy=%s", settings.vector_backend, ok)
    except Exception as exc:  # noqa: BLE001
        logger.warning("vector backend not ready: %s", exc)
    logger.info(
        "startup: llm=%s embedding=%s",
        "mock" if settings.mock_llm else settings.llm_model,
        "mock" if settings.mock_embedding else settings.embedding_model,
    )
    yield
    await dispose_db()


app = FastAPI(title="LMS Knowledge Graph RAG", version="0.1.0", lifespan=lifespan)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/api/version")
async def version() -> dict:
    return {"name": settings.app_name, "version": "0.1.0", "environment": settings.environment}


if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> FileResponse:
        target = WEB_DIST / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(WEB_DIST / "index.html")
else:

    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return {"name": settings.app_name, "docs": "/docs", "health": f"{settings.api_prefix}/health"}