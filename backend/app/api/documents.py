from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from sqlalchemy import delete, select

from app.api.deps import SessionDep, TenantDep
from app.api.schemas import DocumentOut
from app.config import get_settings
from app.db.models import Chunk, Document, KnowledgeBase
from app.services.storage import get_storage
from app.services.tasks import enqueue_ingest
from app.services.vectorstore import get_vector_store

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])

ALLOWED_EXT = {".pdf", ".docx", ".md", ".markdown", ".txt", ".xlsx"}
MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _to_out(doc: Document) -> DocumentOut:
    return DocumentOut(
        id=doc.id,
        kb_id=doc.kb_id,
        name=doc.name,
        filename=doc.filename,
        size=doc.size,
        status=doc.status,
        stage=doc.stage,
        progress=doc.progress,
        error=doc.error,
        page_count=doc.page_count,
        chunk_count=doc.chunk_count,
        meta=doc.meta or {},
        created_at=doc.created_at,
    )


async def _get_kb(session, kb_id: str, tenant: str) -> KnowledgeBase:
    kb = await session.get(KnowledgeBase, kb_id)
    if kb is None or kb.tenant_id != tenant:
        raise HTTPException(404, "knowledge base not found")
    return kb


@router.post("/kbs/{kb_id}/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    kb_id: str,
    background: BackgroundTasks,
    tenant: TenantDep,
    session: SessionDep,
    file: UploadFile = File(...),  # noqa: B008
) -> DocumentOut:
    settings = get_settings()
    kb = await _get_kb(session, kb_id, tenant)

    filename = file.filename or "upload.bin"
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXT:
        raise HTTPException(400, f"unsupported file type: {suffix or 'unknown'}")
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > settings.upload_max_mb * 1024 * 1024:
        raise HTTPException(413, f"file too large (> {settings.upload_max_mb} MB)")

    digest = hashlib.sha256(data).hexdigest()
    exists = (
        await session.execute(
            select(Document).where(Document.kb_id == kb_id, Document.sha256 == digest, Document.status != "failed")
        )
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(409, f"duplicate document: {exists.id}")

    doc = Document(
        tenant_id=tenant,
        kb_id=kb.id,
        name=Path(filename).stem,
        filename=filename,
        mime=MIME.get(suffix, file.content_type or "application/octet-stream"),
        size=len(data),
        object_key="",
        sha256=digest,
        status="pending",
        stage="queued",
    )
    session.add(doc)
    await session.flush()

    safe_name = Path(filename).name
    doc.object_key = f"{tenant}/{kb.id}/{doc.id}/{safe_name}"
    await session.commit()
    await session.refresh(doc)

    storage = get_storage()
    try:
        await storage.put(doc.object_key, data, doc.mime)
    except Exception as exc:
        doc.status = "failed"
        doc.stage = "upload"
        doc.error = f"storage error: {exc}"[:2000]
        await session.commit()
        raise HTTPException(503, "object storage unavailable") from exc

    await enqueue_ingest(doc.id, background)
    return _to_out(doc)


@router.get("/kbs/{kb_id}/documents", response_model=list[DocumentOut])
async def list_documents(kb_id: str, tenant: TenantDep, session: SessionDep) -> list[DocumentOut]:
    await _get_kb(session, kb_id, tenant)
    rows = (
        await session.execute(
            select(Document).where(Document.kb_id == kb_id).order_by(Document.created_at.desc())
        )
    ).scalars().all()
    return [_to_out(d) for d in rows]


@router.get("/documents/{doc_id}", response_model=DocumentOut)
async def get_document(doc_id: str, tenant: TenantDep, session: SessionDep) -> DocumentOut:
    doc = await session.get(Document, doc_id)
    if doc is None or doc.tenant_id != tenant:
        raise HTTPException(404, "document not found")
    return _to_out(doc)


@router.post("/documents/{doc_id}/reingest", response_model=DocumentOut, status_code=202)
async def reingest_document(
    doc_id: str, background: BackgroundTasks, tenant: TenantDep, session: SessionDep
) -> DocumentOut:
    doc = await session.get(Document, doc_id)
    if doc is None or doc.tenant_id != tenant:
        raise HTTPException(404, "document not found")
    doc.status = "pending"
    doc.stage = "queued"
    doc.progress = 0
    doc.error = ""
    await session.commit()
    await enqueue_ingest(doc.id, background)
    return _to_out(doc)


@router.delete("/documents/{doc_id}", status_code=204)
async def delete_document(doc_id: str, tenant: TenantDep, session: SessionDep) -> None:
    doc = await session.get(Document, doc_id)
    if doc is None or doc.tenant_id != tenant:
        raise HTTPException(404, "document not found")
    object_key = doc.object_key
    try:
        await get_vector_store().delete_by_doc(doc.id)
    finally:
        await session.execute(delete(Chunk).where(Chunk.doc_id == doc.id))
        await session.delete(doc)
        await session.commit()
    try:
        await get_storage().delete(object_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to delete object %s: %s", object_key, exc)