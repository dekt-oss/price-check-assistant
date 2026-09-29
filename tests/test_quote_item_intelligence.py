from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from purchase_price.domain import MatchGrade
from purchase_price.evidence_domain import IdentityEvidenceStatus
from purchase_price.services.mfds_identity_index import (
    MfdsIdentityLookup,
    MfdsIdentityRecord,
)
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
