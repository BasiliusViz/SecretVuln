"""Похожие находки: порядок, права, дубли, решение человека, поиск по смыслу."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.api.deps import Principal
from app.models import Finding, FindingEvent
from app.models.finding import FindingStatus
from app.models.finding_event import ActorType, FindingEventType
from app.services.access import load_access
from app.services.embeddings import embed_pending
from app.services.similarity import find_similar, search_by_text
from tests.factories import FakeEmbedClient, make_entity, make_finding


def _raw(message: str) -> dict:
    return {"message": {"text": message}}


async def _principal(db, user) -> Principal:
    return Principal(user=user, access=await load_access(db, user))


async def _event(db, finding, to_status, actor_type=ActorType.user, minutes=0, **kw):
    db.add(FindingEvent(
        finding_id=finding.id, event_type=FindingEventType.status_changed,
        actor_type=actor_type, to_status=to_status,
        created_at=datetime.now(timezone.utc) + timedelta(minutes=minutes), **kw,
    ))
    await db.commit()


async def test_order_by_similarity_and_excludes_self_and_duplicates(db, admin):
    entity = await make_entity(db)
    other = await make_entity(db, "other")
    target = await make_finding(db, entity, "t", raw=_raw("sql injection in user query builder"))
    near = await make_finding(db, entity, "n", raw=_raw("sql injection in user query"))
    far = await make_finding(db, entity, "f", raw=_raw("sql"))
    # тот же fingerprint в другом проекте — та же находка, не «похожая»
    await make_finding(db, other, "t", raw=_raw("sql injection in user query builder"))
    await embed_pending(db, FakeEmbedClient())

    result = await find_similar(db, await _principal(db, admin[0]), target.id)
    assert result["pending"] is False
    ids = [item["id"] for item in result["items"]]
    assert ids == [str(near.id), str(far.id)]
    first = result["items"][0]
    assert first["number"] == f"SV-{near.number}"
    assert first["entity_path"] == entity.path_cache
    assert 0 < result["items"][1]["similarity"] < first["similarity"] <= 1
    assert first["decision"] is None


async def test_limit(db, admin):
    entity = await make_entity(db)
    target = await make_finding(db, entity, "t", raw=_raw("a b c"))
    for i in range(4):
        await make_finding(db, entity, f"x{i}", raw=_raw(f"a b {i}"))
    await embed_pending(db, FakeEmbedClient())
    result = await find_similar(db, await _principal(db, admin[0]), target.id, limit=2)
    assert len(result["items"]) == 2


async def test_foreign_project_invisible(db, two_teams):
    target = await make_finding(db, two_teams.a_svc, "t", raw=_raw("xss in template render"))
    mine = await make_finding(db, two_teams.a_svc, "m", raw=_raw("xss in template"))
    await make_finding(db, two_teams.b_svc, "f", raw=_raw("xss in template render now"))
    await embed_pending(db, FakeEmbedClient())

    result = await find_similar(db, await _principal(db, two_teams.dev_a[0]), target.id)
    assert [i["id"] for i in result["items"]] == [str(mine.id)]


async def test_decision_is_last_human_status_change(db, admin):
    entity = await make_entity(db)
    target = await make_finding(db, entity, "t", raw=_raw("path traversal open file"))
    fp = await make_finding(db, entity, "fp", raw=_raw("path traversal open"),
                            status=FindingStatus.false_positive)
    await _event(db, fp, FindingStatus.triaged, minutes=-10)
    await _event(db, fp, FindingStatus.false_positive, reason="тестовый код",
                 reason_tag="test_code", minutes=-5)
    await _event(db, fp, FindingStatus.fixed, actor_type=ActorType.system)  # не человек
    await embed_pending(db, FakeEmbedClient())

    [item] = (await find_similar(db, await _principal(db, admin[0]), target.id))["items"]
    decision = item["decision"]
    assert decision["status"] == "false_positive"
    assert decision["reason"] == "тестовый код"
    assert decision["reason_tag"] == "test_code"
    assert decision["at"]


async def test_pending_without_vector(db, admin):
    entity = await make_entity(db)
    target = await make_finding(db, entity, "t")
    result = await find_similar(db, await _principal(db, admin[0]), target.id)
    assert result == {"pending": True, "items": []}


async def test_other_model_vectors_ignored(db, admin):
    entity = await make_entity(db)
    target = await make_finding(db, entity, "t", raw=_raw("a b"))
    await make_finding(db, entity, "o", raw=_raw("a b c"))
    await embed_pending(db, FakeEmbedClient(model="old"))
    # целевая пересчитана новой моделью, соседка ещё на старой — несравнимы
    from app.services.embeddings import ensure_embedding

    await ensure_embedding(db, target, FakeEmbedClient(model="new"))
    result = await find_similar(db, await _principal(db, admin[0]), target.id)
    assert result["items"] == []


async def test_search_by_text_with_filters(db, two_teams):
    from app.api.findings import findings_query

    sqli = await make_finding(db, two_teams.a_svc, "s", raw=_raw("sql injection query"))
    xss = await make_finding(db, two_teams.a_svc, "x", raw=_raw("xss template"),
                             status=FindingStatus.confirmed)
    await make_finding(db, two_teams.b_svc, "b", raw=_raw("sql injection query"))
    client = FakeEmbedClient()
    await embed_pending(db, client)
    principal = await _principal(db, two_teams.dev_a[0])

    q = await findings_query(db, principal)
    rows = await search_by_text(db, q, "sql injection", client, limit=10)
    assert [f.id for f, _ in rows] == [sqli.id, xss.id]
    assert rows[0][1] > rows[1][1]

    q = await findings_query(db, principal, statuses=[FindingStatus.confirmed])
    rows = await search_by_text(db, q, "sql injection", client, limit=10)
    assert [f.id for f, _ in rows] == [xss.id]
    assert isinstance(rows[0][0], Finding)
    assert await db.scalar(select(Finding.id).where(Finding.id == sqli.id))
