import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.ai_analysis import AiAnalysisKind, AiVerdict
from app.schemas.finding import UserBriefLite


class AiAnalysisCreate(BaseModel):
    kind: AiAnalysisKind
    verdict: AiVerdict | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    title_plain: str | None = Field(default=None, max_length=500)
    explanation: str | None = Field(default=None, max_length=20000)
    remediation: str | None = Field(default=None, max_length=20000)
    agent: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    prompt_version: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _check(self) -> "AiAnalysisCreate":
        if self.kind == AiAnalysisKind.triage and self.verdict is None:
            raise ValueError("Для вывода «triage» нужен вердикт (verdict)")
        if self.kind == AiAnalysisKind.summary and self.verdict is not None:
            raise ValueError("Вердикт ставится только в выводе «triage»")
        if not any((self.title_plain, self.explanation, self.remediation)) and (
            self.kind == AiAnalysisKind.summary
        ):
            raise ValueError("Пустой вывод: нужен хотя бы один из title_plain/explanation/remediation")
        return self


class AiAnalysisRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    finding_id: uuid.UUID
    kind: AiAnalysisKind
    verdict: AiVerdict | None
    confidence: float | None
    title_plain: str | None
    explanation: str | None
    remediation: str | None
    agent: str | None
    model: str | None
    prompt_version: str | None
    created_by: uuid.UUID | None
    author: UserBriefLite | None
    created_at: datetime
    review_status: str
    reviewed_by: uuid.UUID | None
    reviewer: UserBriefLite | None
    reviewed_at: datetime | None
    review_comment: str | None


class AiAnalysisReview(BaseModel):
    decision: Literal["accept", "reject"]
    comment: str | None = Field(default=None, max_length=2000)
