from datetime import date
from decimal import Decimal

import pytest

from purchase_price.domain import ComparisonScope, EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice
from purchase_price.services.quote_comparability import (
    QuoteComparabilityContext,
    evaluate_quote_comparability_candidate,
)
from purchase_price.services.quote_condition_comparison import build_quote_condition_profile
from purchase_price.ui.quote_review_export import build_record
from purchase_price.ui.quote_review_s5_s6 import (
    condition_diff_rows,
    supplement_evidence_conditions,
)
from purchase_price.ui.quote_review_state import QuoteReviewState


def _evidence() -> CollectedPrice:
    return CollectedPrice(
        manufacturer="Maker",
        product_name="Printer",
        model_name="M-1",
        specification="A3",
        price=Decimal("3300000"),
        evidence_type=EvidenceType.PUBLIC_SALE_PRICE,
        source_type=SourceType.MANUFACTURER,
        source_name="official",
        source_url="https://example.com/evidence",
        collected_at=date(2026, 9, 1),
        transaction_date=date(2026, 8, 30),
        quantity=Decimal("1"),
        unit="대",
        vat_status="포함",
        conditions="배송=포함;설치=포함;옵션=기본구성;보증=3년;유지보수=없음",
        source_record_id="e-1",
        match_grade=MatchGrade.A,
        comparison_scope=ComparisonScope.OBSERVED_ONLY,
    )


def _context() -> QuoteComparabilityContext:
    return QuoteComparabilityContext(
        quote_unit_price=Decimal("3500000"),
        quantity=Decimal("1"),
        unit="대",
        quote_date=date(2026, 9, 1),
        conditions=build_quote_condition_profile(
            vat="포함",
            delivery="포함",
            installation="포함",
            options="기본구성",
            warranty="3년",
            maintenance="없음",
        ),
    )


def test_condition_diff_uses_existing_gate_and_has_nine_rows() -> None:
    evidence = _evidence()
    context = _context()
    decision = evaluate_quote_comparability_candidate(context, evidence)
    assert decision.eligible_candidate is True
    rows = condition_diff_rows(context, evidence, decision)
    assert len(rows) == 9
    assert [row["조건"] for row in rows] == [
        "수량 · 단위",
        "통화",
        "VAT",
        "배송",
        "설치",
        "옵션",
        "보증",
        "유지보수",
        "기준일 차이",
    ]


def test_supplement_requires_url_and_note_and_returns_copy() -> None:
    evidence = _evidence()
    with pytest.raises(ValueError, match="URL"):
        supplement_evidence_conditions(
            evidence,
            source_url="",
            reviewer_note="checked",
            vat_status="포함",
            quantity=Decimal("1"),
            unit="대",
            delivery="포함",
            installation="포함",
            options="기본구성",
            warranty="3년",
            maintenance="없음",
        )
    amended = supplement_evidence_conditions(
        evidence,
        source_url="https://example.com/checked",
        reviewer_note="원문 확인",
        vat_status="포함",
        quantity=Decimal("1"),
        unit="대",
        delivery="포함",
        installation="포함",
        options="기본구성",
        warranty="3년",
        maintenance="없음",
    )
    assert amended is not evidence
    assert amended.source_url == "https://example.com/checked"
    assert evidence.source_url == "https://example.com/evidence"
    assert "담당자 근거조건 보완" in amended.comparison_note


def test_export_omits_uploaded_filename_and_raw_document() -> None:
    state = QuoteReviewState(file_name="real-hospital-quote.xlsx")
    record = build_record(state)
    text = str(record)
    assert "real-hospital-quote.xlsx" not in text
    assert "file_name" not in record
    assert "raw" not in text.casefold()
