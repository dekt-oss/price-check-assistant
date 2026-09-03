from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import Date, DateTime, Enum as SAEnum, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .domain import MatchGrade, SourceType


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

    observations: Mapped[list["PriceObservation"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class PriceObservation(Base):
    __tablename__ = "price_observations"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(10), default="KRW")
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    unit: Mapped[str | None] = mapped_column(String(50))
    vat_status: Mapped[str | None] = mapped_column(String(50))
    conditions: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[SourceType] = mapped_column(SAEnum(SourceType, native_enum=False))
    source_name: Mapped[str] = mapped_column(String(300))
    source_url: Mapped[str | None] = mapped_column(Text)
    collected_at: Mapped[date] = mapped_column(Date, default=date.today)
    transaction_date: Mapped[date | None] = mapped_column(Date)
    match_grade: Mapped[MatchGrade] = mapped_column(SAEnum(MatchGrade, native_enum=False))
    match_note: Mapped[str | None] = mapped_column(Text)

    product: Mapped[Product] = relationship(back_populates="observations")
