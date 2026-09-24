import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, require_permission
from app.db.session import get_db
from app.models import Entity, Import
from app.models.import_ import ImportStatus
from app.schemas.import_ import ImportRead
from app.services.entity_tree import branch_allowed, branch_rejection_message, resolve_default_branch
from app.services.storage import save_sarif

router = APIRouter(prefix="/api/v1", tags=["imports"])

MAX_SARIF_SIZE = 50 * 1024 * 1024  # 50 MB


@router.post(
    "/entities/{entity_id}/imports",
    response_model=ImportRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_import(
    entity_id: uuid.UUID,
    file: UploadFile,
    branch: str | None = Form(None),
    commit_sha: str | None = Form(None),
    pipeline_url: str | None = Form(None),
    scan_scope: str | None = Form(None),
    close_missing: bool = Form(True),
    confirm_empty: bool = Form(False),
    principal: Principal = Depends(require_permission("import", "import")),
    db: AsyncSession = Depends(get_db),
) -> Import:
    entity = await db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entity not found")

    branch = branch or None
    default_branch = await resolve_default_branch(db, entity_id)
    if not branch_allowed(branch, default_branch):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            branch_rejection_message(branch, default_branch),
        )

    content = await file.read()
    if len(content) > MAX_SARIF_SIZE:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large (max 50 MB)")

    filename = file.filename or "upload.sarif"
    storage_key = save_sarif(content, filename)

    import_record = Import(
        entity_id=entity_id,
        uploaded_by_id=principal.user.id,
        filename=filename,
        storage_key=storage_key,
        status=ImportStatus.pending,
        branch=branch,
        commit_sha=commit_sha or None,
        pipeline_url=pipeline_url or None,
        scan_scope=scan_scope or None,
        close_missing=close_missing,
        confirm_empty=confirm_empty,
    )
    db.add(import_record)
    await db.commit()
    await db.refresh(import_record)

    from app.worker import enqueue_import
    await enqueue_import(str(import_record.id))

    return import_record


@router.get("/entities/{entity_id}/imports", response_model=list[ImportRead])
async def list_entity_imports(
    entity_id: uuid.UUID,
    _: object = Depends(require_permission("import", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[Import]:
    entity = await db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entity not found")
    result = await db.scalars(
        select(Import)
        .where(Import.entity_id == entity_id)
        .order_by(Import.created_at.desc())
    )
    return list(result)


@router.get("/imports", response_model=list[ImportRead])
async def list_all_imports(
    _: object = Depends(require_permission("import", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[Import]:
    result = await db.scalars(select(Import).order_by(Import.created_at.desc()).limit(100))
    return list(result)


@router.get("/imports/{import_id}", response_model=ImportRead)
async def get_import(
    import_id: uuid.UUID,
    _: object = Depends(require_permission("import", "read")),
    db: AsyncSession = Depends(get_db),
) -> Import:
    imp = await db.get(Import, import_id)
    if imp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Import not found")
    return imp
