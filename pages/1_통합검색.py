from decimal import Decimal, InvalidOperation

import pandas as pd
import streamlit as st

from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings
from purchase_price.services.g2b_search_policy import (
    G2B_DEFAULT_LOOKBACK_DAYS,
    G2B_LOOKBACK_OPTIONS,
    g2b_lookback_label,
)
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
        "공식 제조사 공개가격과 검증된 나라장터 세부품명 mapping의 구매실적을 함께 검색합니다. "
        "나라장터 직접가격은 exact model + verified mapping에서만 자동 조회하며, mapping이 없으면 "
        "0건으로 숨기지 않고 `미검색`으로 표시합니다."
    )
else:
    st.caption(
        "현재 공식 제조사 공개가격 source를 사용합니다. 나라장터 검색은 G2B_SERVICE_KEY, "
        "DATA_GO_KR_MARKET_SERVICE_KEY 또는 하위호환 DATA_GO_KR_SERVICE_KEY가 설정된 환경에서 활성화됩니다."
    )

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
        help=(
            "기본은 최근 1년이며 2·3·5년까지 조회할 수 있습니다. 검증된 exact model mapping이 "
            "있는 품목의 직접가격만 자동 조회합니다. 거래량이 많아 page cap을 넘으면 날짜구간을 "
            "자동 분할해 완전수집을 시도합니다."
        ),
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

    run = search_all(
        review_input.to_product_query(),
        build_collectors(g2b_lookback_days=int(g2b_lookback_days)),
    )

    st.subheader("출처별 검색상태")
    source_rows = [
        {
            "출처": status.source_name,
            "상태": status.status_label,
            "건수": status.result_count,
            "메모": status.note or status.error or "",
        }
        for status in run.source_statuses
    ]
    if source_rows:
        st.dataframe(pd.DataFrame(source_rows), use_container_width=True, hide_index=True)

    if run.errors:
        st.warning("일부 수집기 오류: " + " / ".join(run.errors))

    skipped_sources = [status for status in run.source_statuses if status.skipped]
    if skipped_sources:
        st.info(
            "`미검색`은 API를 실행했는데 0건이라는 뜻이 아닙니다. 안전한 직접가격 조회에 필요한 "
            "검증된 세부품명 mapping이 없어 해당 API 호출 자체를 보류한 상태입니다."
        )

    if not run.results:
        st.error(
            "현재 연결된 공개가격 source에서 비교자료를 확보하지 못했습니다. 위 출처별 상태에서 "
            "`미검색`, `성공 · 0건`, `실패`를 구분해 확인하세요."
        )
        st.stop()

    assessment = assess_prices(run.results, review_input.quote_unit_price)
    profiles = [build_price_condition_profile(item) for item in run.results]
    condition_average = round(
        sum(profile.completeness_percent for profile in profiles) / len(profiles)
    )

    st.subheader("가격 요약")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("관측 직접근거", f"{assessment.observed_count}건")
    c2.metric("관측가 하단", f"{assessment.low:,.0f}원" if assessment.low is not None else "산정불가")
    c3.metric("관측가 상단", f"{assessment.high:,.0f}원" if assessment.high is not None else "산정불가")
    c4.metric("독립 출처", f"{assessment.source_count}개")
    c5.metric("근거 신뢰도", assessment.confidence)
    c6.metric("평균 조건명시", f"{condition_average}%")

    st.write(assessment.message)
    if review_input.quote_unit_price is not None:
        if assessment.quote_position is None:
            st.info(
                "입력 견적과의 높고 낮음 비교는 보류했습니다. 아래 `가격조건 구조화`에서 "
                "VAT·수량/단위·배송·설치·옵션·보증·유지보수·기준일 중 빠진 조건을 확인할 수 있습니다. "
                "조건이 많이 채워져도 별도 검증 없이 자동으로 `quote_comparable`로 승격하지 않습니다."
            )
        else:
            st.success(f"견적 위치: {assessment.quote_position}")

    rows = []
    condition_rows = []
    for item, profile in zip(run.results, profiles, strict=True):
        rows.append(
            {
                "출처": item.source_name,
                "가격": float(item.price),
                "통화": item.currency,
                "등급": item.match_grade.value,
                "Evidence Type": item.evidence_type.value,
                "비교범위": item.comparison_scope.value,
                "자료성격": item.source_type.value,
                "거래일": item.transaction_date.isoformat() if item.transaction_date else "",
                "VAT": profile.vat,
                "수량·단위": profile.quantity_unit,
                "조건명시": f"{profile.completeness_percent}%",
                "조건": item.conditions or "",
                "비교메모": item.comparison_note or "",
                "근거ID": item.source_record_id or "",
                "수집일": item.collected_at.isoformat(),
                "URL": item.source_url or "",
            }
        )
        condition_rows.append(
            {
                "출처": item.source_name,
                "근거ID": item.source_record_id or "",
                "VAT": profile.vat,
                "수량·단위": profile.quantity_unit,
                "배송": profile.delivery,
                "설치": profile.installation,
                "옵션/부속": profile.options,
                "보증": profile.warranty,
                "유지보수": profile.maintenance,
                "거래/기준일": profile.basis_date,
                "명시율": f"{profile.completeness_percent}%",
                "미확인 조건": ", ".join(profile.missing_labels) or "없음",
            }
        )

    st.subheader("가격 근거자료")
    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        column_config={"가격": st.column_config.NumberColumn(format="%d")},
    )

    st.subheader("가격조건 구조화")
    st.dataframe(
        pd.DataFrame(condition_rows),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "`미확인`은 조건이 없다는 뜻이 아니라 현재 공개근거에서 확인하지 못했다는 뜻입니다. "
        "구조화는 원문에 명시된 조건만 사용하며 배송·설치·옵션·보증을 추정하지 않습니다."
    )

    st.caption(
        "관측 직접근거는 A·B 제품 동일성 + 직접가격 Evidence Type + KRW를 모두 만족해야 합니다. "
        "현재 견적의 높고 낮음 판정은 거래조건까지 명시적으로 `quote_comparable`로 검증된 근거에만 허용합니다."
    )
