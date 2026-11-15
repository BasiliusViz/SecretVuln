import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.decision_request import DecisionType, ReasonTag

CONDITIONS = ("scanner", "rule_id", "cwe", "path_glob")


def _blank_to_none(value: str | None) -> str | None:
    value = (value or "").strip()
    return value or None


def check_rule(
    *, conditions: dict[str, str | None], decision: DecisionType,
    reason_tag: ReasonTag | None, reason: str | None,
) -> None:
    """Правила, общие для создания и для состояния после правки."""
    if not any(conditions.values()):
        raise ValueError("Задайте хотя бы одно условие: сканер, правило, CWE или маску пути")
    # обоснование должно годиться для запроса решения «по правилу»
    if decision == DecisionType.false_positive:
        if reason_tag is None:
            raise ValueError("Укажите причину ложного срабатывания")
        if reason_tag == ReasonTag.other and not reason:
            raise ValueError("Для причины «Другое» опишите её текстом")
    elif not reason:
        raise ValueError("Опишите, почему риск можно принять")


class _Conditions(BaseModel):
    scanner: str | None = Field(default=None, max_length=100)
    rule_id: str | None = Field(default=None, max_length=512)
    cwe: str | None = Field(default=None, max_length=50)
    path_glob: str | None = Field(default=None, max_length=1024)
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator(*CONDITIONS, "reason", mode="before")
    @classmethod
    def _strip(cls, v):
        return _blank_to_none(v) if isinstance(v, str) else v


class MemoryCreate(_Conditions):
    """Правило, созданное вручную, сразу действует."""

    entity_id: uuid.UUID
    decision: DecisionType
    reason_tag: ReasonTag | None = None

    @model_validator(mode="after")
    def _check(self) -> "MemoryCreate":
        check_rule(
            conditions={f: getattr(self, f) for f in CONDITIONS},
            decision=self.decision, reason_tag=self.reason_tag, reason=self.reason,
        )
        return self


class MemoryUpdate(_Conditions):
    """Правка: меняются только переданные поля. `status` — утвердить или выключить."""

    entity_id: uuid.UUID | None = None
    decision: DecisionType | None = None
    reason_tag: ReasonTag | None = None
    status: Literal["approved", "disabled"] | None = None


class MemoryRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    entity_id: uuid.UUID
    entity_path: str = ""
    entity_name: str = ""
    scanner: str | None
    rule_id: str | None
    cwe: str | None
    path_glob: str | None
    decision: str
    reason_tag: str | None
    reason: str | None
    status: str
    source: str
    created_by: uuid.UUID | None
    approved_by: uuid.UUID | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # открытые находки с этой подсказкой (по всему поддереву, без учёта прав читателя)
    open_findings: int = 0
    can_manage: bool = False
