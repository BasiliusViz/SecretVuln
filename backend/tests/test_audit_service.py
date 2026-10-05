from sqlalchemy import select

from app.models import AuditLog
from app.models.finding_event import ActorType


async def test_audit_rows_in_one_transaction_are_ordered(db):
    for i in range(3):
        db.add(AuditLog(actor_type=ActorType.system, action=f"test.{i}"))
    await db.commit()

    rows = (await db.scalars(select(AuditLog).order_by(AuditLog.created_at))).all()
    assert [r.action for r in rows] == ["test.0", "test.1", "test.2"]
    assert len({r.created_at for r in rows}) == 3
    assert rows[0].changes == {}


async def test_record_audit_user_actor_entity_and_target(db, make_user):
    from app.services import audit
    from tests.factories import make_entity

    user, _ = await make_user("auditor@example.com")
    entity = await make_entity(db)
    audit.record_audit(
        db,
        user,
        audit.ENTITY_UPDATE,
        target=("entity", entity.id, entity.path_cache),
        entity=entity,
        changes={"name": ["a", "b"]},
        ip="10.0.0.1",
    )
    await db.commit()

    row = await db.scalar(select(AuditLog))
    assert row.actor_type == ActorType.user
    assert row.actor_id == user.id
    assert row.actor_label == "auditor@example.com"
    assert row.action == "entity.update"
    assert (row.target_type, row.target_id, row.target_label) == (
        "entity",
        entity.id,
        entity.path_cache,
    )
    assert row.entity_id == entity.id
    assert row.entity_path == entity.path_cache
    assert row.changes == {"name": ["a", "b"]}
    assert row.ip == "10.0.0.1"


async def test_record_audit_system_and_anonymous_label(db):
    from app.services import audit

    audit.record_audit(db, None, audit.GROUP_MEMBER_ADD)
    audit.record_audit(db, "x" * 300, audit.AUTH_LOGIN_FAILED)
    await db.commit()

    rows = (await db.scalars(select(AuditLog).order_by(AuditLog.created_at))).all()
    assert rows[0].actor_type == ActorType.system and rows[0].actor_id is None
    assert rows[1].actor_type == ActorType.user and rows[1].actor_id is None
    assert rows[1].actor_label == "x" * 255


def test_diff_only_whitelisted_changed_fields():
    import uuid

    from app.models.entity import RepoType
    from app.services.audit import diff

    gid = uuid.uuid4()
    before = {"name": "a", "repo_type": None, "owner_group_id": None, "x": 1}
    after = {"name": "b", "repo_type": RepoType.gitlab, "owner_group_id": gid, "x": 2}
    assert diff(before, after, ("name", "repo_type", "owner_group_id", "description")) == {
        "name": ["a", "b"],
        "repo_type": [None, "gitlab"],
        "owner_group_id": [None, str(gid)],
    }


def test_snapshot_never_contains_secrets():
    from types import SimpleNamespace

    from app.services.audit import FIELDS, snapshot

    user = SimpleNamespace(email="u@x", hashed_password="h", password="p", token="t")
    assert snapshot(user, ("email", "hashed_password", "password", "token")) == {"email": "u@x"}
    for fields in FIELDS.values():
        assert not {"hashed_password", "password", "token"} & set(fields)


def test_snapshot_strips_credentials_from_urls():
    from types import SimpleNamespace

    from app.services.audit import snapshot

    obj = SimpleNamespace(repo_url="https://user:tok@git.corp:8443/a/b", name="x@y")
    assert snapshot(obj, ("repo_url", "name")) == {"repo_url": "https://git.corp:8443/a/b", "name": "x@y"}
