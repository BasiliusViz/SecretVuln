"""Зависимости аутентификации: извлечение текущего пользователя из JWT."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User

_bearer = HTTPBearer(auto_error=False)


@dataclass
class Principal:
    user: User
    roles: list[str]


async def get_current_principal(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> Principal:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Не авторизован")
    try:
        payload = decode_access_token(creds.credentials)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Недействительный токен")

    user_id = payload.get("sub")
    try:
        user = await db.get(User, uuid.UUID(user_id))
    except (ValueError, TypeError):
        user = None
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден или отключён")

    roles = payload.get("roles", [])
    if user.is_superuser and "superuser" not in roles:
        roles = [*roles, "superuser"]
    return Principal(user=user, roles=roles)


async def get_current_user(principal: Principal = Depends(get_current_principal)) -> User:
    return principal.user


def require_permission(resource: str, action: str):
    """Зависимость: пропускает суперюзера или роль с правом (resource, action)."""
    from app.authz.enforcer import check

    async def _dep(principal: Principal = Depends(get_current_principal)) -> Principal:
        if principal.user.is_superuser:
            return principal
        if check(principal.roles, resource, action):
            return principal
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Недостаточно прав: {resource}:{action}"
        )

    return _dep
