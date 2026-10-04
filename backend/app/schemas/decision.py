import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field, model_validator

from app.models.decision_request import DecisionType, ReasonTag


class DecisionCreate(BaseModel):
    decision_type: DecisionType
    reason_tag: ReasonTag | None = None
    reason: str | None = Field(default=None, max_length=2000)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _check(self) -> "DecisionCreate":
        reason = (self.reason or "").strip()
        if self.decision_type == DecisionType.false_positive:
            if self.reason_tag is None:
                raise ValueError("Укажите причину ложного срабатывания")
            if self.reason_tag == ReasonTag.other and not reason:
                raise ValueError("Для причины «Другое» опишите её текстом")
            if self.expires_at is not None:
                raise ValueError("Срок задаётся только для принятия риска")
        else:
            if not reason:
                raise ValueError("Опишите, почему риск можно принять")
            if self.expires_at is None:
                raise ValueError("Укажите срок, до которого риск принят")
            expires = self.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= datetime.now(timezone.utc):
                raise ValueError("Срок принятия риска должен быть в будущем")
            self.expires_at = expires
        self.reason = reason or None
        return self


class DecisionApprove(BaseModel):
    comment: str | None = Field(default=None, max_length=2000)


class DecisionReject(BaseModel):
    comment: str = Field(min_length=1, max_length=2000)


class DecisionRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    finding_id: uuid.UUID
    finding_number: int | None = None
    finding_title: str | None = None
    decision_type: str
    status: str
    reason_tag: str | None
    reason: str | None
    expires_at: datetime | None
    requested_by_id: uuid.UUID | None
    decided_by_id: uuid.UUID | None
    decision_comment: str | None
    decided_at: datetime | None
    created_at: datetime
    # заполняются в общем списке: путь проекта и право вызывающего одобрять
    entity_path: str | None = None
    can_approve: bool = False
