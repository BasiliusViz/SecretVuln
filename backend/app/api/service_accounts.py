"""Сервисные аккаунты (агенты) и их API-токены. Глобальное право `token:manage`.

Права аккаунт получает обычным путём: участник группы → привязки группы.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, not_found, require_global
from app.db.session import get_db
from app.models import ApiToken, AuthSource, User
from app.schemas.service_account import (
    ApiTokenCreate,
    ApiTokenCreated,
    ApiTokenRead,
    ServiceAccountCreate,
    ServiceAccountRead,
    ServiceAccountUpdate,
)
from app.services import api_tokens, audit

router = APIRouter(prefix="/api/v1/service-accounts", tags=["service-accounts"])

SERVICE_DOMAIN = "service.local"
_manage = require_global("token", "manage")


async def _account_or_404(db: AsyncSession, account_id: uuid.UUID) -> User:
    user = await db.get(User, account_id)
    if user is None or user.auth_source != AuthSource.service:
        raise not_found("Сервисный аккаунт")
    return user


async def _to_read(db: AsyncSession, user: User) -> ServiceAccountRead:
    tokens = await db.scalars(
        select(ApiToken).where(ApiToken.user_id == user.id).order_by(ApiToken.created_at.desc())
    )
    return ServiceAccountRead(
        **ServiceAccountRead.model_validate(user).model_dump(exclude={"tokens"}),
        tokens=[ApiTokenRead.model_validate(t) for t in tokens],
    )


def _token_target(user: User, token: ApiToken) -> tuple[str, uuid.UUID, str]:
    return ("api_token", token.id, f"{user.email}: {token.name}")


@router.get("", response_model=list[ServiceAccountRead])
async def list_service_accounts(
    principal: Principal = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> list[ServiceAccountRead]:
    users = await db.scalars(
        select(User).where(User.auth_source == AuthSource.service).order_by(User.email)
    )
    return [await _to_read(db, u) for u in users]


@router.post("", response_model=ServiceAccountRead, status_code=status.HTTP_201_CREATED)
async def create_service_account(
    data: ServiceAccountCreate,
    request: Request,
    principal: Principal = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> ServiceAccountRead:
    user = User(
        email=f"{data.name}@{SERVICE_DOMAIN}",
        full_name=data.full_name,
        auth_source=AuthSource.service,
        hashed_password=None,
        is_active=True,
        is_superuser=False,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Аккаунт с таким именем уже есть")
    audit.record_audit(
        db, principal.user, audit.SERVICE_ACCOUNT_CREATE,
        target=("service_account", user.id, user.email),
        changes=audit.snapshot(user, audit.FIELDS["service_account"]),
        ip=audit.client_ip(request),
    )
    await db.commit()
    return await _to_read(db, user)


@router.patch("/{account_id}", response_model=ServiceAccountRead)
async def update_service_account(
    account_id: uuid.UUID,
    data: ServiceAccountUpdate,
    request: Request,
    principal: Principal = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> ServiceAccountRead:
    user = await _account_or_404(db, account_id)
    fields = audit.FIELDS["service_account"]
    before = audit.snapshot(user, fields)
    for key, value in data.model_dump(exclude_unset=True).items():
        if key == "is_active" and value is None:
            continue
        setattr(user, key, value)
    changes = audit.diff(before, audit.snapshot(user, fields), fields)
    if changes:
        audit.record_audit(
            db, principal.user, audit.SERVICE_ACCOUNT_UPDATE,
            target=("service_account", user.id, user.email),
            changes=changes,
            ip=audit.client_ip(request),
        )
        await db.commit()
    return await _to_read(db, user)


@router.post(
    "/{account_id}/tokens", response_model=ApiTokenCreated, status_code=status.HTTP_201_CREATED
)
async def create_token(
    account_id: uuid.UUID,
    data: ApiTokenCreate,
    request: Request,
    principal: Principal = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> ApiTokenCreated:
    user = await _account_or_404(db, account_id)
    if not user.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Аккаунт отключён — сначала включите его")
    raw, prefix, token_hash = api_tokens.generate()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=data.expires_in_days)
        if data.expires_in_days else None
    )
    token = ApiToken(
        user_id=user.id,
        name=data.name,
        prefix=prefix,
        token_hash=token_hash,
        expires_at=expires_at,
        created_by=principal.user.id,
    )
    db.add(token)
    await db.flush()
    audit.record_audit(
        db, principal.user, audit.TOKEN_CREATE,
        target=_token_target(user, token),
        changes=audit.snapshot(token, audit.FIELDS["api_token"]),
        ip=audit.client_ip(request),
    )
    await db.commit()
    await db.refresh(token)
    return ApiTokenCreated(**ApiTokenRead.model_validate(token).model_dump(), token=raw)


@router.delete("/{account_id}/tokens/{token_id}", response_model=ApiTokenRead)
async def revoke_token(
    account_id: uuid.UUID,
    token_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(_manage),
    db: AsyncSession = Depends(get_db),
) -> ApiToken:
    """Отзыв: строка остаётся (видно, когда и какой токен отозван)."""
    user = await _account_or_404(db, account_id)
    token = await db.get(ApiToken, token_id)
    if token is None or token.user_id != user.id:
        raise not_found("Токен")
    if token.revoked_at is None:
        token.revoked_at = datetime.now(timezone.utc)
        audit.record_audit(
            db, principal.user, audit.TOKEN_REVOKE,
            target=_token_target(user, token),
            changes=audit.snapshot(token, audit.FIELDS["api_token"]),
            ip=audit.client_ip(request),
        )
        await db.commit()
    return token
