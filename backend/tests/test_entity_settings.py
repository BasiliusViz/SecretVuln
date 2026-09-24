"""Настройки проекта: значения, источники, наследование, закрепление, правила владения."""

import app.api.entity_settings as entity_settings_api
from tests.factories import make_entity, make_group


async def test_settings_default_unset(client, admin, db):
    _, h = admin
    e = await make_entity(db, "svc")
    r = await client.get(f"/api/v1/entities/{e.id}/settings", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["path"] == "svc"
    assert body["fields"]["owner_group_id"] == {"value": None, "source": "unset", "inherited_from": None}
    assert body["ownership_rules"] == []
    assert body["pinned_fields"] == []


async def test_patch_pins_and_normalizes_repo(client, admin, db):
    _, h = admin
    e = await make_entity(db, "svc")
    g = await make_group(db, "payments")
    r = await client.patch(
        f"/api/v1/entities/{e.id}/settings",
        json={
            "owner_group_id": str(g.id),
            "repo_url": "https://GitLab.Corp/Team/App.git/",
            "repo_type": "gitlab",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fields"]["owner_group_id"]["value"] == str(g.id)
    assert body["fields"]["owner_group_id"]["source"] == "manual"
    assert body["fields"]["repo_url"]["value"] == "https://gitlab.corp/Team/App"
    assert set(body["pinned_fields"]) == {"owner_group_id", "repo"}


async def test_settings_are_inherited(client, admin, db):
    _, h = admin
    g = await make_group(db, "payments")
    parent = await make_entity(db, "fintech", owner_group_id=g.id, default_branch="main")
    child = await make_entity(db, "api", parent_id=parent.id)
    body = (await client.get(f"/api/v1/entities/{child.id}/settings", headers=h)).json()
    assert body["fields"]["owner_group_id"] == {
        "value": str(g.id), "source": "inherited", "inherited_from": "fintech",
    }
    assert body["fields"]["default_branch"]["value"] == "main"


async def test_repo_bound_to_one_project(client, admin, db):
    _, h = admin
    a = await make_entity(db, "a", repo_url="https://gitlab.corp/team/app")
    b = await make_entity(db, "b")
    r = await client.patch(
        f"/api/v1/entities/{b.id}/settings",
        json={"repo_url": "https://gitlab.corp/team/app.git"},
        headers=h,
    )
    assert r.status_code == 409
    assert "a" in r.json()["detail"]
    assert a.id  # a остаётся владельцем репозитория


async def test_repo_conflict_at_commit_returns_409(client, admin, db, monkeypatch):
    """TOCTOU: pre-check bypassed (concurrent write), DB unique index still catches it -> 409, not 500."""
    _, h = admin
    a = await make_entity(db, "a", repo_url="https://gitlab.corp/team/app")
    b = await make_entity(db, "b")

    async def _no_owner_found(*args, **kwargs):
        return None

    monkeypatch.setattr(entity_settings_api, "find_repo_owner", _no_owner_found)

    r = await client.patch(
        f"/api/v1/entities/{b.id}/settings",
        json={"repo_url": "https://gitlab.corp/team/app.git"},
        headers=h,
    )
    assert r.status_code == 409
    assert a.id  # a остаётся владельцем репозитория


async def test_unknown_group_rejected(client, admin, db):
    _, h = admin
    e = await make_entity(db, "svc")
    r = await client.patch(
        f"/api/v1/entities/{e.id}/settings",
        json={"owner_group_id": "00000000-0000-0000-0000-000000000000"},
        headers=h,
    )
    assert r.status_code == 422


async def test_ownership_rules_replace_and_inherit(client, admin, db):
    _, h = admin
    g1 = await make_group(db, "payments")
    g2 = await make_group(db, "identity")
    parent = await make_entity(db, "fintech")
    child = await make_entity(db, "api", parent_id=parent.id)
    r = await client.put(
        f"/api/v1/entities/{parent.id}/ownership-rules",
        json=[
            {"pattern": "app/payments/**", "group_id": str(g1.id)},
            {"pattern": "app/auth/**", "group_id": str(g2.id)},
        ],
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert [x["pattern"] for x in body["ownership_rules"]] == ["app/payments/**", "app/auth/**"]
    assert body["ownership_rules"][0]["group_name"] == "payments"
    assert body["rules_source"] == "manual"
    assert "ownership_rules" in body["pinned_fields"]

    child_body = (await client.get(f"/api/v1/entities/{child.id}/settings", headers=h)).json()
    assert [x["entity_path"] for x in child_body["inherited_rules"]] == ["fintech", "fintech"]


async def test_settings_write_requires_permission(client, developer, db):
    _, h = developer
    e = await make_entity(db, "svc")
    r = await client.get(f"/api/v1/entities/{e.id}/settings", headers=h)
    assert r.status_code == 200
    r = await client.patch(f"/api/v1/entities/{e.id}/settings", json={}, headers=h)
    assert r.status_code == 403
