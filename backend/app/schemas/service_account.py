import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ApiTokenRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    prefix: str
    expires_at: datetime | None
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiTokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    # None — бессрочный
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiTokenCreated(ApiTokenRead):
    """Ответ на выдачу: сам токен показывается один раз."""

    token: str


class ServiceAccountCreate(BaseModel):
    # логин аккаунта: станет `<name>@service.local`
    name: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    full_name: str | None = Field(default=None, max_length=255)


class ServiceAccountUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


class ServiceAccountRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    full_name: str | None
    is_active: bool
    created_at: datetime
    tokens: list[ApiTokenRead] = []
