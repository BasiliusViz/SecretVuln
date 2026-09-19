from sqlalchemy import select

from app.models import Finding, FindingEvent
from app.models.finding import FindingStatus
from app.models.finding_event import FindingEventType
from app.services.import_processing import apply_import
from app.services.sarif import parse_sarif
from tests.factories import make_entity, make_import, make_sarif


async def _import(db, entity, fps, scanner="Semgrep", **kw):
    imp = await make_import(db, entity, **kw)
    stats = await apply_import(
        db, imp, parse_sarif(make_sarif(scanner, [{"fp": fp} for fp in fps]))
    )
    await db.commit()
    return stats


async def _status(db, fp):
    f = await db.scalar(select(Finding).where(Finding.fingerprint == fp))
    await db.refresh(f)
    return f.status


async def test_missing_finding_is_closed(db):
    entity = await make_entity(db)
    await _import(db, entity, ["a", "b"])
    stats = await _import(db, entity, ["a"])
    assert stats["closed"] == 1
    assert await _status(db, "b") == FindingStatus.fixed
    assert await _status(db, "a") == FindingStatus.new
    f = await db.scalar(select(Finding).where(Finding.fingerprint == "b"))
    ev = await db.scalar(
        select(FindingEvent).where(
            FindingEvent.finding_id == f.id, FindingEvent.event_type == FindingEventType.auto_fixed
        )
    )
    assert ev is not None and ev.from_status == FindingStatus.new


async def test_decided_findings_are_not_closed(db):
    entity = await make_entity(db)
    await _import(db, entity, ["a", "b"])
    f = await db.scalar(select(Finding).where(Finding.fingerprint == "b"))
    f.status = FindingStatus.false_positive
    await db.commit()
    stats = await _import(db, entity, ["a"])
    assert stats["closed"] == 0
    assert await _status(db, "b") == FindingStatus.false_positive


async def test_other_scope_and_scanner_untouched(db):
    entity = await make_entity(db)
    await _import(db, entity, ["api1"], scanner="Trivy", scan_scope="api:latest")
    await _import(db, entity, ["w1"], scanner="Trivy", scan_scope="worker:latest")
    await _import(db, entity, ["s1"], scanner="Semgrep")
    stats = await _import(db, entity, ["api2"], scanner="Trivy", scan_scope="api:latest")
    assert stats["closed"] == 1
    assert await _status(db, "api1") == FindingStatus.fixed
    assert await _status(db, "w1") == FindingStatus.new
    assert await _status(db, "s1") == FindingStatus.new


async def test_empty_report_needs_confirmation(db):
    entity = await make_entity(db)
    await _import(db, entity, ["a"])
    stats = await _import(db, entity, [])
    assert stats["closed"] == 0
    assert stats["warnings"]
    assert await _status(db, "a") == FindingStatus.new

    stats = await _import(db, entity, [], confirm_empty=True)
    assert stats["closed"] == 1
    assert await _status(db, "a") == FindingStatus.fixed


async def test_close_missing_disabled(db):
    entity = await make_entity(db)
    await _import(db, entity, ["a", "b"])
    stats = await _import(db, entity, ["a"], close_missing=False)
    assert stats["closed"] == 0
    assert await _status(db, "b") == FindingStatus.new


async def test_in_progress_is_closed(db):
    entity = await make_entity(db)
    await _import(db, entity, ["a", "b"])
    f = await db.scalar(select(Finding).where(Finding.fingerprint == "b"))
    f.status = FindingStatus.in_progress
    await db.commit()
    await _import(db, entity, ["a"])
    assert await _status(db, "b") == FindingStatus.fixed
