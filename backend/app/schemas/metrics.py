import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.models.finding import Severity

Metric = Literal["count", "opened", "resolved", "overdue", "sla_ratio", "mttr_days"]
GroupBy = Literal["none", "severity", "scanner", "team", "entity", "week"]
Period = Literal["7d", "30d", "90d", "365d"]


class MetricFilters(BaseModel):
    model_config = {"extra": "forbid"}

    severity: list[Severity] = Field(default_factory=list, max_length=5)
    scanner: str | None = Field(default=None, max_length=100)
    # проект вместе с поддеревом
    entity_id: uuid.UUID | None = None
    tag: str | None = Field(default=None, max_length=64)


class MetricQuery(BaseModel):
    """JSON виджета дашборда. Только значения из белых списков — SQL из запроса не собирается."""

    model_config = {"extra": "forbid"}

    metric: Metric
    group_by: GroupBy = "none"
    period: Period = "30d"
    filters: MetricFilters = Field(default_factory=MetricFilters)


class MetricRow(BaseModel):
    # значение группы: severity/scanner/id команды или проекта/дата недели; None — «без команды»
    key: str | None
    label: str | None
    value: float | None


class MetricResult(BaseModel):
    metric: Metric
    group_by: GroupBy
    period: Period
    rows: list[MetricRow]
