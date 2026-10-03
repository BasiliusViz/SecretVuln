"""«Шумные правила»: правила сканеров, которые чаще всего оказываются ложными."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import Float, cast, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DecisionRequest, Finding
from app.models.decision_request import DecisionStatus, DecisionType
from app.models.finding import FindingStatus

# Решённые: человек посмотрел и вынес вердикт (new/triaged — ещё нет)
DECIDED_STATUSES = (
    FindingStatus.confirmed,
    FindingStatus.in_progress,
    FindingStatus.fixed,
    FindingStatus.false_positive,
    FindingStatus.risk_accepted,
)
TOP_REASONS = 3
LIMIT = 100


async def noisy_rules(db: AsyncSession, *, min_decided: int, min_fp_ratio: float) -> list[dict]:
    decided = func.count()
    fp = func.count().filter(Finding.status == FindingStatus.false_positive)
    ratio = cast(fp, Float) / decided
    rows = (await db.execute(
        select(Finding.scanner, Finding.rule_id, decided, fp)
        .where(Finding.status.in_(DECIDED_STATUSES), Finding.rule_id.is_not(None))
        .group_by(Finding.scanner, Finding.rule_id)
        .having(decided >= min_decided, ratio >= min_fp_ratio)
        .order_by(ratio.desc(), decided.desc())
        .limit(LIMIT)
    )).all()
    if not rows:
        return []

    reasons: dict[tuple[str, str], list[dict]] = defaultdict(list)
    keys = [(r[0], r[1]) for r in rows]
    reason_rows = await db.execute(
        select(Finding.scanner, Finding.rule_id, DecisionRequest.reason_tag, func.count())
        .join(DecisionRequest, DecisionRequest.finding_id == Finding.id)
        .where(
            Finding.status == FindingStatus.false_positive,
            DecisionRequest.decision_type == DecisionType.false_positive,
            DecisionRequest.status == DecisionStatus.approved,
            DecisionRequest.reason_tag.is_not(None),
            tuple_(Finding.scanner, Finding.rule_id).in_(keys),
        )
        .group_by(Finding.scanner, Finding.rule_id, DecisionRequest.reason_tag)
        .order_by(func.count().desc(), DecisionRequest.reason_tag)
    )
    for scanner, rule_id, tag, count in reason_rows:
        bucket = reasons[(scanner, rule_id)]
        if len(bucket) < TOP_REASONS:
            bucket.append({"reason_tag": tag.value, "count": count})

    return [
        {
            "scanner": scanner,
            "rule_id": rule_id,
            "decided": dec,
            "false_positive": fps,
            "fp_ratio": round(fps / dec, 3),
            "top_reasons": reasons.get((scanner, rule_id), []),
        }
        for scanner, rule_id, dec, fps in rows
    ]
