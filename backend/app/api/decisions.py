import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, has_permission, require_permission
from app.db.session import get_db
from app.models import DecisionRequest, Finding
from app.models.decision_request import DecisionStatus
from app.schemas.decision import DecisionApprove, DecisionCreate, DecisionRead, DecisionReject
from app.services.decisions import DecisionError, approve_request, create_request, reject_request

router = APIRouter(prefix="/api/v1", tags=["decisions"])


async def _finding_or_404(db: AsyncSession, finding_id: uuid.UUID) -> Finding:
    finding = await db.get(Finding, finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    return finding


async def _request_or_404(db: AsyncSession, decision_id: uuid.UUID) -> DecisionRequest:
    req = await db.get(DecisionRequest, decision_id)
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Decision request not found")
    return req


@router.post(
    "/findings/{finding_id}/decisions",
    response_model=DecisionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_decision(
    finding_id: uuid.UUID,
    data: DecisionCreate,
    principal: Principal = Depends(require_permission("finding", "triage")),
    db: AsyncSession = Depends(get_db),
) -> DecisionRequest:
    finding = await _finding_or_404(db, finding_id)
    try:
        req = await create_request(
            db, finding, data,
            user_id=principal.user.id,
            can_approve=has_permission(principal, "finding", "approve"),
        )
    except DecisionError as exc:
        raise HTTPException(exc.status_code, exc.message)
    await db.commit()
    await db.refresh(req)
    return req


@router.get("/findings/{finding_id}/decisions", response_model=list[DecisionRead])
async def list_finding_decisions(
    finding_id: uuid.UUID,
    _: object = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[DecisionRequest]:
    await _finding_or_404(db, finding_id)
    result = await db.scalars(
        select(DecisionRequest)
        .where(DecisionRequest.finding_id == finding_id)
        .order_by(DecisionRequest.created_at.desc())
    )
    return list(result)


@router.get("/decisions", response_model=list[DecisionRead])
async def list_decisions(
    decision_status: DecisionStatus | None = Query(None, alias="status"),
    mine: bool = False,
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_permission("finding", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[DecisionRead]:
    q = select(DecisionRequest, Finding.number, Finding.title).join(
        Finding, Finding.id == DecisionRequest.finding_id
    )
    if decision_status:
        q = q.where(DecisionRequest.status == decision_status)
    if mine:
        q = q.where(DecisionRequest.requested_by_id == principal.user.id)
    q = q.order_by(DecisionRequest.created_at.desc()).offset(offset).limit(limit)
    rows = await db.execute(q)
    return [
        DecisionRead.model_validate(req).model_copy(
            update={"finding_number": number, "finding_title": title}
        )
        for req, number, title in rows
    ]


@router.post("/decisions/{decision_id}/approve", response_model=DecisionRead)
async def approve_decision(
    decision_id: uuid.UUID,
    data: DecisionApprove,
    principal: Principal = Depends(require_permission("finding", "approve")),
    db: AsyncSession = Depends(get_db),
) -> DecisionRequest:
    req = await _request_or_404(db, decision_id)
    finding = await _finding_or_404(db, req.finding_id)
    try:
        await approve_request(db, req, finding, user_id=principal.user.id, comment=data.comment)
    except DecisionError as exc:
        raise HTTPException(exc.status_code, exc.message)
    await db.commit()
    await db.refresh(req)
    return req


@router.post("/decisions/{decision_id}/reject", response_model=DecisionRead)
async def reject_decision(
    decision_id: uuid.UUID,
    data: DecisionReject,
    principal: Principal = Depends(require_permission("finding", "approve")),
    db: AsyncSession = Depends(get_db),
) -> DecisionRequest:
    req = await _request_or_404(db, decision_id)
    finding = await _finding_or_404(db, req.finding_id)
    try:
        await reject_request(db, req, finding, user_id=principal.user.id, comment=data.comment)
    except DecisionError as exc:
        raise HTTPException(exc.status_code, exc.message)
    await db.commit()
    await db.refresh(req)
    return req
