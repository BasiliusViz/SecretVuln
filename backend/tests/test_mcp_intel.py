"""MCP: get_finding отдаёт блок intel, search_findings — фильтры kev и min_epss."""

from __future__ import annotations

from app.api.deps import Principal
from app.models import IntelKev
from app.services import agent_tools
from app.services.access import load_access
from tests.factories import make_finding


async def _principal(db, user) -> Principal:
    return Principal(user=user, access=await load_access(db, user))


async def test_get_finding_intel_and_search_filters(db, two_teams):
    t = two_teams
    db.add(IntelKev(cve_id="CVE-2021-44228", ransomware=False))
    await db.commit()
    hot = await make_finding(db, t.a_svc, "hot", number=21, cves=["CVE-2021-44228"],
                             kev=True, epss_max=0.9)
    cold = await make_finding(db, t.a_svc, "cold", number=22, epss_max=0.01)
    foreign = await make_finding(db, t.b_svc, "f", number=23, kev=True, epss_max=0.99)
    p = await _principal(db, t.dev_a[0])

    out = await agent_tools.get_finding(db, p, "SV-21")
    assert out["finding"]["kev"] is True and out["finding"]["cves"] == ["CVE-2021-44228"]
    [cve] = out["intel"]["cves"]
    assert cve["kev"]["ransomware"] is False

    found = await agent_tools.search_findings(db, p, kev=True)
    assert [f["number"] for f in found["findings"]] == ["SV-21"]
    found = await agent_tools.search_findings(db, p, min_epss=0.5)
    assert [f["number"] for f in found["findings"]] == ["SV-21"]
    found = await agent_tools.search_findings(db, p, order="epss_max")
    assert [f["number"] for f in found["findings"]] == ["SV-21", "SV-22"]
    assert hot.id and cold.id and foreign.id
