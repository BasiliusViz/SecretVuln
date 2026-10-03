import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class RepoType(str, enum.Enum):
    gitlab = "gitlab"
    github = "github"
    gitea = "gitea"
    bitbucket = "bitbucket"


class Entity(Base, UUIDPKMixin, TimestampMixin):
    """A node in a free-form user-built tree (like a folder).

    No fixed semantics: an entity can contain child entities and/or receive
    scan results (imports/findings) — both at once. How to structure the tree
    (org -> product -> repo, flat list of repos, ...) is entirely up to the user.
    Name is unique among siblings (per parent), not globally.
    Deleting an entity cascades to its whole subtree, imports and findings.
    """

    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint(
            "parent_id", "name", name="uq_entities_parent_name", postgresql_nulls_not_distinct=True
        ),
        UniqueConstraint(
            "parent_id", "slug", name="uq_entities_parent_slug", postgresql_nulls_not_distinct=True
        ),
        Index(
            "ix_entities_path_cache", "path_cache", unique=True,
            postgresql_ops={"path_cache": "text_pattern_ops"},
        ),
        Index("ix_entities_tags", "tags", postgresql_using="gin"),
        Index(
            "uq_entities_repo_url", "repo_url", unique=True,
            postgresql_where=text("repo_url IS NOT NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    # Адресная часть узла: [a-z0-9._-], уникальна среди соседей
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    # Полный путь fintech/payments/api — пересчитывается при смене slug/родителя (entity_paths)
    path_cache: Mapped[str] = mapped_column(String(2048), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), index=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    # Ветка, из которой строится бэклог; NULL — наследуется от родителя (или любая ветка)
    default_branch: Mapped[str | None] = mapped_column(String(255))
    # Arbitrary user-defined fields (team, criticality, repo URL, ...)
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    # Наследуемые настройки (NULL — берётся у ближайшего предка), см. services/entity_settings.py
    owner_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_groups.id", ondelete="SET NULL")
    )
    repo_url: Mapped[str | None] = mapped_column(String(1024))
    repo_type: Mapped[RepoType | None] = mapped_column(Enum(RepoType, name="repo_type"))
    repo_path_prefix: Mapped[str | None] = mapped_column(String(512))
    # Поля, изменённые в админке: файл .secretvuln.yml их больше не перезаписывает
    pinned_fields: Mapped[list[str]] = mapped_column(ARRAY(String(50)), default=list, nullable=False)
    # Последний применённый .secretvuln.yml (нормализованный)
    config_file: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    config_commit_sha: Mapped[str | None] = mapped_column(String(64))
    config_applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Политика SLA узла; NULL — наследуется от предка (или политика по умолчанию)
    sla_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sla_policies.id", ondelete="RESTRICT")
    )
    # Теги для фильтров и метрик (env:prod, pci); эффективные = свои ∪ предков
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), default=list, server_default="{}", nullable=False
    )

    findings = relationship("Finding", back_populates="entity", cascade="all, delete-orphan")
    imports = relationship("Import", back_populates="entity", cascade="all, delete-orphan")
