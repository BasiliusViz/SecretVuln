"""Файл настроек проекта .secretvuln.yml: разбор, применение с учётом закреплённых полей, выгрузка."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entity, OwnershipRule, RuleSource, UserGroup
from app.models.entity import RepoType
from app.services.entity_settings import find_repo_owner, is_http_url, normalize_repo_url

MAX_CONFIG_SIZE = 64 * 1024


class RepoSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str | None = Field(default=None, max_length=1024)
    type: RepoType | None = None
    path_prefix: str | None = Field(default=None, max_length=512)

    @field_validator("url")
    @classmethod
    def _url_is_http(cls, value: str | None) -> str | None:
        if value is not None and not is_http_url(value):
            raise ValueError("допускаются только ссылки http:// или https://")
        return value


class OwnershipEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=512)
    owner: str = Field(min_length=1, max_length=150)


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1]
    default_branch: str | None = Field(default=None, max_length=255)
    owner: str | None = Field(default=None, max_length=150)
    repo: RepoSection | None = None
    ownership: list[OwnershipEntry] | None = Field(default=None, max_length=200)


class ConfigError(Exception):
    """Файл настроек не разобран — импорт отклоняется (422)."""


def parse_config(content: bytes) -> ProjectConfig:
    if len(content) > MAX_CONFIG_SIZE:
        raise ConfigError(".secretvuln.yml: файл больше 64 КБ")
    try:
        data = yaml.safe_load(content.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ConfigError(f".secretvuln.yml: не удалось разобрать YAML — {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(".secretvuln.yml: ожидается словарь, первая строка — version: 1")
    try:
        return ProjectConfig.model_validate(data)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigError(f".secretvuln.yml: {details}") from exc


async def _group_by_name(db: AsyncSession, name: str) -> UserGroup | None:
    return await db.scalar(select(UserGroup).where(UserGroup.name == name))


async def apply_config(
    db: AsyncSession, entity: Entity, config: ProjectConfig, *, commit_sha: str | None = None
) -> list[str]:
    """Сохраняет файл в узле и переносит значения в незакреплённые поля. Не коммитит."""
    entity.config_file = config.model_dump(mode="json", exclude_none=True)
    entity.config_commit_sha = commit_sha
    entity.config_applied_at = datetime.now(timezone.utc)
    return await apply_stored_config(db, entity)


async def apply_stored_config(
    db: AsyncSession, entity: Entity, *, only: set[str] | None = None
) -> list[str]:
    """Переносит сохранённый config_file в поля узла, пропуская закреплённые. Не коммитит."""
    if entity.config_file is None:
        return []
    cfg = ProjectConfig.model_validate(entity.config_file)
    pinned = set(entity.pinned_fields)
    warnings: list[str] = []

    def wanted(key: str) -> bool:
        return key not in pinned and (only is None or key in only)

    if wanted("default_branch"):
        entity.default_branch = cfg.default_branch

    if wanted("owner_group_id"):
        if cfg.owner is None:
            entity.owner_group_id = None
        else:
            group = await _group_by_name(db, cfg.owner)
            if group is None:
                warnings.append(f"owner: группа «{cfg.owner}» не найдена — владелец не изменён")
            else:
                entity.owner_group_id = group.id

    if wanted("repo"):
        repo = cfg.repo or RepoSection()
        url = normalize_repo_url(repo.url) if repo.url else None
        other = await find_repo_owner(db, url, exclude_id=entity.id) if url else None
        if other is not None:
            warnings.append(
                f"repo.url: репозиторий уже привязан к проекту {other.path_cache} — не изменён"
            )
        else:
            entity.repo_url = url
            entity.repo_type = repo.type
            entity.repo_path_prefix = repo.path_prefix

    if wanted("ownership_rules"):
        await db.execute(delete(OwnershipRule).where(OwnershipRule.entity_id == entity.id))
        position = 0
        for entry in cfg.ownership or []:
            group = await _group_by_name(db, entry.owner)
            if group is None:
                warnings.append(
                    f"ownership: группа «{entry.owner}» не найдена — правило «{entry.path}» пропущено"
                )
                continue
            db.add(OwnershipRule(
                entity_id=entity.id, pattern=entry.path, group_id=group.id,
                position=position, source=RuleSource.file,
            ))
            position += 1

    await db.flush()
    return warnings


async def export_config(db: AsyncSession, entity: Entity) -> str:
    """Собственные настройки узла в формате .secretvuln.yml (без унаследованных)."""
    data: dict[str, Any] = {"version": 1}
    if entity.default_branch:
        data["default_branch"] = entity.default_branch
    if entity.owner_group_id:
        owner = await db.get(UserGroup, entity.owner_group_id)
        if owner is not None:
            data["owner"] = owner.name
    repo = {
        "url": entity.repo_url,
        "type": entity.repo_type.value if entity.repo_type else None,
        "path_prefix": entity.repo_path_prefix,
    }
    repo = {k: v for k, v in repo.items() if v}
    if repo:
        data["repo"] = repo
    rules = await db.scalars(
        select(OwnershipRule)
        .where(OwnershipRule.entity_id == entity.id)
        .order_by(OwnershipRule.position)
    )
    ownership = [{"path": r.pattern, "owner": r.group.name} for r in rules]
    if ownership:
        data["ownership"] = ownership
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
