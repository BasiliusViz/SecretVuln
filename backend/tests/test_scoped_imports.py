"""Права на поддерево: загрузка импортов, автосоздание, файл настроек, списки."""

from __future__ import annotations

from tests.factories import make_import, make_sarif

SARIF = make_sarif("Semgrep", [{"fp": "a"}])
CONFIG = b"version: 1\ndefault_branch: main\n"


def _files(config: bytes | None = None):
    files = {"file": ("s.sarif", SARIF, "application/json")}
    if config is not None:
        files["config"] = (".secretvuln.yml", config, "application/x-yaml")
    return files


async def test_upload_by_node(client, two_teams):
    t = two_teams
    _, h = t.lead_a
    r = await client.post(f"/api/v1/entities/{t.a_svc.id}/imports", files=_files(), headers=h)
    assert r.status_code == 201, r.text
    r = await client.post(f"/api/v1/entities/{t.b_svc.id}/imports", files=_files(), headers=h)
    assert r.status_code == 404
    r = await client.post(
        "/api/v1/imports", data={"entity_id": str(t.b_svc.id)}, files=_files(), headers=h
    )
    assert r.status_code == 404
    # чужой проект по пути неотличим от несуществующего: тот же код и текст
    hidden = await client.post("/api/v1/imports", data={"project_path": "b/svc"}, files=_files(), headers=h)
    missing = await client.post("/api/v1/imports", data={"project_path": "b/nope"}, files=_files(), headers=h)
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json()["detail"].replace("b/svc", "X") == missing.json()["detail"].replace("b/nope", "X")


async def test_auto_create_under_nearest_ancestor(client, two_teams):
    _, h = two_teams.lead_a
    r = await client.post(
        "/api/v1/imports", data={"project_path": "a/new/api", "auto_create": "true"},
        files=_files(), headers=h,
    )
    assert r.status_code == 201, r.text
    assert [e["path"] for e in r.json()["created_entities"]] == ["a/new", "a/new/api"]
    r = await client.post(
        "/api/v1/imports", data={"project_path": "fresh/root", "auto_create": "true"},
        files=_files(), headers=h,
    )
    assert r.status_code == 403
    r = await client.post(
        "/api/v1/imports", data={"project_path": "b/new", "auto_create": "true"},
        files=_files(), headers=h,
    )
    assert r.status_code == 403  # как для несуществующего корня
    r = await client.post(
        "/api/v1/imports", data={"project_path": "b/svc", "auto_create": "true"},
        files=_files(), headers=h,
    )
    assert r.status_code == 403


async def test_config_needs_entity_write_on_node(client, two_teams, make_user, grant):
    from app.authz.enforcer import set_role_permissions

    t = two_teams
    set_role_permissions("CI", [("import", "import"), ("entity", "read")])
    user, h = await make_user("ci-a@test.local")
    await grant(user, "CI", t.a)
    await grant(user, "Руководитель команды", t.b)  # entity:write, но на другой ветке
    r = await client.post(
        f"/api/v1/entities/{t.a_svc.id}/imports", files=_files(CONFIG), headers=h
    )
    assert r.status_code == 403
    _, lead = t.lead_a
    r = await client.post(
        f"/api/v1/entities/{t.a_svc.id}/imports", files=_files(CONFIG), headers=lead
    )
    assert r.status_code == 201, r.text


async def test_import_lists_scoped(client, db, two_teams):
    t = two_teams
    ia = await make_import(db, t.a_svc)
    ib = await make_import(db, t.b_svc)
    _, h = t.dev_a
    ids = {i["id"] for i in (await client.get("/api/v1/imports", headers=h)).json()}
    assert ids == {str(ia.id)}
    assert (await client.get(f"/api/v1/imports/{ib.id}", headers=h)).status_code == 404
    assert (await client.get(f"/api/v1/imports/{ia.id}", headers=h)).status_code == 200
    r = await client.get(f"/api/v1/entities/{t.b_svc.id}/imports", headers=h)
    assert r.status_code == 404
