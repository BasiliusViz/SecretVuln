import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.finding import FindingStatus


class GroupBrief(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str


class UserBriefLite(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    full_name: str | None


class FindingRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    number: int
    entity_id: uuid.UUID
    import_id: uuid.UUID | None
    title: str
    description: str | None
    severity: str
    status: str
    scanner: str
    rule_id: str | None
    cwe: str | None
    file_path: str | None
    line_start: int | None
    line_end: int | None
    scan_scope: str | None
    commit_sha: str | None
    assignee_group_id: uuid.UUID | None
    assignee_user_id: uuid.UUID | None
    assigned_manually: bool
    help_requested_at: datetime | None
    assignee_group: GroupBrief | None
    assignee_user: UserBriefLite | None
    fingerprint: str
    first_seen: datetime
    last_seen: datetime
    created_at: datetime


class FindingStatusUpdate(BaseModel):
    status: FindingStatus
    reason: str | None = Field(default=None, max_length=2000)


class FindingAssign(BaseModel):
    group_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    # true — снять ручное назначение и назначить по правилам
    by_rules: bool = False


class FindingDetail(FindingRead):
    """Карточка для окна уязвимости: адрес проекта, ссылки на код, рекомендация сканера."""

    entity_name: str = ""
    entity_path: str = ""
    code_url: str | None = None
    code_url_head: str | None = None
    help_text: str | None = None
