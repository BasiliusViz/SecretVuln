"""Встроенный ИИ: разбор находки моделью и отбор находок для автозапуска после импорта.

Пишет только `ai_analyses` (две строки: «summary» и «triage»), статус находки не меняет.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import AiAnalysis, AiAnalysisKind, AiReviewStatus, Finding
from app.models.ai_analysis import AiVerdict
from app.models.finding_event import FindingEvent, FindingEventType
from app.models.import_ import Import, ImportStatus
from app.services.ai_analyses import _lock_finding, refresh_ai_verdict
from app.services.llm import client_from_settings
from app.services.llm.prompts import PROMPT_VERSION, TriageAnswer, build_messages

BUILTIN_AGENT = "sv-builtin"


class ChatClient(Protocol):
    model: str

    async def chat_json(self, messages: list[dict], schema: type[TriageAnswer]) -> TriageAnswer: ...


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def triage_finding(
    db: AsyncSession, finding_id: uuid.UUID, client: ChatClient
) -> list[AiAnalysis]:
    """Разобрать находку. Ошибка модели (`LlmError`) пробрасывается — строк не пишем.

    Строки вывода не коммитит. Модель вызывается без блокировки находки и вне транзакции:
    ответ может идти минуту, соединение всё это время не висит «idle in transaction».
    """
    finding = await db.get(Finding, finding_id)
    if finding is None:
        return []
    messages = build_messages(finding)
    await db.commit()  # пока только читали — закрываем транзакцию на время ответа модели
    answer = await client.chat_json(messages, TriageAnswer)

    if await _lock_finding(db, finding_id) is None:  # находку удалили, пока думала модель
        return []
    common = dict(
        finding_id=finding_id,
        agent=BUILTIN_AGENT,
        model=(client.model or None) and client.model[:100],
        prompt_version=PROMPT_VERSION,
        created_by=None,
        review_status=AiReviewStatus.pending,
    )
    rows = [
        AiAnalysis(
            kind=AiAnalysisKind.summary,
            title_plain=_cut(answer.title_plain, 500) or None,
            explanation=_cut(answer.explanation, 20000) or None,
            remediation=_cut(answer.remediation, 20000) or None,
            **common,
        ),
        AiAnalysis(
            kind=AiAnalysisKind.triage,
            verdict=AiVerdict(answer.verdict),
            confidence=answer.confidence,
            explanation=_cut(answer.reasoning, 20000) or None,
            **common,
        ),
    ]
    db.add_all(rows)
    await db.flush()
    await refresh_ai_verdict(db, finding_id)
    return rows


async def triage_with_settings(db: AsyncSession, finding_id: uuid.UUID) -> list[AiAnalysis]:
    return await triage_finding(db, finding_id, client_from_settings())


async def pick_auto_triage(db: AsyncSession, import_id: uuid.UUID) -> list[uuid.UUID]:
    """Новые находки импорта для автозапуска: ИИ включён, импорт прошёл в бэклог
    (значит, основная ветка), у находки ещё нет вывода встроенного ИИ; не больше лимита."""
    settings = get_settings()
    if not settings.ai_enabled or settings.ai_auto_limit <= 0:
        return []
    imp = await db.get(Import, import_id)
    if imp is None or imp.status != ImportStatus.done:
        return []
    already = exists().where(
        AiAnalysis.finding_id == Finding.id,
        AiAnalysis.agent == BUILTIN_AGENT,
        AiAnalysis.created_by.is_(None),
    )
    rows = await db.scalars(
        select(Finding.id)
        .join(FindingEvent, FindingEvent.finding_id == Finding.id)
        .where(
            FindingEvent.event_type == FindingEventType.imported,
            FindingEvent.payload["import_id"].astext == str(import_id),
            ~already,
        )
        .order_by(Finding.severity, Finding.number)  # сначала критичные
        .limit(settings.ai_auto_limit)
    )
    return list(rows)
