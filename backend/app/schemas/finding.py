import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.finding import FindingStatus


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
    fingerprint: str
    first_seen: datetime
    last_seen: datetime
    created_at: datetime


class FindingStatusUpdate(BaseModel):
    status: FindingStatus
    reason: str | None = Field(default=None, max_length=2000)
