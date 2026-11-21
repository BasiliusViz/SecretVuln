"""Загрузка справочника: замена таблицы, откат при ошибке, пересчёт сводных полей, аудит."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import func, select

from app.models import AuditLog, Finding, IntelEpss, IntelKev
from app.models.intel import IntelBduCve, IntelSource, IntelSourceState, IntelStatus
from app.services.intel.enrich import enrich_findings, recompute_findings
from app.services.intel.loader import load_source
from tests.factories import make_entity, make_finding

FIX = Path(__file__).parent / "fixtures" / "intel"


async def _count(db, model) -> int:
    return await db.scalar(select(func.count()).select_from(model))


async def test_load_replaces_table_and_sets_state(db, admin):
    db.add(IntelEpss(cve_id="CVE-2000-0001", epss=0.5, percentile=0.5))
    await db.commit()

    state = await load_source(db, IntelSource.epss, FIX / "epss.csv", user_id=admin[0].id)

    assert state.status == IntelStatus.ok
    assert state.record_count == 3
    assert state.file_date == date(2026, 11, 20)
    assert state.loaded_by == admin[0].id and state.loaded_at is not None
    assert state.error is None
    assert await _count(db, IntelEpss) == 3
    assert await db.get(IntelEpss, "CVE-2000-0001") is None
    log = (await db.scalars(select(AuditLog).where(AuditLog.action == "intel.load"))).one()
    assert log.actor_id == admin[0].id
    assert log.changes["source"] == "epss" and log.changes["record_count"] == 3


async def test_failed_load_keeps_old_data(db, admin):
    db.add(IntelKev(cve_id="CVE-2000-0001", ransomware=False))
    await db.commit()

    state = await load_source(db, IntelSource.kev, FIX / "kev_wrong.json", user_id=admin[0].id)

    assert state.status == IntelStatus.failed
    assert "KEV" in state.error
    assert await db.get(IntelKev, "CVE-2000-0001") is not None
    log = (await db.scalars(select(AuditLog).where(AuditLog.action == "intel.load"))).one()
    assert log.changes["status"] == "failed" and "KEV" in log.changes["error"]


async def test_previous_successful_state_kept_on_failure(db, admin):
    await load_source(db, IntelSource.kev, FIX / "kev.json", user_id=admin[0].id)
    state = await load_source(db, IntelSource.kev, FIX / "kev_wrong.json", user_id=admin[0].id)
    # данные прошлой загрузки на месте — и сведения о них тоже
    assert state.status == IntelStatus.failed
    assert state.record_count == 2
    assert state.file_date == date(2026, 11, 19)


async def test_load_recomputes_findings(db, admin):
    e = await make_entity(db)
    f1 = await make_finding(db, e, "a", cves=["CVE-2021-44228", "CVE-2014-0160"])
    f2 = await make_finding(db, e, "b", cves=["CVE-2099-0001"], kev=True, epss_max=0.3)
    f3 = await make_finding(db, e, "c")

    await load_source(db, IntelSource.epss, FIX / "epss.csv")
    await load_source(db, IntelSource.kev, FIX / "kev.json")
    await load_source(db, IntelSource.bdu, FIX / "bdu.xml")

    for f in (f1, f2, f3):
        await db.refresh(f)
    assert f1.epss_max == 0.94489 and f1.kev is True and f1.has_bdu is True
    # CVE нет в справочниках — сводные поля сбрасываются
    assert f2.epss_max is None and f2.kev is False and f2.has_bdu is False
    assert f3.epss_max is None and f3.kev is False
    assert await _count(db, IntelBduCve) == 2


async def test_enrich_selected_findings(db):
    e = await make_entity(db)
    db.add(IntelKev(cve_id="CVE-2021-44228", ransomware=True))
    await db.commit()
    f1 = await make_finding(db, e, "a", cves=["CVE-2021-44228"])
    f2 = await make_finding(db, e, "b", cves=["CVE-2021-44228"])

    await enrich_findings(db, [f1.id])
    await db.commit()
    await db.refresh(f1)
    await db.refresh(f2)
    assert f1.kev is True and f2.kev is False

    await recompute_findings(db)
    await db.commit()
    await db.refresh(f2)
    assert f2.kev is True


async def test_state_row_created_if_missing(db):
    # строки intel_sources создаёт миграция, но тестовая БД их чистит — загрузчик сам создаёт
    await load_source(db, IntelSource.cwe, FIX / "cwe.xml")
    state = await db.get(IntelSourceState, IntelSource.cwe)
    assert state.status == IntelStatus.ok
    assert await db.scalar(select(func.count()).select_from(Finding)) == 0


async def test_worker_job_loads_and_deletes_file(db, tmp_path, monkeypatch):
    import io

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.core.config import get_settings
    from app.services import storage
    from app.worker import load_intel

    settings = get_settings()
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    key = storage.save_stream(io.BytesIO((FIX / "kev.json").read_bytes()), "kev.json", "intel/kev")
    ctx = {"session_factory": async_sessionmaker(db.bind, expire_on_commit=False)}

    await load_intel(ctx, "kev", key, None)

    state = await db.get(IntelSourceState, IntelSource.kev, populate_existing=True)
    assert state.status == IntelStatus.ok and state.record_count == 2
    assert not (tmp_path / key).exists()

    # файла нет в хранилище — источник не висит в loading
    await load_intel(ctx, "kev", "intel/kev/missing/kev.json", None)
    state = await db.get(IntelSourceState, IntelSource.kev, populate_existing=True)
    assert state.status == IntelStatus.failed
