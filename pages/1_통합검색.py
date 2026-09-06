from decimal import Decimal, InvalidOperation

import pandas as pd
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
    source_rows = []
    for status in run.source_statuses:
        telemetry = status.telemetry or {}
        request_text = ""
        if telemetry.get("request_count") is not None:
            request_text = f"{telemetry['request_count']}/{telemetry.get('request_budget', '-')}"
        source_rows.append({
            "출처": status.source_name,
            "상태": status.status_label,
            "건수": status.result_count,
            "API 요청/예산": request_text,
            "검색창": telemetry.get("window_count", ""),
            "원자료": telemetry.get("records_seen", ""),
            "메모": status.note or status.error or "",
        })
    if source_rows:
        st.dataframe(pd.DataFrame(source_rows), use_container_width=True, hide_index=True)

    failed_sources = [status for status in run.source_statuses if not status.succeeded and not status.skipped]
    if failed_sources:
        failed_names = ", ".join(status.source_name for status in failed_sources)
        st.error(
            "⚠️ 수집 미완료: 일부 출처가 실패했습니다. 현재 표시되는 가격은 성공한 출처만의 부분 근거이며 "
            f"전체 시장가격 범위로 해석하면 안 됩니다. 실패 출처: {failed_names}"
        )
    if run.errors:
        st.warning("일부 수집기 오류: " + " / ".join(run.errors))

    g2b_status = next((s for s in run.source_statuses if s.source_name == SOURCE_NAME), None)
    if g2b_status is not None and g2b_status.telemetry:
        t = g2b_status.telemetry
        st.caption(
            "나라장터 직접가격 수집: "
            f"API 요청 {t.get('request_count', '-')} / 예산 {t.get('request_budget', '-')}회 · "
            f"완료 검색창 {t.get('window_count', '-')}개 · 페이지 {t.get('pages_fetched', '-')} · "
            f"원자료 {t.get('records_seen', '-')}건 · 기간 {t.get('begin_date', '-')} ~ {t.get('end_date', '-')}"
        )

    skipped_g2b = next((s for s in run.source_statuses if s.source_name == SOURCE_NAME and s.skipped), None)
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
        st.write(
            f"상태: **{discovery.status_label}** · 검색어: {', '.join(discovery.terms) or '-'} · "
            f"API 요청 {discovery.request_count}회 · 원자료 확인 {discovery.records_seen}건"
        )
        if discovery.status == "failure":
            st.warning(f"나라장터 후보 탐색 실패: {discovery.error_type or 'unknown error'}")
        elif discovery.candidates:
            discovery_rows = [{
                "거래일": c.transaction_date.isoformat() if c.transaction_date else "",
                "나라장터 표기": c.title,
                "세부품명": c.classification_name,
                "세부품명코드": c.classification_code,
                "후보가격": float(c.price),
                "근거ID": c.source_record_id,
            } for c in discovery.candidates]
            st.dataframe(pd.DataFrame(discovery_rows), use_container_width=True, hide_index=True)
            st.warning("위 후보가격은 미검증 후보이며 적정가격 범위에 자동 포함하지 않습니다.")
        else:
            st.info("선택 기간과 탐색어에서 입력 모델 토큰이 포함된 나라장터 후보를 찾지 못했습니다.")

    if not run.results:
        st.error("검증된 직접 비교가격은 확보하지 못했습니다. 출처별 상태를 확인하세요.")
        st.stop()

    assessment = assess_prices(run.results, review_input.quote_unit_price)
    profiles = [build_price_condition_profile(item) for item in run.results]
    condition_average = round(sum(p.completeness_percent for p in profiles) / len(profiles))

    st.subheader("가격 요약")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("관측 직접근거", f"{assessment.observed_count}건")
    c2.metric("관측가 하단", f"{assessment.low:,.0f}원" if assessment.low is not None else "산정불가")
    c3.metric("관측가 상단", f"{assessment.high:,.0f}원" if assessment.high is not None else "산정불가")
    c4.metric("독립 출처", f"{assessment.source_count}개")
    c5.metric("근거 신뢰도", assessment.confidence)
    c6.metric("평균 조건명시", f"{condition_average}%")
    st.write(assessment.message)
    if failed_sources:
        st.warning("위 가격 요약은 수집이 완료된 출처만 반영한 부분 요약입니다. 실패 출처 복구 전 최종 구매판정에 사용하지 마세요.")

    if review_input.quote_unit_price is not None:
        if assessment.quote_position is None:
            st.info("입력 견적과의 높고 낮음 비교는 거래조건 검증 전까지 보류합니다.")
        else:
            st.success(f"견적 위치: {assessment.quote_position}")

    rows = []
    condition_rows = []
    for item, profile in zip(run.results, profiles, strict=True):
        rows.append({
            "출처": item.source_name, "가격": float(item.price), "통화": item.currency,
            "등급": item.match_grade.value, "Evidence Type": item.evidence_type.value,
            "비교범위": item.comparison_scope.value, "자료성격": item.source_type.value,
            "거래일": item.transaction_date.isoformat() if item.transaction_date else "",
            "VAT": profile.vat, "수량·단위": profile.quantity_unit,
            "조건명시": f"{profile.completeness_percent}%", "조건": item.conditions or "",
            "비교메모": item.comparison_note or "", "근거ID": item.source_record_id or "",
            "수집일": item.collected_at.isoformat(), "URL": item.source_url or "",
        })
        condition_rows.append({
            "출처": item.source_name, "근거ID": item.source_record_id or "", "VAT": profile.vat,
            "수량·단위": profile.quantity_unit, "배송": profile.delivery, "설치": profile.installation,
            "옵션/부속": profile.options, "보증": profile.warranty, "유지보수": profile.maintenance,
            "거래/기준일": profile.basis_date, "명시율": f"{profile.completeness_percent}%",
            "미확인 조건": ", ".join(profile.missing_labels) or "없음",
        })

    st.subheader("가격 근거자료")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.subheader("가격조건 구조화")
    st.dataframe(pd.DataFrame(condition_rows), use_container_width=True, hide_index=True)
    st.caption("미확인은 조건이 없다는 뜻이 아니라 현재 공개근거에서 확인하지 못했다는 뜻입니다.")
