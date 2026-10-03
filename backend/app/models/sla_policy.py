from sqlalchemy import Boolean, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPKMixin


class SlaPolicy(Base, UUIDPKMixin, TimestampMixin):
    """Сроки исправления по критичности (дни; NULL — без срока).

    Назначается узлу дерева (entities.sla_policy_id) и наследуется вниз;
    узлы без своей и без унаследованной политики берут политику по умолчанию.
    """

    __tablename__ = "sla_policies"
    __table_args__ = (
        # ровно одна политика по умолчанию
        Index("uq_sla_policies_default", "is_default", unique=True,
              postgresql_where=text("is_default")),
    )

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    days_critical: Mapped[int | None] = mapped_column(Integer)
    days_high: Mapped[int | None] = mapped_column(Integer)
    days_medium: Mapped[int | None] = mapped_column(Integer)
    days_low: Mapped[int | None] = mapped_column(Integer)
    days_info: Mapped[int | None] = mapped_column(Integer)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def days_for(self, severity: str) -> int | None:
        return getattr(self, f"days_{severity}")
