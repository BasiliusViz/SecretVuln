import uuid
from datetime import datetime
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class EntityCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, max_length=100)
    parent_id: uuid.UUID | None = None
    description: str | None = None
    default_branch: str | None = Field(default=None, max_length=255)
    custom_fields: dict[str, Any] = Field(default_factory=dict)


class EntityUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, max_length=100)
    parent_id: uuid.UUID | None = None
    description: str | None = None
    default_branch: str | None = Field(default=None, max_length=255)
    custom_fields: dict[str, Any] | None = None


class EntityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    path: str = Field(validation_alias=AliasChoices("path_cache", "path"))
    parent_id: uuid.UUID | None
    description: str | None
    default_branch: str | None
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class EntityUpsert(BaseModel):
    """PUT /entities/by-path: только структура; настройки — через файл или /settings."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
