import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import EMBED_DIM
from app.models.base import Base

# Размерность колонки (EMBED_DIM) фиксирована миграцией; другая модель — новая миграция.
__all__ = ["EMBED_DIM", "FindingEmbedding"]


class FindingEmbedding(Base):
    """Вектор канонического текста находки. Одна строка на находку."""

    __tablename__ = "finding_embeddings"

    finding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("findings.id", ondelete="CASCADE"), primary_key=True
    )
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    # sha256(модель + канонический текст): изменился текст или модель — пересчитать
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding = mapped_column(Vector(EMBED_DIM), nullable=False)
    # updated_at находки, по которой сверен текст. Сравниваем на неравенство, а не со
    # временем вектора: импорт, начатый раньше расчёта и закоммиченный позже, иначе потерялся бы
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
