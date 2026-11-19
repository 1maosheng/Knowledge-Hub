from __future__ import annotations

import logging
from typing import ClassVar

from arq.connections import RedisSettings

from app.config import get_settings
from app.services.ingestion import ingest_document

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


async def ingest_task(ctx: dict, doc_id: str) -> str:
    await ingest_document(doc_id)
    return doc_id


class WorkerSettings:
    functions: ClassVar[list] = [ingest_task]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = 2
    job_timeout = 1800
    keep_result = 3600