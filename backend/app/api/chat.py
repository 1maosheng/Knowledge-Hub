from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.agents.qa_graph import get_qa_graph
from app.api.deps import SessionDep, TenantDep
from app.api.schemas import ChatRequest, ConversationOut, MessageOut
from app.config import get_settings
from app.db.models import Conversation, KnowledgeBase, Message
from app.db.session import session_factory

router = APIRouter(tags=["chat"])


def _sse(event: str, data) -> str:
    return f"data: {json.dumps({'event': event, 'data': data}, ensure_ascii=False)}\n\n"


async def _validate_kbs(session, tenant: str, kb_ids: list[str]) -> list[str]:
    ids = list(dict.fromkeys(kb_ids))
    found = (
        await session.execute(
            select(KnowledgeBase.id).where(
                KnowledgeBase.id.in_(ids), KnowledgeBase.tenant_id == tenant
            )
        )
    ).scalars().all()
    if len(set(found)) != len(ids):
        raise HTTPException(404, "knowledge base not found")
    return ids


async def _prepare(session, tenant: str, req: ChatRequest) -> tuple[Conversation, list[dict]]:
    kb_ids = await _validate_kbs(session, tenant, req.kb_ids)

    conversation: Conversation | None = None
    if req.conversation_id:
        conversation = await session.get(Conversation, req.conversation_id)
        if conversation is None or conversation.tenant_id != tenant:
            raise HTTPException(404, "conversation not found")
    if conversation is None:
        conversation = Conversation(
            tenant_id=tenant,
            kb_id=kb_ids[0] if len(kb_ids) == 1 else "",
            title=req.question.strip()[:60],
        )
        session.add(conversation)
        await session.flush()

    history_rows = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
            .limit(10)
        )
    ).scalars().all()
    history = [{"role": m.role, "content": m.content} for m in reversed(history_rows)]

    session.add(
        Message(conversation_id=conversation.id, role="user", content=req.question.strip(), meta={"kb_ids": kb_ids})
    )
    await session.commit()
    await session.refresh(conversation)
    return conversation, history


async def _run_graph(tenant: str, kb_ids: list[str], question: str, history: list[dict], emit) -> dict:
    state = {
        "question": question,
        "tenant_id": tenant,
        "kb_ids": kb_ids,
        "history": history,
    }
    async with session_factory() as session:
        return await get_qa_graph().ainvoke(
            state, config={"configurable": {"session": session, "emit": emit}, "recursion_limit": 50}
        )


async def _persist_answer(conversation_id: str, answer: str, citations: list[dict], verify: dict) -> str:
    async with session_factory() as session:
        msg = Message(
            conversation_id=conversation_id,
            role="assistant",
            content=answer,
            citations=citations,
            meta={"verify": verify},
        )
        session.add(msg)
        await session.commit()
        await session.refresh(msg)
        return msg.id


def _done_payload(conversation_id: str, message_id: str, final: dict) -> dict:
    s = get_settings()
    return {
        "conversation_id": conversation_id,
        "message_id": message_id,
        "answer": final.get("draft", ""),
        "citations": final.get("citations", []),
        "verify": final.get("verify", {}),
        "route": final.get("route", {}),
        "rounds": max(1, final.get("round", 0)),
        "degraded": final.get("degraded", []),
        "stats": final.get("retrieval_stats", []),
        "mock": s.mock_llm,
    }


@router.post("/chat")
async def chat(req: ChatRequest, tenant: TenantDep, session: SessionDep):
    conversation, history = await _prepare(session, tenant, req)
    kb_ids = req.kb_ids

    if not req.stream:
        tokens: list[str] = []

        async def emit_ns(ev: dict) -> None:
            if ev["event"] == "token":
                tokens.append(ev["data"])

        final = await _run_graph(tenant, kb_ids, req.question, history, emit_ns)
        message_id = await _persist_answer(
            conversation.id, final.get("draft", ""), final.get("citations", []), final.get("verify", {})
        )
        return _done_payload(conversation.id, message_id, final)

    async def event_stream() -> AsyncIterator[str]:
        queue: asyncio.Queue = asyncio.Queue()

        async def emit(ev: dict) -> None:
            queue.put_nowait(ev)

        async def run() -> None:
            try:
                final = await _run_graph(tenant, kb_ids, req.question, history, emit)
                queue.put_nowait({"event": "__final__", "data": final})
            except Exception as exc:  # noqa: BLE001
                queue.put_nowait({"event": "error", "data": {"message": f"{type(exc).__name__}: {exc}"}})
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(run())
        yield _sse("start", {"conversation_id": conversation.id, "kb_ids": kb_ids})
        try:
            while True:
                ev = await queue.get()
                if ev is None:
                    break
                if ev["event"] == "__final__":
                    final = ev["data"]
                    message_id = await _persist_answer(
                        conversation.id,
                        final.get("draft", ""),
                        final.get("citations", []),
                        final.get("verify", {}),
                    )
                    yield _sse("done", _done_payload(conversation.id, message_id, final))
                    continue
                yield _sse(ev["event"], ev["data"])
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
async def get_conversation(conversation_id: str, tenant: TenantDep, session: SessionDep) -> ConversationOut:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None or conversation.tenant_id != tenant:
        raise HTTPException(404, "conversation not found")
    rows = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        )
    ).scalars().all()
    return ConversationOut(
        id=conversation.id,
        title=conversation.title,
        kb_id=conversation.kb_id,
        messages=[
            MessageOut(
                id=m.id,
                role=m.role,
                content=m.content,
                citations=m.citations or [],
                created_at=m.created_at,
            )
            for m in rows
        ],
    )