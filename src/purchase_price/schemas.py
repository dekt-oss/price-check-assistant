from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .domain import MatchGrade, SourceType


@dataclass(frozen=True)
class ProductQuery:
    product_name: str = ""
    manufacturer: str = ""
    model_name: str = ""
    specification: str = ""


@dataclass(frozen=True)
class CollectedPrice:
    manufacturer: str | None
    product_name: str
    model_name: str | None
    specification: str | None
    price: Decimal
    source_type: SourceType
    source_name: str
    source_url: str | None
    collected_at: date
    transaction_date: date | None = None
    vat_status: str | None = None
    conditions: str | None = None
    match_grade: MatchGrade = MatchGrade.X
    match_note: str | None = None
