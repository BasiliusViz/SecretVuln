"""Чтение справочников: состояние источников, устаревание, блок `intel` для находки."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Finding, User
from app.models.intel import (
    IntelBdu,
    IntelBduCve,
    IntelCwe,
    IntelEpss,
    IntelKev,
    IntelSource,
    IntelSourceState,
    IntelStatus,
)

# Сколько дней файл считается свежим (по file_date). БДУ и CWE не устаревают.
STALE_DAYS: dict[IntelSource, int] = {IntelSource.epss: 30, IntelSource.kev: 7}
# «Зависшая» загрузка (воркер упал) не блокирует новую дольше этого срока
LOADING_TIMEOUT = timedelta(hours=2)
STUCK_ERROR = "Загрузка не завершилась — загрузите файл ещё раз"


def _today() -> date:
    return datetime.now(timezone.utc).date()


def is_stale(source: IntelSource, file_date: date | None, today: date | None = None) -> bool:
    """Файл устарел: только для EPSS и KEV и только если данные вообще загружены."""
    days = STALE_DAYS.get(source)
    if days is None or file_date is None:
        return False
    return ((today or _today()) - file_date).days > days


def is_loading(state: IntelSourceState, now: datetime | None = None) -> bool:
    if state.status != IntelStatus.loading:
        return False
    if state.started_at is None:
        return True
    return (now or datetime.now(timezone.utc)) - state.started_at < LOADING_TIMEOUT


async def source_states(db: AsyncSession) -> dict[IntelSource, IntelSourceState | None]:
    rows = (await db.scalars(select(IntelSourceState))).all()
    by_source = {r.source: r for r in rows}
    return {s: by_source.get(s) for s in IntelSource}


async def sources_overview(db: AsyncSession) -> list[dict[str, Any]]:
    """Состояние всех четырёх источников для страницы «Справочники»."""
    states = await source_states(db)
    user_ids = {s.loaded_by for s in states.values() if s and s.loaded_by}
    emails = (
        dict((await db.execute(select(User.id, User.email).where(User.id.in_(user_ids)))).all())
        if user_ids else {}
    )
    out = []
    for source, st in states.items():
        status = st.status if st else IntelStatus.idle
        error = st.error if st else None
        if st and status == IntelStatus.loading and not is_loading(st):
            status = IntelStatus.failed  # воркер не отчитался за LOADING_TIMEOUT — зависла
            error = STUCK_ERROR
        out.append({
            "source": source,
            "status": status,
            "loaded_at": st.loaded_at if st else None,
            "loaded_by": emails.get(st.loaded_by) if st and st.loaded_by else None,
            "file_date": st.file_date if st else None,
            "record_count": st.record_count if st else None,
            "error": error,
            "stale": is_stale(source, st.file_date if st else None),
            "stale_after_days": STALE_DAYS.get(source),
        })
    return out


async def finding_intel(db: AsyncSession, finding: Finding) -> dict[str, Any] | None:
    """Блок `intel` карточки находки. None — ни CVE, ни CWE нет."""
    cves: list[str] = list(finding.cves or [])
    cwe_row = await db.get(IntelCwe, finding.cwe.upper()) if finding.cwe else None
    if not cves and not finding.cwe:
        return None

    epss = kev = {}
    bdu_by_cve: dict[str, list[dict[str, Any]]] = {}
    if cves:
        epss = {r.cve_id: r for r in (await db.scalars(
            select(IntelEpss).where(IntelEpss.cve_id.in_(cves)))).all()}
        kev = {r.cve_id: r for r in (await db.scalars(
            select(IntelKev).where(IntelKev.cve_id.in_(cves)))).all()}
        rows = (await db.execute(
            select(IntelBduCve.cve_id, IntelBdu)
            .join(IntelBdu, IntelBdu.bdu_id == IntelBduCve.bdu_id)
            .where(IntelBduCve.cve_id.in_(cves))
            .order_by(IntelBdu.bdu_id)
        )).all()
        for cve_id, bdu in rows:
            bdu_by_cve.setdefault(cve_id, []).append(
                {"id": bdu.bdu_id, "name": bdu.name, "severity": bdu.severity}
            )

    states = await source_states(db)
    stale = [
        s.value for s, st in states.items() if st and st.status != IntelStatus.idle
        and is_stale(s, st.file_date)
    ]
    return {
        "cwe": {
            "id": finding.cwe.upper(),
            "name": cwe_row.name if cwe_row else None,
            "category": cwe_row.category if cwe_row else None,
        } if finding.cwe else None,
        "cves": [
            {
                "id": c,
                "epss": epss[c].epss if c in epss else None,
                "percentile": epss[c].percentile if c in epss else None,
                "kev": {
                    "date_added": kev[c].date_added,
                    "due_date": kev[c].due_date,
                    "name": kev[c].name,
                    "ransomware": kev[c].ransomware,
                } if c in kev else None,
                "bdu": bdu_by_cve.get(c, []),
            }
            for c in cves
        ],
        "stale": stale,
        "sources": {
            s.value: (st.file_date if st else None) for s, st in states.items()
        },
    }
