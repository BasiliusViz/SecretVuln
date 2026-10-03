"""SLA: наследование политики, set_status, пересчёт сроков."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import Entity
from app.models.finding import FindingStatus, Severity
from app.services.entity_tree import effective_sla, effective_tags, entities_with_tag
from app.services.finding_state import compute_due, recompute_due, set_status
from tests.factories import make_entity, make_finding, make_policy

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def test_policy_inheritance_own_parent_default(db):
    default = await make_policy(db, "def", is_default=True)
    strict = await make_policy(db, "strict", high=7)
    root = await make_entity(db, "root", sla_policy_id=strict.id)
    child = await make_entity(db, "child", parent_id=root.id)
    other = await make_entity(db, "other")
    eff = await effective_sla(db, [root, child, other])
    assert eff[root.id].policy_id == strict.id and eff[root.id].inherited_from is None
    assert eff[child.id].policy_id == strict.id and eff[child.id].inherited_from == "root"
    assert eff[other.id].policy_id == default.id and eff[other.id].is_default


async def test_set_status_close_and_reopen(db):
    await make_policy(db, "def", is_default=True)
    f = await make_finding(db, await make_entity(db), severity=Severity.high)
    await compute_due(db, f, start=T0)
    assert f.due_at == T0 + timedelta(days=30)

    now = T0 + timedelta(days=5)
    await set_status(db, f, FindingStatus.fixed, now=now)
    assert f.resolved_at == now and f.sla_start_at == T0

    later = now + timedelta(days=1)
    await set_status(db, f, FindingStatus.false_positive, now=later)
    assert f.resolved_at == now and f.sla_start_at == T0  # закрытый → закрытый

    reopen = T0 + timedelta(days=50)
    await set_status(db, f, FindingStatus.new, now=reopen)
    assert f.resolved_at is None
    assert f.sla_start_at == reopen
    assert f.due_at == reopen + timedelta(days=30)


async def test_severity_without_days_has_no_due(db):
    await make_policy(db, "def", is_default=True)
    f = await make_finding(db, await make_entity(db), severity=Severity.info)
    await compute_due(db, f, start=T0)
    assert f.due_at is None


async def test_recompute_subtree_skips_closed_and_own_policy(db):
    await make_policy(db, "def", is_default=True)
    fast = await make_policy(db, "fast", high=3)
    root = await make_entity(db, "root")
    child = await make_entity(db, "child", parent_id=root.id)
    pinned = await make_entity(db, "pinned", parent_id=root.id, sla_policy_id=(await make_policy(db, "own", high=60)).id)
    open_f = await make_finding(db, child, "a", sla_start_at=T0)
    closed_f = await make_finding(db, child, "b", sla_start_at=T0, status=FindingStatus.fixed)
    own_f = await make_finding(db, pinned, "c", sla_start_at=T0)
    for f in (open_f, closed_f, own_f):
        await compute_due(db, f)
    await db.commit()
    closed_due = closed_f.due_at

    root.sla_policy_id = fast.id
    await recompute_due(db, entity_ids=[root.id, child.id, pinned.id])
    await db.commit()
    for f in (open_f, closed_f, own_f):
        await db.refresh(f)
    assert open_f.due_at == T0 + timedelta(days=3)
    assert closed_f.due_at == closed_due
    assert own_f.due_at == T0 + timedelta(days=60)


async def test_tags_inherited_and_underscore_safe(db):
    root = await make_entity(db, "a_b", tags=["env:prod"])
    child = await make_entity(db, "svc", parent_id=root.id, tags=["pci"])
    # потомок соседа совпал бы по LIKE 'a_b/%': «axb/x»
    await make_entity(db, "x", parent_id=(await make_entity(db, "axb")).id)
    tags = await effective_tags(db, child)
    assert tags == [
        {"tag": "env:prod", "inherited_from": "a_b"},
        {"tag": "pci", "inherited_from": None},
    ]
    ids = set(await db.scalars(entities_with_tag("env:prod")))
    names = set(await db.scalars(select(Entity.name).where(Entity.id.in_(ids))))
    assert names == {"a_b", "svc"}
