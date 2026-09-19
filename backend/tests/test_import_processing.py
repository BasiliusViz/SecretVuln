from sqlalchemy import select

from app.models import Finding
from app.models.finding import FindingStatus
from app.services.import_processing import apply_import
from app.services.sarif import parse_sarif
from tests.factories import make_entity, make_import, make_sarif


async def _run(db, entity, results, **import_kw):
    imp = await make_import(db, entity, **import_kw)
    stats = await apply_import(db, imp, parse_sarif(make_sarif("Semgrep", results)))
    await db.commit()
    return imp, stats


async def test_creates_findings(db):
    entity = await make_entity(db)
    imp, stats = await _run(db, entity, [{"fp": "a"}, {"fp": "b"}])
    assert stats["created"] == 2
    assert stats["total_results"] == 2
    assert imp.scanner == "Semgrep"
    rows = (await db.scalars(select(Finding).where(Finding.entity_id == entity.id))).all()
    assert {f.fingerprint for f in rows} == {"a", "b"}


async def test_reimport_counts_duplicates(db):
    entity = await make_entity(db)
    await _run(db, entity, [{"fp": "a"}, {"fp": "b"}])
    _, stats = await _run(db, entity, [{"fp": "a"}, {"fp": "b"}])
    assert stats["created"] == 0
    assert stats["duplicates"] == 2


async def test_fixed_finding_reopens(db):
    entity = await make_entity(db)
    await _run(db, entity, [{"fp": "a"}])
    finding = await db.scalar(select(Finding).where(Finding.fingerprint == "a"))
    finding.status = FindingStatus.fixed
    await db.commit()

    _, stats = await _run(db, entity, [{"fp": "a"}])
    await db.refresh(finding)
    assert finding.status == FindingStatus.new
    assert stats["updated"] == 1
