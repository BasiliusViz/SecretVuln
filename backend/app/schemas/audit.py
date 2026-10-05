import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.finding_event import ActorType


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    actor_type: ActorType
    actor_id: uuid.UUID | None
    actor_label: str | None
    action: str
    target_type: str | None
    target_id: uuid.UUID | None
    target_label: str | None
    entity_id: uuid.UUID | None
    entity_path: str | None
    changes: dict[str, Any]
    ip: str | None


class AuditLogPage(BaseModel):
    items: list[AuditLogRead]
    total: int
