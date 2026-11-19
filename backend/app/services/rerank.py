from __future__ import annotations

import httpx

from app.config import get_settings


class Reranker:
    """Cross-encoder rerank via an OpenAI-compatible /rerank endpoint (vLLM / TEI)."""

    def __init__(self) -> None:
        s = get_settings()
        self.base_url = s.rerank_base_url.rstrip("/")
        self.api_key = s.rerank_api_key or "EMPTY"
        self.model = s.rerank_model
        self.timeout = s.rerank_timeout

    async def rerank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        url = f"{self.base_url}/rerank"
        payload = {"model": self.model, "query": query, "documents": documents}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        results = data.get("results") or data.get("data") or []
        scores = [0.0] * len(documents)
        for item in results:
            idx = item.get("index")
            score = item.get("relevance_score", item.get("score"))
            if idx is None or score is None:
                continue
            if 0 <= int(idx) < len(scores):
                scores[int(idx)] = float(score)
        return scores