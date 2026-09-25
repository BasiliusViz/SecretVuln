"""POST /imports: адрес проекта путём, автосоздание, файл настроек."""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.api.imports import _read_config
from app.authz.enforcer import set_role_permissions
from app.models import Import
from app.services.config_file import MAX_CONFIG_SIZE
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


async def test_auto_create_name_conflict_gets_unique_name(client, admin, db):
    _, h = admin
    # Корневой узел с тем же именем, что первый сегмент пути, но другим slug —
    # ensure_path(create=False) его не находит (path_cache не совпадает); ensure_path(create=True)
    # больше не падает на уникальности (parent_id, name) — подбирает уникальное имя «fintech-2».
    await make_entity(db, "fintech", slug="fintech-old")
    r = await client.post(
        "/api/v1/imports",
        data={"project_path": "fintech/x", "auto_create": "true"},
        files=_files(), headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["created_entities"][0]["path"] == "fintech"

    created = (await client.get("/api/v1/entities/by-path/fintech", headers=h)).json()
    assert created["name"] == "fintech-2"


async def test_auto_create_genuine_name_race_still_409s(client, admin, db, monkeypatch):
    """Настоящая гонка (concurrent insert обходит проверку уникальности) — IntegrityError
    по uq_entities_parent_name должен вернуть 409, а не 500."""
    import app.services.entity_paths as entity_paths_mod

    _, h = admin
    await make_entity(db, "fintech")

    async def _fake_unique_name(*_args, **_kwargs):
        return "fintech"

    monkeypatch.setattr(entity_paths_mod, "unique_name", _fake_unique_name)
    r = await client.post(
        "/api/v1/imports",
        data={"project_path": "other-root/x", "auto_create": "true"},
        files=_files(), headers=h,
    )
    assert r.status_code == 409, r.text
    assert await db.scalar(select(func.count()).select_from(Import)) == 0


async def test_config_branch_checked_against_sarif_provenance_when_form_branch_empty(
    client, admin, db
):
    """Форма branch пустая, но SARIF содержит provenance-ветку, отличную от default_branch
    из конфига — импорт должен быть отклонён ДО применения конфига к проекту (422),
    Import не создаётся, настройки проекта не меняются."""
    _, h = admin
    entity = await make_entity(db, "svc", repo_url="https://gitlab.corp/old/repo")
    sarif = make_sarif(
        "Semgrep", [{"fp": "a"}], provenance={"branch": "feature", "revisionId": "abc"}
    )
    r = await client.post(
        "/api/v1/imports",
        data={"project_path": "svc"},
        files={
            "file": ("s.sarif", sarif, "application/json"),
            "config": (".secretvuln.yml", b"version: 1\ndefault_branch: main\n", "application/x-yaml"),
        },
        headers=h,
    )
    assert r.status_code == 422, r.text
    assert "main" in r.json()["detail"]
    assert await db.scalar(select(func.count()).select_from(Import)) == 0

    await db.refresh(entity)
    assert entity.default_branch is None
    assert entity.repo_url == "https://gitlab.corp/old/repo"


async def test_read_config_bounds_the_read_size():
    """Не читаем весь файл целиком ради проверки размера — максимум MAX_CONFIG_SIZE + 1 байт."""
    fake = AsyncMock()
    fake.read = AsyncMock(return_value=b"x" * (MAX_CONFIG_SIZE + 1))
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await _read_config(fake)
    assert exc.value.status_code == 422
    fake.read.assert_awaited_once_with(MAX_CONFIG_SIZE + 1)


async def test_legacy_endpoint_accepts_config(client, admin, db):
    _, h = admin
    await make_group(db, "payments")
    e = await make_entity(db, "svc")
    r = await client.post(f"/api/v1/entities/{e.id}/imports", files=_files(CONFIG), headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["entity_path"] == "svc"
