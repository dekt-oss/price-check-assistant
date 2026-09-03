from decimal import Decimal
from pathlib import Path

import pytest

from purchase_price.collectors.manufacturer_public_catalog import (
    ManufacturerCatalogError,
    ManufacturerPublicCatalogCollector,
    load_manufacturer_public_prices,
)
from purchase_price.collectors.registry import build_collectors
from purchase_price.domain import EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import ProductQuery
from purchase_price.services.search import search_all


def test_default_catalog_contains_traceable_gmsr_182_public_price() -> None:
    rows = load_manufacturer_public_prices()

    assert len(rows) >= 1
    row = next(item for item in rows if item.model_name == "GMSR-182")
    assert row.manufacturer == "GMS"
    assert row.specification == "182L"
    assert row.price == Decimal("5000000")
    assert row.source_url == "https://www.gsmedical.co.kr/estimate/"
    assert row.vat_status is None


def test_default_catalog_contains_traceable_c5570_gk_public_price() -> None:
    rows = load_manufacturer_public_prices()

    row = next(item for item in rows if item.model_name == "ApeosPrint C5570 GK")
    assert row.manufacturer == "FUJIFILM Business Innovation"
    assert row.specification == "A3,55ppm"
    assert row.price == Decimal("5500000")
    assert row.source_url.startswith("https://store-fbkr.fujifilm.com/")
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


def test_exact_c5570_gk_query_returns_direct_a_without_inventing_vat() -> None:
    collector = ManufacturerPublicCatalogCollector()

    results = collector.search(
        ProductQuery(
            product_name="컬러 레이저프린터",
            manufacturer="FUJIFILM Business Innovation",
            model_name="ApeosPrint C5570 GK",
            specification="A3,55PPM",
        )
    )

    assert len(results) == 1
    result = results[0]
    assert result.price == Decimal("5500000")
    assert result.match_grade == MatchGrade.A
    assert result.evidence_type == EvidenceType.PUBLIC_SALE_PRICE
    assert result.source_type == SourceType.MANUFACTURER
    assert result.source_record_id == "fujifilm-apeosprint-c5570-gk-store-20260904"
    assert result.vat_status is None
    assert "VAT 포함 여부 미확인" in (result.conditions or "")


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


def _write_catalog(path: Path, *, price: str = "1000", currency: str = "KRW") -> None:
    path.write_text(
        "manufacturer,product_name,model_name,specification,price,currency,source_name,"
        "source_url,verified_at,source_record_id,vat_status,conditions\n"
        f"Maker,Product,MODEL-1,,{price},{currency},Maker official,"
        "https://example.test/product,2026-09-04,record-1,,\n",
        encoding="utf-8",
    )


def test_non_krw_catalog_row_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "manufacturer.csv"
    _write_catalog(path, currency="USD")

    with pytest.raises(ManufacturerCatalogError, match="currency must be KRW"):
        load_manufacturer_public_prices(path)


@pytest.mark.parametrize("price", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_catalog_price_is_rejected(tmp_path: Path, price: str) -> None:
    path = tmp_path / "manufacturer.csv"
    _write_catalog(path, price=price)

    with pytest.raises(ManufacturerCatalogError, match="finite and positive"):
        load_manufacturer_public_prices(path)


def test_missing_catalog_failure_is_isolated_by_search_all(tmp_path: Path) -> None:
    collector = ManufacturerPublicCatalogCollector(tmp_path / "missing.csv")
    query = ProductQuery(product_name="Product", manufacturer="Maker", model_name="MODEL-1")

    run = search_all(query, [collector])

    assert run.results == []
    assert len(run.errors) == 1
    assert run.errors[0].startswith("manufacturer_public_catalog:")
