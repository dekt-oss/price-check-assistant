from decimal import Decimal

from purchase_price.domain import MatchGrade
from purchase_price.services.track_b_db_quote_comparison import (
    TrackBQuoteCandidate,
    TrackBQuoteComparison,
)
from purchase_price.ui.track_b_transactions import direct_transaction_rows


def test_direct_transaction_row_exposes_v3_price_evidence_fields() -> None:
    candidate = TrackBQuoteCandidate(
        source_record_id="delivery:REQ-1|change:00|line:1",
        product_title="채혈기, 제조사A, C101",
        price=Decimal("450"),
        match_grade=MatchGrade.A,
        match_note="model_exact_and_product_match",
        delta_percent=None,
        raw_object_key="raw/v1/example.json.gz",
        amount_check="consistent",
        transaction_date="2025-12-09",
        supplier="주식회사 워터맨하우스",
        demand_institution="기관A",
        quantity=Decimal("100"),
        unit="개",
        total_amount=Decimal("45000"),
        manufacturer="제조사A",
        model_name="C101",
        specification="",
        product_id="12345678",
        detail_code="1234567890",
    )
    result = TrackBQuoteComparison(
        status="success",
        candidates=(candidate,),
        examined=1,
    )

    rows = direct_transaction_rows(result)

    assert len(rows) == 1
    row = rows[0]
    assert row["가격"] == "450원"
    assert row["단가구분"] == "원문 단가"
    assert row["단위"] == "개"
    assert row["포장입수"] == "미확인"
    assert row["수량"] == "100"
    assert row["VAT"] == "미확인"
    assert row["총액"] == "45,000원"
    assert row["매칭등급"] == "A"
    assert row["매칭근거"] == "model_exact_and_product_match"
