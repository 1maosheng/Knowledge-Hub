from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.services.ingestion import ingest_document

logger = logging.getLogger(__name__)


async def enqueue_ingest(doc_id: str, background=None) -> str:
    """Queue ingestion: arq when configured, otherwise inline background task."""
    settings = get_settings()
    if settings.task_backend == "arq":
        try:
            from arq import create_pool
            from arq.connections import RedisSettings

            pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
            await pool.enqueue_job("ingest_task", doc_id)
            await pool.close()
            return "queued"
        except Exception as exc:  # noqa: BLE001
            logger.warning("arq enqueue failed, falling back to inline: %s", exc)

    if background is not None:
        background.add_task(ingest_document, doc_id)
    else:
        asyncio.create_task(ingest_document(doc_id))
    return "inline"