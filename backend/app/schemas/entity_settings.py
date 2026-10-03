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


class EffectiveSlaRead(BaseModel):
    policy_id: uuid.UUID | None
    policy_name: str | None
    # своя политика узла; иначе унаследована (inherited_from) или по умолчанию
    own: bool
    inherited_from: str | None
    is_default: bool


class EffectiveTag(BaseModel):
    tag: str
    inherited_from: str | None


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
    sla: EffectiveSlaRead
    tags: list[str]
    effective_tags: list[EffectiveTag]


class EntitySettingsUpdate(BaseModel):
    default_branch: str | None = Field(default=None, max_length=255)
    owner_group_id: uuid.UUID | None = None
    repo_url: str | None = Field(default=None, max_length=1024)
    repo_type: RepoType | None = None
    repo_path_prefix: str | None = Field(default=None, max_length=512)
    # NULL — наследовать политику от предка (или по умолчанию)
    sla_policy_id: uuid.UUID | None = None
    tags: list[str] | None = Field(default=None, max_length=100)


class RuleIn(BaseModel):
    pattern: str = Field(min_length=1, max_length=512)
    group_id: uuid.UUID


class UnpinRequest(BaseModel):
    field: Literal["default_branch", "owner_group_id", "repo", "ownership_rules"]
