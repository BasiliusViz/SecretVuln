import uuid
from datetime import datetime

from pydantic import BaseModel


class UserBrief(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    full_name: str | None
    auth_source: str


class GroupCreate(BaseModel):
    name: str
    description: str | None = None
    source: str = "manual"  # manual | ldap
    # Для source=ldap: CN LDAP-группы. Если не задан — берётся name.
    ldap_group: str | None = None


class GroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    ldap_group: str | None = None


class GroupRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    description: str | None
    source: str
    ldap_group: str | None
    last_synced_at: datetime | None
    member_count: int = 0
    # GET /groups?entity_id=X: есть ли у группы finding:read на X (для предупреждения
    # при назначении); без entity_id — None. Привязки — GET /groups/{id}/bindings
    has_access: bool | None = None


class GroupDetail(GroupRead):
    members: list[UserBrief] = []


class SyncResult(BaseModel):
    added: int
    removed: int
    provisioned: int  # сколько новых пользователей заведено из LDAP
    total: int
