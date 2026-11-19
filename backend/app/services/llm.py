from __future__ import annotations

import re
from collections.abc import AsyncIterator
from functools import lru_cache

import jieba
from openai import AsyncOpenAI

from app.config import get_settings

_EVIDENCE_LINE = re.compile(r"^\[(\d+)\]\s*(.*)$")


class LLMClient:
    async def complete(self, messages: list[dict], temperature: float | None = None,
                       max_tokens: int | None = None) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    async def stream(self, messages: list[dict], temperature: float | None = None) -> AsyncIterator[str]:
        raise NotImplementedError


class OpenAICompatibleLLM(LLMClient):
    def __init__(self) -> None:
        s = get_settings()
        self.model = s.llm_model
        self.temperature = s.llm_temperature
        self.max_tokens = s.llm_max_tokens
        self.client = AsyncOpenAI(
            base_url=s.llm_base_url,
            api_key=s.llm_api_key or "EMPTY",
            timeout=s.llm_timeout,
            max_retries=1,
        )

    async def complete(self, messages: list[dict], temperature: float | None = None,
                       max_tokens: int | None = None) -> str:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature if temperature is None else temperature,
            max_tokens=max_tokens or self.max_tokens,
        )
        return resp.choices[0].message.content or ""

    async def stream(self, messages: list[dict], temperature: float | None = None) -> AsyncIterator[str]:
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature if temperature is None else temperature,
            max_tokens=self.max_tokens,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content


class MockLLM(LLMClient):
    """Extractive fake LLM so the full pipeline can be demoed/tested without a model server."""

    def _pick(self, messages: list[dict]) -> tuple[str, list[tuple[int, str]]]:
        user = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")
        question = ""
        for line in user.split("\n"):
            if line.startswith("问题："):
                question = line[3:].strip()
                break
        evidence: list[tuple[int, str]] = []
        for line in user.split("\n"):
            m = _EVIDENCE_LINE.match(line.strip())
            if m:
                evidence.append((int(m.group(1)), m.group(2).strip()))
        return question or user[:80], evidence

    REFUSAL = "根据现有知识库资料，无法确定该问题的答案。"

    def _answer(self, messages: list[dict]) -> str:
        question, evidence = self._pick(messages)
        if not evidence:
            return self.REFUSAL
        q_terms = {t for t in jieba.lcut(question) if len(t) > 1}
        # Grounding gate: if the retrieved text shares almost nothing with the question,
        # answer "cannot determine" instead of stitching random sentences together.
        overlap = [sum(1 for t in q_terms if t in text) for _, text in evidence]
        if max(overlap, default=0) < 2:
            return self.REFUSAL

        scored: list[tuple[float, int, str]] = []
        for idx, text in evidence:
            sentences = [s.strip() for s in re.split(r"(?<=[。！？!?；;])", text) if s.strip()]
            base = sum(1 for t in q_terms if t in text)
            for pos, sentence in enumerate(sentences):
                s_score = base * 0.5 + sum(1 for t in q_terms if t in sentence)
                if sentence.endswith(("？", "?")) and pos + 1 < len(sentences):
                    # FAQ layout: the answer is the sentence right after the question.
                    s_score += 1.5
                scored.append((s_score, idx, sentence, text, pos))
        scored.sort(key=lambda x: x[0], reverse=True)

        picked: list[str] = []
        used: set[str] = set()
        for _, idx, sentence, text, pos in scored:
            if sentence in picked:
                continue
            if idx in used and len(picked) >= 2:
                continue
            picked.append(f"{sentence}[{idx}]")
            used.add(idx)
            if sentence.endswith(("？", "?")):
                nxt = [s.strip() for s in re.split(r"(?<=[。！？!?；;])", text) if s.strip()]
                if pos + 1 < len(nxt) and nxt[pos + 1] not in picked:
                    picked.append(f"{nxt[pos + 1]}[{idx}]")
            if len(picked) >= 4:
                break
        if not picked:
            return self.REFUSAL
        return "根据知识库资料：" + "".join(picked)

    async def complete(self, messages: list[dict], temperature: float | None = None,
                       max_tokens: int | None = None) -> str:
        return self._answer(messages)

    async def stream(self, messages: list[dict], temperature: float | None = None) -> AsyncIterator[str]:
        text = self._answer(messages)
        step = 6
        for i in range(0, len(text), step):
            yield text[i : i + step]


@lru_cache
def get_llm() -> LLMClient:
    if get_settings().mock_llm:
        return MockLLM()
    return OpenAICompatibleLLM()