from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from purchase_price.domain import MatchGrade
from purchase_price.evidence_domain import IdentityEvidenceStatus
from purchase_price.services.mfds_identity_index import (
    MfdsIdentityLookup,
    MfdsIdentityRecord,
)
from purchase_price.services.mfds_recall import MfdsRecallLookupResult
from purchase_price.services.quote_extraction import QuoteItem
from purchase_price.ui import quote_market_research
from purchase_price.ui.quote_item_intelligence import (
    QuoteItemIntelligenceSummary,
    build_quote_item_intelligence_summary,
    item_status_cards,
    item_status_cards_html,
    mfds_permit_note,
    quote_item_intelligence_rows,
)
from purchase_price.ui.quote_review_state import QuoteReviewState


def _with_live(lookup):
    """Wrap an index-only fake lookup in the (result, live) shape of the shared live lookup."""

    from purchase_price.services.track_b_live_gap_fill import TrackBLiveGapFill

    def wrapped(query, *, quote_unit_price):
        return lookup(query, quote_unit_price=quote_unit_price), TrackBLiveGapFill("up_to_date")

    return wrapped


def _item(model: str = "DFM100") -> QuoteItem:
    return QuoteItem(
        source_sheet="Sheet1",
        source_row=2,
        product_name="심장충격기",
        manufacturer="Philips",
        model_name=model,
        specification="",
        quantity=Decimal("1"),
        unit="대",
        unit_price=Decimal("12500000"),
    )


def _identity_record(
    *,
    permit: str = "수허 12-3456",
    company: str = "필립스코리아",
    model: str = "DFM100",
) -> MfdsIdentityRecord:
    return MfdsIdentityRecord(
        udi_di=None,
        product_name="심장충격기",
        classification_no=None,
        grade=None,
        permit_number=permit,
        permit_date=None,
        model_name=model,
        trade_name=None,
        registered_company=company,
    )


def test_integrated_summary_uses_only_ab_direct_prices_and_suppliers() -> None:
    track_b = SimpleNamespace(
        candidates=(
            SimpleNamespace(
                price=Decimal("9900000"),
                match_grade=MatchGrade.A,
                supplier="공급사A",
            ),
            SimpleNamespace(
                price=Decimal("13200000"),
                match_grade=MatchGrade.B,
                supplier="공급사B",
            ),
            SimpleNamespace(
                price=Decimal("5000000"),
                match_grade=MatchGrade.C,
                supplier="참고업체",
            ),
        ),
        reference_candidates=(),
    )
    identity = MfdsIdentityLookup(
        status="success",
        query="DFM100",
        match_type="model",
        records=(_identity_record(),),
    )
    mfds = SimpleNamespace(
        permit_numbers=("수허 12-3456",),
        business_records=(SimpleNamespace(company_name="Philips", industry_type="수입업"),),
    )

    result = build_quote_item_intelligence_summary(
        item=_item(),
        track_b=track_b,
        mfds_workspace=mfds,
        mfds_identity=identity,
    )

    assert result.direct_count == 2
    assert result.observed_low == Decimal("9900000")
    assert result.observed_high == Decimal("13200000")
    assert result.supplier_names == ("공급사A", "공급사B")
    assert "참고업체" not in result.supplier_names
    assert result.identity_status == "허가 목록에서 같은 모델 확인"
    assert result.responsible_companies == ("필립스코리아",)
    assert result.business_license_status == "제조·수입업 허가 1건 확인"
    assert result.safety_status == "공식 확인 필요"


def test_ambiguous_identity_is_not_presented_as_confirmed() -> None:
    records = (
        _identity_record(permit="수허 1", company="회사A"),
        _identity_record(permit="수허 2", company="회사B"),
    )
    identity = MfdsIdentityLookup(
        status="success",
        query="DFM100",
        match_type="model",
        records=records,  # type: ignore[arg-type]
    )

    assert identity.identity_status == IdentityEvidenceStatus.AMBIGUOUS

    result = build_quote_item_intelligence_summary(
        item=_item(),
        track_b=SimpleNamespace(candidates=(), reference_candidates=()),
        mfds_workspace=None,
        mfds_identity=identity,
    )

    assert result.identity_status == "같은 모델명이 여러 허가에 있어 직접 살펴봐야 함"
    assert result.responsible_companies == ("회사A", "회사B")
    assert set(result.permit_numbers) == {"수허 1", "수허 2"}


def test_no_identity_does_not_invent_company_or_safety_clearance() -> None:
    result = build_quote_item_intelligence_summary(
        item=_item(model=""),
        track_b=SimpleNamespace(candidates=(), reference_candidates=()),
        mfds_workspace=None,
        mfds_identity=None,
    )

    assert result.identity_status == "아직 조회하지 않음"
    assert result.responsible_companies == ()
    assert result.supplier_names == ()
    assert result.safety_status == "자동조회 미연결"
    assert "안전함" not in result.safety_message


def test_integrated_rows_keep_evidence_roles_separate() -> None:
    summary = build_quote_item_intelligence_summary(
        item=_item(),
        track_b=SimpleNamespace(
            candidates=(
                SimpleNamespace(
                    price=Decimal("10000000"),
                    match_grade=MatchGrade.A,
                    supplier="납품사",
                ),
            ),
            reference_candidates=(),
        ),
        mfds_workspace=None,
        mfds_identity=MfdsIdentityLookup(
            status="success",
            query="DFM100",
            match_type="model",
            records=(_identity_record(company="품목책임회사"),),  # type: ignore[arg-type]
        ),
    )

    rows = quote_item_intelligence_rows([(0, "심장충격기", summary)])

    assert rows[0]["제조·수입업체(식약처)"] == "품목책임회사"
    assert rows[0]["납품업체(나라장터)"] == "납품사"
    assert rows[0]["회수·판매중지"] == "공식 확인 필요"
    assert rows[0]["나라장터 같은 모델 거래"] == "1건 · 10,000,000원"


def test_quote_identity_lookup_is_cached_and_prefers_model(monkeypatch) -> None:
    state = QuoteReviewState(items=[_item()])
    calls: list[str] = []
    lookup = MfdsIdentityLookup(
        status="success_0",
        query="DFM100",
        match_type=None,
        records=(),
    )

    def fake_lookup(query: str):
        calls.append(query)
        return lookup

    monkeypatch.setattr(quote_market_research, "lookup_mfds_identity_from_r2", fake_lookup)

    quote_market_research._ensure_mfds_identity(state)
    quote_market_research._ensure_mfds_identity(state)

    assert calls == ["DFM100"]
    assert state.mfds_identity[0] is lookup


def test_quote_identity_lookup_uses_product_only_when_model_missing(monkeypatch) -> None:
    state = QuoteReviewState(items=[_item(model="")])
    calls: list[str] = []

    def fake_lookup(query: str):
        calls.append(query)
        return MfdsIdentityLookup(
            status="success_0",
            query=query,
            match_type=None,
            records=(),
        )

    monkeypatch.setattr(quote_market_research, "lookup_mfds_identity_from_r2", fake_lookup)

    quote_market_research._ensure_mfds_identity(state)

    assert calls == ["심장충격기"]


def test_reset_downstream_clears_cached_integrated_identity() -> None:
    state = QuoteReviewState(items=[_item()])
    state.mfds_identity[0] = MfdsIdentityLookup(
        status="success_0",
        query="DFM100",
        match_type=None,
        records=(),
    )

    state.reset_downstream(after_step=3)

    assert state.mfds_identity == {}


def test_quote_ui_exposes_integrated_item_status_contract() -> None:
    from pathlib import Path

    source = Path("src/purchase_price/ui/quote_market_research.py").read_text(
        encoding="utf-8"
    )

    assert "### 품목별 조사 상태" in source
    assert "PERMIT_VS_TRADES_NOTE" in source
    assert "회수·판매중지 자동 조회가 연결되지 않은 경우" in source
    assert "_ensure_mfds_identity" in source



def test_integrated_summary_surfaces_recall_api_authorization_state() -> None:
    result = build_quote_item_intelligence_summary(
        item=_item(),
        track_b=SimpleNamespace(candidates=(), reference_candidates=()),
        mfds_workspace=None,
        mfds_identity=None,
        safety_lookup=MfdsRecallLookupResult(
            status="not_authorized",
            query_type="model",
            query="DFM100",
            error_type="PublicDataClientError",
            error_message="SERVICE_KEY_IS_NOT_REGISTERED_ERROR code=30",
            checked_at="2026-09-30T08:00:00+09:00",
        ),
    )

    assert result.safety_status == "공식 API 인증 미승인"
    assert "활용승인" in result.safety_message
    assert "안전함" not in result.safety_message


def test_quote_safety_lookup_is_cached(monkeypatch) -> None:
    state = QuoteReviewState(items=[_item()])
    calls: list[tuple[str, str]] = []
    lookup = MfdsRecallLookupResult(
        status="success_0",
        query_type="model",
        query="DFM100",
        checked_at="2026-09-30T08:00:00+09:00",
    )

    def fake_lookup(*, model_name: str = "", product_name: str = ""):
        calls.append((model_name, product_name))
        return lookup

    monkeypatch.setattr(quote_market_research, "lookup_mfds_recall", fake_lookup)

    quote_market_research._ensure_safety_lookup(state)
    quote_market_research._ensure_safety_lookup(state)

    assert calls == [("DFM100", "심장충격기")]
    assert state.safety_lookup[0] is lookup
    assert 0 not in state.item_research_failures


def test_quote_safety_failure_is_retryable_without_blocking_item() -> None:
    state = QuoteReviewState(items=[_item()])
    state.safety_lookup[0] = MfdsRecallLookupResult(
        status="failure",
        query_type="model",
        query="DFM100",
        error_type="PublicDataClientError",
        error_message="synthetic",
        checked_at="2026-09-30T08:00:00+09:00",
    )
    state.item_research_failures = {0: {"Safety": "PublicDataClientError"}}

    quote_market_research._retry_failed_stage(state, 0, "Safety")

    assert state.safety_lookup == {}
    assert state.item_research_failures == {}


def test_reset_downstream_clears_cached_safety_lookup() -> None:
    state = QuoteReviewState(items=[_item()])
    state.safety_lookup[0] = MfdsRecallLookupResult(
        status="success_0",
        query_type="model",
        query="DFM100",
    )

    state.reset_downstream(after_step=3)

    assert state.safety_lookup == {}


def test_quote_ui_runs_official_safety_lookup_contract() -> None:
    from pathlib import Path

    source = Path("src/purchase_price/ui/quote_market_research.py").read_text(
        encoding="utf-8"
    )

    assert "_ensure_safety_lookup" in source
    assert "lookup_mfds_recall" in source
    assert 'failures["Safety"]' in source
    assert "safety_lookup=state.safety_lookup.get(index)" in source


def test_quote_track_b_uses_same_canonical_model_as_unified_search(monkeypatch) -> None:
    state = QuoteReviewState(items=[_item(model="DFM100")])
    state.mfds_identity[0] = MfdsIdentityLookup(
        status="success",
        query="DFM100",
        match_type="model",
        records=(_identity_record(model="Efficia DFM100"),),
    )
    captured: list[tuple[str, str, str, str]] = []

    def fake_lookup(query, *, quote_unit_price):
        captured.append(
            (
                query.product_name,
                query.manufacturer,
                query.model_name,
                query.specification,
            )
        )
        return SimpleNamespace(
            status="success_0",
            candidates=(),
            reference_candidates=(),
            suggestions=(),
        )

    monkeypatch.setattr(quote_market_research, "lookup_track_b_quote_with_live", _with_live(fake_lookup))

    quote_market_research._ensure_track_b_comparison(state)

    assert captured == [("심장충격기", "", "Efficia DFM100", "")]


def test_quote_unified_query_keeps_quote_conditions_out_of_retrieval() -> None:
    state = QuoteReviewState(items=[_item(model="DFM100")])
    state.items[0] = state.items[0].__class__(
        **{
            **state.items[0].__dict__,
            "specification": "200J / 옵션포함",
        }
    )
    state.mfds_identity[0] = MfdsIdentityLookup(
        status="success",
        query="DFM100",
        match_type="model",
        records=(_identity_record(model="Efficia DFM100"),),
    )

    query = quote_market_research._quote_item_unified_query(state, 0)

    assert query.product_name == "심장충격기"
    assert query.model_name == "Efficia DFM100"
    assert query.manufacturer == ""
    assert query.specification == ""


def test_quote_batch_contract_resolves_identity_before_track_b() -> None:
    from pathlib import Path

    source = Path("src/purchase_price/ui/quote_market_research.py").read_text(
        encoding="utf-8"
    )

    identity_pos = source.index("_ensure_mfds_identity(state)")
    track_b_pos = source.index("_ensure_track_b_comparison(state)")
    assert identity_pos < track_b_pos
    assert "_quote_item_unified_query(state, index)" in source


def _ambiguous_identity() -> MfdsIdentityLookup:
    records = (
        _identity_record(permit="제인 20-5001", company="회사A", model="M40"),
        _identity_record(permit="제허 12-1069", company="회사B", model="M40"),
        _identity_record(permit="제허 22-131", company="회사C", model="M40"),
    )
    return MfdsIdentityLookup(
        status="success",
        query="M40",
        match_type="model",
        records=records,  # type: ignore[arg-type]
    )


def test_permit_note_never_says_no_match_when_the_full_list_has_the_model() -> None:
    # The live API only reads the first pages of the product list, so it can miss a model that the
    # full permit index has. The note must follow the index and list the permits once.
    workspace = SimpleNamespace(
        status="success",
        records=tuple(range(721)),
        active_records=(),
        exact_confirmed=False,
        exact_ambiguous=False,
        permit_numbers=(),
    )
    level, text = mfds_permit_note(workspace, _ambiguous_identity())

    assert level == "warning"
    assert "여러 허가" in text
    assert "제인 20-5001" in text and "제허 12-1069" in text and "제허 22-131" in text
    assert "찾지 못" not in text


def test_permit_note_single_index_match_is_confirmed() -> None:
    identity = MfdsIdentityLookup(
        status="success",
        query="DFM100",
        match_type="model",
        records=(_identity_record(),),  # type: ignore[arg-type]
    )
    workspace = SimpleNamespace(
        status="success", records=(1, 2), active_records=(), exact_confirmed=False,
        exact_ambiguous=False, permit_numbers=(),
    )
    level, text = mfds_permit_note(workspace, identity)

    assert level == "success"
    assert "수허 12-3456" in text


def test_permit_note_only_hedges_when_neither_source_found_the_model() -> None:
    workspace = SimpleNamespace(
        status="success", records=(1, 2), active_records=(), exact_confirmed=False,
        exact_ambiguous=False, permit_numbers=(),
    )
    level, text = mfds_permit_note(workspace, None)

    assert level == "info"
    assert "직접 확인" in text
    assert mfds_permit_note(None, None) is None


def test_amount_check_labels_are_plain_korean() -> None:
    from purchase_price.ui.quote_market_research import amount_check_label

    assert amount_check_label("consistent") == "금액 일치"
    assert amount_check_label("inconsistent") == "금액 확인 필요"
    assert amount_check_label("not_checked") == "확인 불가"
    assert amount_check_label("unknown") == "확인 불가"
    assert amount_check_label(None) == "확인 불가"
    assert amount_check_label("something_new") == "확인 불가"


def _summary(**overrides) -> QuoteItemIntelligenceSummary:
    values = dict(
        direct_count=267,
        observed_low=None,
        observed_high=None,
        other_unit_count=0,
        other_units=(),
        main_unit="대",
        supplier_names=("가", "나", "다"),
        identity_status="같은 모델명이 여러 허가에 있어 직접 살펴봐야 함",
        permit_numbers=(),
        responsible_companies=("(주)메디아나",),
        business_license_status="식약처에서 직접 확인",
        safety_status="공식 안전정보 일치 미확인",
        safety_message="",
    )
    values.update(overrides)
    return QuoteItemIntelligenceSummary(**values)


def test_status_cards_use_short_values_and_keep_the_full_sentence_below() -> None:
    cards = {label: (value, sub) for label, value, sub, _ in item_status_cards(_summary())}

    assert cards["식약처 허가 확인"] == ("허가 여러 건", "같은 모델명이 여러 허가에 있어 직접 살펴봐야 함")
    assert cards["회수·판매중지"] == ("일치 기록 없음", "공식 안전정보 일치 미확인")
    assert cards["같은 제품 거래"][0] == "267건"
    assert all(len(value) <= 10 for value, _ in cards.values())


def test_status_cards_html_has_wrapping_grid_and_comma_counts() -> None:
    html = item_status_cards_html(_summary(direct_count=1234, supplier_names=tuple("가" * 1)))

    assert "qi-cards" in html and "max-width: 1200px" in html
    assert "1,234건" in html
    assert "…" not in html and "nowrap" not in html
