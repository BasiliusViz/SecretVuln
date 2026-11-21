"""Обогащение при импорте, backfill старых находок, встроенный CWE."""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import Finding, IntelCwe, IntelEpss, IntelKev
from app.models.intel import IntelBdu, IntelBduCve, IntelSource, IntelSourceState, IntelStatus
from app.services.import_processing import apply_import
from app.services.intel.builtin import backfill_cves, seed_builtin_cwe
from app.services.sarif import parse_sarif
from tests.factories import make_entity, make_finding, make_import, make_sarif


async def _intel(db):
    db.add_all([
        IntelEpss(cve_id="CVE-2021-44228", epss=0.94, percentile=0.99),
        IntelEpss(cve_id="CVE-2014-0160", epss=0.5, percentile=0.8),
        IntelKev(cve_id="CVE-2021-44228", ransomware=True),
        IntelBdu(bdu_id="BDU:2014-00001", name="Heartbleed", severity="Высокий"),
        IntelBduCve(bdu_id="BDU:2014-00001", cve_id="CVE-2014-0160"),
    ])
    await db.commit()


async def test_import_fills_cves_and_summary(db):
    await _intel(db)
    e = await make_entity(db)
    imp = await make_import(db, e)
    runs = parse_sarif(make_sarif("Trivy", [
        {"rule_id": "CVE-2021-44228", "fp": "a"},
        {"rule_id": "CVE-2014-0160", "fp": "b"},
        {"rule_id": "semgrep.sqli", "fp": "c"},
    ]))
    await apply_import(db, imp, runs)
    await db.commit()

    rows = {
        f.fingerprint: f for f in (await db.scalars(
            select(Finding).execution_options(populate_existing=True))).all()
    }
    assert rows["a"].cves == ["CVE-2021-44228"]
    assert rows["a"].kev is True and rows["a"].epss_max == 0.94 and rows["a"].has_bdu is False
    assert rows["b"].has_bdu is True and rows["b"].kev is False
    assert rows["c"].cves == [] and rows["c"].epss_max is None


async def test_reimport_updates_existing(db):
    e = await make_entity(db)
    imp = await make_import(db, e)
    sarif = make_sarif("Trivy", [{"rule_id": "CVE-2021-44228", "fp": "a"}])
    await apply_import(db, imp, parse_sarif(sarif))
    await db.commit()
    await _intel(db)  # справочник загрузили после первого импорта

    imp2 = await make_import(db, e)
    await apply_import(db, imp2, parse_sarif(sarif))
    await db.commit()
    f = await db.scalar(select(Finding).execution_options(populate_existing=True))
    assert f.kev is True


async def test_backfill_from_raw_is_idempotent(db):
    await _intel(db)
    e = await make_entity(db)
    old = await make_finding(db, e, "a", raw={"ruleId": "CVE-2021-44228"})
    kept = await make_finding(db, e, "b", raw={"ruleId": "x"}, cves=["CVE-2014-0160"])
    plain = await make_finding(db, e, "c", raw={"ruleId": "semgrep.sqli"})

    changed, updated = await backfill_cves(db)
    assert changed == 1
    assert updated == 2
    for f in (old, kept, plain):
        await db.refresh(f)
    assert old.cves == ["CVE-2021-44228"] and old.kev is True
    assert kept.cves == ["CVE-2014-0160"] and kept.has_bdu is True
    assert plain.cves == []

    assert await backfill_cves(db) == (0, 0)


async def test_builtin_cwe_seed_only_when_empty(db):
    n = await seed_builtin_cwe(db)
    assert n > 1000
    sql = await db.get(IntelCwe, "CWE-89")
    assert sql.category == "Injection"
    state = await db.get(IntelSourceState, IntelSource.cwe)
    assert state.status == IntelStatus.ok and state.record_count == n
    assert await seed_builtin_cwe(db) == 0
    assert await db.scalar(select(func.count()).select_from(IntelCwe)) == n
