"""MCP: find_similar и search_findings(query) — поиск по смыслу для агентов."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.deps import Principal
from app.services import agent_tools
from app.services.access import load_access
from app.services.embeddings import embed_pending
from tests.factories import FakeEmbedClient, make_finding


def _raw(message: str) -> dict:
    return {"message": {"text": message}}


async def _principal(db, user) -> Principal:
    return Principal(user=user, access=await load_access(db, user))


async def _data(db, t):
    target = await make_finding(db, t.a_svc, "t", number=10, raw=_raw("ssrf fetch url"))
    near = await make_finding(db, t.a_svc, "n", number=11, raw=_raw("ssrf fetch"))
    await make_finding(db, t.b_svc, "f", number=12, raw=_raw("ssrf fetch url now"))
    await embed_pending(db, FakeEmbedClient())
    return target, near


async def test_find_similar_by_number_scoped(db, two_teams, embeddings_on):
    target, near = await _data(db, two_teams)
    p = await _principal(db, two_teams.dev_a[0])
    out = await agent_tools.find_similar(db, p, "SV-10", k=5)
    assert out["notice"] == agent_tools.UNTRUSTED_NOTICE
    assert [i["id"] for i in out["items"]] == [str(near.id)]
    item = out["items"][0]
    assert item["untrusted"]["title"] == near.title and "title" not in item
    assert out["pending"] is False


async def test_find_similar_foreign_is_not_found(db, two_teams, embeddings_on):
    await _data(db, two_teams)
    p = await _principal(db, two_teams.dev_a[0])
    with pytest.raises(HTTPException) as e:
        await agent_tools.find_similar(db, p, "SV-12")
    assert e.value.status_code == 404


async def test_find_similar_disabled(db, two_teams):
    await make_finding(db, two_teams.a_svc, "t", number=10)
    p = await _principal(db, two_teams.dev_a[0])
    with pytest.raises(HTTPException) as e:
        await agent_tools.find_similar(db, p, "SV-10")
    assert "выключен" in e.value.detail


async def test_search_findings_query(db, two_teams, embeddings_on):
    target, near = await _data(db, two_teams)
    p = await _principal(db, two_teams.dev_a[0])
    out = await agent_tools.search_findings(db, p, query="ssrf fetch url")
    ids = [f["id"] for f in out["findings"]]
    assert ids == [str(target.id), str(near.id)]  # чужая ветка не видна
    assert out["findings"][0]["similarity"] >= out["findings"][1]["similarity"]
    assert out["notice"] == agent_tools.UNTRUSTED_NOTICE


async def test_search_findings_query_disabled(db, two_teams):
    p = await _principal(db, two_teams.dev_a[0])
    with pytest.raises(HTTPException) as e:
        await agent_tools.search_findings(db, p, query="ssrf")
    assert "выключен" in e.value.detail
    # без query — обычный поиск работает
    assert (await agent_tools.search_findings(db, p))["findings"] == []


async def test_search_findings_query_model_error(db, two_teams, embeddings_on):
    p = await _principal(db, two_teams.dev_a[0])
    embeddings_on.error = True
    with pytest.raises(HTTPException) as e:
        await agent_tools.search_findings(db, p, query="ssrf")
    assert e.value.status_code == 503
