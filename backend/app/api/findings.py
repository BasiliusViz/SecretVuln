import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, ensure, not_found, require_permission
from app.db.session import get_db
from app.models import (
    DecisionRequest,
    DecisionStatus,
    Entity,
    Finding,
    Import,
    User,
    UserGroup,
    user_group_members,
)
from app.models.decision_request import DecisionType
from app.models.entity import RepoType
from app.models.finding import OPEN_STATUSES, FindingStatus, Severity
from app.models.finding_event import ActorType, FindingEvent, FindingEventType
from app.schemas.decision import DecisionCreate
from app.schemas.finding import (
    BulkAction,
    BulkResult,
    BulkSkipped,
    CommentCreate,
    FindingAssign,
    FindingDetail,
    FindingRead,
    FindingStatusUpdate,
    HelpRequest,
    NoisyRule,
)
from app.schemas.finding_event import FindingEventRead
from app.services.code_links import build_code_url, guess_repo_type
from app.services.decisions import DecisionError, create_request
from app.services.entity_paths import subtree_ids
from app.services.entity_settings import effective_settings
from app.services.entity_tree import entities_with_tag
from app.services.events import record_event
from app.services.finding_state import set_status
from app.services.noisy_rules import noisy_rules
from app.services.ownership import build_resolver

router = APIRouter(prefix="/api/v1", tags=["findings"])


async def entity_filter(
    db: AsyncSession, principal: Principal, entity_id: uuid.UUID, include_descendants: bool
):
    """Условие на Finding.entity_id: сам проект или всё его поддерево.

    Узел должен быть виден хотя бы заглушкой (иначе 404); доступная часть
    поддерева отсекается отдельным фильтром по праву.
    """
    entity = await db.get(Entity, entity_id)
    if entity is None or not principal.access.can_see(entity):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден")
    if not include_descendants:
        return Finding.entity_id == entity_id
    return Finding.entity_id.in_(subtree_ids(entity))


def readable(principal: Principal):
    """Условие на Finding: проекты, где у вызывающего есть finding:read."""
    return principal.access.entity_scope("finding:read", Finding.entity_id)


async def finding_checked(
    db: AsyncSession, principal: Principal, finding_id: uuid.UUID, perm: str
) -> Finding:
    """Загрузить находку и проверить право на её проект (404 — не читается, 403 — нет права)."""
    finding = await db.get(Finding, finding_id)
    if finding is None:
        raise not_found("Уязвимость")
    entity = await db.get(Entity, finding.entity_id)
    ensure(principal, perm, entity, what="Уязвимость")
    return finding


async def finding_path(db: AsyncSession, finding: Finding) -> str:
    return await db.scalar(select(Entity.path_cache).where(Entity.id == finding.entity_id))


async def load_finding(db: AsyncSession, finding_id: uuid.UUID) -> Finding:
    """Перечитать находку вместе с командой/исполнителем (selectin) — для ответа после изменений."""
    return await db.scalar(
        select(Finding).where(Finding.id == finding_id).execution_options(populate_existing=True)
    )


async def to_detail(db: AsyncSession, finding: Finding) -> FindingDetail:
    entity = await db.get(Entity, finding.entity_id)
    settings = await effective_settings(db, entity)
    imp = await db.get(Import, finding.import_id) if finding.import_id else None
    project_repo_url = settings["repo_url"]["value"]
    if project_repo_url:
        # Проект сам знает свой репозиторий — SARIF repositoryUri сканера не учитываем.
        repo_url = project_repo_url
        repo_type = RepoType(settings["repo_type"]["value"]) if settings["repo_type"]["value"] else None
    else:
        # У проекта репозиторий не настроен — берём то, что сканер сообщил в отчёте.
        repo_url = imp.repo_url if imp else None
        repo_type = guess_repo_type(repo_url) if repo_url else None
    common = dict(
        repo_url=repo_url,
        repo_type=repo_type,
        path=finding.file_path,
        line=finding.line_start,
        path_prefix=settings["repo_path_prefix"]["value"],
    )
    return FindingDetail.model_validate(finding).model_copy(update={
        "entity_name": entity.name,
        "entity_path": entity.path_cache,
        "code_url": build_code_url(ref=finding.commit_sha, ref_is_commit=True, **common),
        "code_url_head": build_code_url(
            ref=settings["default_branch"]["value"], ref_is_commit=False, **common
        ),
    })


@router.get("/findings", response_model=list[FindingRead])
async def list_findings(
    entity_id: uuid.UUID | None = None,
    include_descendants: bool = False,
    severity: Severity | None = None,
    finding_status: list[FindingStatus] | None = Query(None, alias="status"),
    scanner: str | None = None,
    assignee_group_id: uuid.UUID | None = None,
    unassigned: bool = False,
    mine: bool = False,
    help_requested: bool = False,
    pending_decision: bool = False,
    overdue: bool = False,
    tag: str | None = Query(None, max_length=64),
    order: Literal["last_seen", "severity", "number", "due_at"] = "last_seen",
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[Finding]:
    q = select(Finding).where(readable(principal))
    if entity_id:
        q = q.where(await entity_filter(db, principal, entity_id, include_descendants))
    if severity:
        q = q.where(Finding.severity == severity)
    if finding_status:
        q = q.where(Finding.status.in_(finding_status))
    if scanner:
        q = q.where(Finding.scanner == scanner)
    if assignee_group_id:
        q = q.where(Finding.assignee_group_id == assignee_group_id)
    if unassigned:
        q = q.where(Finding.assignee_group_id.is_(None))
    if help_requested:
        q = q.where(Finding.help_requested_at.is_not(None))
    if overdue:
        q = q.where(Finding.status.in_(OPEN_STATUSES), Finding.due_at < func.now())
    if tag:
        q = q.where(Finding.entity_id.in_(entities_with_tag(tag.strip().lower())))
    if pending_decision:
        q = q.where(
            select(DecisionRequest.id)
            .where(
                DecisionRequest.finding_id == Finding.id,
                DecisionRequest.status == DecisionStatus.pending,
            )
            .exists()
        )
    if mine:
        my_groups = select(user_group_members.c.group_id).where(
            user_group_members.c.user_id == principal.user.id
        )
        q = q.where(or_(
            Finding.assignee_user_id == principal.user.id,
            Finding.assignee_group_id.in_(my_groups),
        ))
    if order == "severity":
        q = q.order_by(Finding.severity, Finding.first_seen)
    elif order == "number":
        q = q.order_by(Finding.number.desc())
    elif order == "due_at":
        q = q.order_by(Finding.due_at.asc().nulls_last(), Finding.number)
    else:
        q = q.order_by(Finding.last_seen.desc())
    result = await db.scalars(q.offset(offset).limit(limit))
    return list(result)


@router.get("/findings/stats")
async def findings_stats(
    entity_id: uuid.UUID | None = None,
    include_descendants: bool = False,
    principal: Principal = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    scope = readable(principal)
    if entity_id:
        scope = and_(scope, await entity_filter(db, principal, entity_id, include_descendants))
    q = select(Finding.severity, func.count()).where(scope).group_by(Finding.severity)
    q2 = select(Finding.status, func.count()).where(scope).group_by(Finding.status)
    by_severity = {sev.value: cnt for sev, cnt in (await db.execute(q)).all()}
    by_status = {st.value: cnt for st, cnt in (await db.execute(q2)).all()}
    total = sum(by_severity.values())
    return {"total": total, "by_severity": by_severity, "by_status": by_status}


@router.get("/findings/noisy-rules", response_model=list[NoisyRule])
async def list_noisy_rules(
    min_decided: int = Query(10, ge=1, le=100000),
    min_fp_ratio: float = Query(0.7, ge=0, le=1),
    principal: Principal = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Правила, по которым большинство решённых находок — ложные (кандидаты на отключение)."""
    return await noisy_rules(
        db, min_decided=min_decided, min_fp_ratio=min_fp_ratio, scope=readable(principal)
    )


@router.get("/findings/by-number/{number}", response_model=FindingDetail)
async def get_finding_by_number(
    number: int,
    principal: Principal = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> FindingDetail:
    finding_id = await db.scalar(select(Finding.id).where(Finding.number == number))
    if finding_id is None:
        raise not_found("Уязвимость")
    return await to_detail(db, await finding_checked(db, principal, finding_id, "finding:read"))


@router.get("/findings/{finding_id}", response_model=FindingDetail)
async def get_finding(
    finding_id: uuid.UUID,
    principal: Principal = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> FindingDetail:
    return await to_detail(db, await finding_checked(db, principal, finding_id, "finding:read"))


@router.get("/findings/{finding_id}/events", response_model=list[FindingEventRead])
async def list_finding_events(
    finding_id: uuid.UUID,
    principal: Principal = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[FindingEventRead]:
    await finding_checked(db, principal, finding_id, "finding:read")
    rows = await db.execute(
        select(FindingEvent, User.full_name, User.email)
        .outerjoin(User, User.id == FindingEvent.actor_id)
        .where(FindingEvent.finding_id == finding_id)
        .order_by(FindingEvent.created_at, FindingEvent.id)
    )
    return [
        FindingEventRead.model_validate(event).model_copy(update={"actor_name": full_name or email})
        for event, full_name, email in rows
    ]


# Ставятся вручную. Ложное/риск — через запросы (decisions), «Исправлена» — только повторным сканом.
MANUAL_STATUSES = {
    FindingStatus.new,
    FindingStatus.triaged,
    FindingStatus.confirmed,
    FindingStatus.in_progress,
}
DECISION_STATUSES = {FindingStatus.false_positive, FindingStatus.risk_accepted}


@router.patch("/findings/{finding_id}", response_model=FindingRead)
async def update_finding_status(
    finding_id: uuid.UUID,
    data: FindingStatusUpdate,
    principal: Principal = Depends(require_permission("finding", "triage")),
    db: AsyncSession = Depends(get_db),
) -> Finding:
    finding = await finding_checked(db, principal, finding_id, "finding:triage")

    if data.status in DECISION_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "«Ложное срабатывание» и «Риск принят» оформляются запросом: "
            f"POST /api/v1/findings/{finding_id}/decisions",
        )
    if data.status not in MANUAL_STATUSES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "«Исправлена» ставится автоматически, когда повторный скан не находит уязвимость",
        )
    if finding.status in DECISION_STATUSES and not principal.access.allows(
        "finding:approve", await finding_path(db, finding)
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Снять решение может только AppSec (право finding:approve)"
        )

    if finding.status != data.status:
        previous = await set_status(db, finding, data.status)
        record_event(
            db, finding.id, FindingEventType.status_changed,
            actor_type=ActorType.user, actor_id=principal.user.id,
            from_status=previous, to_status=data.status,
            reason=(data.reason or "").strip() or None,
        )
        await db.commit()
    return await load_finding(db, finding.id)


@router.post("/findings/{finding_id}/assign", response_model=FindingRead)
async def assign_finding(
    finding_id: uuid.UUID,
    data: FindingAssign,
    principal: Principal = Depends(require_permission("finding", "triage")),
    db: AsyncSession = Depends(get_db),
) -> Finding:
    finding = await finding_checked(db, principal, finding_id, "finding:triage")

    if data.by_rules:
        new_group = (await build_resolver(db, finding.entity_id)).resolve(finding.file_path)
        finding.assigned_manually = False
        finding.assignee_user_id = None
    else:
        if data.group_id is not None and await db.get(UserGroup, data.group_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Команда не найдена")
        if data.user_id is not None and await db.get(User, data.user_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Пользователь не найден")
        new_group = data.group_id
        finding.assigned_manually = True
        finding.assignee_user_id = data.user_id

    record_event(
        db, finding.id, FindingEventType.assigned,
        actor_type=ActorType.user, actor_id=principal.user.id,
        payload={
            "from_group_id": str(finding.assignee_group_id) if finding.assignee_group_id else None,
            "to_group_id": str(new_group) if new_group else None,
            "user_id": str(data.user_id) if data.user_id and not data.by_rules else None,
            "by_rules": data.by_rules,
        },
    )
    finding.assignee_group_id = new_group
    await db.commit()
    return await load_finding(db, finding.id)


CLOSED_FOR_HELP = {FindingStatus.fixed, *DECISION_STATUSES}


@router.post(
    "/findings/{finding_id}/comments",
    response_model=FindingEventRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_comment(
    finding_id: uuid.UUID,
    data: CommentCreate,
    principal: Principal = Depends(require_permission("finding", "triage")),
    db: AsyncSession = Depends(get_db),
) -> FindingEventRead:
    finding = await finding_checked(db, principal, finding_id, "finding:triage")
    text = data.text.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Комментарий пустой")
    if data.resolve_help and not principal.access.allows(
        "finding:approve", await finding_path(db, finding)
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Закрыть вопрос может только AppSec (право finding:approve)"
        )
    event = record_event(
        db, finding.id, FindingEventType.comment,
        actor_type=ActorType.user, actor_id=principal.user.id, reason=text,
    )
    if data.resolve_help and finding.help_requested_at is not None:
        finding.help_requested_at = None
        record_event(
            db, finding.id, FindingEventType.help_resolved,
            actor_type=ActorType.user, actor_id=principal.user.id,
        )
    await db.commit()
    await db.refresh(event)
    return FindingEventRead.model_validate(event).model_copy(update={
        "actor_name": principal.user.full_name or principal.user.email,
    })


@router.post("/findings/{finding_id}/help", response_model=FindingDetail)
async def request_help(
    finding_id: uuid.UUID,
    data: HelpRequest,
    principal: Principal = Depends(require_permission("finding", "triage")),
    db: AsyncSession = Depends(get_db),
) -> FindingDetail:
    finding = await finding_checked(db, principal, finding_id, "finding:triage")
    if finding.status in CLOSED_FOR_HELP:
        raise HTTPException(status.HTTP_409_CONFLICT, "Уязвимость уже закрыта")
    if finding.help_requested_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Вопрос AppSec уже задан — дождитесь ответа")
    finding.help_requested_at = datetime.now(timezone.utc)
    record_event(
        db, finding.id, FindingEventType.help_requested,
        actor_type=ActorType.user, actor_id=principal.user.id, reason=data.text.strip(),
    )
    await db.commit()
    return await to_detail(db, await load_finding(db, finding.id))


def _first_error(exc: ValidationError) -> str:
    return str(exc.errors()[0]["msg"]).removeprefix("Value error, ")


@router.post("/findings/bulk", response_model=BulkResult)
async def bulk_action(
    data: BulkAction,
    principal: Principal = Depends(require_permission("finding", "triage")),
    db: AsyncSession = Depends(get_db),
) -> BulkResult:
    decision: DecisionCreate | None = None
    if data.action == "false_positive":
        try:
            decision = DecisionCreate(
                decision_type=DecisionType.false_positive,
                reason_tag=data.reason_tag,
                reason=data.reason,
            )
        except ValidationError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, _first_error(exc))
    if data.action == "assign" and await db.get(UserGroup, data.group_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Команда не найдена")

    ids = list(dict.fromkeys(data.ids))
    rows = await db.execute(
        select(Finding, Entity.path_cache)
        .join(Entity, Entity.id == Finding.entity_id)
        .where(Finding.id.in_(ids))
    )
    found = {f.id: (f, path) for f, path in rows}
    # Всё или ничего: хоть одна не читается — 404, хоть на одну нет права — 403
    access = principal.access
    if any(i not in found or not access.allows("finding:read", found[i][1]) for i in ids):
        raise not_found("Уязвимость")
    if not all(access.allows("finding:triage", path) for _, path in found.values()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав: finding:triage")
    if data.action == "false_positive" and not all(
        access.allows("finding:approve", path) for _, path in found.values()
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Отметить ложным сразу может только AppSec (право finding:approve)",
        )
    applied = 0
    skipped: list[BulkSkipped] = []
    for finding_id in ids:
        finding = found[finding_id][0]
        if data.action == "confirm":
            if finding.status not in MANUAL_STATUSES:
                skipped.append(BulkSkipped(id=finding_id, reason="Уже закрыта или решена"))
                continue
            if finding.status == FindingStatus.confirmed:
                skipped.append(BulkSkipped(id=finding_id, reason="Уже подтверждена"))
                continue
            previous = await set_status(db, finding, FindingStatus.confirmed)
            record_event(
                db, finding.id, FindingEventType.status_changed,
                actor_type=ActorType.user, actor_id=principal.user.id,
                from_status=previous, to_status=FindingStatus.confirmed,
            )
        elif data.action == "false_positive":
            try:
                await create_request(
                    db, finding, decision, user_id=principal.user.id, can_approve=True
                )
            except DecisionError as exc:
                skipped.append(BulkSkipped(id=finding_id, reason=exc.message))
                continue
        else:
            record_event(
                db, finding.id, FindingEventType.assigned,
                actor_type=ActorType.user, actor_id=principal.user.id,
                payload={
                    "from_group_id": str(finding.assignee_group_id) if finding.assignee_group_id else None,
                    "to_group_id": str(data.group_id),
                    "by_rules": False,
                },
            )
            finding.assignee_group_id = data.group_id
            finding.assignee_user_id = None
            finding.assigned_manually = True
        applied += 1
    await db.commit()
    return BulkResult(applied=applied, skipped=skipped)
