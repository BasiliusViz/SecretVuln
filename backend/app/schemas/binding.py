import uuid
from datetime import datetime

from pydantic import BaseModel


class BindingCreate(BaseModel):
    """POST /entities/{id}/bindings: группа получает роль на проект."""

    group_id: uuid.UUID
    role_id: uuid.UUID


class GroupBindingCreate(BaseModel):
    """POST /groups/{id}/bindings: entity_id = None — на всё дерево."""

    role_id: uuid.UUID
    entity_id: uuid.UUID | None = None


class BindingRead(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    group_name: str
    role_id: uuid.UUID
    role_name: str
    entity_id: uuid.UUID | None
    # None — привязка на всё дерево
    entity_path: str | None
    created_at: datetime
    created_by: uuid.UUID | None


class RoleGrant(BaseModel):
    """Можно ли вызывающему выдать роль на проект: каких прав ему не хватает."""

    id: uuid.UUID
    name: str
    grantable: bool
    missing: list[str]


class EntityBindings(BaseModel):
    own: list[BindingRead]
    # на предках и глобальные; источник — entity_path (None — всё дерево)
    inherited: list[BindingRead]
    # только если вызывающий может управлять доступом к проекту
    roles: list[RoleGrant] | None = None
