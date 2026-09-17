import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class FindingRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
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
    fingerprint: str
    first_seen: datetime
    last_seen: datetime
    created_at: datetime
