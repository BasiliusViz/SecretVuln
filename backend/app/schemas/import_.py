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
    status: str
    stats: dict[str, Any]
    error: str | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
