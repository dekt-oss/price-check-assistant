from decimal import Decimal, InvalidOperation

import streamlit as st

from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL, SOURCE_NAME
from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings
from purchase_price.services.g2b_search_policy import (
    G2B_DEFAULT_LOOKBACK_DAYS,
    G2B_LOOKBACK_OPTIONS,
    g2b_lookback_label,
)
from purchase_price.services.g2b_unmapped_discovery import discover_unmapped_g2b_candidates
from purchase_price.services.price_conditions import build_price_condition_profile
from purchase_price.services.pricing import assess_prices
from purchase_price.services.purchase_review import build_purchase_review_input
from purchase_price.services.search import search_all
from purchase_price.ui.widgets import (
    render_condition_table,
    render_discovery_candidates,
    render_evidence_table,
    render_observation_cards,
    render_source_status,
)

st.set_page_config(page_title="통합검색", page_icon="🔎", layout="wide")
st.title("통합검색")

settings = get_settings()
g2b_enabled = bool((settings.resolved_g2b_service_key or "").strip())
if g2b_enabled:
    st.caption(
        "공식 제조사 공개가격과 나라장터 구매실적을 함께 검색합니다. verified mapping이 있는 exact "
        "모델은 직접가격 검색을 수행하고, mapping이 없는 모델도 나라장터 후보 탐색은 수행하되 "
        "검증 전 후보가격을 직접 시세로 자동 승격하지 않습니다."
    )
else:
    st.caption("현재 공식 제조사 공개가격 source를 사용합니다. 나라장터는 API key 설정 시 활성화됩니다.")

with st.form("search-form"):
    c1, c2 = st.columns(2)
    with c1:
        product_name = st.text_input("제품명", placeholder="예: 약품냉장고")
        manufacturer = st.text_input("제조사", placeholder="예: GMS")
    with c2:
        model_name = st.text_input("모델명", placeholder="예: GMSR-182")
        specification = st.text_input("규격", placeholder="예: 182L")
    quote_text = st.text_input("현재 견적 단가 (선택)", placeholder="예: 5000000")
    g2b_lookback_days = st.selectbox(
        "나라장터 검색기간",
        options=G2B_LOOKBACK_OPTIONS,
        index=G2B_LOOKBACK_OPTIONS.index(G2B_DEFAULT_LOOKBACK_DAYS),
        format_func=g2b_lookback_label,
        disabled=not g2b_enabled,
        help="기본 최근 1년, 최대 5년. 직접가격 검색은 bounded request budget 안에서 완전수집을 시도합니다.",
    )
    submitted = st.form_submit_button("가격자료 검색", type="primary")

if submitted:
    quote = None
    if quote_text.strip():
        try:
            quote = Decimal(quote_text.replace(",", "").strip())
        except InvalidOperation:
            st.error("견적 단가는 숫자로 입력하세요.")
            st.stop()

    review_input = build_purchase_review_input(
        product_name=product_name,
        manufacturer=manufacturer,
        model_name=model_name,
        specification=specification,
        quote_unit_price=quote,
    )
    if review_input is None:
        st.warning("검색조건을 하나 이상 입력하세요.")
        st.stop()

    query = review_input.to_product_query()
    run = search_all(query, build_collectors(g2b_lookback_days=int(g2b_lookback_days)))

    st.subheader("출처별 검색상태")
    render_source_status(run)

    failed_sources = [
        status for status in run.source_statuses if not status.succeeded and not status.skipped
    ]
    if failed_sources:
        failed_names = ", ".join(status.source_name for status in failed_sources)
        st.error(
            "수집 미완료: 일부 출처가 실패했습니다. 현재 표시되는 가격은 성공한 출처만의 부분 근거이며 "
            f"전체 시장가격 범위로 해석하면 안 됩니다. 실패 출처: {failed_names}"
        )
    if run.errors:
        st.warning("일부 수집기 오류: " + " / ".join(run.errors))

    g2b_status = next((s for s in run.source_statuses if s.source_name == SOURCE_NAME), None)
    if g2b_status is not None and g2b_status.telemetry:
        telemetry = g2b_status.telemetry
        st.caption(
            "나라장터 직접가격 수집: "
            f"API 요청 {telemetry.get('request_count', '-')} / "
            f"예산 {telemetry.get('request_budget', '-')}회 · "
            f"완료 검색창 {telemetry.get('window_count', '-')}개 · "
            f"페이지 {telemetry.get('pages_fetched', '-')} · "
            f"원자료 {telemetry.get('records_seen', '-')}건 · "
            f"기간 {telemetry.get('begin_date', '-')} ~ {telemetry.get('end_date', '-')}"
        )

    skipped_g2b = next(
        (status for status in run.source_statuses if status.source_name == SOURCE_NAME and status.skipped),
        None,
    )
    discovery = None
    if skipped_g2b is not None and g2b_enabled and query.product_name.strip():
        with st.spinner("verified mapping이 없어 나라장터 미검증 후보를 별도로 탐색하고 있습니다..."):
            discovery = discover_unmapped_g2b_candidates(
                query,
                service_key=(settings.resolved_g2b_service_key or "").strip(),
                lookback_days=int(g2b_lookback_days),
                base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
                timeout_seconds=settings.g2b_request_timeout_seconds,
                max_retries=settings.g2b_max_retries,
                pages_per_term_window=1,
            )
        st.subheader("나라장터 미검증 후보 탐색")
        render_discovery_candidates(discovery)

    if not run.results:
        st.error("검증된 직접 비교가격은 확보하지 못했습니다. 출처별 상태를 확인하세요.")
        st.stop()

    assessment = assess_prices(run.results, review_input.quote_unit_price)
    profiles = [build_price_condition_profile(item) for item in run.results]
    condition_average = round(
        sum(profile.completeness_percent for profile in profiles) / len(profiles)
    )

    st.subheader("가격 요약")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("관측 직접근거", f"{assessment.observed_count}건")
    c2.metric("독립 출처", f"{assessment.source_count}개")
    c3.metric("근거 신뢰도", assessment.confidence)
    c4.metric("평균 조건명시", f"{condition_average}%")
    render_observation_cards(run.results)
    st.write(assessment.message)
    if failed_sources:
        st.warning(
            "위 가격 요약은 수집이 완료된 출처만 반영한 부분 요약입니다. "
            "실패 출처 복구 전 최종 구매판정에 사용하지 마세요."
        )

    if review_input.quote_unit_price is not None:
        if assessment.quote_position is None:
            st.info("입력 견적과의 높고 낮음 비교는 거래조건 검증 전까지 보류합니다.")
        else:
            st.success(f"견적 위치: {assessment.quote_position}")

    st.subheader("가격 근거자료")
    render_evidence_table(run.results)
    st.subheader("가격조건 구조화")
    render_condition_table(run.results)
