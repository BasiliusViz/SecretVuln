import uuid

from app.models import DecisionRequest
from app.models.decision_request import DecisionStatus, DecisionType, ReasonTag
from app.models.finding import FindingStatus
from tests.factories import make_entity, make_finding

URL = "/api/v1/findings/noisy-rules"


async def _fp(db, entity, fp, rule, tag):
    f = await make_finding(db, entity, fp, rule_id=rule, status=FindingStatus.false_positive)
    db.add(DecisionRequest(
        id=uuid.uuid4(), finding_id=f.id, decision_type=DecisionType.false_positive,
        status=DecisionStatus.approved, reason_tag=tag,
    ))
    await db.commit()


async def test_noisy_rules_thresholds_and_reasons(client, developer, db):
    _, headers = developer
    e = await make_entity(db)
    # noisy: 4 ложных из 5 решённых + 1 новая (не решена)
    tags = [ReasonTag.test_code, ReasonTag.test_code, ReasonTag.sanitized, ReasonTag.dead_code]
    for i, tag in enumerate(tags):
        await _fp(db, e, f"n{i}", "noisy", tag)
    await make_finding(db, e, "n-ok", rule_id="noisy", status=FindingStatus.confirmed)
    await make_finding(db, e, "n-new", rule_id="noisy")
    # quiet: 1 ложное из 5
    await _fp(db, e, "q0", "quiet", ReasonTag.other)
    for i in range(4):
        await make_finding(db, e, f"q{i + 1}", rule_id="quiet", status=FindingStatus.fixed)

    r = await client.get(URL, params={"min_decided": 5, "min_fp_ratio": 0.7}, headers=headers)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    row = rows[0]
    assert (row["rule_id"], row["decided"], row["false_positive"], row["fp_ratio"]) == ("noisy", 5, 4, 0.8)
    assert row["top_reasons"][0] == {"reason_tag": "test_code", "count": 2}
    assert len(row["top_reasons"]) == 3

    r = await client.get(URL, params={"min_decided": 6}, headers=headers)
    assert r.json() == []
