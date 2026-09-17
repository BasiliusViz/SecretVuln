import uuid

from pydantic import BaseModel


class Permission(BaseModel):
    resource: str
    action: str


class RoleCreate(BaseModel):
    name: str
    description: str | None = None
    permissions: list[Permission] = []


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class RoleRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    is_builtin: bool
    permissions: list[Permission] = []


class PermissionsUpdate(BaseModel):
    permissions: list[Permission]
