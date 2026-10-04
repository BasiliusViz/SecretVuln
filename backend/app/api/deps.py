"""Зависимости аутентификации и доступа.

JWT только удостоверяет пользователя. Права собираются из привязок на каждый
запрос (`load_access`), поэтому правка ролей и привязок действует сразу.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import Entity, User
from app.services.access import Access, load_access

_bearer = HTTPBearer(auto_error=False)

# Право на чтение того же ресурса: без него объекта «не существует» (404).
_READ_OF = {
    "entity": "entity:read",
    "finding": "finding:read",
    "import": "import:read",
    "sla": "entity:read",
    "access": "entity:read",
}


@dataclass
class Principal:
    user: User
    access: Access


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

    return Principal(user=user, access=await load_access(db, user))


async def get_current_user(principal: Principal = Depends(get_current_principal)) -> User:
    return principal.user


async def get_access(principal: Principal = Depends(get_current_principal)) -> Access:
    return principal.access


def require_permission(resource: str, action: str):
    """Ворота эндпоинта: право есть хоть где-то. Объект проверяет `ensure`."""
    perm = f"{resource}:{action}"

    async def _dep(principal: Principal = Depends(get_current_principal)) -> Principal:
        if principal.access.anywhere(perm):
            return principal
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Недостаточно прав: {perm}")

    return _dep


def require_global(resource: str, action: str):
    """Право на всё дерево (корневые проекты, глобальные справочники)."""
    perm = f"{resource}:{action}"

    async def _dep(principal: Principal = Depends(get_current_principal)) -> Principal:
        if principal.access.is_global(perm):
            return principal
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Недостаточно прав: {perm}")

    return _dep


def not_found(what: str = "Объект") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} не найден")


def ensure(
    access: Access | Principal,
    perm: str,
    target: Entity | str | None,
    *,
    what: str = "Объект",
) -> None:
    """Право `perm` на проект `target` (None — глобально).

    Нет ни чтения, ни самого права → 404 (не выдаём существование объекта);
    чтение есть, права нет → 403.
    """
    if isinstance(access, Principal):
        access = access.access
    if access.allows(perm, target):
        return
    read = _READ_OF.get(perm.split(":", 1)[0], "entity:read")
    if target is not None and not access.allows(read, target):
        raise not_found(what)
    raise HTTPException(status.HTTP_403_FORBIDDEN, f"Недостаточно прав: {perm}")
