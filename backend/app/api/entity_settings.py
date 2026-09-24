"""Настройки проекта: чтение с источниками, правка (закрепляет поле), правила владения."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_permission
from app.db.session import get_db
from app.models import Entity, OwnershipRule, RuleSource, UserGroup
from app.schemas.entity_settings import (
    EntitySettingsRead,
    EntitySettingsUpdate,
    InheritedRule,
    RuleIn,
    RuleRead,
)
from app.services.entity_settings import (
    FIELD_PIN,
    effective_settings,
    find_repo_owner,
    lineage,
    normalize_repo_url,
    own_source,
)

router = APIRouter(prefix="/api/v1/entities", tags=["entity-settings"])


async def _entity_or_404(db: AsyncSession, entity_id: uuid.UUID) -> Entity:
    entity = await db.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Проект не найден")
    return entity


async def _rules(db: AsyncSession, entity_id: uuid.UUID) -> list[OwnershipRule]:
    result = await db.scalars(
        select(OwnershipRule)
        .where(OwnershipRule.entity_id == entity_id)
        .order_by(OwnershipRule.position)
    )
    return list(result)


async def settings_read(
    db: AsyncSession, entity: Entity, warnings: Sequence[str] = ()
) -> EntitySettingsRead:
    own = await _rules(db, entity.id)
    inherited: list[InheritedRule] = []
    for node in (await lineage(db, entity))[1:]:
        for rule in await _rules(db, node.id):
            inherited.append(InheritedRule(
                entity_path=node.path_cache, pattern=rule.pattern,
                group_id=rule.group_id, group_name=rule.group.name,
            ))
    return EntitySettingsRead(
        entity_id=entity.id,
        path=entity.path_cache,
        fields=await effective_settings(db, entity),
        ownership_rules=[
            RuleRead(
                id=r.id, pattern=r.pattern, group_id=r.group_id, group_name=r.group.name,
                position=r.position, source=r.source.value,
            )
            for r in own
        ],
        rules_source=own_source(entity, "ownership_rules"),
        inherited_rules=inherited,
        pinned_fields=list(entity.pinned_fields),
        has_config_file=entity.config_file is not None,
        config_commit_sha=entity.config_commit_sha,
        config_applied_at=entity.config_applied_at,
        warnings=list(warnings),
    )


def _pin(entity: Entity, *keys: str) -> None:
    entity.pinned_fields = sorted(set(entity.pinned_fields) | set(keys))


@router.get("/{entity_id}/settings", response_model=EntitySettingsRead)
async def get_settings_(
    entity_id: uuid.UUID,
    _: object = Depends(require_permission("entity", "read")),
    db: AsyncSession = Depends(get_db),
) -> EntitySettingsRead:
    return await settings_read(db, await _entity_or_404(db, entity_id))


@router.patch("/{entity_id}/settings", response_model=EntitySettingsRead)
async def update_settings(
    entity_id: uuid.UUID,
    data: EntitySettingsUpdate,
    _: object = Depends(require_permission("entity", "write")),
    db: AsyncSession = Depends(get_db),
) -> EntitySettingsRead:
    entity = await _entity_or_404(db, entity_id)
    fields = data.model_dump(exclude_unset=True)

    group_id = fields.get("owner_group_id")
    if group_id is not None and await db.get(UserGroup, group_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Команда не найдена")
    for key in ("default_branch", "repo_url", "repo_path_prefix"):
        if key in fields and isinstance(fields[key], str):
            fields[key] = fields[key].strip() or None
    if fields.get("repo_url"):
        fields["repo_url"] = normalize_repo_url(fields["repo_url"])
        other = await find_repo_owner(db, fields["repo_url"], exclude_id=entity.id)
        if other is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Репозиторий уже привязан к проекту {other.path_cache}",
            )

    for key, value in fields.items():
        setattr(entity, key, value)
    _pin(entity, *(FIELD_PIN[key] for key in fields))
    await db.commit()
    return await settings_read(db, entity)


@router.put("/{entity_id}/ownership-rules", response_model=EntitySettingsRead)
async def replace_rules(
    entity_id: uuid.UUID,
    rules: list[RuleIn] = Body(..., max_length=200),
    _: object = Depends(require_permission("entity", "write")),
    db: AsyncSession = Depends(get_db),
) -> EntitySettingsRead:
    entity = await _entity_or_404(db, entity_id)
    for rule in rules:
        if await db.get(UserGroup, rule.group_id) is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"Команда для правила «{rule.pattern}» не найдена"
            )
    await db.execute(delete(OwnershipRule).where(OwnershipRule.entity_id == entity.id))
    for position, rule in enumerate(rules):
        db.add(OwnershipRule(
            entity_id=entity.id, pattern=rule.pattern.strip(), group_id=rule.group_id,
            position=position, source=RuleSource.manual,
        ))
    _pin(entity, "ownership_rules")
    await db.commit()
    return await settings_read(db, entity)
