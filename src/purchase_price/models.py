from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .domain import EvidenceType, MatchGrade, SourceType


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    manufacturer: Mapped[str | None] = mapped_column(String(200), index=True)
    product_name: Mapped[str] = mapped_column(String(300), index=True)
    model_name: Mapped[str | None] = mapped_column(String(200), index=True)
    specification: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    aliases: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    observations: Mapped[list[PriceObservation]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class CollectionRun(Base):
    __tablename__ = "collection_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_name: Mapped[str] = mapped_column(String(100), index=True)
    query_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="running", index=True)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    evidence: Mapped[list[RawEvidence]] = relationship(back_populates="run")


class RawEvidence(Base):
    __tablename__ = "raw_evidence"
    __table_args__ = (UniqueConstraint("source_name", "payload_hash", name="uq_evidence_source_hash"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection_runs.id", ondelete="SET NULL"), index=True
    )
    source_name: Mapped[str] = mapped_column(String(100), index=True)
    source_record_id: Mapped[str | None] = mapped_column(String(300), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    original_title: Mapped[str | None] = mapped_column(Text)
    payload_text: Mapped[str] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64), index=True)
    parser_version: Mapped[str] = mapped_column(String(50), default="v1")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[CollectionRun | None] = relationship(back_populates="evidence")
    observations: Mapped[list[PriceObservation]] = relationship(back_populates="evidence")


class PriceObservation(Base):
    __tablename__ = "price_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    evidence_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_evidence.id", ondelete="SET NULL"), index=True
    )
    price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    evidence_type: Mapped[EvidenceType] = mapped_column(
        SAEnum(EvidenceType, native_enum=False), index=True
    )
    currency: Mapped[str] = mapped_column(String(10), default="KRW")
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    unit: Mapped[str | None] = mapped_column(String(50))
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    vat_status: Mapped[str | None] = mapped_column(String(50))
    conditions: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[SourceType] = mapped_column(SAEnum(SourceType, native_enum=False))
    source_name: Mapped[str] = mapped_column(String(300))
    source_url: Mapped[str | None] = mapped_column(Text)
    source_record_id: Mapped[str | None] = mapped_column(String(300), index=True)
    original_title: Mapped[str | None] = mapped_column(Text)
    collected_at: Mapped[date] = mapped_column(Date, default=date.today)
    transaction_date: Mapped[date | None] = mapped_column(Date)
    match_grade: Mapped[MatchGrade] = mapped_column(SAEnum(MatchGrade, native_enum=False))
    match_note: Mapped[str | None] = mapped_column(Text)

    product: Mapped[Product] = relationship(back_populates="observations")
    evidence: Mapped[RawEvidence | None] = relationship(back_populates="observations")
