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
