"""POST /imports: адрес проекта путём, автосоздание, файл настроек."""

from sqlalchemy import func, select

from app.authz.enforcer import set_role_permissions
from app.models import Import
from tests.factories import make_entity, make_group, make_sarif

SARIF = make_sarif("Semgrep", [{"fp": "a"}])
CONFIG = b"version: 1\ndefault_branch: main\nowner: payments\n"


def _files(config: bytes | None = None):
    files = {"file": ("s.sarif", SARIF, "application/json")}
    if config is not None:
        files["config"] = (".secretvuln.yml", config, "application/x-yaml")
    return files


async def test_auto_create_by_path(client, admin):
    _, h = admin
    r = await client.post(
        "/api/v1/imports",
        data={"project_path": "fintech/payments/api", "auto_create": "true"},
        files=_files(), headers=h,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["entity_path"] == "fintech/payments/api"
    assert [e["path"] for e in body["created_entities"]] == [
        "fintech", "fintech/payments", "fintech/payments/api",
    ]
    assert client.enqueued == [body["id"]]

    r = await client.post(
        "/api/v1/imports",
        data={"project_path": "fintech/payments/api", "auto_create": "true"},
        files=_files(), headers=h,
    )
    assert r.json()["created_entities"] == []
    assert r.json()["entity_id"] == body["entity_id"]


async def test_missing_path_without_auto_create_404(client, admin):
    _, h = admin
    r = await client.post(
        "/api/v1/imports", data={"project_path": "nope/x"}, files=_files(), headers=h
    )
    assert r.status_code == 404
    assert "auto_create" in r.json()["detail"]


async def test_entity_id_or_path_exactly_one(client, admin, db):
    _, h = admin
    e = await make_entity(db, "svc")
    r = await client.post(
        "/api/v1/imports",
        data={"project_path": "svc", "entity_id": str(e.id)},
        files=_files(), headers=h,
    )
    assert r.status_code == 422
    r = await client.post("/api/v1/imports", files=_files(), headers=h)
    assert r.status_code == 422


async def test_ci_role_without_entity_write(client, make_user, db):
    set_role_permissions("CI", [("import", "import")])
    _, h = await make_user("ci@test.local", roles=("CI",))
    await make_entity(db, "svc")

    r = await client.post(
        "/api/v1/imports", data={"project_path": "new/app", "auto_create": "true"},
        files=_files(), headers=h,
    )
    assert r.status_code == 403
    r = await client.post(
        "/api/v1/imports", data={"project_path": "svc"}, files=_files(CONFIG), headers=h
    )
    assert r.status_code == 403
    r = await client.post("/api/v1/imports", data={"project_path": "svc"}, files=_files(), headers=h)
    assert r.status_code == 201


async def test_bad_config_rejects_import(client, admin, db):
    _, h = admin
    await make_entity(db, "svc")
    r = await client.post(
        "/api/v1/imports", data={"project_path": "svc"},
        files=_files(b"version: 1\nbogus: 1"), headers=h,
    )
    assert r.status_code == 422
    assert ".secretvuln.yml" in r.json()["detail"]
    assert await db.scalar(select(func.count()).select_from(Import)) == 0


async def test_config_applied_with_warnings(client, admin, db):
    _, h = admin
    payments = await make_group(db, "payments")
    config = CONFIG + b"ownership:\n  - path: 'x/**'\n    owner: ghost\n"
    r = await client.post(
        "/api/v1/imports", data={"project_path": "svc", "auto_create": "true", "commit_sha": "c1"},
        files=_files(config), headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["config_warnings"] == [
        "ownership: группа «ghost» не найдена — правило «x/**» пропущено"
    ]
    settings = (await client.get(f"/api/v1/entities/{r.json()['entity_id']}/settings", headers=h)).json()
    assert settings["fields"]["owner_group_id"]["value"] == str(payments.id)
    assert settings["fields"]["owner_group_id"]["source"] == "file"
    assert settings["config_commit_sha"] == "c1"


async def test_config_branch_applies_before_branch_check(client, admin):
    _, h = admin
    r = await client.post(
        "/api/v1/imports",
        data={"project_path": "svc", "auto_create": "true", "branch": "feature-x"},
        files=_files(b"version: 1\ndefault_branch: main\n"), headers=h,
    )
    assert r.status_code == 422
    assert "main" in r.json()["detail"]


async def test_auto_create_conflict_409(client, admin, db):
    _, h = admin
    # Корневой узел с тем же именем, что первый сегмент пути, но другим slug —
    # ensure_path(create=False) его не находит (path_cache не совпадает),
    # а ensure_path(create=True) падает на уникальности (parent_id, name).
    await make_entity(db, "fintech", slug="fintech-old")
    r = await client.post(
        "/api/v1/imports",
        data={"project_path": "fintech/x", "auto_create": "true"},
        files=_files(), headers=h,
    )
    assert r.status_code == 409, r.text
    assert await db.scalar(select(func.count()).select_from(Import)) == 0


async def test_legacy_endpoint_accepts_config(client, admin, db):
    _, h = admin
    await make_group(db, "payments")
    e = await make_entity(db, "svc")
    r = await client.post(f"/api/v1/entities/{e.id}/imports", files=_files(CONFIG), headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["entity_path"] == "svc"
