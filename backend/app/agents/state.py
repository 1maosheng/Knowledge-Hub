from __future__ import annotations

from operator import add
from typing import Annotated, TypedDict


class QAState(TypedDict, total=False):
    # input
    question: str
    tenant_id: str
    kb_ids: list[str]
    history: list[dict]
    # routing
    route: dict
    queries: list[str]
    round: int
    sufficient: bool
    # retrieval
    evidence: Annotated[list[dict], add]
    retrieval_stats: Annotated[list[dict], add]
    degraded: Annotated[list[str], add]
    # generation
    draft: str
    citations: list[dict]
    verify: dict