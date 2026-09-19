import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class FindingEventRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    finding_id: uuid.UUID
    event_type: str
    actor_type: str
    actor_id: uuid.UUID | None
    from_status: str | None
    to_status: str | None
    reason: str | None
    reason_tag: str | None
    payload: dict[str, Any]
    created_at: datetime
