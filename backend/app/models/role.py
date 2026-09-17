from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class Role(Base, UUIDPKMixin, TimestampMixin):
    """Role metadata for the admin panel role constructor.

    The actual permissions (role -> resource/action policies) and user-role
    assignments live in Casbin's `casbin_rule` table, managed by
    casbin-sqlalchemy-adapter. This table only holds display metadata and the
    LDAP group mapping. `name` must match the role subject used in Casbin
    policies (e.g. "role:analyst").
    """

    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # DN or CN of the LDAP group whose members get this role on login
    ldap_group: Mapped[str | None] = mapped_column(String(512), index=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
