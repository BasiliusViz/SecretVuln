from sqlalchemy import select

from app.models import Finding
from app.models.finding import FindingStatus
from app.services.import_processing import apply_import
from app.services.sarif import parse_sarif
from tests.factories import make_entity, make_import, make_sarif


async def _import(db, entity, fps):
    imp = await make_import(db, entity)
    await apply_import(db, imp, parse_sarif(make_sarif("Semgrep", [{"fp": fp} for fp in fps])))
    await db.commit()
    return imp


async def test_import_records_imported_event(client, admin, db):
    _, headers = admin
    entity = await make_entity(db)
    imp = await _import(db, entity, ["a"])
    finding = await db.scalar(select(Finding).where(Finding.fingerprint == "a"))

    r = await client.get(f"/api/v1/findings/{finding.id}/events", headers=headers)
    assert r.status_code == 200
    events = r.json()
    assert [e["event_type"] for e in events] == ["imported"]
    assert events[0]["actor_type"] == "system"
    assert events[0]["payload"]["import_id"] == str(imp.id)


async def test_reopen_records_event(client, admin, db):
    _, headers = admin
    entity = await make_entity(db)
    await _import(db, entity, ["a"])
    finding = await db.scalar(select(Finding).where(Finding.fingerprint == "a"))
    finding.status = FindingStatus.fixed
    await db.commit()
    await _import(db, entity, ["a"])

    events = (await client.get(f"/api/v1/findings/{finding.id}/events", headers=headers)).json()
    assert [e["event_type"] for e in events] == ["imported", "reopened"]
    assert events[1]["from_status"] == "fixed"
    assert events[1]["to_status"] == "new"


async def test_events_404_for_unknown_finding(client, admin):
    _, headers = admin
    r = await client.get(
        "/api/v1/findings/00000000-0000-0000-0000-000000000000/events", headers=headers
    )
    assert r.status_code == 404
