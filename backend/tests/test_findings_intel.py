"""API находок и метрики: блок intel в SV-N, фильтры/сортировка списка, cwe_category и kev."""

from __future__ import annotations

from datetime import date

from app.models import IntelCwe, IntelEpss, IntelKev
from app.models.intel import IntelBdu, IntelBduCve, IntelSource, IntelSourceState, IntelStatus
from tests.factories import make_entity, make_finding


async def _setup(db):
    e = await make_entity(db)
    db.add_all([
        IntelCwe(cwe_id="CWE-89", name="SQL Injection", category="Injection"),
        IntelCwe(cwe_id="CWE-502", name="Deserialization", category="Resource Control"),
        IntelEpss(cve_id="CVE-2021-44228", epss=0.94, percentile=0.99),
        IntelEpss(cve_id="CVE-2014-0160", epss=0.2, percentile=0.7),
        IntelKev(cve_id="CVE-2021-44228", ransomware=True, date_added=date(2021, 12, 10),
                 due_date=date(2021, 12, 24), name="Log4j RCE"),
        IntelBdu(bdu_id="BDU:2021-05969", name="Log4j", severity="Критический"),
        IntelBduCve(bdu_id="BDU:2021-05969", cve_id="CVE-2021-44228"),
        IntelSourceState(source=IntelSource.kev, status=IntelStatus.ok,
                         file_date=date(2020, 1, 1)),
        IntelSourceState(source=IntelSource.epss, status=IntelStatus.ok,
                         file_date=date(2099, 1, 1)),
    ])
    await db.commit()
    log4j = await make_finding(db, e, "a", cwe="CWE-502", cves=["CVE-2021-44228"],
                               epss_max=0.94, kev=True, has_bdu=True)
    heart = await make_finding(db, e, "b", cves=["CVE-2014-0160", "CVE-2099-0001"],
                               epss_max=0.2)
    sqli = await make_finding(db, e, "c", cwe="CWE-89")
    plain = await make_finding(db, e, "d")
    return log4j, heart, sqli, plain


async def _numbers(client, h, query: str) -> list[int]:
    r = await client.get(f"/api/v1/findings?{query}", headers=h)
    assert r.status_code == 200, r.text
    return [f["number"] for f in r.json()]


async def test_detail_intel_block(client, admin, db):
    log4j, heart, sqli, plain = await _setup(db)
    _, h = admin
    r = await client.get(f"/api/v1/findings/{log4j.id}", headers=h)
    intel = r.json()["intel"]
    assert intel["cwe"] == {"id": "CWE-502", "name": "Deserialization",
                            "category": "Resource Control"}
    [cve] = intel["cves"]
    assert cve["id"] == "CVE-2021-44228" and cve["epss"] == 0.94 and cve["percentile"] == 0.99
    assert cve["kev"] == {"date_added": "2021-12-10", "due_date": "2021-12-24",
                          "name": "Log4j RCE", "ransomware": True}
    assert cve["bdu"] == [{"id": "BDU:2021-05969", "name": "Log4j", "severity": "Критический"}]
    assert intel["stale"] == ["kev"]
    assert intel["sources"]["kev"] == "2020-01-01" and intel["sources"]["bdu"] is None

    r = await client.get(f"/api/v1/findings/{heart.id}", headers=h)
    cves = r.json()["intel"]["cves"]
    assert [c["id"] for c in cves] == ["CVE-2014-0160", "CVE-2099-0001"]
    assert cves[1] == {"id": "CVE-2099-0001", "epss": None, "percentile": None,
                       "kev": None, "bdu": []}

    # CWE без записи в справочнике — id есть, названия нет
    r = await client.get(f"/api/v1/findings/{sqli.id}", headers=h)
    assert r.json()["intel"]["cwe"]["name"] == "SQL Injection"
    r = await client.get(f"/api/v1/findings/{plain.id}", headers=h)
    assert r.json()["intel"] is None


async def test_list_fields_filters_and_order(client, admin, db):
    log4j, heart, sqli, plain = await _setup(db)
    _, h = admin
    r = await client.get("/api/v1/findings?order=epss_max", headers=h)
    rows = r.json()
    assert [f["number"] for f in rows] == [log4j.number, heart.number, plain.number, sqli.number]
    assert rows[0]["epss_max"] == 0.94 and rows[0]["kev"] is True
    assert rows[0]["cves"] == ["CVE-2021-44228"]

    assert await _numbers(client, h, "kev=true") == [log4j.number]
    assert set(await _numbers(client, h, "kev=false")) == {heart.number, sqli.number, plain.number}
    assert set(await _numbers(client, h, "min_epss=0.1")) == {log4j.number, heart.number}
    assert await _numbers(client, h, "min_epss=0.5") == [log4j.number]
    assert await _numbers(client, h, "has_bdu=true") == [log4j.number]
    assert await _numbers(client, h, "cwe_category=Injection") == [sqli.number]
    r = await client.get("/api/v1/findings?min_epss=2", headers=h)
    assert r.status_code == 422


async def test_list_respects_visibility(client, make_user, grant, builtin_policies, db):
    log4j, *_ = await _setup(db)
    other = await make_entity(db, "other")
    user, h = await make_user("dev@test.local")
    await grant(user, "Разработчик", other)
    assert await _numbers(client, h, "kev=true") == []
    r = await client.get(f"/api/v1/findings/{log4j.id}", headers=h)
    assert r.status_code == 404


async def test_metrics_group_by_cwe_category_and_kev_filter(client, admin, db):
    await _setup(db)
    _, h = admin
    r = await client.post("/api/v1/metrics/aggregate", headers=h,
                          json={"metric": "count", "group_by": "cwe_category"})
    assert r.status_code == 200, r.text
    rows = {row["key"]: row["value"] for row in r.json()["rows"]}
    assert rows == {"Injection": 1, "Resource Control": 1, None: 2}

    r = await client.post("/api/v1/metrics/aggregate", headers=h,
                          json={"metric": "count", "filters": {"kev": True}})
    assert r.json()["rows"][0]["value"] == 1
