import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.decision_request import ReasonTag
from app.models.finding import FindingStatus


class GroupBrief(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str


class UserBriefLite(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    full_name: str | None


class MemoryBrief(BaseModel):
    """Правило команды, подсказанное находке."""

    model_config = {"from_attributes": True}

    id: uuid.UUID
    decision: str
    reason_tag: str | None
    reason: str | None


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
    assignee_group_id: uuid.UUID | None
    assignee_user_id: uuid.UUID | None
    assigned_manually: bool
    help_requested_at: datetime | None
    assignee_group: GroupBrief | None
    assignee_user: UserBriefLite | None
    fingerprint: str
    first_seen: datetime
    last_seen: datetime
    created_at: datetime
    sla_start_at: datetime | None = None
    due_at: datetime | None = None
    resolved_at: datetime | None = None
    ai_verdict: str | None = None
    memory_id: uuid.UUID | None = None
    memory: MemoryBrief | None = None
    # обогащение: CVE из SARIF и сводные поля справочников
    cves: list[str] = []
    epss_max: float | None = None
    kev: bool = False
    has_bdu: bool = False

    @field_validator("memory", mode="before")
    @classmethod
    def _only_active_memory(cls, v):
        # импорт мог поставить подсказку правила, которое тут же выключили, — его текст не отдаём
        status = getattr(v, "status", None)
        if status is not None and getattr(status, "value", status) != "approved":
            return None
        return v


class FindingStatusUpdate(BaseModel):
    status: FindingStatus
    reason: str | None = Field(default=None, max_length=2000)
    # смена статуса «по выводу ИИ»: ссылка попадает в событие истории
    ai_analysis_id: uuid.UUID | None = None


class FindingAssign(BaseModel):
    group_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    # true — снять ручное назначение и назначить по правилам
    by_rules: bool = False


class IntelCwe(BaseModel):
    id: str
    name: str | None = None
    category: str | None = None


class IntelKevBrief(BaseModel):
    date_added: date | None = None
    due_date: date | None = None
    name: str | None = None
    ransomware: bool = False


class IntelBduBrief(BaseModel):
    id: str
    name: str | None = None
    severity: str | None = None


class IntelCve(BaseModel):
    id: str
    epss: float | None = None
    percentile: float | None = None
    kev: IntelKevBrief | None = None
    bdu: list[IntelBduBrief] = []


class FindingIntel(BaseModel):
    """Справочные данные находки (блок «Угрозы» в окне SV-N)."""

    cwe: IntelCwe | None = None
    cves: list[IntelCve] = []
    stale: list[str] = []  # источники с устаревшим файлом: epss, kev
    sources: dict[str, date | None] = {}  # дата файла каждого источника


class FindingDetail(FindingRead):
    """Карточка для окна уязвимости: адрес проекта, ссылки на код, рекомендация сканера."""

    entity_name: str = ""
    entity_path: str = ""
    code_url: str | None = None
    code_url_head: str | None = None
    help_text: str | None = None
    intel: FindingIntel | None = None


class CommentCreate(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    # AppSec отвечает на «Нужна помощь» и снимает флаг
    resolve_help: bool = False


class HelpRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class BulkAction(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    action: Literal["confirm", "false_positive", "assign"]
    reason_tag: ReasonTag | None = None
    reason: str | None = Field(default=None, max_length=2000)
    group_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _check(self) -> "BulkAction":
        if self.action == "assign" and self.group_id is None:
            raise ValueError("Для назначения укажите команду")
        return self


class BulkSkipped(BaseModel):
    id: uuid.UUID
    reason: str


class BulkResult(BaseModel):
    applied: int
    skipped: list[BulkSkipped]


class ReasonCount(BaseModel):
    reason_tag: str
    count: int


class NoisyRule(BaseModel):
    scanner: str
    rule_id: str
    decided: int
    false_positive: int
    fp_ratio: float
    top_reasons: list[ReasonCount]
