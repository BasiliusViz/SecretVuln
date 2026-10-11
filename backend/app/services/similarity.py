"""Похожие находки и поиск по смыслу поверх `finding_embeddings` (pgvector, косинус).

Фильтр видимости `Access` идёт в том же запросе, поэтому HNSW-индекс включается в
`iterative_scan = relaxed_order`: иначе индекс отдаёт ef_search ближайших, фильтр прав их
выкидывает, и выдача пустеет. Порядок при relaxed_order приблизительный — досортировываем.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal
from app.models import Entity, Finding, FindingEmbedding, FindingEvent
from app.models.finding import FindingStatus
from app.models.finding_event import ActorType
from app.services.masking import mask

# Переходы, которые считаются решением человека для блока «Похожие» (не «взял в работу»)
DECIDED_STATUSES = (
    FindingStatus.confirmed, FindingStatus.false_positive,
    FindingStatus.risk_accepted, FindingStatus.fixed,
)


def _similarity(distance: float) -> float:
    # косинусное расстояние 0..2 → близость 0..1
    return round(max(0.0, min(1.0, 1.0 - float(distance))), 4)


async def _iterative_scan(db: AsyncSession) -> None:
    # SET LOCAL живёт до конца текущей транзакции — запрос ниже идёт в ней же
    await db.execute(text("SET LOCAL hnsw.iterative_scan = relaxed_order"))


async def human_decisions(
    db: AsyncSession, finding_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """Последнее решение человека по каждой находке: переход в решающий статус
    (взял в работу или переоткрыл — не решение)."""
    if not finding_ids:
        return {}
    rows = await db.scalars(
        select(FindingEvent)
        .where(
            FindingEvent.finding_id.in_(finding_ids),
            FindingEvent.actor_type == ActorType.user,
            FindingEvent.to_status.in_(DECIDED_STATUSES),
        )
        .distinct(FindingEvent.finding_id)
        .order_by(FindingEvent.finding_id, FindingEvent.created_at.desc())
    )
    return {
        e.finding_id: {
            "status": e.to_status.value,
            "reason": e.reason,
            "reason_tag": e.reason_tag,
            "at": e.created_at.isoformat(),
        }
        for e in rows
    }


async def nearest(
    db: AsyncSession, finding: Finding, scope, limit: int
) -> list[tuple[Finding, float]] | None:
    """Ближайшие к находке в пределах условия `scope`. None — у находки ещё нет вектора."""
    target = await db.get(FindingEmbedding, finding.id)
    if target is None:
        return None
    distance = FindingEmbedding.embedding.cosine_distance(target.embedding)
    await _iterative_scan(db)
    rows = (await db.execute(
        select(Finding, distance.label("distance"))
        .join(FindingEmbedding, FindingEmbedding.finding_id == Finding.id)
        .where(
            scope,
            FindingEmbedding.model == target.model,  # векторы разных моделей несравнимы
            Finding.id != finding.id,
            Finding.fingerprint != finding.fingerprint,  # та же находка в другом проекте
        )
        .order_by(distance)
        .limit(limit)
    )).all()
    pairs = [(f, _similarity(d)) for f, d in rows]
    return sorted(pairs, key=lambda p: p[1], reverse=True)


async def find_similar(
    db: AsyncSession, principal: Principal, finding_id: uuid.UUID, limit: int = 5
) -> dict[str, Any]:
    """Похожие на находку среди видимых вызывающему. Видимость самой находки проверяет
    вызывающий (эндпоинт или MCP)."""
    finding = await db.get(Finding, finding_id)
    scope = principal.access.entity_scope("finding:read", Finding.entity_id)
    pairs = await nearest(db, finding, scope, limit) if finding else None
    if pairs is None:
        return {"pending": True, "items": []}
    paths = dict((await db.execute(
        select(Entity.id, Entity.path_cache).where(Entity.id.in_({f.entity_id for f, _ in pairs}))
    )).all()) if pairs else {}
    decisions = await human_decisions(db, [f.id for f, _ in pairs])
    return {
        "pending": False,
        "items": [
            {
                "id": str(f.id),
                "number": f"SV-{f.number}",
                "title": f.title,
                "entity_path": paths.get(f.entity_id),
                "status": f.status.value,
                "severity": f.severity.value,
                "similarity": sim,
                "decision": decisions.get(f.id),
            }
            for f, sim in pairs
        ],
    }


async def search_by_text(
    db: AsyncSession, base: Select, query: str, client, limit: int = 50, offset: int = 0
) -> list[tuple[Finding, float]]:
    """Поиск по смыслу: `base` — запрос `findings_query` (права и фильтры уже в нём),
    сортировка заменяется на близость к вектору запроса. Ошибка модели — `LlmError`."""
    [vector] = await client.embed([mask(query)])
    distance = FindingEmbedding.embedding.cosine_distance(vector)
    q = (
        base.order_by(None)
        .add_columns(distance.label("distance"))
        .join(FindingEmbedding, FindingEmbedding.finding_id == Finding.id)
        .where(FindingEmbedding.model == client.model)
        .order_by(distance)
        .offset(offset)
        .limit(limit)
    )
    await _iterative_scan(db)
    rows = (await db.execute(q)).all()
    pairs = [(f, _similarity(d)) for f, d in rows]
    return sorted(pairs, key=lambda p: p[1], reverse=True)
