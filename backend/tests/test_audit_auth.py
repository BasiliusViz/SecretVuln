"""Журнал аудита: вход (успех/неудача) и LDAP-синхронизация групп при входе."""

from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import select

from app.core.security import hash_password
from app.models import AuditLog, User, UserGroup
from app.models.finding_event import ActorType
from app.models.user import AuthSource
from app.models.user_group import GroupSource
from app.services import audit
from app.services.auth.ldap import LdapUser


async def _rows(db, action=None):
    q = select(AuditLog).order_by(AuditLog.created_at)
    if action:
        q = q.where(AuditLog.action == action)
    return (await db.scalars(q)).all()


async def _local_user(db, email="u@test.local", active=True):
    user = User(
        email=email,
        auth_source=AuthSource.local,
        hashed_password=hash_password("Secret123!"),
        is_active=active,
    )
    db.add(user)
    await db.commit()
    return user


async def test_login_ok_is_logged(client, db):
    user = await _local_user(db)
    r = await client.post(
        "/api/v1/auth/login", json={"email": "U@test.local", "password": "Secret123!"}
    )
    assert r.status_code == 200
    (row,) = await _rows(db)
    assert row.action == audit.AUTH_LOGIN
    assert row.actor_type == ActorType.user and row.actor_id == user.id
    assert row.entity_id is None
    assert row.ip


async def test_login_failed_is_committed_before_401(client, db):
    await _local_user(db)
    r = await client.post(
        "/api/v1/auth/login", json={"email": "u@test.local", "password": "wrong-pass"}
    )
    assert r.status_code == 401
    r = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@test.local", "password": "x"}
    )
    assert r.status_code == 401
    rows = await _rows(db)
    assert [r.action for r in rows] == [audit.AUTH_LOGIN_FAILED] * 2
    assert [r.actor_label for r in rows] == ["u@test.local", "nobody@test.local"]
    assert all(r.actor_id is None for r in rows)
    assert "wrong-pass" not in str([r.changes for r in rows])


async def test_login_inactive_is_failed(client, db):
    await _local_user(db, active=False)
    r = await client.post(
        "/api/v1/auth/login", json={"email": "u@test.local", "password": "Secret123!"}
    )
    assert r.status_code == 403
    (row,) = await _rows(db)
    assert row.action == audit.AUTH_LOGIN_FAILED
    assert row.changes == {"reason": "inactive"}


async def test_ldap_login_syncs_groups_only_on_change(client, db, monkeypatch):
    group = UserGroup(name="Devs", source=GroupSource.ldap, ldap_group="devs")
    db.add(group)
    await db.commit()
    monkeypatch.setattr(
        "app.api.auth.get_settings", lambda: SimpleNamespace(ldap_enabled=True)
    )
    monkeypatch.setattr(
        "app.api.auth.ldap_authenticate",
        lambda email, pw: LdapUser(dn="uid=l", email=email, full_name="L", groups=["devs"]),
    )
    for _ in range(2):
        r = await client.post(
            "/api/v1/auth/login", json={"email": "l@test.local", "password": "x"}
        )
        assert r.status_code == 200

    adds = await _rows(db, audit.GROUP_MEMBER_ADD)
    assert len(adds) == 1
    assert adds[0].actor_type == ActorType.system
    assert (adds[0].target_type, adds[0].target_id) == ("group", group.id)
    assert adds[0].changes == {"user": "l@test.local"}
    assert len(await _rows(db, audit.AUTH_LOGIN)) == 2


async def test_ldap_rejected_unknown_vs_known_user(client, db, monkeypatch):
    """LDAP не различает «нет пользователя» и «неверный пароль» — причина зависит от того, знаем ли мы его."""
    db.add(User(email="known@test.local", auth_source=AuthSource.ldap))
    await db.commit()
    monkeypatch.setattr("app.api.auth.get_settings", lambda: SimpleNamespace(ldap_enabled=True))
    monkeypatch.setattr("app.api.auth.ldap_authenticate", lambda email, pw: None)

    for email in ("ghost@test.local", "known@test.local"):
        r = await client.post("/api/v1/auth/login", json={"email": email, "password": "x"})
        assert r.status_code == 401

    rows = await _rows(db, audit.AUTH_LOGIN_FAILED)
    assert [(r.actor_label, r.changes) for r in rows] == [
        ("ghost@test.local", {"reason": "ldap_rejected"}),
        ("known@test.local", {"reason": "bad_password"}),
    ]
