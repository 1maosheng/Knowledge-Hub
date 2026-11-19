from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.api.deps import SessionDep, TenantDep
from app.api.schemas import KBCreate, KBOut
from app.db.models import Document, KnowledgeBase
from app.services.storage import get_storage
from app.services.vectorstore import get_vector_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/kbs", tags=["kbs"])


async def _doc_count(session, kb_ids: list[str]) -> dict[str, int]:
    from sqlalchemy import func, select

    if not kb_ids:
        return {}
    stmt = (
        select(Document.kb_id, func.count(Document.id))
        .where(Document.kb_id.in_(kb_ids))
        .group_by(Document.kb_id)
    )
    rows = await session.execute(stmt)
    return {kb_id: count for kb_id, count in rows.all()}


def _to_out(kb: KnowledgeBase, doc_count: int = 0) -> KBOut:
    return KBOut(
        id=kb.id,
        name=kb.name,
        description=kb.description,
        doc_count=doc_count,
        created_at=kb.created_at,
    )


@router.post("", response_model=KBOut, status_code=201)
async def create_kb(body: KBCreate, tenant: TenantDep, session: SessionDep) -> KBOut:
    kb = KnowledgeBase(tenant_id=tenant, name=body.name.strip(), description=body.description.strip())
    session.add(kb)
    await session.commit()
    await session.refresh(kb)
    return _to_out(kb)


@router.get("", response_model=list[KBOut])
async def list_kbs(tenant: TenantDep, session: SessionDep) -> list[KBOut]:
    from sqlalchemy import select

    rows = (await session.execute(select(KnowledgeBase).where(KnowledgeBase.tenant_id == tenant))).scalars().all()
    counts = await _doc_count(session, [kb.id for kb in rows])
    return [_to_out(kb, counts.get(kb.id, 0)) for kb in rows]


@router.get("/{kb_id}", response_model=KBOut)
async def get_kb(kb_id: str, tenant: TenantDep, session: SessionDep) -> KBOut:
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None or kb.tenant_id != tenant:
        raise HTTPException(404, "knowledge base not found")
    counts = await _doc_count(session, [kb.id])
    return _to_out(kb, counts.get(kb.id, 0))


@router.delete("/{kb_id}", status_code=204)
async def delete_kb(kb_id: str, tenant: TenantDep, session: SessionDep) -> None:
    from sqlalchemy import select

    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None or kb.tenant_id != tenant:
        raise HTTPException(404, "knowledge base not found")

    storage = get_storage()
    store = get_vector_store()
    docs = (await session.execute(select(Document).where(Document.kb_id == kb_id))).scalars().all()
    for doc in docs:
        try:
            await store.delete_by_doc(doc.id)
            await storage.delete(doc.object_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to clean up document %s: %s", doc.id, exc)
    await session.delete(kb)
    await session.commit()