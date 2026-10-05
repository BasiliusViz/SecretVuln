import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Uploader(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str | None = Field(default=None, validation_alias="full_name")


class ImportRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    entity_id: uuid.UUID
    # грузить через selectinload / refresh — ленивая загрузка в async недоступна
    uploaded_by: Uploader | None = None
    filename: str
    scanner: str | None
    branch: str | None
    commit_sha: str | None
    pipeline_url: str | None
    repo_url: str | None
    scan_scope: str | None
    close_missing: bool
    confirm_empty: bool
    config_warnings: list[str] = []
    status: str
    stats: dict[str, Any]
    error: str | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CreatedEntity(BaseModel):
    id: uuid.UUID
    path: str


class ImportCreated(ImportRead):
    # Заполняются в API через model_copy — у ORM-объекта Import этих атрибутов нет
    entity_path: str = ""
    created_entities: list[CreatedEntity] = []
