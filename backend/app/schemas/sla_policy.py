import uuid
from datetime import datetime

from pydantic import BaseModel, Field

# NULL — без срока для этой критичности
Days = int | None


class SlaPolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    days_critical: Days = Field(default=None, ge=1, le=3650)
    days_high: Days = Field(default=None, ge=1, le=3650)
    days_medium: Days = Field(default=None, ge=1, le=3650)
    days_low: Days = Field(default=None, ge=1, le=3650)
    days_info: Days = Field(default=None, ge=1, le=3650)
    is_default: bool = False


class SlaPolicyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    days_critical: Days = Field(default=None, ge=1, le=3650)
    days_high: Days = Field(default=None, ge=1, le=3650)
    days_medium: Days = Field(default=None, ge=1, le=3650)
    days_low: Days = Field(default=None, ge=1, le=3650)
    days_info: Days = Field(default=None, ge=1, le=3650)
    # только true: снять флаг можно, назначив по умолчанию другую политику
    is_default: bool | None = None


class SlaPolicyRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    days_critical: Days
    days_high: Days
    days_medium: Days
    days_low: Days
    days_info: Days
    is_default: bool
    # сколько проектов назначили политику напрямую
    entities_count: int = 0
    created_at: datetime
    updated_at: datetime
