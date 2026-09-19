import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ImportRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    entity_id: uuid.UUID
    filename: str
    scanner: str | None
    branch: str | None
    commit_sha: str | None
    pipeline_url: str | None
    scan_scope: str | None
    close_missing: bool
    confirm_empty: bool
    status: str
    stats: dict[str, Any]
    error: str | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
