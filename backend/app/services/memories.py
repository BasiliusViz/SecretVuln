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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload, load_only

from app.models.decision_request import DecisionRequest, DecisionStatus
from app.models.entity import Entity
from app.models.finding import OPEN_STATUSES, Finding
from app.models.finding_event import ActorType, FindingEventType
from app.models.triage_memory import MemorySource, MemoryStatus, TriageMemory
from app.services import audit
from app.services.access import Access, ancestors, in_prefix
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


def _segment_matches(pattern: str, text: str) -> bool:
    """`*` и `?` внутри одного каталога. Без регулярных выражений: время не больше
    len(pattern) * len(text), катастрофического перебора на «злой» маске не бывает."""
    p = t = 0
    star = mark = -1
    while t < len(text):
        if p < len(pattern) and (pattern[p] == "?" or pattern[p] == text[t]):
            p += 1
            t += 1
        elif p < len(pattern) and pattern[p] == "*":
            star, mark = p, t
            p += 1
        elif star != -1:
            p = star + 1
            mark += 1
            t = mark
        else:
            return False
    while p < len(pattern) and pattern[p] == "*":
        p += 1
    return p == len(pattern)


@lru_cache(maxsize=512)
def glob_segments(glob: str) -> tuple[str, ...]:
    """Маска по каталогам; идущие подряд `**` схлопнуты, `**` внутри имени — как `*`."""
    out: list[str] = []
    for seg in normalize_path(glob).split("/"):
        if seg == "**":
            if not out or out[-1] != "**":
                out.append(seg)
        else:
            out.append(re.sub(r"\*+", "*", seg))
    return tuple(out)


def path_matches(glob: str, file_path: str | None) -> bool:
    """`*` и `?` — внутри каталога, `**` — через каталоги, в т. ч. ноль (`a/**/b` ~ `a/b`)."""
    if not file_path:
        return False
    parts = normalize_path(file_path).split("/")
    # reach — до каких позиций пути можно дойти, разобрав очередной кусок маски
    reach = {0}
    for seg in glob_segments(glob):
        if seg == "**":
            reach = set(range(min(reach), len(parts) + 1))
        else:
            reach = {i + 1 for i in reach if i < len(parts) and _segment_matches(seg, parts[i])}
        if not reach:
            return False
    return len(parts) in reach


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
    old_id = finding.memory_id
    changed = old_id != new_id
    if memory is None:
        if changed:
            _clear_hint(db, finding, actor_id=actor_id)
        return changed
    finding.memory_id = new_id
    if changed or always_event:
        record_event(
            db, finding.id, FindingEventType.memory_hint,
            actor_type=ActorType.user if actor_id else ActorType.system,
            actor_id=actor_id,
            reason=memory.reason,
            reason_tag=memory.reason_tag.value if memory.reason_tag else None,
            payload={"memory_id": str(memory.id), "decision": memory.decision.value},
        )
    return changed


def _clear_hint(db: AsyncSession, finding: Finding, *, actor_id: uuid.UUID | None = None) -> None:
    """Снять подсказку и записать это в историю (без текста правила: оно может быть
    уже не про эту находку). Ключ `removed_memory_id`, не `memory_id`: событие не
    «по правилу»."""
    old_id = finding.memory_id
    finding.memory_id = None
    record_event(
        db, finding.id, FindingEventType.memory_hint_removed,
        actor_type=ActorType.user if actor_id else ActorType.system,
        actor_id=actor_id,
        payload={"removed_memory_id": str(old_id)},
    )


def _still_applies(rules: dict[uuid.UUID, Rule], finding: Finding, path: str) -> bool:
    """Правило, стоящее у находки, всё ещё действует на неё."""
    rule = rules.get(finding.memory_id)
    return rule is not None and in_prefix(path, rule.path) and conditions_match(rule.memory, finding)


async def hint_in_scope(db: AsyncSession, finding: Finding, memory: TriageMemory) -> bool:
    """Область правила — проект находки или его предок (страховка от устаревшего
    `memory_id`: подсказка не должна выдавать правило чужой ветки)."""
    finding_path = await db.scalar(select(Entity.path_cache).where(Entity.id == finding.entity_id))
    memory_path = await db.scalar(select(Entity.path_cache).where(Entity.id == memory.entity_id))
    return (
        finding_path is not None and memory_path is not None
        and in_prefix(finding_path, memory_path)
    )


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
            _clear_hint(db, finding, actor_id=actor_id)
            changed += 1
    await db.flush()
    return changed


async def recompute_subtree(
    db: AsyncSession, entity_ids: list[uuid.UUID], *, actor_id: uuid.UUID | None = None
) -> int:
    """Пересчёт подсказок находок поддерева после переноса проекта: набор правил
    предков сменился. Открытым — самое точное правило заново; у закрытых подсказка
    только снимается, если её правило больше на них не действует."""
    if not entity_ids:
        return 0
    await db.flush()
    rules = await load_rules(db)
    by_id = {r.memory.id: r for r in rules}
    rows = (
        await db.execute(
            select(Finding, Entity.path_cache)
            .join(Entity, Entity.id == Finding.entity_id)
            .where(
                Finding.entity_id.in_(entity_ids),
                or_(Finding.status.in_(OPEN_STATUSES), Finding.memory_id.is_not(None)),
            )
            .options(*_LIGHT)
        )
    ).all()
    changed = 0
    for finding, path in rows:
        if finding.status in OPEN_STATUSES:
            changed += _set_hint(db, finding, pick(rules, finding, path), actor_id=actor_id)
        elif not _still_applies(by_id, finding, path):
            _clear_hint(db, finding, actor_id=actor_id)
            changed += 1
    await db.flush()
    return changed


async def open_hint_counts(
    db: AsyncSession, memory_ids: Iterable[uuid.UUID], access: Access
) -> dict[uuid.UUID, int]:
    """Число открытых находок с подсказкой по каждому правилу — только в проектах,
    где у читателя есть `finding:read` (правило сверху не выдаёт объём чужих веток)."""
    ids = list(memory_ids)
    if not ids:
        return {}
    rows = await db.execute(
        select(Finding.memory_id, func.count())
        .where(
            Finding.memory_id.in_(ids),
            Finding.status.in_(OPEN_STATUSES),
            access.entity_scope("finding:read", Finding.entity_id),
        )
        .group_by(Finding.memory_id)
    )
    return {mid: n for mid, n in rows.all()}


# --- предложения ---


async def suggest_after_approval(
    db: AsyncSession, finding: Finding, req: DecisionRequest
) -> TriageMemory | None:
    """После одобрения решения: если в проекте набралось SUGGEST_THRESHOLD разных находок
    с одобренным решением этого типа по тому же (сканер, правило сканера) — создаёт
    правило `suggested`. Не предлагает, если запрос был «по правилу», если на находку
    уже действует правило (здесь или сверху), если то же уже предлагалось (ключ
    происхождения `suggest_key` не меняется при правке и переносе) или есть правило с
    теми же сканером, правилом и решением в проекте или у предка (в любом статусе)."""
    if not finding.rule_id or req.memory_id is not None:
        return None
    await db.flush()
    path = await db.scalar(select(Entity.path_cache).where(Entity.id == finding.entity_id))
    if path is None or pick(await load_rules(db, path), finding, path) is not None:
        return None
    scanner = (finding.scanner or "").strip().lower()
    key = f"{finding.entity_id}|{scanner}|{finding.rule_id}|{req.decision_type.value}"
    chain = select(Entity.id).where(Entity.path_cache.in_([*ancestors(path), path]))
    existing = await db.scalar(
        select(TriageMemory.id).where(or_(
            TriageMemory.suggest_key == key,
            and_(
                TriageMemory.entity_id.in_(chain),
                func.lower(func.trim(TriageMemory.scanner)) == scanner,
                TriageMemory.rule_id == finding.rule_id,
                TriageMemory.decision == req.decision_type,
            ),
        )).limit(1)
    )
    if existing is not None:
        return None
    rows = (
        await db.execute(
            select(DecisionRequest.finding_id, DecisionRequest.reason_tag, DecisionRequest.reason)
            .join(Finding, Finding.id == DecisionRequest.finding_id)
            .where(
                Finding.entity_id == finding.entity_id,
                func.lower(func.trim(Finding.scanner)) == scanner,
                Finding.rule_id == finding.rule_id,
                DecisionRequest.decision_type == req.decision_type,
                DecisionRequest.status == DecisionStatus.approved,
            )
            # свежие первыми: обоснование — из последнего решения с выбранной причиной
            .order_by(
                DecisionRequest.decided_at.desc().nulls_last(),
                DecisionRequest.created_at.desc(),
            )
        )
    ).all()
    findings_n = len({r.finding_id for r in rows})
    if findings_n < SUGGEST_THRESHOLD:
        return None
    common = Counter(r.reason_tag for r in rows if r.reason_tag is not None).most_common(1)
    tag = common[0][0] if common else None
    # причина и текст — из одного запроса, иначе пара может не пройти check_rule
    reason = next((r.reason for r in rows if r.reason_tag == tag and r.reason), None)
    memory = TriageMemory(
        id=uuid.uuid4(),
        entity_id=finding.entity_id,
        scanner=finding.scanner,
        rule_id=finding.rule_id,
        decision=req.decision_type,
        reason_tag=tag,
        reason=reason,
        status=MemoryStatus.suggested,
        source=MemorySource.suggested,
        suggest_key=key,
    )
    try:
        # два одобрения одновременно: второе упрётся в уникальный suggest_key
        async with db.begin_nested():
            db.add(memory)
            await db.flush()
    except IntegrityError:
        return None
    # создано системой — в журнале без автора
    audit.record_audit(
        db, None, audit.MEMORY_SUGGEST,
        target=("memory", memory.id, audit.memory_label(memory)),
        entity=await db.get(Entity, finding.entity_id),
        changes={
            **audit.snapshot(memory, audit.FIELDS["memory"]),
            "decision_id": str(req.id),
            "approved_decisions": len(rows),
            "approved_findings": findings_n,
        },
    )
    return memory
