"""Команда-владелец: маски путей, порядок правил, наследование, ручное назначение."""

import json

import pytest
from sqlalchemy import select

from app.models import FindingEvent, FindingEventType, OwnershipRule, RuleSource
from app.models.finding import Finding
from app.services.import_processing import apply_import
from app.services.ownership import path_matches
from app.services.sarif import parse_sarif
from tests.factories import make_entity, make_group, make_import, make_sarif


@pytest.mark.parametrize("pattern,path,expected", [
    ("app/payments/**", "app/payments/x/y.py", True),
    ("app/payments/**", "app/paymentsx/y.py", False),
    ("*.py", "a.py", True),
    ("*.py", "dir/a.py", False),
    ("**/test_*.py", "a/b/test_x.py", True),
    ("**/test_*.py", "test_x.py", True),
    ("app/auth/", "app/auth/login.py", True),
    ("./app/*.py", "/app/main.py", True),
    ("app/?.py", "app/a.py", True),
    ("app/?.py", "app/ab.py", False),
])
def test_path_matches(pattern, path, expected):
    assert path_matches(pattern, path) is expected


async def _rule(db, entity, pattern, group, position=0):
    db.add(OwnershipRule(
        entity_id=entity.id, pattern=pattern, group_id=group.id,
        position=position, source=RuleSource.manual,
    ))
    await db.commit()


async def _import(db, entity, results):
    imp = await make_import(db, entity)
    stats = await apply_import(db, imp, parse_sarif(make_sarif("Semgrep", results)))
    await db.commit()
    return stats


async def _by_fp(db, fp):
    return await db.scalar(select(Finding).where(Finding.fingerprint == fp))


async def test_rule_then_owner_then_nobody(db):
    payments = await make_group(db, "payments")
    platform = await make_group(db, "platform")
    owned = await make_entity(db, "svc", owner_group_id=platform.id)
    await _rule(db, owned, "app/payments/**", payments)
    await _import(db, owned, [
        {"fp": "p", "path": "app/payments/pay.py"},
        {"fp": "o", "path": "app/other.py"},
    ])
    assert (await _by_fp(db, "p")).assignee_group_id == payments.id
    assert (await _by_fp(db, "o")).assignee_group_id == platform.id

    orphan = await make_entity(db, "orphan")
    await _import(db, orphan, [{"fp": "n", "path": "x.py"}])
    assert (await _by_fp(db, "n")).assignee_group_id is None


async def test_rules_inherited_and_child_first(db):
    parent_team = await make_group(db, "parent-team")
    child_team = await make_group(db, "child-team")
    parent = await make_entity(db, "fintech")
    child = await make_entity(db, "api", parent_id=parent.id)
    await _rule(db, parent, "app/**", parent_team)
    await _rule(db, child, "app/core/**", child_team)
    await _import(db, child, [
        {"fp": "core", "path": "app/core/a.py"},
        {"fp": "misc", "path": "app/misc.py"},
    ])
    assert (await _by_fp(db, "core")).assignee_group_id == child_team.id
    assert (await _by_fp(db, "misc")).assignee_group_id == parent_team.id


async def test_rule_change_reassigns_on_next_import(db):
    a = await make_group(db, "a")
    b = await make_group(db, "b")
    e = await make_entity(db, "svc", owner_group_id=a.id)
    await _import(db, e, [{"fp": "x", "path": "app/x.py"}])
    assert (await _by_fp(db, "x")).assignee_group_id == a.id

    await _rule(db, e, "app/**", b)
    stats = await _import(db, e, [{"fp": "x", "path": "app/x.py"}])
    finding = await _by_fp(db, "x")
    assert finding.assignee_group_id == b.id
    assert stats["reassigned"] == 1
    events = list(await db.scalars(
        select(FindingEvent).where(
            FindingEvent.finding_id == finding.id,
            FindingEvent.event_type == FindingEventType.assigned,
        )
    ))
    assert len(events) == 1
    assert events[0].payload["to_group_id"] == str(b.id)


async def test_manual_assignment_survives_reimport(client, admin, db):
    _, h = admin
    a = await make_group(db, "a")
    manual = await make_group(db, "manual")
    e = await make_entity(db, "svc", owner_group_id=a.id)
    await _import(db, e, [{"fp": "x", "path": "app/x.py"}])
    finding = await _by_fp(db, "x")

    r = await client.post(
        f"/api/v1/findings/{finding.id}/assign", json={"group_id": str(manual.id)}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["assignee_group"]["name"] == "manual"
    assert r.json()["assigned_manually"] is True

    await _import(db, e, [{"fp": "x", "path": "app/x.py"}])
    await db.refresh(finding)
    assert finding.assignee_group_id == manual.id

    r = await client.post(f"/api/v1/findings/{finding.id}/assign", json={"by_rules": True}, headers=h)
    assert r.json()["assignee_group_id"] == str(a.id)
    assert r.json()["assigned_manually"] is False


async def test_assign_requires_triage_and_valid_group(client, make_user, admin, db):
    _, h = admin
    e = await make_entity(db, "svc")
    await _import(db, e, [{"fp": "x"}])
    finding = await _by_fp(db, "x")
    r = await client.post(
        f"/api/v1/findings/{finding.id}/assign",
        json={"group_id": "00000000-0000-0000-0000-000000000000"},
        headers=h,
    )
    assert r.status_code == 422
    _, viewer = await make_user("viewer@test.local")
    r = await client.post(f"/api/v1/findings/{finding.id}/assign", json={"by_rules": True}, headers=viewer)
    assert r.status_code == 403


async def test_reassign_subtree_endpoint(client, admin, db):
    _, h = admin
    team = await make_group(db, "team")
    parent = await make_entity(db, "p")
    child = await make_entity(db, "c", parent_id=parent.id)
    await _import(db, child, [{"fp": "x", "path": "app/x.py"}])
    assert (await _by_fp(db, "x")).assignee_group_id is None

    await _rule(db, parent, "app/**", team)
    r = await client.post(f"/api/v1/entities/{parent.id}/reassign", headers=h)
    assert r.status_code == 200
    assert r.json() == {"reassigned": 1}
    finding = await _by_fp(db, "x")
    await db.refresh(finding)
    assert finding.assignee_group_id == team.id


def test_parser_reads_rule_help_and_repo():
    sarif = {
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "Semgrep", "rules": [
                {"id": "r1", "help": {"text": "Use parameters", "markdown": "Use **parameters**"}},
            ]}},
            "versionControlProvenance": [{"repositoryUri": "https://gitlab.corp/t/app"}],
            "results": [{
                "ruleId": "r1", "message": {"text": "m"},
                "partialFingerprints": {"primaryLocationLineHash": "h"},
            }],
        }],
    }
    run = parse_sarif(json.dumps(sarif).encode())[0]
    assert run.results[0].help == "Use **parameters**"
    assert run.repository_uri == "https://gitlab.corp/t/app"
