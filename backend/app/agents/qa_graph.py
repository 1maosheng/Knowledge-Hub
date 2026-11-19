from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, StateGraph

from app.agents.citations import truncate_evidence, verify_answer
from app.agents.prompts import build_answer_messages
from app.agents.state import QAState
from app.config import get_settings
from app.services.llm import get_llm
from app.services.retrieval import Retriever, extract_terms

logger = logging.getLogger(__name__)

_GRAPH_HINTS = ("关系", "关联", "影响", "对比", "为什么", "链路", "上下游", "分别", "各自", "依赖")
_SQL_HINTS = ("统计", "占比", "趋势", "排名", "总计", "汇总")


def _rules_route(question: str) -> dict:
    need_graph = any(k in question for k in _GRAPH_HINTS)
    need_sql = any(k in question for k in _SQL_HINTS)
    simple = len(question) <= 20 and not (need_graph or need_sql)
    return {
        "need_graph": need_graph,
        "need_sql": need_sql,
        "complexity": "simple" if simple else "complex",
    }


def _dedupe(evidence: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for ev in evidence:
        cur = best.get(ev["chunk_id"])
        if cur is None or ev.get("score", 0) > cur.get("score", 0):
            best[ev["chunk_id"]] = ev
    return sorted(best.values(), key=lambda e: e.get("score", 0), reverse=True)


async def _emit(config: RunnableConfig, event: str, data: Any) -> None:
    fn = (config.get("configurable") or {}).get("emit")
    if fn is not None:
        await fn({"event": event, "data": data})


def _session(config: RunnableConfig):
    session = (config.get("configurable") or {}).get("session")
    if session is None:
        raise RuntimeError("graph config missing database session")
    return session


async def router_node(state: QAState, config: RunnableConfig) -> dict:
    route = _rules_route(state["question"])
    await _emit(config, "route", route)
    return {"route": route, "queries": [state["question"]], "round": 0, "evidence": [], "degraded": []}


async def retrieve_node(state: QAState, config: RunnableConfig) -> dict:
    session = _session(config)
    retriever = Retriever(session)
    queries = state.get("queries") or [state["question"]]
    evidence: list[dict] = []
    stats: list[dict] = []
    degraded: list[str] = []
    for q in queries[:3]:
        outcome = await retriever.search(q, state["tenant_id"], state["kb_ids"])
        evidence.extend(ev.to_dict() for ev in outcome.items)
        stats.append(outcome.stats)
        degraded.extend(outcome.degraded)
    merged = _dedupe(evidence)
    await _emit(
        config,
        "retrieve",
        {
            "round": state.get("round", 0) + 1,
            "queries": queries,
            "hits": len(merged),
            "stats": stats,
            "degraded": degraded,
            "preview": [{"doc_name": e["doc_name"], "page": e["page"], "score": e["score"]} for e in merged[:5]],
        },
    )
    return {"evidence": merged, "retrieval_stats": stats, "degraded": degraded}


def _coverage(question: str, evidence: list[dict]) -> float:
    terms = extract_terms(question, limit=8)
    if not terms:
        return 1.0
    blob = " ".join(e["text"] for e in evidence[:3])
    return sum(1 for t in terms if t in blob) / len(terms)


async def _expand_queries(question: str) -> list[str]:
    llm = get_llm()
    prompt = (
        "把用户问题改写成 2 个不同的检索查询（同义改写/拆分），只输出 JSON 字符串数组。\n"
        f"问题：{question}"
    )
    try:
        text = await llm.complete([{"role": "user", "content": prompt}], temperature=0.3, max_tokens=200)
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            arr = json.loads(match.group(0))
            queries = [str(x).strip() for x in arr if str(x).strip()][:2]
            if queries:
                return queries
    except Exception as exc:  # noqa: BLE001
        logger.warning("query expansion failed, falling back: %s", exc)
    return [question]


async def assess_node(state: QAState, config: RunnableConfig) -> dict:
    settings = get_settings()
    evidence = _dedupe(state.get("evidence", []))
    round_no = state.get("round", 0) + 1
    coverage = _coverage(state["question"], evidence)
    sufficient = bool(evidence) and coverage >= settings.sufficiency_threshold
    await _emit(
        config,
        "assess",
        {"round": round_no, "hits": len(evidence), "coverage": round(coverage, 2), "sufficient": sufficient},
    )
    if sufficient or round_no >= settings.max_retrieval_rounds:
        return {"sufficient": sufficient, "round": round_no}
    queries = await _expand_queries(state["question"])
    return {"sufficient": False, "round": round_no, "queries": queries}


async def answer_node(state: QAState, config: RunnableConfig) -> dict:
    settings = get_settings()
    llm = get_llm()
    evidence = truncate_evidence(_dedupe(state.get("evidence", [])), settings.max_context_chars)
    if not evidence:
        answer = "根据现有知识库资料，无法确定该问题的答案。请补充相关文档后再试。"
        await _emit(config, "token", answer)
        return {"draft": answer, "citations": []}

    messages = build_answer_messages(state["question"], evidence, state.get("history"))
    buf: list[str] = []
    try:
        async for token in llm.stream(messages):
            buf.append(token)
            await _emit(config, "token", token)
    except Exception as exc:
        logger.exception("llm stream failed")
        if not buf:
            buf.append("回答生成失败，请稍后重试。")
            await _emit(config, "token", buf[0])
        await _emit(config, "degrade", f"llm_error:{type(exc).__name__}")
    return {"draft": "".join(buf)}


async def verify_node(state: QAState, config: RunnableConfig) -> dict:
    evidence = _dedupe(state.get("evidence", []))
    report = verify_answer(state.get("draft", ""), evidence)
    citations = report.pop("citations", [])
    await _emit(config, "verify", report)
    if citations:
        await _emit(config, "citations", citations)
    return {"verify": report, "citations": citations}


def _route_after_retrieve(state: QAState) -> str:
    if state.get("sufficient"):
        return "answer"
    if state.get("round", 0) >= get_settings().max_retrieval_rounds:
        return "answer"
    return "retry"


@lru_cache
def get_qa_graph():
    builder = StateGraph(QAState)
    builder.add_node("router", router_node)
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("assess", assess_node)
    builder.add_node("answer", answer_node)
    builder.add_node("verify", verify_node)

    builder.set_entry_point("router")
    builder.add_edge("router", "retrieve")
    builder.add_edge("retrieve", "assess")
    builder.add_conditional_edges("assess", _route_after_retrieve, {"retry": "retrieve", "answer": "answer"})
    builder.add_edge("answer", "verify")
    builder.add_edge("verify", END)
    return builder.compile()