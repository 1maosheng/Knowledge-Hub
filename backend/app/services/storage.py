from __future__ import annotations

import io
from pathlib import Path
from typing import Protocol

import anyio
from minio import Minio

from app.config import get_settings


class ObjectStorage(Protocol):
    async def ensure_ready(self) -> None: ...
    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


class MinioStorage:
    def __init__(self) -> None:
        s = get_settings()
        self.bucket = s.minio_bucket
        self.client = Minio(
            s.minio_endpoint,
            access_key=s.minio_access_key,
            secret_key=s.minio_secret_key,
            secure=s.minio_secure,
        )
        self._ready = False

    async def ensure_ready(self) -> None:
        if self._ready:
            return

        def _ensure() -> None:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)

        await anyio.to_thread.run_sync(_ensure)
        self._ready = True

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        await self.ensure_ready()
        await anyio.to_thread.run_sync(
            lambda: self.client.put_object(
                self.bucket, key, io.BytesIO(data), length=len(data), content_type=content_type
            )
        )

    async def get(self, key: str) -> bytes:
        await self.ensure_ready()

        def _get() -> bytes:
            resp = self.client.get_object(self.bucket, key)
            try:
                return resp.read()
            finally:
                resp.close()
                resp.release_conn()

        return await anyio.to_thread.run_sync(_get)

    async def delete(self, key: str) -> None:
        await self.ensure_ready()
        await anyio.to_thread.run_sync(lambda: self.client.remove_object(self.bucket, key))


class LocalStorage:
    """Filesystem fallback so the slice can run without MinIO."""

    def __init__(self) -> None:
        s = get_settings()
        self.root = Path(s.local_storage_dir).resolve()

    async def ensure_ready(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root)):
            raise ValueError("invalid object key")
        return p

    async def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        await self.ensure_ready()
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        await anyio.to_thread.run_sync(p.write_bytes, data)

    async def get(self, key: str) -> bytes:
        return await anyio.to_thread.run_sync(self._path(key).read_bytes)

    async def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            await anyio.to_thread.run_sync(p.unlink)


def get_storage() -> ObjectStorage:
    s = get_settings()
    if s.storage_backend == "local":
        return LocalStorage()
    return MinioStorage()