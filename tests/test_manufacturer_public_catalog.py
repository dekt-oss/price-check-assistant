from decimal import Decimal

from purchase_price.collectors.manufacturer_public_catalog import (
    ManufacturerPublicCatalogCollector,
    load_manufacturer_public_prices,
)
from purchase_price.collectors.registry import build_collectors
from purchase_price.domain import EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import ProductQuery


def test_default_catalog_contains_traceable_gmsr_182_public_price() -> None:
    rows = load_manufacturer_public_prices()

    assert len(rows) >= 1
    row = next(item for item in rows if item.model_name == "GMSR-182")
    assert row.manufacturer == "GMS"
    assert row.specification == "182L"
    assert row.price == Decimal("5000000")
    assert row.source_url == "https://www.gsmedical.co.kr/estimate/"
    assert row.vat_status is None


def test_exact_gmsr_182_query_returns_direct_a_without_inventing_conditions() -> None:
    collector = ManufacturerPublicCatalogCollector()

    results = collector.search(
        ProductQuery(
            product_name="약품냉장고",
            manufacturer="GMS",
            model_name="GMSR-182",
            specification="182L",
        )
    )

    assert len(results) == 1
    result = results[0]
    assert result.price == Decimal("5000000")
    assert result.match_grade == MatchGrade.A
    assert result.evidence_type == EvidenceType.PUBLIC_SALE_PRICE
    assert result.source_type == SourceType.MANUFACTURER
    assert result.source_record_id == "gms-gmsr-182-estimate-20260904"
    assert result.quantity is None
    assert result.unit is None
    assert result.transaction_date is None
    assert result.vat_status is None
    assert "VAT" in (result.conditions or "")


def test_different_model_is_not_returned_as_public_price_evidence() -> None:
    collector = ManufacturerPublicCatalogCollector()

    results = collector.search(
        ProductQuery(
            product_name="약품냉장고",
            manufacturer="GMS",
            model_name="GMSR-322",
        )
    )

    assert results == []


def test_registry_can_enable_real_manufacturer_source_without_mock() -> None:
    collectors = build_collectors(include_mock=False, include_manufacturer_public=True)

    assert len(collectors) == 1
    assert isinstance(collectors[0], ManufacturerPublicCatalogCollector)
