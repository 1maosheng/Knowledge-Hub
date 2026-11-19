from __future__ import annotations

import re
import threading

import anyio
from pymilvus import DataType, MilvusClient

from app.config import get_settings
from app.services.vectorstore.base import ChunkVector, VectorHit

_SAFE = re.compile(r"[^a-zA-Z0-9_\-]")


def _safe(value: str) -> str:
    return _SAFE.sub("", value)


class MilvusVectorStore:
    def __init__(self) -> None:
        s = get_settings()
        self.uri = s.milvus_uri
        self.token = s.milvus_token
        self.collection = s.milvus_collection
        self.dim = s.embedding_dim
        self._client: MilvusClient | None = None
        self._lock = threading.Lock()
        self._ready = False

    def _sync_client(self) -> MilvusClient:
        if self._client is None:
            self._client = MilvusClient(uri=self.uri, token=self.token or None)
        if not self._ready:
            if not self._client.has_collection(self.collection):
                schema = self._client.create_schema(auto_id=False, enable_dynamic_field=False)
                schema.add_field("chunk_id", DataType.VARCHAR, is_primary=True, max_length=64)
                schema.add_field("tenant_id", DataType.VARCHAR, max_length=64)
                schema.add_field("kb_id", DataType.VARCHAR, max_length=32)
                schema.add_field("doc_id", DataType.VARCHAR, max_length=32)
                schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=self.dim)
                index_params = self._client.prepare_index_params()
                index_params.add_index(
                    field_name="embedding",
                    index_type="HNSW",
                    metric_type="COSINE",
                    params={"M": 16, "efConstruction": 200},
                )
                self._client.create_collection(
                    collection_name=self.collection,
                    schema=schema,
                    index_params=index_params,
                )
            self._client.load_collection(self.collection)
            self._ready = True
        return self._client

    async def upsert(self, items: list[ChunkVector]) -> None:
        if not items:
            return
        rows = [
            {
                "chunk_id": it.chunk_id,
                "tenant_id": it.tenant_id,
                "kb_id": it.kb_id,
                "doc_id": it.doc_id,
                "embedding": it.vector,
            }
            for it in items
        ]

        def _run() -> None:
            with self._lock:
                self._sync_client().upsert(collection_name=self.collection, data=rows)

        await anyio.to_thread.run_sync(_run)

    async def delete_by_doc(self, doc_id: str) -> None:
        expr = f'doc_id == "{_safe(doc_id)}"'

        def _run() -> None:
            with self._lock:
                client = self._sync_client()
                client.delete(collection_name=self.collection, filter=expr)

        await anyio.to_thread.run_sync(_run)

    async def search(self, tenant_id: str, kb_ids: list[str], vector: list[float],
                     top_k: int) -> list[VectorHit]:
        if not kb_ids:
            return []
        kb_list = ", ".join(f'"{_safe(k)}"' for k in kb_ids)
        expr = f'tenant_id == "{_safe(tenant_id)}" and kb_id in [{kb_list}]'

        def _run() -> list[VectorHit]:
            with self._lock:
                client = self._sync_client()
                res = client.search(
                    collection_name=self.collection,
                    data=[vector],
                    filter=expr,
                    limit=max(1, top_k),
                    output_fields=["chunk_id"],
                    search_params={"metric_type": "COSINE", "params": {"ef": 64}},
                )
            hits: list[VectorHit] = []
            for row in res[0]:
                hits.append(VectorHit(chunk_id=row["entity"]["chunk_id"], score=float(row["distance"])))
            return hits

        return await anyio.to_thread.run_sync(_run)

    async def health(self) -> bool:
        def _run() -> bool:
            with self._lock:
                return bool(self._sync_client().list_collections())

        try:
            return await anyio.to_thread.run_sync(_run)
        except Exception:  # noqa: BLE001
            return False