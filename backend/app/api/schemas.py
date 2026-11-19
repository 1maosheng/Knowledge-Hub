from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class KBCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class KBOut(BaseModel):
    id: str
    name: str
    description: str
    doc_count: int = 0
    created_at: datetime | None = None


class DocumentOut(BaseModel):
    id: str
    kb_id: str
    name: str
    filename: str
    size: int
    status: str
    stage: str
    progress: int
    error: str
    page_count: int
    chunk_count: int
    meta: dict = {}
    created_at: datetime | None = None


class SearchRequest(BaseModel):
    kb_ids: list[str] = Field(min_length=1)
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=8, ge=1, le=50)


class ChatRequest(BaseModel):
    kb_ids: list[str] = Field(min_length=1)
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    stream: bool = True


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    citations: list[dict] = []
    created_at: datetime | None = None


class ConversationOut(BaseModel):
    id: str
    title: str
    kb_id: str
    messages: list[MessageOut] = []