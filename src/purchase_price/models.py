from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
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
from .domain import ComparisonScope, EvidenceType, MatchGrade, SourceType


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
    __table_args__ = (
        UniqueConstraint(
            "evidence_id",
            "product_id",
            "derivation_version",
            "evidence_type",
            name="uq_price_observation_derivation",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    evidence_id: Mapped[int] = mapped_column(
        ForeignKey("raw_evidence.id", ondelete="SET NULL"), nullable=False, index=True
    )
    derivation_version: Mapped[str] = mapped_column(String(80), default="v1")
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
    comparison_scope: Mapped[ComparisonScope] = mapped_column(
        SAEnum(ComparisonScope, native_enum=False), default=ComparisonScope.OBSERVED_ONLY
    )
    comparison_note: Mapped[str | None] = mapped_column(Text)
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
    evidence: Mapped[RawEvidence] = relationship(back_populates="observations")


class TrackBDeliveryLine(Base):
    """DB serving index for immutable Track B delivery-line history held in R2."""

    __tablename__ = "track_b_delivery_lines"
    __table_args__ = (
        UniqueConstraint(
            "delivery_request_number", "change_order", "product_sequence",
            name="uq_track_b_stable_identity",
        ),
        UniqueConstraint(
            "delivery_request_number", "change_order_number", "product_sequence",
            name="uq_track_b_numeric_change_order",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    delivery_request_number: Mapped[str] = mapped_column(String(120), index=True)
    change_order: Mapped[str] = mapped_column(String(30))
    change_order_number: Mapped[int] = mapped_column(Integer)
    product_sequence: Mapped[str] = mapped_column(String(40))
    item_sha256: Mapped[str] = mapped_column(String(64))
    identity_conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    identity_conflict_count: Mapped[int] = mapped_column(Integer, default=0)
    raw_object_key: Mapped[str] = mapped_column(Text)
    raw_payload_sha256: Mapped[str] = mapped_column(String(64))
    detail_code: Mapped[str] = mapped_column(String(10), index=True)
    product_id: Mapped[str | None] = mapped_column(String(100), index=True)
    product_title: Mapped[str | None] = mapped_column(Text)
    product_class: Mapped[str | None] = mapped_column(String(300))
    class_key: Mapped[str | None] = mapped_column(String(300), index=True)
    manufacturer: Mapped[str | None] = mapped_column(String(300))
    manufacturer_qualifier: Mapped[str | None] = mapped_column(String(50))
    model_name: Mapped[str | None] = mapped_column(String(300))
    model_qualifier: Mapped[str | None] = mapped_column(String(50))
    model_qualifier_verified_as_origin: Mapped[bool] = mapped_column(Boolean, default=False)
    model_key: Mapped[str | None] = mapped_column(String(300), index=True)
    specification: Mapped[str | None] = mapped_column(Text)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    unit: Mapped[str | None] = mapped_column(String(50))
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    amount_check: Mapped[str] = mapped_column(String(30))
    transaction_date: Mapped[date | None] = mapped_column(Date)
    supplier: Mapped[str | None] = mapped_column(String(300))
    demand_institution: Mapped[str | None] = mapped_column(String(300))
    contract_delivery_type: Mapped[str | None] = mapped_column(Text, deferred=True)
    contract_type: Mapped[str | None] = mapped_column(Text, deferred=True)
    delivery_condition: Mapped[str | None] = mapped_column(Text, deferred=True)
    # 사업명 (cntrctDlvrReqNm): what the institution called the purchase; serving schema v3.
    business_name: Mapped[str | None] = mapped_column(Text, deferred=True)
    api_params_json: Mapped[str] = mapped_column(Text)


class HospitalMasterRecord(Base):
    """Canonical hospital identity used to join KHIDI / HIRA / ALIO / news data."""

    __tablename__ = "hospital_master"

    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[str] = mapped_column(String(40), unique=True)
    canonical_name: Mapped[str] = mapped_column(String(200), unique=True)
    short_name: Mapped[str | None] = mapped_column(String(100))
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    foundation: Mapped[str | None] = mapped_column(String(200))
    network: Mapped[str | None] = mapped_column(String(200), index=True)
    region: Mapped[str | None] = mapped_column(String(50), index=True)
    hospital_type: Mapped[str | None] = mapped_column(String(50), index=True)
    ownership: Mapped[str | None] = mapped_column(String(50))
    bed_count: Mapped[int | None] = mapped_column(Integer)
    bed_count_as_of: Mapped[date | None] = mapped_column(Date)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class HospitalFinancial(Base):
    """One account amount per hospital, fiscal year and source (raw figures, never derived)."""

    __tablename__ = "hospital_financial"
    __table_args__ = (
        UniqueConstraint(
            "hospital_id", "fiscal_year", "account_code", "source",
            name="uq_hospital_financial_account",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[str] = mapped_column(
        ForeignKey("hospital_master.hospital_id", ondelete="CASCADE"), index=True
    )
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    fiscal_period_start: Mapped[date | None] = mapped_column(Date)
    fiscal_period_end: Mapped[date | None] = mapped_column(Date)
    account_code: Mapped[str] = mapped_column(String(60))
    account_name: Mapped[str | None] = mapped_column(String(200))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 0))
    source: Mapped[str] = mapped_column(String(40))
    source_url: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class HospitalMetric(Base):
    """Derived metric computed by code from ``hospital_financial`` (see hospital_metrics)."""

    __tablename__ = "hospital_metric"
    __table_args__ = (
        UniqueConstraint("hospital_id", "fiscal_year", "metric_key", name="uq_hospital_metric"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    hospital_id: Mapped[str] = mapped_column(
        ForeignKey("hospital_master.hospital_id", ondelete="CASCADE"), index=True
    )
    fiscal_year: Mapped[int] = mapped_column(Integer, index=True)
    metric_key: Mapped[str] = mapped_column(String(60))
    value: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    inputs_json: Mapped[str | None] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NewsKeyword(Base):
    __tablename__ = "news_keyword"
    __table_args__ = (UniqueConstraint("group_key", "text", name="uq_news_keyword_group_text"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(String(200))
    group_key: Mapped[str] = mapped_column(String(60), index=True)
    group_name: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    alert: Mapped[str] = mapped_column(String(20), default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NewsItem(Base):
    """A detected article: display fields only (NAVER terms), never AI input."""

    __tablename__ = "news_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[str] = mapped_column(String(600), unique=True)
    title: Mapped[str] = mapped_column(Text)
    source_domain: Mapped[str | None] = mapped_column(String(200))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    url: Mapped[str] = mapped_column(Text)
    naver_link: Mapped[str | None] = mapped_column(Text)
    keywords_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataSourceLog(Base):
    __tablename__ = "data_source_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_name: Mapped[str] = mapped_column(String(100), index=True)
    query_text: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
