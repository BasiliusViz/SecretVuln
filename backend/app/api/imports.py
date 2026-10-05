import json
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, ensure, not_found, require_permission
from app.api.entities import ensure_path_write, get_entity_checked
from app.db.session import get_db
from app.models import Entity, Import
from app.models.import_ import ImportStatus
from app.schemas.import_ import CreatedEntity, ImportCreated, ImportRead
from app.services.config_file import MAX_CONFIG_SIZE, ConfigError, ProjectConfig, apply_config, parse_config
from app.services.entity_paths import ensure_path
from app.services.entity_tree import branch_allowed, branch_rejection_message, resolve_default_branch
from app.services.storage import save_sarif

router = APIRouter(prefix="/api/v1", tags=["imports"])

MAX_SARIF_SIZE = 50 * 1024 * 1024  # 50 MB


def _derive_branch(content: bytes) -> str | None:
    """Лёгкий разбор SARIF ради versionControlProvenance[0].branch. Невалидный JSON —
    просто пропускаем (полный разбор и отчёт об ошибке — задача воркера)."""
    try:
        data = json.loads(content)
        runs = data.get("runs") or []
        if not runs:
            return None
        vcp = (runs[0].get("versionControlProvenance") or [{}])[0]
        branch = vcp.get("branch")
        return branch or None
    except (ValueError, AttributeError, TypeError, IndexError):
        return None


async def _read_config(config: UploadFile | None) -> ProjectConfig | None:
    if config is None:
        return None
    try:
        # На один байт больше лимита достаточно, чтобы parse_config признал файл слишком
        # большим — не читаем произвольно огромную загрузку целиком ради этой проверки.
        return parse_config(await config.read(MAX_CONFIG_SIZE + 1))
    except ConfigError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


async def _create_import(
    db: AsyncSession,
    principal: Principal,
    entity: Entity,
    file: UploadFile,
    *,
    config: ProjectConfig | None,
    created: list[Entity],
    branch: str | None,
    commit_sha: str | None,
    pipeline_url: str | None,
    scan_scope: str | None,
    close_missing: bool,
    confirm_empty: bool,
) -> ImportCreated:
    content = await file.read()
    if len(content) > MAX_SARIF_SIZE:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large (max 50 MB)")

    warnings: list[str] = []
    if config is not None:
        if not principal.access.allows("entity:write", entity):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Файл настроек проекта применяется только с правом entity:write на проект",
            )
        warnings = await apply_config(
            db, entity, config, commit_sha=commit_sha or None, access=principal.access
        )

    branch = branch or None
    # Ветка формы не задана — проверяем по ветке из SARIF-provenance, чтобы не закоммитить
    # конфиг, который повторный скан воркера всё равно отклонит.
    branch_for_check = branch or _derive_branch(content)
    default_branch = await resolve_default_branch(db, entity.id)
    if not branch_allowed(branch_for_check, default_branch):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            branch_rejection_message(branch_for_check, default_branch),
        )

    filename = file.filename or "upload.sarif"
    storage_key = save_sarif(content, filename)

    import_record = Import(
        entity_id=entity.id,
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
        config_warnings=warnings,
    )
    db.add(import_record)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Конфликт при создании импорта, повторите попытку")
    await db.refresh(import_record)

    from app.worker import enqueue_import
    await enqueue_import(str(import_record.id))

    return ImportCreated.model_validate(import_record).model_copy(update={
        "entity_path": entity.path_cache,
        "created_entities": [CreatedEntity(id=e.id, path=e.path_cache) for e in created],
    })


@router.post(
    "/entities/{entity_id}/imports",
    response_model=ImportCreated,
    status_code=status.HTTP_201_CREATED,
)
async def create_import(
    entity_id: uuid.UUID,
    file: UploadFile,
    config: UploadFile | None = File(None),
    branch: str | None = Form(None),
    commit_sha: str | None = Form(None),
    pipeline_url: str | None = Form(None),
    scan_scope: str | None = Form(None),
    close_missing: bool = Form(True),
    confirm_empty: bool = Form(False),
    principal: Principal = Depends(require_permission("import", "import")),
    db: AsyncSession = Depends(get_db),
) -> ImportCreated:
    parsed = await _read_config(config)
    entity = await get_entity_checked(db, principal, entity_id, "import:import")
    return await _create_import(
        db, principal, entity, file, config=parsed, created=[],
        branch=branch, commit_sha=commit_sha, pipeline_url=pipeline_url,
        scan_scope=scan_scope, close_missing=close_missing, confirm_empty=confirm_empty,
    )


@router.post("/imports", response_model=ImportCreated, status_code=status.HTTP_201_CREATED)
async def create_import_by_path(
    file: UploadFile,
    entity_id: uuid.UUID | None = Form(None),
    project_path: str | None = Form(None),
    auto_create: bool = Form(False),
    config: UploadFile | None = File(None),
    branch: str | None = Form(None),
    commit_sha: str | None = Form(None),
    pipeline_url: str | None = Form(None),
    scan_scope: str | None = Form(None),
    close_missing: bool = Form(True),
    confirm_empty: bool = Form(False),
    principal: Principal = Depends(require_permission("import", "import")),
    db: AsyncSession = Depends(get_db),
) -> ImportCreated:
    """Единая точка загрузки для CI: проект по entity_id или по пути (с автосозданием)."""
    project_path = (project_path or "").strip() or None
    if (entity_id is None) == (project_path is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Укажите entity_id или project_path (одно из двух)"
        )
    parsed = await _read_config(config)

    created: list[Entity] = []
    if entity_id is not None:
        entity = await get_entity_checked(db, principal, entity_id, "import:import")
    else:
        try:
            entity, _ = await ensure_path(db, project_path, create=False)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
        # Невидимый проект неотличим от отсутствующего: тот же ответ
        if entity is not None and not principal.access.can_see(entity):
            if auto_create:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав: entity:write")
            entity = None
        if entity is None:
            if not auto_create:
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND,
                    f"Проект «{project_path}» не найден. Передайте auto_create=true, чтобы создать его",
                )
            # entity:write на ближайшем существующем предке (новый корень — глобально)
            # и право загрузки на путь будущего узла
            await ensure_path_write(db, principal, project_path)
            if not principal.access.allows("import:import", project_path):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав: import:import")
            try:
                entity, created = await ensure_path(db, project_path, create=True)
            except IntegrityError:
                await db.rollback()
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"Конфликт при создании проекта «{project_path}», повторите попытку",
                )
        else:
            ensure(principal, "import:import", entity, what="Проект")

    return await _create_import(
        db, principal, entity, file, config=parsed, created=created,
        branch=branch, commit_sha=commit_sha, pipeline_url=pipeline_url,
        scan_scope=scan_scope, close_missing=close_missing, confirm_empty=confirm_empty,
    )


@router.get("/entities/{entity_id}/imports", response_model=list[ImportRead])
async def list_entity_imports(
    entity_id: uuid.UUID,
    principal: Principal = Depends(require_permission("import", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[Import]:
    await get_entity_checked(db, principal, entity_id, "import:read")
    result = await db.scalars(
        select(Import)
        .where(Import.entity_id == entity_id)
        .order_by(Import.created_at.desc())
    )
    return list(result)


@router.get("/imports", response_model=list[ImportRead])
async def list_all_imports(
    principal: Principal = Depends(require_permission("import", "read")),
    db: AsyncSession = Depends(get_db),
) -> list[Import]:
    result = await db.scalars(
        select(Import)
        .where(principal.access.entity_scope("import:read", Import.entity_id))
        .order_by(Import.created_at.desc())
        .limit(100)
    )
    return list(result)


@router.get("/imports/{import_id}", response_model=ImportRead)
async def get_import(
    import_id: uuid.UUID,
    principal: Principal = Depends(require_permission("import", "read")),
    db: AsyncSession = Depends(get_db),
) -> Import:
    imp = await db.get(Import, import_id)
    if imp is None:
        raise not_found("Импорт")
    ensure(principal, "import:read", await db.get(Entity, imp.entity_id), what="Импорт")
    return imp
