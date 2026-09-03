from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from purchase_price.collectors.base import PriceCollector
from purchase_price.domain import EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.services.product_matching import ProductIdentity, grade_product_identity

DEFAULT_CATALOG_PATH = Path(__file__).resolve().parents[3] / "data" / "public_manufacturer_prices.csv"
SUPPORTED_CURRENCY = "KRW"


class ManufacturerCatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class ManufacturerPublicPrice:
    manufacturer: str
    product_name: str
    model_name: str
    specification: str | None
    price: Decimal
    currency: str
    source_name: str
    source_url: str
    verified_at: date
    source_record_id: str
    vat_status: str | None
    conditions: str | None


def _optional(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def load_manufacturer_public_prices(
    path: Path = DEFAULT_CATALOG_PATH,
) -> tuple[ManufacturerPublicPrice, ...]:
    if not path.exists():
        raise ManufacturerCatalogError(f"manufacturer price catalog not found: {path}")

    required = {
        "manufacturer",
        "product_name",
        "model_name",
        "price",
        "currency",
        "source_name",
        "source_url",
        "verified_at",
        "source_record_id",
    }
    rows: list[ManufacturerPublicPrice] = []
    seen_ids: set[str] = set()

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ManufacturerCatalogError("manufacturer price catalog is missing required columns")

        for line_number, row in enumerate(reader, start=2):
            manufacturer = (row.get("manufacturer") or "").strip()
            product_name = (row.get("product_name") or "").strip()
            model_name = (row.get("model_name") or "").strip()
            source_name = (row.get("source_name") or "").strip()
            source_url = (row.get("source_url") or "").strip()
            source_record_id = (row.get("source_record_id") or "").strip()
            currency = ((row.get("currency") or SUPPORTED_CURRENCY).strip() or SUPPORTED_CURRENCY).upper()

            if not all(
                [manufacturer, product_name, model_name, source_name, source_url, source_record_id]
            ):
                raise ManufacturerCatalogError(
                    f"manufacturer price catalog line {line_number} has blank required fields"
                )
            if source_record_id in seen_ids:
                raise ManufacturerCatalogError(
                    f"duplicate manufacturer source_record_id: {source_record_id}"
                )
            if currency != SUPPORTED_CURRENCY:
                raise ManufacturerCatalogError(
                    f"manufacturer catalog line {line_number} currency must be {SUPPORTED_CURRENCY}"
                )

            try:
                price = Decimal((row.get("price") or "").strip())
            except InvalidOperation as exc:
                raise ManufacturerCatalogError(
                    f"invalid price on manufacturer catalog line {line_number}"
                ) from exc
            if not price.is_finite() or price <= 0:
                raise ManufacturerCatalogError(
                    f"manufacturer catalog line {line_number} price must be finite and positive"
                )

            try:
                verified_at = date.fromisoformat((row.get("verified_at") or "").strip())
            except ValueError as exc:
                raise ManufacturerCatalogError(
                    f"invalid verified_at on manufacturer catalog line {line_number}"
                ) from exc

            seen_ids.add(source_record_id)
            rows.append(
                ManufacturerPublicPrice(
                    manufacturer=manufacturer,
                    product_name=product_name,
                    model_name=model_name,
                    specification=_optional(row.get("specification")),
                    price=price,
                    currency=currency,
                    source_name=source_name,
                    source_url=source_url,
                    verified_at=verified_at,
                    source_record_id=source_record_id,
                    vat_status=_optional(row.get("vat_status")),
                    conditions=_optional(row.get("conditions")),
                )
            )

    return tuple(rows)


class ManufacturerPublicCatalogCollector(PriceCollector):
    """Curated adapter for prices visibly published on an official manufacturer page.

    The adapter never invents current prices or fills missing commercial conditions. Each row must
    carry a traceable public URL and explicit verification date. Rows are graded by the same F3
    identity contract as procurement records, so only A/B observations can enter direct pricing.
    Catalog loading is lazy so malformed or missing catalog data remains inside the per-collector
    failure isolation boundary in `search_all()`.
    """

    name = "manufacturer_public_catalog"

    def __init__(self, path: Path = DEFAULT_CATALOG_PATH) -> None:
        self._path = path
        self._rows: tuple[ManufacturerPublicPrice, ...] | None = None

    def _load_rows(self) -> tuple[ManufacturerPublicPrice, ...]:
        if self._rows is None:
            self._rows = load_manufacturer_public_prices(self._path)
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

            results.append(
                CollectedPrice(
                    manufacturer=row.manufacturer,
                    product_name=row.product_name,
                    model_name=row.model_name,
                    specification=row.specification,
                    price=row.price,
                    evidence_type=EvidenceType.PUBLIC_SALE_PRICE,
                    source_type=SourceType.MANUFACTURER,
                    source_name=row.source_name,
                    source_url=row.source_url,
                    collected_at=row.verified_at,
                    currency=row.currency,
                    vat_status=row.vat_status,
                    conditions=row.conditions,
                    source_record_id=row.source_record_id,
                    original_title=identity.source_title,
                    match_grade=decision.grade,
                    match_note=decision.note,
                )
            )
        return results
