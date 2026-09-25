"""Файл настроек .secretvuln.yml: разбор, применение, закрепление, выгрузка."""

import pytest
from sqlalchemy import select

from app.models import OwnershipRule
from app.services.config_file import ConfigError, apply_config, export_config, parse_config
from tests.factories import make_entity, make_group

GOOD = b"""
version: 1
default_branch: main
owner: payments
repo:
  url: https://gitlab.corp/fintech/payments.git
  type: gitlab
  path_prefix: services/api
ownership:
  - path: "app/payments/**"
    owner: payments
  - path: "app/auth/**"
    owner: identity
"""


def test_parse_valid():
    cfg = parse_config(GOOD)
    assert cfg.default_branch == "main"
    assert cfg.repo.type.value == "gitlab"
    assert [o.path for o in cfg.ownership] == ["app/payments/**", "app/auth/**"]


@pytest.mark.parametrize("content", [
    b"version: 1\nowner: [unclosed",
    b"- just a list",
    b"version: 2",
    b"version: 1\nunknown_key: 1",
    b"version: 1\nrepo:\n  type: svn",
])
def test_parse_invalid(content):
    with pytest.raises(ConfigError):
        parse_config(content)


async def test_apply_sets_fields_and_rules(db):
    payments = await make_group(db, "payments")
    e = await make_entity(db, "svc")
    warnings = await apply_config(db, e, parse_config(GOOD), commit_sha="abc")
    await db.commit()

    assert e.default_branch == "main"
    assert e.owner_group_id == payments.id
    assert e.repo_url == "https://gitlab.corp/fintech/payments"
    assert e.repo_path_prefix == "services/api"
    assert e.config_commit_sha == "abc"
    rules = list(await db.scalars(select(OwnershipRule).where(OwnershipRule.entity_id == e.id)))
    assert [r.pattern for r in rules] == ["app/payments/**"]  # identity нет
    assert warnings == [
        "ownership: группа «identity» не найдена — правило «app/auth/**» пропущено"
    ]


async def test_pinned_fields_are_kept(db):
    await make_group(db, "payments")
    manual = await make_group(db, "manual-team")
    e = await make_entity(db, "svc", owner_group_id=manual.id, pinned_fields=["owner_group_id"])
    await apply_config(db, e, parse_config(GOOD))
    await db.commit()
    assert e.owner_group_id == manual.id
    assert e.default_branch == "main"


async def test_unpin_restores_file_value(client, admin, db):
    _, h = admin
    payments = await make_group(db, "payments")
    manual = await make_group(db, "manual-team")
    e = await make_entity(db, "svc")
    await apply_config(db, e, parse_config(GOOD))
    await db.commit()

    r = await client.patch(
        f"/api/v1/entities/{e.id}/settings", json={"owner_group_id": str(manual.id)}, headers=h
    )
    assert r.json()["fields"]["owner_group_id"]["source"] == "manual"

    r = await client.post(
        f"/api/v1/entities/{e.id}/settings/unpin", json={"field": "owner_group_id"}, headers=h
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["fields"]["owner_group_id"] == {
        "value": str(payments.id), "source": "file", "inherited_from": None,
    }
    assert "owner_group_id" not in body["pinned_fields"]


async def test_export_roundtrip(client, admin, db):
    _, h = admin
    await make_group(db, "payments")
    e = await make_entity(db, "svc")
    await apply_config(db, e, parse_config(GOOD))
    await db.commit()

    text = await export_config(db, e)
    cfg = parse_config(text.encode())
    assert cfg.owner == "payments"
    assert cfg.repo.url == "https://gitlab.corp/fintech/payments"

    r = await client.get(f"/api/v1/entities/{e.id}/config.yml", headers=h)
    assert r.status_code == 200
    assert "owner: payments" in r.text
    assert ".secretvuln.yml" in r.headers["content-disposition"]
