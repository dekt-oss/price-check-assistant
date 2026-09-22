from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import streamlit as st

from purchase_price.services.g2b_search_policy import (
    G2B_DEFAULT_LOOKBACK_DAYS,
    G2B_LOOKBACK_OPTIONS,
    g2b_lookback_label,
)
from purchase_price.services.pricing import assess_prices
from purchase_price.services.purchase_review import build_purchase_review_input
from purchase_price.services.track_b_r2_quote_index import lookup_track_b_quote_from_r2
from purchase_price.services.unified_search_intent import (
    UnifiedSearchInterpretation,
    interpret_unified_search,
)
from purchase_price.ui.market_research import (
    render_market_reference_summary,
    render_procurement_research,
    run_market_research,
)
from purchase_price.ui.quote_review_state import (
    QUOTE_REVIEW_STATE_SESSION_KEY,
    QuoteReviewState,
)
from purchase_price.ui.quote_review_steps import _store_extraction
from purchase_price.ui.runtime_secrets import hydrate_streamlit_runtime_secrets
from purchase_price.ui.track_b_transactions import (
    candidate_counts,
    has_transaction_candidates,
    transaction_rows,
)
from purchase_price.ui.widgets import (
    evidence_rows,
    render_evidence_table,
    render_observation_cards,
    render_source_status,
)

HOME_SEARCH_STATE_KEY = "home_unified_search_result"
HOME_SEARCH_DETAILS_KEY = "home_search_details"


def _parse_quote(value: str) -> Decimal | None:
    if not value.strip():
        return None
    try:
        return Decimal(value.replace(",", "").strip())
    except InvalidOperation as exc:
        raise ValueError("견적 단가는 숫자로 입력하세요.") from exc


def _execute_search(
    *,
    search_text: str,
    product_name: str,
    manufacturer: str,
    model_name: str,
    specification: str,
    quote_text: str,
    lookback_days: int,
) -> dict[str, Any]:
    raw_search = search_text.strip()
    interpretation = interpret_unified_search(
        search_text=raw_search,
        product_name=product_name,
        manufacturer=manufacturer,
        model_name=model_name,
        specification=specification,
    )
    resolved_model = interpretation.model_name
    resolved_product = interpretation.product_name
    resolved_manufacturer = interpretation.manufacturer
    resolved_specification = interpretation.specification
    if (
        not resolved_product
        and not resolved_model
        and not resolved_manufacturer
        and not resolved_specification
    ):
        raise ValueError("품목 또는 모델명을 입력하세요.")

    quote = _parse_quote(quote_text)
    review_input = build_purchase_review_input(
        product_name=resolved_product,
        manufacturer=resolved_manufacturer,
        model_name=resolved_model,
        specification=resolved_specification,
        quote_unit_price=quote,
    )
    if review_input is None:
        raise ValueError("검색조건을 확인하세요.")
    query = review_input.to_product_query()

    track_b = lookup_track_b_quote_from_r2(query, quote_unit_price=review_input.quote_unit_price)
    model_probe_used = False
    if (
        raw_search
        and not interpretation.model_name
        and not product_name.strip()
        and track_b.status == "success_0"
    ):
        model_probe_input = build_purchase_review_input(
            product_name=raw_search,
            manufacturer=resolved_manufacturer,
            model_name=raw_search,
            specification=resolved_specification,
            quote_unit_price=quote,
        )
        if model_probe_input is not None:
            model_probe_query = model_probe_input.to_product_query()
            model_probe = lookup_track_b_quote_from_r2(
                model_probe_query,
                quote_unit_price=model_probe_input.quote_unit_price,
            )
            if has_transaction_candidates(model_probe):
                track_b = model_probe
                query = model_probe_query
                model_probe_used = True

    run, discovery, market_bundle = run_market_research(
        query,
        lookback_days=int(lookback_days),
        research_pages_per_term=1,
        research_request_budget=18,
        procurement_detail_limit=4,
    )
    rows = transaction_rows(track_b)
    strict_count, reference_count = candidate_counts(track_b)
    return {
        "heading": resolved_model or resolved_product or raw_search,
        "review_input": review_input,
        "query": query,
        "track_b": track_b,
        "rows": rows,
        "strict_count": strict_count,
        "reference_count": reference_count,
        "model_probe_used": model_probe_used,
        "interpretation": interpretation,
        "run": run,
        "discovery": discovery,
        "market_bundle": market_bundle,
    }


def _render_search_interpretation(
    interpretation: UnifiedSearchInterpretation,
) -> None:
    if not interpretation.auto_hydrated:
        return

    with st.container(border=True):
        st.markdown("**검색어 해석**")
        c1, c2, c3 = st.columns(3)
        c1.caption("품명")
        c1.write(interpretation.product_name or "미확인")
        c2.caption("제조사")
        c2.write(interpretation.manufacturer or "미확인")
        c3.caption("모델")
        c3.write(interpretation.model_name or "미확인")

        if interpretation.mapping_verified:
            st.success(
                "검증된 모델 매핑을 검색 편의용으로 적용했습니다. "
                "공식 동일제품 판정은 아래 A/B 근거에서 별도로 확인합니다."
            )
        else:
            st.info(
                "등록된 모델 검색 힌트로 입력을 구조화했습니다. "
                "이 해석 자체는 공식 조달분류나 동일제품 확정 근거가 아닙니다."
            )


def _render_search_result(state: dict[str, Any]) -> None:
    heading = state["heading"]
    review_input = state["review_input"]
    query = state["query"]
    track_b = state["track_b"]
    rows = state["rows"]
    strict_count = state["strict_count"]
    reference_count = state["reference_count"]
    run = state["run"]
    discovery = state["discovery"]
    market_bundle = state["market_bundle"]
    interpretation = state.get("interpretation")
    research_count = len(getattr(market_bundle, "records", ()) or ())

    st.divider()
    if isinstance(interpretation, UnifiedSearchInterpretation):
        _render_search_interpretation(interpretation)

    st.subheader(f"{heading} 거래가격")
    s1, s2, s3 = st.columns(3)
    s1.metric("동일성 확인 A/B", f"{strict_count}건")
    s2.metric("검색 참고", f"{reference_count}건")
    s3.metric("공개조달 Research", f"{research_count}건")
    if strict_count:
        st.success(
            f"동일성 확인 근거 {strict_count}건을 우선 표시합니다. "
            "규격·VAT·설치·옵션·보증 조건은 개별 원자료를 확인하세요."
        )
    elif reference_count:
        st.warning(
            f"직접 비교 가능한 A/B 근거는 0건이고 검색 참고가 {reference_count}건입니다. "
            "참고가격을 적정가격으로 자동 해석하지 않습니다."
        )
    elif research_count:
        st.info(
            "납품요구 직접가격은 없지만 공개조달 Research 근거가 있습니다. "
            "입찰예산·계약총액은 동일제품 단가로 사용하지 않습니다."
        )
    with st.container(border=True):
        st.markdown("**나라장터 거래가격**")
        if state["model_probe_used"]:
            st.caption("입력어가 모델명과 일치해 모델 기준 결과를 우선 표시합니다.")
        if rows:
            st.dataframe(
                rows,
                use_container_width=True,
                hide_index=True,
                column_config={"가격": st.column_config.TextColumn("가격")},
            )
            st.caption(f"동일성 확인 {strict_count}건 · 검색 참고 {reference_count}건")
        elif track_b.status == "unavailable":
            st.info("가격 검색 인덱스에 연결하지 못했습니다. 공개 시장자료도 함께 조사합니다.")
        elif track_b.status == "not_ingested":
            st.info("수집 자료의 빠른 가격 인덱스를 만드는 중입니다.")
        elif track_b.status == "insufficient_identity":
            st.info("품목 또는 모델명을 입력하세요.")
        else:
            st.info("현재 수집 범위에서 거래가격을 찾지 못했습니다. 공개 시장자료를 추가 조사합니다.")

    if not rows and run.results:
        public_rows = evidence_rows(run.results)
        st.markdown("**공개 시장가격**")
        st.dataframe(
            [
                {
                    "가격": row["단가"],
                    "출처": row["출처"],
                    "거래일": row["거래일"] or "미확인",
                    "자료성격": row["자료성격"],
                    "URL": row["URL"],
                }
                for row in public_rows
            ],
            use_container_width=True,
            hide_index=True,
            column_config={"가격": st.column_config.NumberColumn("가격", format="%d원")},
        )

    show_details = st.toggle("상세 조사·근거 보기", value=False, key=HOME_SEARCH_DETAILS_KEY)
    if show_details:
        st.markdown("#### 상세 조사·근거")
        render_market_reference_summary(
            discovery,
            query=query,
            quote_unit_price=review_input.quote_unit_price,
        )
        render_procurement_research(market_bundle)
        render_source_status(run)
        if run.results:
            assessment = assess_prices(run.results, review_input.quote_unit_price)
            m1, m2, m3 = st.columns(3)
            m1.metric("직접가격 근거", f"{assessment.observed_count}건")
            m2.metric("독립 출처", f"{assessment.source_count}개")
            m3.metric("근거 신뢰도", assessment.confidence)
            render_observation_cards(run.results)
            render_evidence_table(run.results)
        else:
            st.caption("엄격한 동일제품 직접가격은 현재 조사 범위에서 확인되지 않았습니다.")


hydrate_streamlit_runtime_secrets()
st.set_page_config(page_title="구매가격 검색", page_icon="🔎", layout="wide")
st.markdown(
    '<span id="unified-search-runtime-v3" style="display:none">unified-search-runtime-v3</span>',
    unsafe_allow_html=True,
)

st.markdown(
    """
<style>
.block-container {max-width: 1180px; padding-top: 2.2rem;}
[data-testid="stForm"] {border: 0; padding: 0;}
[data-testid="stFileUploader"] {margin-top: 0.2rem;}
.home-kicker {text-align:center; color:#6b7280; font-size:0.95rem; margin-bottom:0.15rem;}
.home-title {text-align:center; font-size:2.35rem; font-weight:750; margin:0.2rem 0 0.35rem 0;}
.home-subtitle {text-align:center; color:#6b7280; margin-bottom:1.6rem;}
.home-section {margin-top:1.15rem;}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown('<div class="home-kicker">공개 조달·시장근거 기반 구매검토</div>', unsafe_allow_html=True)
st.markdown('<div class="home-title">무엇을 조사할까요?</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="home-subtitle">모델명만 입력해도 알려진 모델 힌트를 안전하게 구조화해 가격·공급·조달근거를 함께 찾습니다.</div>',
    unsafe_allow_html=True,
)

with st.form("home_unified_search"):
    search_col, button_col = st.columns([8, 1.35], gap="small")
    with search_col:
        search_text = st.text_input(
            "통합 검색",
            placeholder="품목·모델·제조사  예) DFM100, ROTAPRO, Philips Efficia DFM100",
            label_visibility="collapsed",
        )
    with button_col:
        submitted = st.form_submit_button("검색", type="primary", use_container_width=True)

    st.caption(
        "한 줄 검색은 검증된 매핑과 등록된 모델 힌트만 자동 해석합니다. "
        "정확한 품명·제조사·모델을 알고 있으면 아래 조건에서 직접 수정할 수 있습니다."
    )

    with st.expander("정확도 높이기 · 상세 검색조건", expanded=False):
        a1, a2 = st.columns(2)
        product_name = a1.text_input("품명", placeholder="예: 가스마취기")
        manufacturer = a2.text_input("제조사", placeholder="예: Getinge / Maquet")
        model_name = a1.text_input("모델명", placeholder="예: FLOW-C")
        specification = a2.text_input("규격", placeholder="선택")
        quote_text = a1.text_input("현재 견적 단가", placeholder="선택 · 예: 66000000")
        lookback_days = a2.selectbox(
            "나라장터 검색기간",
            options=G2B_LOOKBACK_OPTIONS,
            index=G2B_LOOKBACK_OPTIONS.index(G2B_DEFAULT_LOOKBACK_DAYS),
            format_func=g2b_lookback_label,
        )

st.markdown('<div class="home-section"></div>', unsafe_allow_html=True)
with st.container(border=True):
    st.markdown("**견적서로 바로 시작**")
    st.caption("PDF · Excel · 이미지 견적서를 올리면 품목을 추출하고 같은 형식으로 거래가격을 찾습니다.")
    uploaded = st.file_uploader(
        "견적서 업로드",
        type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"],
        label_visibility="collapsed",
        key="home_quote_upload",
    )

if uploaded is not None:
    if QUOTE_REVIEW_STATE_SESSION_KEY not in st.session_state:
        st.session_state[QUOTE_REVIEW_STATE_SESSION_KEY] = QuoteReviewState()
    quote_state: QuoteReviewState = st.session_state[QUOTE_REVIEW_STATE_SESSION_KEY]
    if quote_state.file_name != uploaded.name or quote_state.extraction is None:
        with st.spinner("견적서에서 품목을 추출하고 있습니다..."):
            _store_extraction(uploaded, quote_state)
    st.switch_page("pages/2_견적_검토.py")

if submitted:
    try:
        with st.status("가격·거래근거를 조사하고 있습니다...", expanded=False) as status:
            search_state = _execute_search(
                search_text=search_text,
                product_name=product_name,
                manufacturer=manufacturer,
                model_name=model_name,
                specification=specification,
                quote_text=quote_text,
                lookback_days=int(lookback_days),
            )
            st.session_state[HOME_SEARCH_STATE_KEY] = search_state
            st.session_state[HOME_SEARCH_DETAILS_KEY] = False
            status.update(label="추가 자료 확인 완료", state="complete")
    except ValueError as exc:
        st.warning(str(exc))
        st.stop()

search_state = st.session_state.get(HOME_SEARCH_STATE_KEY)
if isinstance(search_state, dict):
    _render_search_result(search_state)

st.caption(
    "검색 참고 가격은 실제 관측값이지만 동일제품으로 확정된 가격은 아닙니다. "
    "모델·규격·VAT·설치·옵션 조건이 확인된 경우에만 직접 비교합니다."
)
