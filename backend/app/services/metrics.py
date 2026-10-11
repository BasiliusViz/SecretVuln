"""Generic-агрегаты для виджетов дашборда.

Метрики:
- count     — открытые находки сейчас (срез);
- opened    — появились за период (по first_seen);
- resolved  — сколько находок закрыто за период;
- overdue   — открытые с истёкшим сроком сейчас (срез);
- sla_ratio — доля открытых со сроком, которые ещё не просрочены (срез; без due_at не участвуют);
- mttr_days — среднее «закрытие в fixed − first_seen» в днях по закрытиям за период.
  Считается по событиям, не по находкам: переоткрытая и снова исправленная находка
  входит дважды, второй раз — от того же first_seen (полное время от обнаружения).
- ai_agreement — процент (0–100) согласия людей с вердиктами ИИ по выводам «triage»
  за период (по created_at вывода); в строке ещё `count` — сколько выводов учтено.
  Явное согласие — вывод принят/отклонён; иначе неявное — по итоговому статусу находки.
  `uncertain` и находки без решения (new/triaged) не учитываются. От каждого агента по
  находке учитывается только последний вывод (повторный разбор не умножает голос), а
  «исправлено» подтверждает вердикт, только если так закрыл человек, а не автозакрытие.

resolved и mttr_days считаются по истории (`finding_events`: переход из открытого
статуса в закрытый), а не по `resolved_at`: переоткрытие обнуляет `resolved_at`,
и прошлое закрытие пропало бы из метрик задним числом.

group_by=week всегда ограничен периодом по «временной» колонке метрики.
"""

from __future__ import annotations

import enum
from datetime import datetime, timedelta, timezone

from sqlalchemy import Float, and_, case, cast, func, literal, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AiAnalysis, AiAnalysisKind, Entity, Finding, FindingEvent, UserGroup
from app.models.ai_analysis import AiReviewStatus, AiVerdict
from app.models.finding import CLOSED_STATUSES, OPEN_STATUSES, FindingStatus
from app.models.finding_event import FindingEventType
from app.schemas.metrics import MetricQuery, MetricRow
from app.services.entity_paths import subtree_ids
from app.services.entity_tree import entities_with_tag

MAX_GROUPS = 50
# 365 дней — до 54 недель (неполные по краям)
MAX_WEEKS = 54
PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90, "365d": 365}
# Колонка времени метрики: для периода и для группировки по неделям
TIME_COLUMN = {
    "count": Finding.first_seen,
    "opened": Finding.first_seen,
    "resolved": FindingEvent.created_at,
    "overdue": Finding.due_at,
    "sla_ratio": Finding.due_at,
    "mttr_days": FindingEvent.created_at,
    "ai_agreement": AiAnalysis.created_at,
}
# Метрики по событиям закрытия: Finding JOIN FindingEvent
CLOSURE = {"resolved", "mttr_days"}
# Метрики-срезы: период к ним не применяется (кроме группировки по неделям)
SNAPSHOT = {"count", "overdue", "sla_ratio"}
GROUP_COLUMN = {
    "severity": Finding.severity,
    "scanner": Finding.scanner,
    "team": Finding.assignee_group_id,
    "entity": Finding.entity_id,
    "ai_agent": AiAnalysis.agent,
    "ai_model": AiAnalysis.model,
}

# Статусы, которыми человек подтвердил, что уязвимость настоящая
_CONFIRMED = (FindingStatus.confirmed, FindingStatus.in_progress, FindingStatus.risk_accepted)
_FP, _TP = AiVerdict.false_positive, AiVerdict.true_positive
_IS_FP = Finding.status == FindingStatus.false_positive
# «исправлено» автозакрытием (находка пропала из скана) — не решение человека;
# смотрим последнее закрытие в fixed: прошлое ручное могло быть до переоткрытия
_FIXED_BY_HUMAN = and_(
    Finding.status == FindingStatus.fixed,
    select(FindingEvent.event_type)
    .where(FindingEvent.finding_id == Finding.id, FindingEvent.to_status == FindingStatus.fixed)
    .order_by(FindingEvent.created_at.desc(), FindingEvent.id.desc())
    .limit(1)
    .correlate(Finding)
    .scalar_subquery()
    != FindingEventType.auto_fixed,
)
_IS_CONFIRMED = or_(Finding.status.in_(_CONFIRMED), _FIXED_BY_HUMAN)
_Later = aliased(AiAnalysis)
# Последний вывод «triage» этого агента по находке
_IS_LATEST = AiAnalysis.id == (
    select(_Later.id)
    .where(
        _Later.finding_id == AiAnalysis.finding_id,
        _Later.agent.is_not_distinct_from(AiAnalysis.agent),
        _Later.kind == AiAnalysisKind.triage,
    )
    .order_by(_Later.created_at.desc(), _Later.id.desc())
    .limit(1)
    .correlate(AiAnalysis)
    .scalar_subquery()
)
# 1 — согласие, 0 — несогласие, NULL — вывод не учитывается
AGREEMENT = case(
    (AiAnalysis.review_status == AiReviewStatus.accepted, 1),
    (AiAnalysis.review_status == AiReviewStatus.rejected, 0),
    (and_(AiAnalysis.verdict == _FP, _IS_FP), 1),
    (and_(AiAnalysis.verdict == _FP, _IS_CONFIRMED), 0),
    (and_(AiAnalysis.verdict == _TP, _IS_CONFIRMED), 1),
    (and_(AiAnalysis.verdict == _TP, _IS_FP), 0),
    else_=None,
)


def _value(metric: str, now: datetime):
    if metric == "ai_agreement":
        return func.avg(AGREEMENT) * 100
    if metric == "sla_ratio":
        on_time = func.count().filter(Finding.due_at >= now)
        return cast(on_time, Float) / func.nullif(func.count(), 0)
    if metric == "mttr_days":
        return func.avg(func.extract("epoch", FindingEvent.created_at - Finding.first_seen)) / 86400
    if metric == "resolved":
        # закрытую, переоткрытую и снова закрытую за период считаем один раз
        return func.count(func.distinct(Finding.id))
    return func.count()


def _closure(to_statuses) -> list:
    """Событие перехода из открытого статуса в закрытый (смена «ложное → исправлено» — не закрытие)."""
    return [
        FindingEvent.to_status.in_(to_statuses),
        FindingEvent.from_status.is_(None) | FindingEvent.from_status.in_(OPEN_STATUSES),
    ]


def _metric_conditions(metric: str, now: datetime) -> list:
    if metric == "count":
        return [Finding.status.in_(OPEN_STATUSES)]
    if metric == "resolved":
        return _closure(CLOSED_STATUSES)
    if metric == "overdue":
        return [Finding.status.in_(OPEN_STATUSES), Finding.due_at < now]
    if metric == "sla_ratio":
        return [Finding.status.in_(OPEN_STATUSES), Finding.due_at.is_not(None)]
    if metric == "mttr_days":
        return _closure([FindingStatus.fixed])
    if metric == "ai_agreement":
        return [
            AiAnalysis.kind == AiAnalysisKind.triage,
            AiAnalysis.verdict.in_([_TP, _FP]),
            _IS_LATEST,
            AGREEMENT.is_not(None),
        ]
    return []


async def _filter_conditions(db: AsyncSession, query: MetricQuery) -> list:
    f = query.filters
    conds: list = []
    if f.severity:
        conds.append(Finding.severity.in_(f.severity))
    if f.scanner:
        conds.append(Finding.scanner == f.scanner)
    if f.entity_id:
        entity = await db.get(Entity, f.entity_id)
        conds.append(
            Finding.entity_id.in_(subtree_ids(entity)) if entity else Finding.entity_id == f.entity_id
        )
    if f.tag:
        conds.append(Finding.entity_id.in_(entities_with_tag(f.tag.strip().lower())))
    return conds


async def _labels(db: AsyncSession, group_by: str, keys: list) -> dict:
    ids = [k for k in keys if k is not None]
    if not ids:
        return {}
    if group_by == "team":
        return dict((await db.execute(select(UserGroup.id, UserGroup.name).where(UserGroup.id.in_(ids)))).all())
    if group_by == "entity":
        return dict((await db.execute(select(Entity.id, Entity.path_cache).where(Entity.id.in_(ids)))).all())
    return {}


async def aggregate(
    db: AsyncSession, query: MetricQuery, *, now: datetime | None = None, scope=None
) -> list[MetricRow]:
    """scope — SQL-условие на Finding (доступные вызывающему проекты); None — все."""
    now = now or datetime.now(timezone.utc)
    start = now - timedelta(days=PERIOD_DAYS[query.period])
    time_col = TIME_COLUMN[query.metric]
    value = _value(query.metric, now).label("value")

    conds = _metric_conditions(query.metric, now) + await _filter_conditions(db, query)
    if scope is not None:
        conds.append(scope)
    if query.metric not in SNAPSHOT or query.group_by == "week":
        conds.append(time_col >= start)

    if query.group_by == "none":
        group = literal("all")
    elif query.group_by == "week":
        group = func.date_trunc("week", func.timezone("UTC", time_col))
    else:
        group = GROUP_COLUMN[query.group_by]
    group = group.label("grp")

    is_ai = query.metric == "ai_agreement"
    q = select(group, value, (func.count() if is_ai else literal(None)).label("cnt"))
    if query.metric in CLOSURE:
        q = q.select_from(Finding).join(FindingEvent, FindingEvent.finding_id == Finding.id)
    elif is_ai:
        q = q.select_from(Finding).join(AiAnalysis, AiAnalysis.finding_id == Finding.id)
    q = q.where(*conds).group_by(group)
    if query.group_by == "week":
        q = q.order_by(group.desc())
    else:
        q = q.order_by(value.desc().nulls_last(), group)
    rows = (await db.execute(q.limit(MAX_WEEKS if query.group_by == "week" else MAX_GROUPS))).all()
    if query.group_by == "week":
        rows = list(reversed(rows))

    labels = await _labels(db, query.group_by, [r.grp for r in rows])
    result: list[MetricRow] = []
    for grp, val, cnt in rows:
        if grp is None:
            key = None
        elif query.group_by == "week":
            key = grp.date().isoformat()
        elif isinstance(grp, enum.Enum):
            key = grp.value
        else:
            key = str(grp)
        label = labels.get(grp, key) if grp is not None else None
        result.append(MetricRow(
            key=key, label=label, value=round(float(val), 4) if val is not None else None,
            count=cnt,
        ))
    if query.group_by == "none" and not result:
        empty = None if query.metric in ("sla_ratio", "mttr_days", "ai_agreement") else 0
        result.append(MetricRow(
            key="all", label="all", value=empty, count=0 if is_ai else None,
        ))
    return result
