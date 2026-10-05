"""Аутентификация: локальный вход (email/пароль) и LDAP.

Единый эндпоинт /auth/login:
  1. Если есть локальный пользователь с паролем — проверяем пароль в БД.
  2. Иначе, если LDAP включён — аутентифицируем через LDAP, при успехе
     провижёним/обновляем пользователя и добавляем его в наши LDAP-группы.

Токен несёт только id пользователя: права собираются из привязок на каждый запрос.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, get_current_principal
from app.core.config import get_settings
from app.core.security import create_access_token, verify_password
from app.db.session import get_db
from app.models import User, UserGroup
from app.models.user import AuthSource
from app.models.user_group import GroupSource
from app.schemas.auth import LoginRequest, TokenResponse, UserRead
from app.services.auth.ldap import LdapError, authenticate as ldap_authenticate

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


async def _sync_user_groups(db: AsyncSession, user: User, ldap_groups: list[str]) -> None:
    """Добавляет пользователя в наши LDAP-группы, привязанные к его LDAP-группам."""
    if not ldap_groups:
        return
    result = await db.scalars(
        select(UserGroup).where(
            UserGroup.source == GroupSource.ldap,
            UserGroup.ldap_group.in_(ldap_groups),
        )
    )
    changed = False
    for group in result:
        if user not in group.members:
            group.members.append(user)
            changed = True
    if changed:
        await db.commit()


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    settings = get_settings()
    email = data.email.lower()

    user = await db.scalar(select(User).where(User.email == email))

    # 1. Локальный пользователь с паролем.
    if user and user.auth_source == AuthSource.local and user.hashed_password:
        if not verify_password(data.password, user.hashed_password):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный email или пароль")
        if not user.is_active:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Учётная запись отключена")
        token = create_access_token(user.id)
        return TokenResponse(access_token=token)

    # 2. LDAP.
    if settings.ldap_enabled:
        try:
            ldap_user = ldap_authenticate(email, data.password)
        except LdapError as e:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"LDAP недоступен: {e}")
        if ldap_user is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный email или пароль")

        # Провижёнинг / обновление локальной записи.
        if user is None:
            user = User(
                email=ldap_user.email.lower(),
                full_name=ldap_user.full_name,
                auth_source=AuthSource.ldap,
                ldap_dn=ldap_user.dn,
            )
            db.add(user)
        else:
            user.full_name = ldap_user.full_name or user.full_name
            user.ldap_dn = ldap_user.dn
        await db.commit()
        await db.refresh(user)

        if not user.is_active:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Учётная запись отключена")

        # Ленивая синхронизация: добавляем юзера в наши LDAP-группы,
        # совпадающие с его группами в LDAP (полный синк — по кнопке в UI).
        await _sync_user_groups(db, user, ldap_user.groups)

        token = create_access_token(user.id)
        return TokenResponse(access_token=token)

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный email или пароль")


@router.get("/me", response_model=UserRead)
async def me(principal: Principal = Depends(get_current_principal)) -> UserRead:
    return UserRead(
        id=principal.user.id,
        email=principal.user.email,
        full_name=principal.user.full_name,
        auth_source=principal.user.auth_source.value,
        is_active=principal.user.is_active,
        is_superuser=principal.user.is_superuser,
        roles=sorted(principal.access.role_names),
        permissions=sorted(principal.access.grants),
        scoped_permissions=principal.access.scoped_permissions(),
    )
