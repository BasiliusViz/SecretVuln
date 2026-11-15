"""Правила команды: API, права на поддерево, пересчёт, запрос по правилу, предложения, MCP."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.deps import Principal
from app.models import (
    AuditLog,
    DecisionRequest,
    FindingEvent,
    FindingEventType,
    MemorySource,
    MemoryStatus,
    TriageMemory,
)
from app.models.finding import FindingStatus
from app.services import agent_tools
from app.services.access import load_access
from tests.factories import make_entity, make_finding, make_memory

URL = "/api/v1/memories"
FP = {"decision": "false_positive", "reason_tag": "test_code"}


async def _refresh(db, *objs):
    for o in objs:
        await db.refresh(o)


async def _audit(db, action):
    return (await db.scalars(select(AuditLog).where(AuditLog.action == action))).all()


# --- создание и проверка полей ---


async def test_create_applies_to_open_findings_and_audits(client, db, admin):
    _, h = admin
    root = await make_entity(db, "fintech")
    svc = await make_entity(db, "api", parent_id=root.id)
    hit = await make_finding(db, svc, "f1", rule_id="rule.a", file_path="tests/a.py")
    miss = await make_finding(db, svc, "f2", rule_id="rule.a", file_path="src/a.py")
    closed = await make_finding(
        db, svc, "f3", rule_id="rule.a", file_path="tests/b.py", status=FindingStatus.fixed
    )

    r = await client.post(
        URL, headers=h,
        json={"entity_id": str(root.id), "rule_id": " rule.a ", "path_glob": "tests/**", **FP},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "approved" and body["source"] == "manual"
    assert body["rule_id"] == "rule.a" and body["entity_path"] == "fintech"
    assert body["open_findings"] == 1 and body["can_manage"] is True
    assert body["approved_at"] and body["approved_by"] == str(admin[0].id)

    await _refresh(db, hit, miss, closed)
    assert str(hit.memory_id) == body["id"]
    assert miss.memory_id is None and closed.memory_id is None
    assert hit.status == FindingStatus.new  # подсказка статус не меняет
    events = (
        await db.scalars(
            select(FindingEvent).where(FindingEvent.event_type == FindingEventType.memory_hint)
        )
    ).all()
    assert [e.finding_id for e in events] == [hit.id]

    (row,) = await _audit(db, "memory.create")
    assert row.entity_path == "fintech" and row.target_label == "rule.a · tests/**"
    assert row.changes["hints_changed"] == 1 and row.changes["path_glob"] == "tests/**"

    # находка отдаёт краткое правило, фильтр has_memory работает
    r = await client.get("/api/v1/findings", params={"has_memory": True}, headers=h)
    (item,) = r.json()
    assert item["id"] == str(hit.id)
    assert item["memory"] == {
        "id": body["id"], "decision": "false_positive", "reason_tag": "test_code", "reason": None,
    }
    r = await client.get("/api/v1/findings", params={"has_memory": False}, headers=h)
    assert {f["id"] for f in r.json()} == {str(miss.id), str(closed.id)}
    r = await client.get(f"/api/v1/findings/{hit.id}", headers=h)
    assert r.json()["memory"]["id"] == body["id"]


@pytest.mark.parametrize(
    "payload",
    [
        {**FP},  # ни одного условия
        {**FP, "rule_id": "   "},
        {"decision": "false_positive", "rule_id": "r"},  # нет причины
        {"decision": "false_positive", "reason_tag": "other", "rule_id": "r"},  # «другое» без текста
        {"decision": "risk_accepted", "rule_id": "r"},  # риск без обоснования
    ],
)
async def test_create_validation(client, db, admin, payload):
    entity = await make_entity(db)
    r = await client.post(URL, headers=admin[1], json={"entity_id": str(entity.id), **payload})
    assert r.status_code == 422, r.text


# --- права ---


async def test_rights_on_subtree(client, db, two_teams, make_user, grant):
    t = two_teams
    appsec_a = await make_user("appsec-a@test.local")
    await grant(appsec_a[0], "Инженер ИБ", t.a)
    _, h = appsec_a

    # своя ветка — можно; чужая — проекта «нет»; без права — 403
    r = await client.post(URL, headers=h, json={"entity_id": str(t.a_svc.id), "rule_id": "r", **FP})
    assert r.status_code == 201, r.text
    mine = r.json()["id"]
    r = await client.post(URL, headers=h, json={"entity_id": str(t.b.id), "rule_id": "r", **FP})
    assert r.status_code == 404
    r = await client.post(
        URL, headers=t.dev_a[1], json={"entity_id": str(t.a_svc.id), "rule_id": "r", **FP}
    )
    assert r.status_code == 403

    foreign = await make_memory(db, t.b)
    for method, url in (("GET", f"{URL}/{foreign.id}"), ("PATCH", f"{URL}/{foreign.id}")):
        r = await client.request(method, url, headers=h, json={"status": "disabled"})
        assert r.status_code == 404, (method, r.status_code)

    # читатель видит, но менять не может
    r = await client.get(f"{URL}/{mine}", headers=t.dev_a[1])
    assert r.status_code == 200 and r.json()["can_manage"] is False
    r = await client.patch(f"{URL}/{mine}", headers=t.dev_a[1], json={"status": "disabled"})
    assert r.status_code == 403

    # перенос области в чужую ветку запрещён
    r = await client.patch(f"{URL}/{mine}", headers=h, json={"entity_id": str(t.b.id)})
    assert r.status_code == 404
    assert (await db.scalar(select(TriageMemory.entity_id).where(TriageMemory.id == foreign.id)))


async def test_ancestor_rules_are_visible_but_not_manageable(client, db, two_teams, make_user, grant):
    t = two_teams
    on_a = await make_memory(db, t.a)            # предок
    on_svc = await make_memory(db, t.a_svc)      # сам проект
    on_b = await make_memory(db, t.b)            # чужая ветка
    deep = await make_user("deep@test.local")
    await grant(deep[0], "Инженер ИБ", t.a_svc)
    _, h = deep

    rows = (await client.get(URL, headers=h)).json()
    assert {m["id"] for m in rows} == {str(on_a.id), str(on_svc.id)}
    by_id = {m["id"]: m for m in rows}
    assert by_id[str(on_a.id)]["can_manage"] is False
    assert by_id[str(on_svc.id)]["can_manage"] is True

    assert (await client.get(f"{URL}/{on_a.id}", headers=h)).status_code == 200
    assert (await client.get(f"{URL}/{on_b.id}", headers=h)).status_code == 404
    r = await client.patch(f"{URL}/{on_a.id}", headers=h, json={"status": "disabled"})
    assert r.status_code == 403

    rows = (await client.get(URL, params={"manageable": True}, headers=h)).json()
    assert {m["id"] for m in rows} == {str(on_svc.id)}


async def test_list_filters(client, db, admin):
    _, h = admin
    root = await make_entity(db, "fintech")
    svc = await make_entity(db, "api", parent_id=root.id)
    other = await make_entity(db, "other")
    on_root = await make_memory(db, root)
    on_svc = await make_memory(db, svc, status=MemoryStatus.suggested)
    await make_memory(db, other)

    async def ids(**params):
        r = await client.get(URL, params=params, headers=h)
        assert r.status_code == 200, r.text
        return {m["id"] for m in r.json()}

    assert await ids(status="suggested") == {str(on_svc.id)}
    # проект: его правила и правила предков; с потомками — ещё и поддерево
    assert await ids(entity_id=str(svc.id)) == {str(on_root.id), str(on_svc.id)}
    assert await ids(entity_id=str(root.id)) == {str(on_root.id)}
    assert await ids(entity_id=str(root.id), include_descendants=True) == {
        str(on_root.id), str(on_svc.id)
    }


# --- утверждение, правка, выключение ---


async def test_approve_edit_disable_recompute_and_audit(client, db, admin):
    _, h = admin
    entity = await make_entity(db)
    in_tests = await make_finding(db, entity, "f1", rule_id="rule.a", file_path="tests/a.py")
    in_src = await make_finding(db, entity, "f2", rule_id="rule.a", file_path="src/a.py")
    memory = await make_memory(
        db, entity, status=MemoryStatus.suggested, source=MemorySource.suggested,
        reason_tag="test_code",
    )
    url = f"{URL}/{memory.id}"

    # правка предложенного ничего не применяет
    r = await client.patch(url, headers=h, json={"path_glob": "tests/**"})
    assert r.status_code == 200, r.text
    await _refresh(db, in_tests, in_src)
    assert in_tests.memory_id is None

    r = await client.patch(url, headers=h, json={"status": "approved"})
    assert r.status_code == 200 and r.json()["open_findings"] == 1
    assert r.json()["approved_by"] == str(admin[0].id)
    await _refresh(db, in_tests, in_src)
    assert in_tests.memory_id == memory.id and in_src.memory_id is None

    # правка условия действующего правила = пересчёт
    r = await client.patch(url, headers=h, json={"path_glob": None})
    assert r.json()["open_findings"] == 2
    await _refresh(db, in_tests, in_src)
    assert in_src.memory_id == memory.id

    # правка обоснования подсказки не трогает
    r = await client.patch(url, headers=h, json={"reason": "Новый текст"})
    assert r.status_code == 200 and r.json()["reason"] == "Новый текст"

    # нельзя оставить правило без условий или без причины
    assert (await client.patch(url, headers=h, json={"rule_id": None})).status_code == 422
    assert (await client.patch(url, headers=h, json={"reason_tag": None})).status_code == 422
    assert (await client.patch(url, headers=h, json={"status": "suggested"})).status_code == 422

    r = await client.patch(url, headers=h, json={"status": "disabled"})
    assert r.json()["status"] == "disabled" and r.json()["open_findings"] == 0
    await _refresh(db, in_tests, in_src)
    assert in_tests.memory_id is None and in_src.memory_id is None

    assert len(await _audit(db, "memory.approve")) == 1
    assert len(await _audit(db, "memory.disable")) == 1
    updates = await _audit(db, "memory.update")
    assert len(updates) == 3
    assert {"path_glob": [None, "tests/**"]} in [u.changes for u in updates]
    (approve,) = await _audit(db, "memory.approve")
    assert approve.changes == {"status": ["suggested", "approved"], "hints_changed": 1}


async def test_move_scope_recomputes_both_branches(client, db, admin):
    _, h = admin
    a = await make_entity(db, "a")
    b = await make_entity(db, "b")
    fa = await make_finding(db, a, "fa", rule_id="rule.a")
    fb = await make_finding(db, b, "fb", rule_id="rule.a")
    r = await client.post(URL, headers=h, json={"entity_id": str(a.id), "rule_id": "rule.a", **FP})
    mid = r.json()["id"]
    r = await client.patch(f"{URL}/{mid}", headers=h, json={"entity_id": str(b.id)})
    assert r.status_code == 200 and r.json()["entity_path"] == "b"
    await _refresh(db, fa, fb)
    assert fa.memory_id is None and str(fb.memory_id) == mid
    (row,) = await _audit(db, "memory.update")
    assert row.changes["entity_path"] == ["a", "b"] and row.entity_path == "b"


# --- запрос по правилу ---


async def test_decision_by_memory(client, db, admin, developer):
    entity = await make_entity(db)
    finding = await make_finding(db, entity, "f1", rule_id="rule.a")
    other = await make_finding(db, entity, "f2", rule_id="rule.b")
    memory = await make_memory(db, entity, reason_tag="test_code")
    finding.memory_id = memory.id
    await db.commit()
    _, h = developer
    body = {"decision_type": "false_positive", "reason_tag": "test_code", "memory_id": str(memory.id)}

    # правило не является подсказкой этой находки
    r = await client.post(f"/api/v1/findings/{other.id}/decisions", headers=h, json=body)
    assert r.status_code == 422
    # тип решения расходится с правилом
    r = await client.post(
        f"/api/v1/findings/{finding.id}/decisions", headers=h,
        json={
            "decision_type": "risk_accepted", "reason": "ok", "memory_id": str(memory.id),
            "expires_at": "2099-01-01T00:00:00Z",
        },
    )
    assert r.status_code == 422

    r = await client.post(f"/api/v1/findings/{finding.id}/decisions", headers=h, json=body)
    assert r.status_code == 201, r.text
    assert r.json()["memory_id"] == str(memory.id) and r.json()["status"] == "pending"
    await db.refresh(finding)
    assert finding.status == FindingStatus.new  # решает по-прежнему человек с finding:approve

    r = await client.post(f"/api/v1/decisions/{r.json()['id']}/approve", headers=admin[1], json={})
    assert r.status_code == 200, r.text
    events = (
        await db.scalars(select(FindingEvent).where(FindingEvent.finding_id == finding.id))
    ).all()
    refs = {e.event_type: e.payload.get("memory_id") for e in events}
    assert refs[FindingEventType.request_created] == str(memory.id)
    assert refs[FindingEventType.request_decided] == str(memory.id)

    # выключенное правило для запроса не годится
    memory.status = MemoryStatus.disabled
    other.memory_id = memory.id
    await db.commit()
    r = await client.post(f"/api/v1/findings/{other.id}/decisions", headers=h, json=body)
    assert r.status_code == 422


# --- предложения ---


async def _decide(client, h, finding, tag="test_code"):
    r = await client.post(
        f"/api/v1/findings/{finding.id}/decisions", headers=h,
        json={"decision_type": "false_positive", "reason_tag": tag, "reason": f"причина {tag}"},
    )
    assert r.status_code == 201 and r.json()["status"] == "approved", r.text


async def test_suggestion_after_three_approved_and_no_repeats(client, db, admin):
    _, h = admin  # может одобрять — запрос одобряется сразу
    entity = await make_entity(db)
    other = await make_entity(db, "other")
    f = [await make_finding(db, entity, f"f{i}", rule_id="rule.a") for i in range(5)]
    await _decide(client, h, await make_finding(db, other, "x", rule_id="rule.a"))  # другой проект
    await _decide(client, h, await make_finding(db, entity, "y", rule_id="rule.b"))  # другое правило

    await _decide(client, h, f[0], "test_code")
    await _decide(client, h, f[1], "test_code")
    assert (await db.scalars(select(TriageMemory))).all() == []
    await _decide(client, h, f[2], "dead_code")

    (memory,) = (await db.scalars(select(TriageMemory))).all()
    assert memory.status == MemoryStatus.suggested and memory.source == MemorySource.suggested
    assert (memory.entity_id, memory.scanner, memory.rule_id) == (entity.id, "Semgrep", "rule.a")
    assert memory.decision.value == "false_positive"
    assert memory.reason_tag.value == "test_code"  # самый частый тег
    assert memory.reason == "причина dead_code"    # обоснование последнего решения
    assert memory.created_by is None
    (row,) = await _audit(db, "memory.suggest")
    assert row.actor_id is None and row.changes["approved_decisions"] == 3
    # предложенное правило ничего не подсказывает
    await db.refresh(f[3])
    assert f[3].memory_id is None

    # правило уже есть (в любом статусе) — повторно не предлагается
    await _decide(client, h, f[3])
    assert len((await db.scalars(select(TriageMemory))).all()) == 1
    r = await client.patch(f"{URL}/{memory.id}", headers=h, json={"status": "disabled"})
    assert r.status_code == 200
    await _decide(client, h, f[4])
    assert len((await db.scalars(select(TriageMemory))).all()) == 1
    assert (await db.scalar(select(DecisionRequest.id).limit(1))) is not None


# --- MCP ---


async def _principal(db, user) -> Principal:
    return Principal(user=user, access=await load_access(db, user))


async def test_mcp_list_memories_and_get_finding(db, two_teams):
    t = two_teams
    wide = await make_memory(db, t.a, rule_id="rule.a", reason="Широкое")
    narrow = await make_memory(db, t.a_svc, rule_id="rule.a", path_glob="tests/**")
    await make_memory(db, t.a_svc, status=MemoryStatus.suggested)
    await make_memory(db, t.b)
    finding = await make_finding(db, t.a_svc, "f1", number=10, rule_id="rule.a", memory_id=wide.id)
    await make_finding(db, t.a_svc, "f2", number=11)
    p = await _principal(db, t.dev_a[0])

    out = await agent_tools.list_memories(db, p, "a/svc")
    assert out["project"] == "a/svc"
    assert [m["id"] for m in out["memories"]] == [str(narrow.id), str(wide.id)]  # точные — первыми
    assert out["memories"][1] == {
        "id": str(wide.id), "scope": "a", "scanner": None, "rule_id": "rule.a", "cwe": None,
        "path_glob": None, "decision": "false_positive", "reason_tag": None, "reason": "Широкое",
    }
    by_id = await agent_tools.list_memories(db, p, str(t.a.id))
    assert [m["id"] for m in by_id["memories"]] == [str(wide.id)]
    for foreign in ("b", str(t.b.id), "нет/такого"):
        with pytest.raises(HTTPException) as e:
            await agent_tools.list_memories(db, p, foreign)
        assert e.value.status_code == 404

    got = await agent_tools.get_finding(db, p, "SV-10")
    assert got["memory"]["id"] == str(wide.id) and got["memory"]["scope"] == "a"
    assert (await agent_tools.get_finding(db, p, "SV-11"))["memory"] is None
    assert finding.memory_id == wide.id
