"""Этап 7: кнопка «Разобрать ИИ» (`POST /findings/{id}/ai-triage`) и `GET /ai/status`."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import AuditLog
from tests.factories import make_entity, make_finding


@pytest.fixture
def queued(monkeypatch) -> list[str]:
    calls: list[str] = []

    async def _fake(finding_id: str) -> bool:
        calls.append(finding_id)
        return True

    monkeypatch.setattr("app.worker.enqueue_ai_triage", _fake)
    return calls


@pytest.fixture
def ai_on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "ai_base_url", "http://llm.local/v1")
    monkeypatch.setattr(s, "ai_model", "fake-model")
    return s


async def test_trigger_enqueues_and_audits(client, db, admin, ai_on, queued):
    _, headers = admin
    finding = await make_finding(db, await make_entity(db))

    r = await client.post(f"/api/v1/findings/{finding.id}/ai-triage", headers=headers)
    assert r.status_code == 202, r.text
    assert r.json() == {"queued": True}
    # повторный разбор тоже ставится в очередь
    r = await client.post(f"/api/v1/findings/{finding.id}/ai-triage", headers=headers)
    assert r.status_code == 202
    assert queued == [str(finding.id), str(finding.id)]

    rows = list(await db.scalars(select(AuditLog).where(AuditLog.action == "ai_triage.request")))
    assert len(rows) == 2
    assert rows[0].target_type == "finding" and rows[0].target_id == finding.id
    assert rows[0].entity_id == finding.entity_id


async def test_trigger_disabled_is_503(client, db, admin, ai_on, queued, monkeypatch):
    monkeypatch.setattr(ai_on, "ai_base_url", "")
    _, headers = admin
    finding = await make_finding(db, await make_entity(db))

    r = await client.post(f"/api/v1/findings/{finding.id}/ai-triage", headers=headers)
    assert r.status_code == 503
    assert queued == []


async def test_trigger_needs_triage(client, db, make_user, grant, ai_on, queued):
    entity = await make_entity(db)
    finding = await make_finding(db, entity)
    viewer, headers = await make_user("viewer@test.local")
    await grant(viewer, "Наблюдатель", entity)  # без finding:triage
    agent, agent_headers = await make_user("agent@test.local")
    await grant(agent, "ИИ-агент", entity)  # finding:analyze — запись выводов, не запуск

    r = await client.post(f"/api/v1/findings/{finding.id}/ai-triage", headers=agent_headers)
    assert r.status_code == 403

    r = await client.post(f"/api/v1/findings/{finding.id}/ai-triage", headers=headers)
    assert r.status_code == 403
    assert queued == []


async def test_trigger_foreign_finding_is_404(client, db, make_user, grant, two_teams, ai_on,
                                              queued):
    user, headers = await make_user("analyst@test.local")
    await grant(user, "Разработчик", two_teams.a)
    mine = await make_finding(db, two_teams.a_svc, fingerprint="m")
    foreign = await make_finding(db, two_teams.b_svc, fingerprint="f")

    r = await client.post(f"/api/v1/findings/{foreign.id}/ai-triage", headers=headers)
    assert r.status_code == 404
    r = await client.post(f"/api/v1/findings/{mine.id}/ai-triage", headers=headers)
    assert r.status_code == 202
    assert queued == [str(mine.id)]


async def test_trigger_duplicate_not_audited(client, db, admin, ai_on, monkeypatch):
    async def _dup(finding_id: str) -> bool:
        return False  # разбор этой находки уже в очереди

    monkeypatch.setattr("app.worker.enqueue_ai_triage", _dup)
    _, headers = admin
    finding = await make_finding(db, await make_entity(db))

    r = await client.post(f"/api/v1/findings/{finding.id}/ai-triage", headers=headers)
    assert r.status_code == 202 and r.json() == {"queued": False}
    assert not list(await db.scalars(select(AuditLog).where(AuditLog.action == "ai_triage.request")))


async def test_trigger_queue_down_is_503_without_audit(client, db, admin, ai_on, monkeypatch):
    async def _down(finding_id: str) -> None:
        raise ConnectionError("redis down")

    monkeypatch.setattr("app.worker.enqueue_ai_triage", _down)
    _, headers = admin
    finding = await make_finding(db, await make_entity(db))

    r = await client.post(f"/api/v1/findings/{finding.id}/ai-triage", headers=headers)
    assert r.status_code == 503
    assert not list(await db.scalars(select(AuditLog).where(AuditLog.action == "ai_triage.request")))


async def test_status(client, developer, ai_on, monkeypatch):
    _, headers = developer
    r = await client.get("/api/v1/ai/status", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"enabled": True, "model": "fake-model"}

    monkeypatch.setattr(ai_on, "ai_base_url", "")
    r = await client.get("/api/v1/ai/status", headers=headers)
    assert r.json() == {"enabled": False, "model": None}


async def test_status_requires_login(client):
    r = await client.get("/api/v1/ai/status")
    assert r.status_code == 401
