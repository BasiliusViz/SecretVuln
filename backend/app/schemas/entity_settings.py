import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.entity import RepoType


class SettingValue(BaseModel):
    value: Any
    source: Literal["manual", "file", "inherited", "unset"]
    inherited_from: str | None


class RuleRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    pattern: str
    group_id: uuid.UUID
    group_name: str
    position: int
    source: str


class InheritedRule(BaseModel):
    entity_path: str
    pattern: str
    group_id: uuid.UUID
    group_name: str


class EntitySettingsRead(BaseModel):
    entity_id: uuid.UUID
    path: str
    fields: dict[str, SettingValue]
    ownership_rules: list[RuleRead]
    rules_source: Literal["manual", "file"]
    inherited_rules: list[InheritedRule]
    pinned_fields: list[str]
    has_config_file: bool
    config_commit_sha: str | None
    config_applied_at: datetime | None
    warnings: list[str] = []


class EntitySettingsUpdate(BaseModel):
    default_branch: str | None = Field(default=None, max_length=255)
    owner_group_id: uuid.UUID | None = None
    repo_url: str | None = Field(default=None, max_length=1024)
    repo_type: RepoType | None = None
    repo_path_prefix: str | None = Field(default=None, max_length=512)


class RuleIn(BaseModel):
    pattern: str = Field(min_length=1, max_length=512)
    group_id: uuid.UUID


class UnpinRequest(BaseModel):
    field: Literal["default_branch", "owner_group_id", "repo", "ownership_rules"]
