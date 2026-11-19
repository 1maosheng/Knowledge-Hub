from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache

import jieba
from openai import AsyncOpenAI

from app.config import get_settings

_CJK = re.compile(r"[\u4e00-\u9fff]")
_WORD = re.compile(r"[a-zA-Z0-9_]+")
_STOP = set("的了和是在有为与及或等这那其中以及对于关于我们你们他们它其")


class Embedder:
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover - interface
        raise NotImplementedError


class OpenAIEmbedder(Embedder):
    def __init__(self, base_url: str, api_key: str, model: str, dim: int, batch: int = 32, timeout: float = 60.0):
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key or "EMPTY", timeout=timeout, max_retries=1)
        self.model = model
        self.dim = dim
        self.batch = batch

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch):
            chunk = texts[i : i + self.batch]
            resp = await self.client.embeddings.create(model=self.model, input=chunk)
            vectors = [item.embedding for item in sorted(resp.data, key=lambda d: d.index)]
            for v in vectors:
                if len(v) != self.dim:
                    raise ValueError(
                        f"embedding dim mismatch: model returned {len(v)}, EMBEDDING_DIM={self.dim}"
                    )
            out.extend(vectors)
        return out


class MockEmbedder(Embedder):
    """Lexical hashing embedder: deterministic, offline, good enough to demo retrieval."""

    def __init__(self, dim: int = 1024):
        self.dim = dim
        jieba.setLogLevel(60)

    @staticmethod
    def _features(text: str) -> list[tuple[str, float]]:
        feats: list[tuple[str, float]] = []
        text = text.lower()
        for tok in jieba.lcut(text):
            tok = tok.strip()
            if not tok or tok in _STOP:
                continue
            if _WORD.fullmatch(tok) or _CJK.search(tok):
                if len(tok) > 1:
                    feats.append((tok, 3.0))
                else:
                    feats.append((tok, 1.0))
        compact = re.sub(r"\s+", "", text)
        for i in range(len(compact) - 1):
            feats.append((compact[i : i + 2], 1.0))
        return feats

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for feat, weight in self._features(text):
            h = hashlib.md5(feat.encode("utf-8")).digest()
            idx = int.from_bytes(h[:4], "little") % self.dim
            sign = 1.0 if h[4] % 2 == 0 else -1.0
            vec[idx] += sign * weight
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    if s.mock_embedding:
        return MockEmbedder(s.embedding_dim)
    return OpenAIEmbedder(
        base_url=s.embedding_base_url,
        api_key=s.embedding_api_key,
        model=s.embedding_model,
        dim=s.embedding_dim,
        batch=s.embedding_batch_size,
        timeout=s.embedding_timeout,
    )