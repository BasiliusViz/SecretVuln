"""Импорты: кто загрузил (`uploaded_by`), фильтр «только мои», запись `import.create` в журнал."""

from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog
from app.services import audit
from tests.factories import make_entity, make_import, make_sarif


def _files():
    return {"file": ("r.sarif", make_sarif("Semgrep", []), "application/json")}


async def test_upload_sets_uploaded_by_and_logs(client, db, admin):
    user, h = admin
    e = await make_entity(db, "p")
    r = await client.post(f"/api/v1/entities/{e.id}/imports", files=_files(), headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["uploaded_by"] == {
        "id": str(user.id),
        "email": "admin@test.local",
        "display_name": None,
    }

    row = await db.scalar(select(AuditLog).where(AuditLog.action == audit.IMPORT_CREATE))
    assert row.entity_id == e.id and row.actor_id == user.id
    assert row.target_type == "import" and str(row.target_id) == body["id"]
    assert row.target_label == "r.sarif"
    assert row.changes["filename"] == "r.sarif"

    one = (await client.get(f"/api/v1/imports/{body['id']}", headers=h)).json()
    assert one["uploaded_by"]["email"] == "admin@test.local"
    listed = (await client.get(f"/api/v1/entities/{e.id}/imports", headers=h)).json()
    assert listed[0]["uploaded_by"]["id"] == str(user.id)


async def test_uploaded_by_null_and_filter_me(client, db, admin, make_user):
    user, h = admin
    other, _ = await make_user("other@test.local")
    e = await make_entity(db, "p")
    await make_import(db, e)  # без автора (как от старых версий/CI без пользователя)
    mine = await make_import(db, e, uploaded_by_id=user.id)
    await make_import(db, e, uploaded_by_id=other.id)

    all_ = (await client.get("/api/v1/imports", headers=h)).json()
    assert len(all_) == 3
    assert any(i["uploaded_by"] is None for i in all_)
    only = (await client.get("/api/v1/imports", params={"uploaded_by": "me"}, headers=h)).json()
    assert [i["id"] for i in only] == [str(mine.id)]
    r = await client.get("/api/v1/imports", params={"uploaded_by": "someone"}, headers=h)
    assert r.status_code == 422
