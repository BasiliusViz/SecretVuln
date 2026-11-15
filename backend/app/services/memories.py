"""Правила команды («память»): сопоставление с находками и подсказки.

Правило только подсказывает: ставит `findings.memory_id` и пишет событие
`memory_hint`. Статус находки меняет человек — через обычный запрос решения.

Одна логика выбора (`pick`) для импорта, утверждения, правки и выключения правила.
Подходят только правила `approved`, чья область — проект находки или его предок.
Если подошло несколько — самое точное: ближайшая область → больше условий → раньше создано.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload, load_only

from app.models.decision_request import DecisionRequest, DecisionStatus
from app.models.entity import Entity
from app.models.finding import OPEN_STATUSES, Finding
from app.models.finding_event import ActorType, FindingEventType
from app.models.triage_memory import MemorySource, MemoryStatus, TriageMemory
from app.services import audit
from app.services.access import ancestors, in_prefix
from app.services.events import record_event

CONDITION_FIELDS: tuple[str, ...] = ("scanner", "rule_id", "cwe", "path_glob")
# Сколько одобренных решений одного типа по одному (сканер, правило) в проекте
# нужно, чтобы предложить правило команды.
SUGGEST_THRESHOLD = 3


@dataclass(frozen=True)
class Rule:
    """Правило вместе с путём его области."""

    memory: TriageMemory
    path: str


# --- маска пути ---


def normalize_path(path: str | None) -> str:
    p = (path or "").replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


@lru_cache(maxsize=512)
def glob_regex(glob: str) -> re.Pattern[str]:
    """`*` и `?` — внутри каталога, `**` — через каталоги (`a/**/b` подходит и к `a/b`)."""
    g = normalize_path(glob)
    out: list[str] = []
    i = 0
    while i < len(g):
        if g.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif g.startswith("**", i):
            out.append(".*")
            i += 2
        elif g[i] == "*":
            out.append("[^/]*")
            i += 1
        elif g[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(g[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def path_matches(glob: str, file_path: str | None) -> bool:
    if not file_path:
        return False
    return glob_regex(glob).match(normalize_path(file_path)) is not None


# --- сопоставление ---


def _same(a: str | None, b: str | None) -> bool:
    return a is not None and b is not None and a.strip().lower() == b.strip().lower()


def conditions_match(memory: TriageMemory, finding: Finding) -> bool:
    """Все заданные условия правила совпали с находкой (пустое правило не подходит никому)."""
    if not any(getattr(memory, f) for f in CONDITION_FIELDS):
        return False
    if memory.scanner and not _same(memory.scanner, finding.scanner):
        return False
    if memory.rule_id and memory.rule_id != finding.rule_id:
        return False
    if memory.cwe and not _same(memory.cwe, finding.cwe):
        return False
    if memory.path_glob and not path_matches(memory.path_glob, finding.file_path):
        return False
    return True


def precision(rule: Rule) -> tuple:
    """Ключ сортировки: меньше — точнее."""
    conditions = sum(1 for f in CONDITION_FIELDS if getattr(rule.memory, f))
    return (-rule.path.count("/"), -conditions, rule.memory.created_at, str(rule.memory.id))


def pick(rules: Iterable[Rule], finding: Finding, finding_path: str) -> TriageMemory | None:
    """Самое точное из подходящих правил или None."""
    matched = [
        r for r in rules
        if in_prefix(finding_path, r.path) and conditions_match(r.memory, finding)
    ]
    return min(matched, key=precision).memory if matched else None


async def load_rules(db: AsyncSession, for_path: str | None = None) -> list[Rule]:
    """Действующие правила: все или только применимые к проекту `for_path` (он и предки)."""
    q = (
        select(TriageMemory, Entity.path_cache)
        .join(Entity, Entity.id == TriageMemory.entity_id)
        .where(TriageMemory.status == MemoryStatus.approved)
    )
    if for_path is not None:
        q = q.where(Entity.path_cache.in_([*ancestors(for_path), for_path]))
    return [Rule(m, p) for m, p in (await db.execute(q)).all()]


# --- применение ---


def _set_hint(
    db: AsyncSession,
    finding: Finding,
    memory: TriageMemory | None,
    *,
    always_event: bool = False,
    actor_id: uuid.UUID | None = None,
) -> bool:
    new_id = memory.id if memory else None
    changed = finding.memory_id != new_id
    finding.memory_id = new_id
    if memory is not None and (changed or always_event):
        record_event(
            db, finding.id, FindingEventType.memory_hint,
            actor_type=ActorType.user if actor_id else ActorType.system,
            actor_id=actor_id,
            reason=memory.reason,
            reason_tag=memory.reason_tag.value if memory.reason_tag else None,
            payload={"memory_id": str(memory.id), "decision": memory.decision.value},
        )
    return changed


async def hint_imported(db: AsyncSession, findings: list[Finding], entity_id: uuid.UUID) -> int:
    """Подсказки новым и переоткрытым находкам импорта. Возвращает число находок с подсказкой."""
    if not findings:
        return 0
    path = await db.scalar(select(Entity.path_cache).where(Entity.id == entity_id))
    rules = await load_rules(db, path)
    hinted = 0
    for finding in findings:
        memory = pick(rules, finding, path) if rules else None
        _set_hint(db, finding, memory, always_event=True)
        hinted += memory is not None
    return hinted


_LIGHT = (
    load_only(
        Finding.entity_id, Finding.status, Finding.scanner, Finding.rule_id, Finding.cwe,
        Finding.file_path, Finding.memory_id,
    ),
    lazyload(Finding.assignee_group),
    lazyload(Finding.assignee_user),
    lazyload(Finding.memory),
)


async def recompute(
    db: AsyncSession, memory: TriageMemory, *, actor_id: uuid.UUID | None = None
) -> int:
    """Пересчёт подсказок после утверждения, правки или выключения правила.

    Затрагивает находки, у которых это правило уже стоит, и открытые находки его
    области, подходящие под условие. Каждой открытой выбирается самое точное из всех
    действующих правил; у закрытых подсказка только снимается (решения не откатываются).
    Возвращает число изменённых находок.
    """
    await db.flush()
    rules = await load_rules(db)
    active = memory.status == MemoryStatus.approved
    scope_path = await db.scalar(select(Entity.path_cache).where(Entity.id == memory.entity_id))

    cond = [Finding.memory_id == memory.id]
    if active and scope_path is not None:
        in_scope = [
            Finding.status.in_(OPEN_STATUSES),
            or_(Entity.path_cache == scope_path,
                func.starts_with(Entity.path_cache, scope_path + "/")),
        ]
        # грубый отбор в SQL, точное сравнение (и маска пути) — в conditions_match
        if memory.scanner:
            in_scope.append(func.lower(Finding.scanner) == memory.scanner.strip().lower())
        if memory.rule_id:
            in_scope.append(Finding.rule_id == memory.rule_id)
        if memory.cwe:
            in_scope.append(func.lower(Finding.cwe) == memory.cwe.strip().lower())
        cond.append(and_(*in_scope))

    rows = (
        await db.execute(
            select(Finding, Entity.path_cache)
            .join(Entity, Entity.id == Finding.entity_id)
            .where(or_(*cond))
            .options(*_LIGHT)
        )
    ).all()

    changed = 0
    for finding, path in rows:
        if finding.status in OPEN_STATUSES:
            best = pick(rules, finding, path)
            changed += _set_hint(db, finding, best, actor_id=actor_id)
        elif finding.memory_id == memory.id and not (
            active and in_prefix(path, scope_path or "") and conditions_match(memory, finding)
        ):
            finding.memory_id = None
            changed += 1
    await db.flush()
    return changed


async def open_hint_counts(db: AsyncSession, memory_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Число открытых находок с подсказкой по каждому правилу."""
    ids = list(memory_ids)
    if not ids:
        return {}
    rows = await db.execute(
        select(Finding.memory_id, func.count())
        .where(Finding.memory_id.in_(ids), Finding.status.in_(OPEN_STATUSES))
        .group_by(Finding.memory_id)
    )
    return {mid: n for mid, n in rows.all()}


# --- предложения ---


async def suggest_after_approval(
    db: AsyncSession, finding: Finding, req: DecisionRequest
) -> TriageMemory | None:
    """После одобрения решения: если в проекте набралось SUGGEST_THRESHOLD одобренных
    решений этого типа по тому же (сканер, правило сканера), а правила команды с таким
    же проектом, сканером, правилом и решением ещё нет (в любом статусе, в т. ч.
    отклонённого) — создаёт правило `suggested`."""
    if not finding.rule_id:
        return None
    await db.flush()
    same = (
        TriageMemory.entity_id == finding.entity_id,
        TriageMemory.scanner == finding.scanner,
        TriageMemory.rule_id == finding.rule_id,
        TriageMemory.decision == req.decision_type,
    )
    if await db.scalar(select(TriageMemory.id).where(*same).limit(1)) is not None:
        return None
    tags = (
        await db.scalars(
            select(DecisionRequest.reason_tag)
            .join(Finding, Finding.id == DecisionRequest.finding_id)
            .where(
                Finding.entity_id == finding.entity_id,
                Finding.scanner == finding.scanner,
                Finding.rule_id == finding.rule_id,
                DecisionRequest.decision_type == req.decision_type,
                DecisionRequest.status == DecisionStatus.approved,
            )
        )
    ).all()
    if len(tags) < SUGGEST_THRESHOLD:
        return None
    common = Counter(t for t in tags if t is not None).most_common(1)
    memory = TriageMemory(
        id=uuid.uuid4(),
        entity_id=finding.entity_id,
        scanner=finding.scanner,
        rule_id=finding.rule_id,
        decision=req.decision_type,
        reason_tag=common[0][0] if common else None,
        reason=req.reason,
        status=MemoryStatus.suggested,
        source=MemorySource.suggested,
    )
    db.add(memory)
    # создано системой — в журнале без автора
    audit.record_audit(
        db, None, audit.MEMORY_SUGGEST,
        target=("memory", memory.id, audit.memory_label(memory)),
        entity=await db.get(Entity, finding.entity_id),
        changes={
            **audit.snapshot(memory, audit.FIELDS["memory"]),
            "decision_id": str(req.id),
            "approved_decisions": len(tags),
        },
    )
    return memory
