from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration comes from env vars / .env (12-factor)."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "lms-kgbuild"
    environment: str = "dev"
    api_prefix: str = "/api"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- infra ---
    database_url: str = "postgresql+asyncpg://lms:lms@localhost:5432/lms"
    redis_url: str = "redis://localhost:6379/0"

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "lms-docs"
    minio_secure: bool = False

    # "minio" | "local"
    storage_backend: str = "minio"
    local_storage_dir: str = "./.data/objects"

    # --- knowledge graph (P1) ---
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "lmsneo4j"

    # --- vector store ---
    vector_backend: str = "memory"  # memory | milvus
    milvus_uri: str = "http://localhost:19530"
    milvus_token: str = ""
    milvus_collection: str = "lms_chunks_v1"

    # --- model gateways (OpenAI-compatible, e.g. vLLM) ---
    llm_base_url: str = ""
    llm_api_key: str = "EMPTY"
    llm_model: str = "qwen2.5-32b-instruct"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 2048
    llm_timeout: float = 120.0
    llm_force_mock: bool = False

    embedding_base_url: str = ""
    embedding_api_key: str = "EMPTY"
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024
    embedding_batch_size: int = 32
    embedding_timeout: float = 60.0

    rerank_base_url: str = ""
    rerank_api_key: str = "EMPTY"
    rerank_model: str = "bge-reranker-v2-m3"
    rerank_timeout: float = 30.0

    # --- ingestion ---
    chunk_size: int = 600
    chunk_overlap: int = 80
    max_extract_chars: int = 2_000_000
    upload_max_mb: int = 100

    # --- retrieval ---
    retrieval_top_k: int = 20
    retrieval_bm25_k: int = 30
    rerank_top_k: int = 8
    max_context_chars: int = 12_000
    max_retrieval_rounds: int = 2
    sufficiency_threshold: float = 0.35

    task_backend: str = "inline"  # inline | arq
    default_tenant: str = "default"

    @property
    def mock_llm(self) -> bool:
        return self.llm_force_mock or not self.llm_base_url.strip()

    @property
    def mock_embedding(self) -> bool:
        return not self.embedding_base_url.strip()

    @property
    def rerank_enabled(self) -> bool:
        return bool(self.rerank_base_url.strip())

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()