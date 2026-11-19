from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import SessionDep, TenantDep
from app.api.schemas import SearchRequest
from app.db.models import KnowledgeBase
from app.services.retrieval import Retriever

router = APIRouter(tags=["search"])


@router.post("/search")
async def search(body: SearchRequest, tenant: TenantDep, session: SessionDep) -> dict:
    from sqlalchemy import select

    kb_ids = list(dict.fromkeys(body.kb_ids))
    rows = (
        await session.execute(
            select(KnowledgeBase.id).where(
                KnowledgeBase.id.in_(kb_ids), KnowledgeBase.tenant_id == tenant
            )
        )
    ).scalars().all()
    if len(set(rows)) != len(kb_ids):
        raise HTTPException(404, "knowledge base not found")

    outcome = await Retriever(session).search(body.query, tenant, kb_ids, top_k=body.top_k)
    return {
        "query": body.query,
        "hits": [item.to_dict() for item in outcome.items],
        "stats": outcome.stats,
        "degraded": outcome.degraded,
    }