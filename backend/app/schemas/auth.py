import uuid

from pydantic import BaseModel


class LoginRequest(BaseModel):
    # str, а не EmailStr: домены вроде .local/.corp валидны в LDAP, но
    # отклоняются email-validator как зарезервированные.
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserRead(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    full_name: str | None
    auth_source: str
    is_active: bool
    is_superuser: bool
    roles: list[str] = []
    # «есть хоть где-то» — для меню
    permissions: list[str] = []
    # право → "*" (везде) или префиксы путей проектов — для кнопок
    scoped_permissions: dict[str, str | list[str]] = {}
