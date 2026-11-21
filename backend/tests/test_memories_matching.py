"""Правила команды: сопоставление, выбор самого точного, подсказка при импорте, пересчёт."""

import pytest
from sqlalchemy import select

from app.models import Finding, FindingEvent, FindingEventType, MemoryStatus
from app.models.finding import FindingStatus
from app.services.import_processing import apply_import
from app.services.memories import (
    Rule,
    conditions_match,
    load_rules,
    path_matches,
    pick,
    recompute,
)
from app.services.sarif import parse_sarif
from tests.factories import make_entity, make_finding, make_import, make_memory, make_sarif


@pytest.mark.parametrize(
    "glob, path, ok",
    [
        ("tests/*", "tests/a.py", True),
        ("tests/*", "tests/unit/a.py", False),
        ("tests/**", "tests/unit/a.py", True),
        ("tests/**", "src/tests/a.py", False),
        ("**/tests/**", "src/tests/a.py", True),
        ("**/tests/**", "tests/a.py", True),
        ("**/test_*.py", "test_a.py", True),
        ("**/test_*.py", "pkg/sub/test_a.py", True),
        ("src/**/gen/*.py", "src/gen/a.py", True),
        ("src/**/gen/*.py", "src/x/y/gen/a.py", True),
        ("src/**/gen/*.py", "src/x/gen/sub/a.py", False),
        ("a?.py", "ab.py", True),
        ("a?.py", "a/.py", False),
        ("app/a.py", "./app/a.py", True),
        ("app/a.py", "app\\a.py", True),
        ("app/a.py", "app/a.pyc", False),
        ("a+b/*.py", "a+b/x.py", True),
        ("tests/**", None, False),
        ("**", "a/b.py", True),
        ("tests/**/**/*.py", "tests/a.py", True),
        ("a**b/*.py", "axxb/c.py", True),
        ("a**b/*.py", "a/b/c.py", False),
        ("*.py", "a/b.py", False),
    ],
)
def test_path_mask(glob, path, ok):
    assert path_matches(glob, path) is ok


def test_hostile_mask_is_fast():
    import time

    path = "/".join(["a" * 20] * 40) + "/x.py"
    globs = ("**/" * 100 + "nope", "*a" * 140 + "b", "**" * 150, "/".join(["*a*a*a*b"] * 30))
    started = time.perf_counter()
    for glob in globs:
        assert path_matches(glob, path) is False
    assert time.perf_counter() - started < 1


async def test_each_condition_must_match(db):
    entity = await make_entity(db)
    finding = await make_finding(
        db, entity, scanner="Semgrep", rule_id="rule.a", cwe="CWE-89", file_path="tests/a.py"
    )

    async def matches(**kw):
        return conditions_match(await make_memory(db, entity, **kw), finding)

    assert await matches(scanner="semgrep")  # сканер и CWE — без учёта регистра
    assert not await matches(scanner="trivy")
    assert await matches(rule_id="rule.a")
    assert not await matches(rule_id="rule.b")
    assert await matches(cwe="cwe-89")
    assert not await matches(cwe="CWE-79")
    assert await matches(path_glob="tests/**")
    assert not await matches(path_glob="src/**")
    # все заданные сразу
    assert await matches(scanner="Semgrep", rule_id="rule.a", cwe="CWE-89", path_glob="tests/*")
    assert not await matches(scanner="Semgrep", rule_id="rule.a", path_glob="src/**")


async def test_scope_is_entity_or_ancestor_and_only_approved(db):
    root = await make_entity(db, "fintech")
    svc = await make_entity(db, "api", parent_id=root.id)
    other = await make_entity(db, "other")
    finding = await make_finding(db, svc, rule_id="rule.a")

    await make_memory(db, other)
    await make_memory(db, root, status=MemoryStatus.suggested)
    await make_memory(db, root, status=MemoryStatus.disabled)
    assert pick(await load_rules(db), finding, svc.path_cache) is None
    assert await load_rules(db, svc.path_cache) == []

    on_root = await make_memory(db, root)
    assert pick(await load_rules(db), finding, svc.path_cache).id == on_root.id
    assert [r.memory.id for r in await load_rules(db, svc.path_cache)] == [on_root.id]


async def test_most_precise_wins(db):
    root = await make_entity(db, "fintech")
    svc = await make_entity(db, "api", parent_id=root.id)
    finding = await make_finding(db, svc, rule_id="rule.a", file_path="tests/a.py")

    far_exact = await make_memory(db, root, rule_id="rule.a", path_glob="tests/**")
    near_first = await make_memory(db, svc, rule_id="rule.a")
    rules = await load_rules(db)
    # ближайшая область важнее числа условий
    assert pick(rules, finding, svc.path_cache).id == near_first.id

    near_exact = await make_memory(db, svc, rule_id="rule.a", path_glob="tests/**")
    near_late = await make_memory(db, svc, rule_id="rule.a")
    rules = await load_rules(db)
    # при равной области — больше условий
    assert pick(rules, finding, svc.path_cache).id == near_exact.id
    # при прочих равных — более раннее
    tie = [Rule(near_late, svc.path_cache), Rule(near_first, svc.path_cache)]
    assert pick(tie, finding, svc.path_cache).id == near_first.id
    assert far_exact.id not in {pick(rules, finding, svc.path_cache).id}


# --- импорт ---


async def _run(db, entity, results):
    imp = await make_import(db, entity)
    stats = await apply_import(db, imp, parse_sarif(make_sarif("Semgrep", results)))
    await db.commit()
    return stats


async def _hints(db, finding):
    return (
        await db.scalars(
            select(FindingEvent).where(
                FindingEvent.finding_id == finding.id,
                FindingEvent.event_type == FindingEventType.memory_hint,
            )
        )
    ).all()


async def test_import_hints_new_finding_without_changing_status(db):
    entity = await make_entity(db)
    memory = await make_memory(db, entity, rule_id="rule.a", path_glob="tests/**")
    stats = await _run(
        db, entity,
        [{"fp": "a", "path": "tests/a.py"}, {"fp": "b", "path": "src/b.py"}],
    )
    assert stats["memory_hints"] == 1
    a = await db.scalar(select(Finding).where(Finding.fingerprint == "a"))
    b = await db.scalar(select(Finding).where(Finding.fingerprint == "b"))
    assert a.memory_id == memory.id and a.status == FindingStatus.new
    assert b.memory_id is None
    events = await _hints(db, a)
    assert len(events) == 1
    assert events[0].payload == {"memory_id": str(memory.id), "decision": "false_positive"}
    assert await _hints(db, b) == []


async def test_import_hints_reopened_but_not_duplicates(db):
    entity = await make_entity(db)
    await _run(db, entity, [{"fp": "a"}, {"fp": "b"}])
    a = await db.scalar(select(Finding).where(Finding.fingerprint == "a"))
    b = await db.scalar(select(Finding).where(Finding.fingerprint == "b"))
    a.status = FindingStatus.fixed
    await db.commit()
    # правило не утверждалось через API — у открытой «b» подсказки нет и импорт её не ставит
    memory = await make_memory(db, entity)

    await _run(db, entity, [{"fp": "a"}, {"fp": "b"}])
    await db.refresh(a)
    await db.refresh(b)
    assert a.status == FindingStatus.new and a.memory_id == memory.id
    assert len(await _hints(db, a)) == 1
    assert b.memory_id is None


# --- пересчёт ---


async def test_recompute_on_approve_disable_and_edit(db):
    root = await make_entity(db, "fintech")
    svc = await make_entity(db, "api", parent_id=root.id)
    other = await make_entity(db, "other")
    in_tests = await make_finding(db, svc, "f1", rule_id="rule.a", file_path="tests/a.py")
    in_src = await make_finding(db, svc, "f2", rule_id="rule.a", file_path="src/a.py")
    closed = await make_finding(
        db, svc, "f3", rule_id="rule.a", file_path="tests/b.py", status=FindingStatus.fixed
    )
    foreign = await make_finding(db, other, "f4", rule_id="rule.a")

    async def refresh():
        await db.commit()
        for f in (in_tests, in_src, closed, foreign):
            await db.refresh(f)

    wide = await make_memory(db, root)  # rule.a на всём fintech
    assert await recompute(db, wide) == 2
    await refresh()
    assert in_tests.memory_id == wide.id and in_src.memory_id == wide.id
    assert closed.memory_id is None and foreign.memory_id is None  # закрытые и чужие не трогаем

    narrow = await make_memory(db, svc, rule_id="rule.a", path_glob="tests/**")
    assert await recompute(db, narrow) == 1
    await refresh()
    assert in_tests.memory_id == narrow.id and in_src.memory_id == wide.id

    # повторное утверждение широкого не перебивает более точное
    assert await recompute(db, wide) == 0

    # правка условия: узкое больше не подходит — находка возвращается к широкому
    narrow.path_glob = "docs/**"
    await recompute(db, narrow)
    await refresh()
    assert in_tests.memory_id == wide.id

    # выключение: подсказки сбрасываются, других правил нет
    wide.status = MemoryStatus.disabled
    await recompute(db, wide)
    await refresh()
    assert in_tests.memory_id is None and in_src.memory_id is None


async def test_disable_clears_closed_findings_but_keeps_status(db):
    entity = await make_entity(db)
    memory = await make_memory(db, entity)
    decided = await make_finding(
        db, entity, rule_id="rule.a", status=FindingStatus.false_positive, memory_id=memory.id
    )
    memory.status = MemoryStatus.disabled
    await recompute(db, memory)
    await db.commit()
    await db.refresh(decided)
    assert decided.memory_id is None
    assert decided.status == FindingStatus.false_positive
