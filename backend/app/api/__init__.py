from __future__ import annotations

from fastapi import APIRouter

from app.api import chat, documents, health, kbs, search

api_router = APIRouter()
for module in (health, kbs, documents, search, chat):
    api_router.include_router(module.router)

__all__ = ["api_router"]