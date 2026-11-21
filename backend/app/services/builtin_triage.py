"""Встроенный ИИ: разбор находки моделью и отбор находок для автозапуска после импорта.

Пишет только `ai_analyses` (две строки: «summary» и «triage»), статус находки не меняет.
"""

from __future__ import annotations

import uuid
from typing import Protocol

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import AiAnalysis, AiAnalysisKind, AiReviewStatus, Entity, Finding, FindingStatus
from app.models.ai_analysis import AiVerdict
from app.models.finding_event import ActorType, FindingEvent, FindingEventType
from app.models.triage_memory import TriageMemory
from app.models.import_ import Import, ImportStatus
from app.services.ai_analyses import _lock_finding, refresh_ai_verdict
from app.services.embeddings import embed_client, ensure_embedding
from app.services import memories
from app.services.llm import client_from_settings
from app.services.intel.read import finding_intel
from app.services.llm.prompts import PROMPT_VERSION, TriageAnswer, build_messages
from app.services.similarity import human_decisions, nearest

BUILTIN_AGENT = "sv-builtin"
SIMILAR_LIMIT = 3
# решённые человеком статусы: на них триажёр опирается как на практику команды
DECIDED = (FindingStatus.false_positive, FindingStatus.confirmed, FindingStatus.risk_accepted)


class ChatClient(Protocol):
    model: str

    async def chat_json(self, messages: list[dict], schema: type[TriageAnswer]) -> TriageAnswer: ...


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def similar_decided(
    db: AsyncSession, finding: Finding, embed=None
) -> list[tuple[Finding, dict | None]]:
    """До 3 похожих находок, решённых человеком, из проекта находки и его подпроектов.

    Только поддерево: кто видит находку, видит и всё её поддерево, поэтому текст вывода ИИ
    не перескажет находку соседней ветки, закрытой от читателей этой.
    Векторы выключены или модель недоступна — пустой список, разбор идёт без похожих.
    """
    embed = embed or embed_client()
    if embed is None or not await ensure_embedding(db, finding, embed):
        return []
    path = await db.scalar(select(Entity.path_cache).where(Entity.id == finding.entity_id))
    subtree = select(Entity.id).where(or_(
        Entity.path_cache == path, Entity.path_cache.startswith(path + "/", autoescape=True)
    ))
    human_decided = (
        select(FindingEvent.id)
        .where(
            FindingEvent.finding_id == Finding.id,
            FindingEvent.actor_type == ActorType.user,
            FindingEvent.to_status == Finding.status,
        )
        .exists()
    )
    scope = Finding.entity_id.in_(subtree) & Finding.status.in_(DECIDED) & human_decided
    pairs = await nearest(db, finding, scope, SIMILAR_LIMIT) or []
    decisions = await human_decisions(db, [f.id for f, _ in pairs])
    return [(f, decisions.get(f.id)) for f, _ in pairs]


async def triage_finding(
    db: AsyncSession, finding_id: uuid.UUID, client: ChatClient, embed=None
) -> list[AiAnalysis]:
    """Разобрать находку. Ошибка модели (`LlmError`) пробрасывается — строк не пишем.

    Строки вывода не коммитит. Модель вызывается без блокировки находки и вне транзакции:
    ответ может идти минуту, соединение всё это время не висит «idle in transaction».
    """
    finding = await db.get(Finding, finding_id)
    if finding is None:
        return []
    similar = await similar_decided(db, finding, embed)
    memory = await db.get(TriageMemory, finding.memory_id) if finding.memory_id else None
    if memory is not None and not await memories.hint_in_scope(db, finding, memory):
        memory = None  # устаревшая подсказка из чужой ветки — в промпт не берём
    intel = await finding_intel(db, finding)
    messages = build_messages(finding, similar, memory, intel)
    similar_ids = [str(f.id) for f, _ in similar]
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
        similar_ids=similar_ids,
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
