from datetime import date
from decimal import Decimal

from purchase_price.domain import ComparisonScope, EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice
from purchase_price.services.quote_comparability import QuoteComparabilityContext
from purchase_price.services.quote_condition_comparison import build_quote_condition_profile
from purchase_price.services.quote_extraction import QuoteExtractionResult, QuoteItem
from purchase_price.services.search import SearchRun
from purchase_price.ui.quote_review_state import IdentityResult, QuoteReviewState, can_enter


def _item() -> QuoteItem:
    return QuoteItem(
        source_sheet="Sheet1",
        source_row=2,
        product_name="컬러 레이저프린터",
        manufacturer="FUJIFILM Business Innovation",
        model_name="ApeosPrint C5570 GK",
        specification="A3",
        quantity=Decimal("1"),
        unit="대",
        unit_price=Decimal("3500000"),
        vat_status="포함",
        delivery_condition="포함",
        installation_condition="포함",
        option_condition="기본구성",
        warranty_condition="3년",
        maintenance_condition="없음",
    )


def _evidence() -> CollectedPrice:
    return CollectedPrice(
        manufacturer="FUJIFILM Business Innovation",
        product_name="컬러 레이저프린터",
        model_name="ApeosPrint C5570 GK",
        specification="A3",
        price=Decimal("3300000"),
        evidence_type=EvidenceType.PUBLIC_SALE_PRICE,
        source_type=SourceType.MANUFACTURER,
        source_name="manufacturer",
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


def test_gate_walks_from_extraction_to_identity_and_search() -> None:
    item = _item()
    state = QuoteReviewState()
    assert can_enter(2, state) == (False, ("견적서를 업로드하고 추출을 실행하세요.",))

    state.extraction = QuoteExtractionResult(items=(), warnings=())
    assert can_enter(2, state) == (True, ())
    assert can_enter(3, state) == (
        False,
        ("자동 추출 품목이 없어 수동 품목을 1건 이상 입력하세요.",),
    )

    state.items = [item]
    assert can_enter(3, state)[0] is False

    state.item_confirmed[0] = True
    assert can_enter(3, state) == (True, ())
    assert can_enter(4, state)[0] is False

    state.identity[0] = IdentityResult(ready=True, status="verified mapping", mapping_verified=True)
    assert can_enter(4, state) == (True, ())
    assert can_enter(5, state)[0] is False

    state.search_runs[0] = SearchRun(results=[])
    assert can_enter(5, state) == (True, ())


def test_step_six_requires_existing_candidate_gate_not_ui_shortcut() -> None:
    item = _item()
    state = QuoteReviewState(
        extraction=QuoteExtractionResult(items=(item,), warnings=()),
        items=[item],
        item_confirmed={0: True},
        identity={0: IdentityResult(ready=True, status="verified", mapping_verified=True)},
        search_runs={0: SearchRun(results=[_evidence()])},
        comparability_context={0: _context()},
    )
    allowed, reasons = can_enter(6, state)
    assert allowed is True
    assert reasons == ()


def test_reset_downstream_invalidates_derived_state() -> None:
    item = _item()
    state = QuoteReviewState(
        extraction=QuoteExtractionResult(items=(item,), warnings=()),
        items=[item],
        item_confirmed={0: True},
        identity={0: IdentityResult(ready=True, status="verified")},
        search_runs={0: SearchRun()},
        comparability_context={0: _context()},
        approvals={"pair": object()},  # type: ignore[dict-item]
        step=6,
    )
    state.reset_downstream(after_step=2)
    assert state.identity == {}
    assert state.search_runs == {}
    assert state.comparability_context == {}
    assert state.approvals == {}
    assert state.step == 2
