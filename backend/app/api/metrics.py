"""Агрегаты для виджетов дашборда: тело запроса = JSON виджета."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.db.session import get_db
from app.schemas.metrics import MetricQuery, MetricResult
from app.services.metrics import aggregate

router = APIRouter(prefix="/api/v1/metrics", tags=["metrics"])


@router.post("/aggregate", response_model=MetricResult)
async def aggregate_metric(
    query: MetricQuery,
    _: object = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> MetricResult:
    return MetricResult(
        metric=query.metric, group_by=query.group_by, period=query.period,
        rows=await aggregate(db, query),
    )
