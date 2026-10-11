"""GET /findings/{id}/similar и embeddings_enabled в /ai/status."""

from __future__ import annotations

from app.services.embeddings import embed_pending
from tests.factories import FakeEmbedClient, make_finding


def _raw(message: str) -> dict:
    return {"message": {"text": message}}


async def test_similar_ok_and_scoped(client, db, two_teams, embeddings_on):
    target = await make_finding(db, two_teams.a_svc, "t", raw=_raw("open redirect in login"))
    mine = await make_finding(db, two_teams.a_svc, "m", raw=_raw("open redirect"))
    await make_finding(db, two_teams.b_svc, "f", raw=_raw("open redirect in login page"))
    await embed_pending(db, FakeEmbedClient())

    r = await client.get(f"/api/v1/findings/{target.id}/similar", headers=two_teams.dev_a[1])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pending"] is False
    assert [i["id"] for i in body["items"]] == [str(mine.id)]

    r = await client.get(f"/api/v1/findings/{target.id}/similar?limit=1",
                         headers=two_teams.dev_a[1])
    assert len(r.json()["items"]) == 1


async def test_similar_pending(client, db, two_teams, embeddings_on):
    target = await make_finding(db, two_teams.a_svc, "t")
    r = await client.get(f"/api/v1/findings/{target.id}/similar", headers=two_teams.dev_a[1])
    assert r.json() == {"pending": True, "items": []}


async def test_similar_foreign_finding_404(client, db, two_teams, embeddings_on):
    foreign = await make_finding(db, two_teams.b_svc, "f")
    r = await client.get(f"/api/v1/findings/{foreign.id}/similar", headers=two_teams.dev_a[1])
    assert r.status_code == 404


async def test_similar_no_permission(client, db, two_teams, make_user, embeddings_on):
    target = await make_finding(db, two_teams.a_svc, "t")
    _, headers = await make_user("nobody@test.local")
    r = await client.get(f"/api/v1/findings/{target.id}/similar", headers=headers)
    assert r.status_code in (403, 404)


async def test_similar_disabled_503(client, db, two_teams):
    target = await make_finding(db, two_teams.a_svc, "t")
    r = await client.get(f"/api/v1/findings/{target.id}/similar", headers=two_teams.dev_a[1])
    assert r.status_code == 503


async def test_similar_limit_bounds(client, db, two_teams, embeddings_on):
    target = await make_finding(db, two_teams.a_svc, "t")
    for limit in (0, 21):
        r = await client.get(f"/api/v1/findings/{target.id}/similar?limit={limit}",
                             headers=two_teams.dev_a[1])
        assert r.status_code == 422


async def test_ai_status_reports_embeddings(client, two_teams, embeddings_on):
    r = await client.get("/api/v1/ai/status", headers=two_teams.dev_a[1])
    assert r.json()["embeddings_enabled"] is True


async def test_ai_status_embeddings_off(client, two_teams):
    r = await client.get("/api/v1/ai/status", headers=two_teams.dev_a[1])
    assert r.json()["embeddings_enabled"] is False
