from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_session


async def tenant_id(x_tenant_id: Annotated[str | None, Header()] = None) -> str:
    return (x_tenant_id or get_settings().default_tenant).strip()


TenantDep = Annotated[str, Depends(tenant_id)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]