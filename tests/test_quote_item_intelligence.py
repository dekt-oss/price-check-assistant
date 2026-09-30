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
    build_quote_item_intelligence_summary,
    quote_item_intelligence_rows,
)
from purchase_price.ui.quote_review_state import QuoteReviewState


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
    assert result.identity_status == "모델 exact 확인"
    assert result.responsible_companies == ("필립스코리아",)
    assert result.business_license_status == "제조사명 업허가 1건"
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

    assert result.identity_status == "복수 identity · 확인 필요"
    assert result.responsible_companies == ("회사A", "회사B")
    assert set(result.permit_numbers) == {"수허 1", "수허 2"}


def test_no_identity_does_not_invent_company_or_safety_clearance() -> None:
    result = build_quote_item_intelligence_summary(
        item=_item(model=""),
        track_b=SimpleNamespace(candidates=(), reference_candidates=()),
        mfds_workspace=None,
        mfds_identity=None,
    )

    assert result.identity_status == "미조회"
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

    assert rows[0]["품목 책임주체"] == "품목책임회사"
    assert rows[0]["실제 조달 공급업체"] == "납품사"
    assert rows[0]["Safety"] == "공식 확인 필요"


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

    assert "### 통합 품목 상태" in source
    assert '"품목 책임주체"' in source
    assert '"실제 조달 공급업체"' in source
    assert '"Safety"' in source
    assert "Safety 자동조회가 미연결인 경우" in source
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

    monkeypatch.setattr(quote_market_research, "lookup_track_b_quote", fake_lookup)

    quote_market_research._ensure_track_b_comparison(state)

    assert captured == [("심장충격기", "Philips", "Efficia DFM100", "")]


def test_quote_batch_contract_resolves_identity_before_track_b() -> None:
    from pathlib import Path

    source = Path("src/purchase_price/ui/quote_market_research.py").read_text(
        encoding="utf-8"
    )

    identity_pos = source.index("_ensure_mfds_identity(state)")
    track_b_pos = source.index("_ensure_track_b_comparison(state)")
    assert identity_pos < track_b_pos
    assert "_quote_item_unified_query(state, index)" in source
