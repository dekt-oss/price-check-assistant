from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from purchase_price.collectors.base import PriceCollector
from purchase_price.domain import ComparisonScope, EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.services.product_matching import ProductIdentity, grade_product_identity

DEFAULT_WEB_CATALOG_PATH = Path(__file__).resolve().parents[3] / "data" / "public_web_prices.csv"
SUPPORTED_CURRENCY = "KRW"


class WebPublicCatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class WebPublicPrice:
    seller_name: str
    seller_type: str
    manufacturer: str
    product_name: str
    model_name: str
    specification: str | None
    price: Decimal
    currency: str
    source_url: str
    verified_at: date
    source_record_id: str
    vat_status: str | None
    conditions: str | None


def _optional(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def load_web_public_prices(
    path: Path = DEFAULT_WEB_CATALOG_PATH,
) -> tuple[WebPublicPrice, ...]:
    if not path.exists():
        raise WebPublicCatalogError(f"web price catalog not found: {path}")

    required = {
        "seller_name",
        "seller_type",
        "manufacturer",
        "product_name",
        "model_name",
        "price",
        "currency",
        "source_url",
        "verified_at",
        "source_record_id",
    }
    rows: list[WebPublicPrice] = []
    seen_ids: set[str] = set()

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise WebPublicCatalogError("web price catalog is missing required columns")

        for line_number, row in enumerate(reader, start=2):
            seller_name = (row.get("seller_name") or "").strip()
            seller_type = (row.get("seller_type") or "").strip().casefold()
            manufacturer = (row.get("manufacturer") or "").strip()
            product_name = (row.get("product_name") or "").strip()
            model_name = (row.get("model_name") or "").strip()
            source_url = (row.get("source_url") or "").strip()
            source_record_id = (row.get("source_record_id") or "").strip()
            currency = ((row.get("currency") or SUPPORTED_CURRENCY).strip() or SUPPORTED_CURRENCY).upper()

            if seller_type not in {"b2b", "retail"}:
                raise WebPublicCatalogError(
                    f"web price catalog line {line_number} seller_type must be b2b or retail"
                )
            if not all(
                [
                    seller_name,
                    manufacturer,
                    product_name,
                    model_name,
                    source_url,
                    source_record_id,
                ]
            ):
                raise WebPublicCatalogError(
                    f"web price catalog line {line_number} has blank required fields"
                )
            if source_record_id in seen_ids:
                raise WebPublicCatalogError(
                    f"duplicate web source_record_id: {source_record_id}"
                )
            if currency != SUPPORTED_CURRENCY:
                raise WebPublicCatalogError(
                    f"web price catalog line {line_number} currency must be {SUPPORTED_CURRENCY}"
                )

            try:
                price = Decimal((row.get("price") or "").strip())
            except InvalidOperation as exc:
                raise WebPublicCatalogError(
                    f"invalid price on web price catalog line {line_number}"
                ) from exc
            if not price.is_finite() or price <= 0:
                raise WebPublicCatalogError(
                    f"web price catalog line {line_number} price must be finite and positive"
                )

            try:
                verified_at = date.fromisoformat((row.get("verified_at") or "").strip())
            except ValueError as exc:
                raise WebPublicCatalogError(
                    f"invalid verified_at on web price catalog line {line_number}"
                ) from exc

            seen_ids.add(source_record_id)
            rows.append(
                WebPublicPrice(
                    seller_name=seller_name,
                    seller_type=seller_type,
                    manufacturer=manufacturer,
                    product_name=product_name,
                    model_name=model_name,
                    specification=_optional(row.get("specification")),
                    price=price,
                    currency=currency,
                    source_url=source_url,
                    verified_at=verified_at,
                    source_record_id=source_record_id,
                    vat_status=_optional(row.get("vat_status")),
                    conditions=_optional(row.get("conditions")),
                )
            )

    return tuple(rows)


def web_public_catalog_has_rows(path: Path = DEFAULT_WEB_CATALOG_PATH) -> bool:
    try:
        return bool(load_web_public_prices(path))
    except WebPublicCatalogError:
        return False


class WebPublicCatalogCollector(PriceCollector):
    """Curated public web-sale observations kept separate from direct procurement evidence.

    Search-engine snippets or inferred prices must never be inserted here. Every row requires a
    traceable seller page, explicit verification date and observed KRW price. Even an exact A/B
    product match stays REFERENCE_ONLY so web-shop conditions cannot silently enter the direct
    procurement price range.
    """

    name = "web_public_catalog"

    def __init__(self, path: Path = DEFAULT_WEB_CATALOG_PATH) -> None:
        self._path = path
        self._rows: tuple[WebPublicPrice, ...] | None = None

    def _load_rows(self) -> tuple[WebPublicPrice, ...]:
        if self._rows is None:
            self._rows = load_web_public_prices(self._path)
        return self._rows

    def search(self, query: ProductQuery) -> list[CollectedPrice]:
        results: list[CollectedPrice] = []
        for row in self._load_rows():
            identity = ProductIdentity(
                manufacturer=row.manufacturer,
                product_name=row.product_name,
                model_name=row.model_name,
                specification=row.specification,
                source_title=(
                    f"{row.product_name}, {row.manufacturer}, {row.model_name}"
                    + (f", {row.specification}" if row.specification else "")
                ),
            )
            decision = grade_product_identity(query, identity)
            if decision.grade == MatchGrade.X:
                continue

            source_type = SourceType.B2B if row.seller_type == "b2b" else SourceType.RETAIL
            results.append(
                CollectedPrice(
                    manufacturer=row.manufacturer,
                    product_name=row.product_name,
                    model_name=row.model_name,
                    specification=row.specification,
                    price=row.price,
                    evidence_type=EvidenceType.PUBLIC_SALE_PRICE,
                    source_type=source_type,
                    source_name=f"웹 · {row.seller_name}",
                    source_url=row.source_url,
                    collected_at=row.verified_at,
                    currency=row.currency,
                    vat_status=row.vat_status,
                    conditions=row.conditions,
                    source_record_id=row.source_record_id,
                    original_title=identity.source_title,
                    match_grade=decision.grade,
                    match_note=decision.note,
                    comparison_scope=ComparisonScope.REFERENCE_ONLY,
                    comparison_note=(
                        "웹 판매점 공개가격 · 판매조건/VAT/배송/설치/재고가 조달거래와 다를 수 있어 "
                        "직접 조달가격 범위와 견적 높고 낮음 판정에는 사용하지 않음"
                    ),
                )
            )
        return results
