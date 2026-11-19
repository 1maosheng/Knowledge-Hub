from __future__ import annotations

from app.agents.qa_graph import _route_after_retrieve
from app.agents.state import QAState
from app.config import get_settings


def test_state_declares_sufficient_channel():
    # LangGraph silently drops writes to undeclared keys; this guards the
    # ``assess -> answer`` edge against regressing into an extra retry round.
    assert "sufficient" in QAState.__annotations__


def test_route_prefers_sufficient():
    assert _route_after_retrieve({"sufficient": True, "round": 1}) == "answer"


def test_route_stops_at_max_rounds():
    settings = get_settings()
    assert (
        _route_after_retrieve({"sufficient": False, "round": settings.max_retrieval_rounds})
        == "answer"
    )


def test_route_retries_when_not_sufficient():
    assert _route_after_retrieve({"sufficient": False, "round": 0}) == "retry"