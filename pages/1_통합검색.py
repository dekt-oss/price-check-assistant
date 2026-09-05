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
            "기본은 최근 1년이며 2·3·5년까지 조회할 수 있습니다. verified mapping이 있는 품목의 "
            "직접가격은 완전수집을 시도하고, mapping이 없는 품목은 bounded 후보 탐색을 수행합니다."
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

    query = review_input.to_product_query()
    run = search_all(
        query,
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

    skipped_g2b = next(
        (
            status
            for status in run.source_statuses
            if status.source_name == SOURCE_NAME and status.skipped
        ),
        None,
    )
    discovery = None
    if (
        skipped_g2b is not None
        and g2b_enabled
        and query.product_name.strip()
        and (settings.resolved_g2b_service_key or "").strip()
    ):
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
        st.caption(
            "이 표는 verified mapping이 없는 모델을 위해 나라장터를 실제로 탐색한 결과입니다. "
            "모델 토큰이 포함된 후보만 보여주지만 세부품명 mapping이 검증되기 전에는 가격범위·견적판정에 넣지 않습니다."
        )
        st.write(
            f"상태: **{discovery.status_label}** · 검색어: {', '.join(discovery.terms) or '-'} · "
            f"API 요청 {discovery.request_count}회 · 원자료 확인 {discovery.records_seen}건"
        )
        if discovery.status == "failure":
            st.warning(f"나라장터 후보 탐색 실패: {discovery.error_type or 'unknown error'}")
        elif discovery.candidates:
            discovery_rows = [
                {
                    "거래일": (
                        candidate.transaction_date.isoformat()
                        if candidate.transaction_date is not None
                        else ""
                    ),
                    "나라장터 표기": candidate.title,
                    "세부품명": candidate.classification_name,
                    "세부품명코드": candidate.classification_code,
                    "후보가격": float(candidate.price),
                    "근거ID": candidate.source_record_id,
                }
                for candidate in discovery.candidates
            ]
            st.dataframe(
                pd.DataFrame(discovery_rows),
                use_container_width=True,
                hide_index=True,
                column_config={"후보가격": st.column_config.NumberColumn(format="%d")},
            )
            st.warning(
                "위 후보가격은 나라장터에서 실제 관측됐지만 아직 `미검증 후보`입니다. 세부품명/제품 identity를 "
                "검증하기 전에는 A/B 직접가격이나 적정가격 범위로 사용하지 않습니다."
            )
        else:
            st.info("선택 기간과 탐색어에서 입력 모델 토큰이 포함된 나라장터 후보를 찾지 못했습니다.")

    skipped_sources = [status for status in run.source_statuses if status.skipped]
    if skipped_sources:
        st.info(
            "`미검색`은 API를 실행했는데 0건이라는 뜻이 아닙니다. 직접가격 검색 안전조건이 충족되지 "
            "않은 상태이며, 가능한 경우 위 별도 후보 탐색으로 실제 나라장터 존재 여부를 확인합니다."
        )

    if not run.results:
        st.error(
            "검증된 직접 비교가격은 확보하지 못했습니다. 위 출처별 상태와 나라장터 미검증 후보를 "
            "구분해서 확인하세요. 후보가 있어도 검증 전에는 견적의 높고 낮음을 자동 판정하지 않습니다."
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
