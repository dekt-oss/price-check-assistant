from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_research_record_contract_contains_p0_07_provenance_fields() -> None:
    text = (
        REPO_ROOT / "src" / "purchase_price" / "services" / "g2b_market_models.py"
    ).read_text(encoding="utf-8")

    for field in (
        "product_id",
        "detail_product_code",
        "item_sequence",
        "original_specification",
        "original_amount_text",
        "delivery_condition",
        "record_change_order",
    ):
        assert f"{field}:" in text


def test_procurement_research_table_exposes_trace_fields_with_nonpromotion_warning() -> None:
    text = (
        REPO_ROOT / "src" / "purchase_price" / "ui" / "g2b_market_research.py"
    ).read_text(encoding="utf-8")

    for label in (
        '"품목식별번호"',
        '"세부품명번호"',
        '"라인"',
        '"원문규격"',
        '"원문금액"',
        '"납품조건"',
        '"변경차수"',
    ):
        assert label in text
    assert "해당 필드 존재만으로 동일제품이나 단가 Evidence로 승격하지 않습니다" in text


def test_shopping_candidate_table_exposes_line_provenance_without_band_promotion() -> None:
    text = (REPO_ROOT / "src" / "purchase_price" / "ui" / "market_research.py").read_text(
        encoding="utf-8"
    )

    assert '"기관": candidate.institution' in text
    assert '"공급업체": candidate.supplier' in text
    assert '"수량·단위": _quantity_unit(candidate)' in text
    assert '"라인": candidate.item_sequence' in text
    assert '"납품조건": candidate.delivery_condition' in text
    assert '"변경차수": candidate.record_change_order' in text
    assert '"원문규격": candidate.original_specification' in text
    assert "provenance이며 가격 승격 근거가 아닙니다" in text
