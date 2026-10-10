"""API-токены сервисных аккаунтов.

Формат `sv_<random>`: префикс отличает токен от JWT в заголовке Authorization.
В БД — только sha256 и первые символы для узнавания в списке.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ApiToken, AuthSource, User

TOKEN_PREFIX = "sv_"
_SHOWN = 11  # `sv_` + 8 символов
# last_used_at обновляется не чаще раза в минуту: без записи в БД на каждый запрос агента
_TOUCH_EVERY = timedelta(minutes=1)


def is_api_token(raw: str) -> bool:
    return raw.startswith(TOKEN_PREFIX)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate() -> tuple[str, str, str]:
    """(токен, его префикс для показа, sha256)."""
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return raw, raw[:_SHOWN], hash_token(raw)


def is_usable(token: ApiToken, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    if token.revoked_at is not None:
        return False
    return token.expires_at is None or token.expires_at > now


async def authenticate(db: AsyncSession, raw: str) -> User | None:
    """Владелец действующего токена или None (нет, отозван, истёк, аккаунт отключён)."""
    token = await db.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(raw)))
    now = datetime.now(timezone.utc)
    if token is None or not is_usable(token, now):
        return None
    user = await db.get(User, token.user_id)
    if user is None or not user.is_active or user.auth_source != AuthSource.service:
        return None
    if token.last_used_at is None or now - token.last_used_at > _TOUCH_EVERY:
        await db.execute(
            update(ApiToken).where(ApiToken.id == token.id).values(last_used_at=now)
        )
        await db.commit()
    return user
