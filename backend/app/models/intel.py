"""Справочники обогащения: EPSS, CISA KEV, БДУ ФСТЭК, CWE.

Каждая загрузка целиком заменяет таблицу своего источника (файлы — полные снимки).
В находку копируются только сводные поля (`cves`, `epss_max`, `kev`, `has_bdu`),
полные данные читаются отсюда при открытии SV-N.
"""

import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IntelSource(str, enum.Enum):
    epss = "epss"
    kev = "kev"
    bdu = "bdu"
    cwe = "cwe"


class IntelStatus(str, enum.Enum):
    idle = "idle"
    loading = "loading"
    ok = "ok"
    failed = "failed"


class IntelEpss(Base):
    __tablename__ = "intel_epss"

    cve_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    epss: Mapped[float] = mapped_column(Float, nullable=False)
    percentile: Mapped[float] = mapped_column(Float, nullable=False)
    score_date: Mapped[date | None] = mapped_column(Date)


class IntelKev(Base):
    __tablename__ = "intel_kev"

    cve_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    date_added: Mapped[date | None] = mapped_column(Date)
    name: Mapped[str | None] = mapped_column(Text)
    ransomware: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)


class IntelBdu(Base):
    __tablename__ = "intel_bdu"

    bdu_id: Mapped[str] = mapped_column(String(32), primary_key=True)  # BDU:2021-05969
    name: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str | None] = mapped_column(Text)  # текст ФСТЭК как есть


class IntelBduCve(Base):
    __tablename__ = "intel_bdu_cve"
    __table_args__ = (Index("ix_intel_bdu_cve_cve_id", "cve_id"),)

    bdu_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    cve_id: Mapped[str] = mapped_column(String(32), primary_key=True)


class IntelCwe(Base):
    __tablename__ = "intel_cwe"

    cwe_id: Mapped[str] = mapped_column(String(16), primary_key=True)  # CWE-89
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)


class IntelSourceState(Base):
    """Состояние источника: статус последней загрузки, дата файла, число записей."""

    __tablename__ = "intel_sources"

    source: Mapped[IntelSource] = mapped_column(
        Enum(IntelSource, name="intel_source"), primary_key=True
    )
    status: Mapped[IntelStatus] = mapped_column(
        Enum(IntelStatus, name="intel_status"), default=IntelStatus.idle, nullable=False
    )
    loaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    loaded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    file_date: Mapped[date | None] = mapped_column(Date)
    record_count: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    # момент постановки текущей загрузки (для «зависшего» loading)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
