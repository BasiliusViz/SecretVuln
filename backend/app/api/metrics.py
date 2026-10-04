"""Агрегаты для виджетов дашборда: тело запроса = JSON виджета."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, require_permission
from app.api.findings import readable
from app.db.session import get_db
from app.models import Entity
from app.schemas.metrics import MetricQuery, MetricResult
from app.services.metrics import aggregate

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


@router.post("/aggregate", response_model=MetricResult)
async def aggregate_metric(
    query: MetricQuery,
    principal: Principal = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> MetricResult:
    if query.filters.entity_id:
        entity = await db.get(Entity, query.filters.entity_id)
        if entity is None or not principal.access.can_see(entity):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден")
    return MetricResult(
        metric=query.metric, group_by=query.group_by, period=query.period,
        rows=await aggregate(db, query, scope=readable(principal)),
    )
