from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from purchase_price.collectors.registry import build_collectors
from purchase_price.collectors.web_public_catalog import (
    WebPublicCatalogCollector,
    WebPublicCatalogError,
    load_web_public_prices,
)
from purchase_price.domain import ComparisonScope, EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import ProductQuery
from purchase_price.services.pricing import assess_prices


def _write_catalog(
    path: Path,
    *,
    seller_type: str = "b2b",
    price: str = "1200000",
    currency: str = "KRW",
) -> None:
    path.write_text(
        "seller_name,seller_type,manufacturer,product_name,model_name,specification,price,"
        "currency,source_url,verified_at,source_record_id,vat_status,conditions\n"
        f"웹판매사,{seller_type},Maker,Product,MODEL-1,Spec-A,{price},{currency},"
        "https://seller.example.test/model-1,2026-09-30,web-1,,배송·설치 별도 확인\n",
        encoding="utf-8",
    )


def test_web_catalog_exact_match_is_labeled_web_and_reference_only(tmp_path: Path) -> None:
    path = tmp_path / "web.csv"
    _write_catalog(path)
    collector = WebPublicCatalogCollector(path)

    results = collector.search(
        ProductQuery(
            product_name="Product",
            manufacturer="Maker",
            model_name="MODEL-1",
            specification="Spec-A",
        )
    )

    assert len(results) == 1
    result = results[0]
    assert result.price == Decimal("1200000")
    assert result.match_grade == MatchGrade.A
    assert result.evidence_type == EvidenceType.PUBLIC_SALE_PRICE
    assert result.source_type == SourceType.B2B
    assert result.source_name == "웹 · 웹판매사"
    assert result.comparison_scope == ComparisonScope.REFERENCE_ONLY
    assert result.source_url == "https://seller.example.test/model-1"


def test_web_reference_price_never_enters_direct_observed_range(tmp_path: Path) -> None:
    path = tmp_path / "web.csv"
    _write_catalog(path)
    result = WebPublicCatalogCollector(path).search(
        ProductQuery(
            product_name="Product",
            manufacturer="Maker",
            model_name="MODEL-1",
            specification="Spec-A",
        )
    )[0]

    assessment = assess_prices([result], current_quote=Decimal("1500000"))

    assert assessment.observed_count == 0
    assert assessment.quote_comparable_count == 0
    assert assessment.low is None
    assert assessment.quote_position is None


def test_retail_web_source_maps_to_retail_type(tmp_path: Path) -> None:
    path = tmp_path / "web.csv"
    _write_catalog(path, seller_type="retail")

    result = WebPublicCatalogCollector(path).search(
        ProductQuery(product_name="Product", manufacturer="Maker", model_name="MODEL-1")
    )[0]

    assert result.source_type == SourceType.RETAIL
    assert result.comparison_scope == ComparisonScope.REFERENCE_ONLY


@pytest.mark.parametrize(
    ("seller_type", "currency", "price", "message"),
    [
        ("marketplace", "KRW", "1000", "seller_type must be b2b or retail"),
        ("b2b", "USD", "1000", "currency must be KRW"),
        ("b2b", "KRW", "NaN", "finite and positive"),
    ],
)
def test_web_catalog_rejects_untrusted_rows(
    tmp_path: Path,
    seller_type: str,
    currency: str,
    price: str,
    message: str,
) -> None:
    path = tmp_path / "web.csv"
    _write_catalog(path, seller_type=seller_type, currency=currency, price=price)

    with pytest.raises(WebPublicCatalogError, match=message):
        load_web_public_prices(path)


def test_empty_default_web_catalog_does_not_change_active_collector_set() -> None:
    collectors = build_collectors(
        include_mock=False,
        include_manufacturer_public=True,
        include_g2b=False,
        include_web_public=True,
    )

    assert [collector.name for collector in collectors] == ["manufacturer_public_catalog"]


def test_web_catalog_contract_requires_traceable_source_fields() -> None:
    rows = load_web_public_prices()

    assert rows == ()
