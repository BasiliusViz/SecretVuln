"""API справочников: право intel:manage (только глобальное), загрузка, 409, лимиты, статус."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.authz.enforcer import set_role_permissions
from app.core.config import get_settings
from app.models.intel import IntelSource, IntelSourceState, IntelStatus
from app.services.intel.loader import load_source
from tests.factories import make_entity

FIX = Path(__file__).parent / "fixtures" / "intel"


@pytest.fixture
def intel_env(client, tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "storage_path", str(tmp_path))
    jobs: list[tuple] = []

    async def _fake(source, key, user_id):
        jobs.append((source, key, user_id))

    monkeypatch.setattr("app.worker.enqueue_intel", _fake)
    return jobs, tmp_path


def _file(name: str, fixture: str | None = None, content: bytes | None = None):
    data = content if content is not None else (FIX / (fixture or name)).read_bytes()
    return {"file": (name, data, "application/octet-stream")}


async def test_upload_enqueues_and_marks_loading(client, admin, intel_env, db):
    jobs, root = intel_env
    user, headers = admin
    r = await client.post("/api/v1/intel/kev", files=_file("kev.json"), headers=headers)
    assert r.status_code == 202, r.text
    assert r.json() == {"source": "kev", "status": "loading"}
    [(source, key, user_id)] = jobs
    assert source == "kev" and user_id == str(user.id)
    assert key.startswith("intel/kev/") and (root / key).is_file()
    state = await db.get(IntelSourceState, IntelSource.kev)
    assert state.status == IntelStatus.loading and state.started_at is not None


async def test_parallel_upload_409(client, admin, intel_env):
    _, headers = admin
    r = await client.post("/api/v1/intel/kev", files=_file("kev.json"), headers=headers)
    assert r.status_code == 202
    r = await client.post("/api/v1/intel/kev", files=_file("kev.json"), headers=headers)
    assert r.status_code == 409
    assert r.json()["detail"] == "Загрузка уже идёт"
    # другой источник грузить можно
    r = await client.post("/api/v1/intel/epss", files=_file("epss.csv"), headers=headers)
    assert r.status_code == 202


async def test_stuck_loading_does_not_block(client, admin, intel_env, db):
    _, headers = admin
    db.add(IntelSourceState(
        source=IntelSource.kev, status=IntelStatus.loading,
        started_at=datetime.now(timezone.utc) - timedelta(hours=3),
    ))
    await db.commit()
    r = await client.get("/api/v1/intel", headers=headers)
    kev = next(s for s in r.json() if s["source"] == "kev")
    assert kev["status"] == "failed" and kev["error"]
    r = await client.post("/api/v1/intel/kev", files=_file("kev.json"), headers=headers)
    assert r.status_code == 202


async def test_wrong_extension_400(client, admin, intel_env):
    _, headers = admin
    r = await client.post("/api/v1/intel/kev", files=_file("kev.xlsx", "kev.json"), headers=headers)
    assert r.status_code == 400
    assert intel_env[0] == []


async def test_too_large_413(client, admin, intel_env, monkeypatch):
    _, headers = admin
    monkeypatch.setattr(get_settings(), "intel_max_mb", 0)
    r = await client.post("/api/v1/intel/epss", files=_file("epss.csv"), headers=headers)
    assert r.status_code == 413
    assert intel_env[0] == []


async def test_permission_required(client, make_user, intel_env, builtin_policies):
    _, headers = await make_user("dev@test.local", roles=("Инженер ИБ",))
    assert (await client.get("/api/v1/intel", headers=headers)).status_code == 403
    r = await client.post("/api/v1/intel/kev", files=_file("kev.json"), headers=headers)
    assert r.status_code == 403


async def test_admin_role_has_permission(client, make_user, intel_env, builtin_policies):
    _, headers = await make_user("adm@test.local", roles=("Администратор",))
    assert (await client.get("/api/v1/intel", headers=headers)).status_code == 200


async def test_project_binding_does_not_grant(client, db, make_user, grant, intel_env):
    from app.cli import BUILTIN_ROLES  # noqa: F401 — роль собираем сами

    set_role_permissions("Справочники", [("intel", "manage"), ("finding", "read")])
    entity = await make_entity(db, "svc")
    user, headers = await make_user("p@test.local")
    await grant(user, "Справочники", entity)
    assert (await client.get("/api/v1/intel", headers=headers)).status_code == 403
    r = await client.post("/api/v1/intel/kev", files=_file("kev.json"), headers=headers)
    assert r.status_code == 403
    # та же роль на всё дерево — даёт
    await grant(user, "Справочники")
    assert (await client.get("/api/v1/intel", headers=headers)).status_code == 200


async def test_list_sources_overview(client, admin, db):
    user, headers = admin
    await load_source(db, IntelSource.kev, FIX / "kev.json", user_id=user.id)
    r = await client.get("/api/v1/intel", headers=headers)
    assert r.status_code == 200
    by = {s["source"]: s for s in r.json()}
    assert list(by) == ["epss", "kev", "bdu", "cwe"]
    assert by["kev"]["status"] == "ok"
    assert by["kev"]["record_count"] == 2
    assert by["kev"]["file_date"] == "2026-11-19"
    assert by["kev"]["loaded_by"] == user.email
    assert by["kev"]["stale_after_days"] == 7
    # файл KEV от 19.11.2026 — сегодня он не моложе 7 дней только в будущем; проверяем логику
    assert by["kev"]["stale"] == ((datetime.now(timezone.utc).date() - date(2026, 11, 19)).days > 7)
    assert by["epss"]["status"] == "idle" and by["epss"]["stale"] is False
