from __future__ import annotations

import pandas as pd
import streamlit as st

from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings
from purchase_price.domain import DIRECT_PRICE_EVIDENCE_TYPES, ComparisonScope, MatchGrade
from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.services.search import search_all

st.set_page_config(page_title="공개가격 수집상태", page_icon="📡", layout="wide")
st.title("공개가격 출처별 수집상태")
st.caption(
    "검색 한 번에 각 공개가격 source가 성공했는지, 정상 0건인지, 실패했는지를 분리하고 "
    "A/B 직접가격 근거와 C/D·기타 참고근거를 따로 확인합니다."
)

settings = get_settings()
g2b_enabled = bool((settings.resolved_g2b_service_key or "").strip())

with st.form("source-status-search"):
    c1, c2 = st.columns(2)
    with c1:
        product_name = st.text_input("제품명", placeholder="예: 약품냉장고")
        manufacturer = st.text_input("제조사", placeholder="예: GMS")
    with c2:
        model_name = st.text_input("모델명", placeholder="예: GMSR-182")
        specification = st.text_input("규격", placeholder="예: 182L")
    g2b_lookback_days = st.selectbox(
        "나라장터 검색기간",
        [30, 90, 180, 365],
        index=1,
        format_func=lambda days: f"최근 {days}일",
        disabled=not g2b_enabled,
    )
    submitted = st.form_submit_button("출처별 수집 실행", type="primary")


def _is_direct_price(item: CollectedPrice) -> bool:
    return (
        item.match_grade in {MatchGrade.A, MatchGrade.B}
        and item.evidence_type in DIRECT_PRICE_EVIDENCE_TYPES
        and item.currency.strip().upper() == "KRW"
        and item.price.is_finite()
        and item.price > 0
        and item.comparison_scope
        in {ComparisonScope.OBSERVED_ONLY, ComparisonScope.QUOTE_COMPARABLE}
    )


def _evidence_row(item: CollectedPrice) -> dict[str, object]:
    return {
        "출처": item.source_name,
        "제품명": item.product_name,
        "모델": item.model_name or "",
        "가격": float(item.price),
        "통화": item.currency,
        "등급": item.match_grade.value,
        "Evidence Type": item.evidence_type.value,
        "비교범위": item.comparison_scope.value,
        "거래일": item.transaction_date.isoformat() if item.transaction_date else "",
        "근거ID": item.source_record_id or "",
        "원문": item.source_url or "",
    }


if submitted:
    query = ProductQuery(
        product_name=product_name.strip(),
        manufacturer=manufacturer.strip(),
        model_name=model_name.strip(),
        specification=specification.strip(),
    )
    if not any((query.product_name, query.manufacturer, query.model_name, query.specification)):
        st.warning("검색조건을 하나 이상 입력하세요.")
        st.stop()

    collectors = build_collectors(g2b_lookback_days=int(g2b_lookback_days))
    run = search_all(query, collectors)

    st.subheader("1. Source 실행상태")
    status_rows = [
        {
            "Source": status.source_name,
            "상태": status.status_label,
            "결과건수": status.result_count,
            "오류": status.error or "",
        }
        for status in run.source_statuses
    ]
    st.dataframe(pd.DataFrame(status_rows), use_container_width=True, hide_index=True)
    st.caption(
        "`성공 · 0건`은 API/collector가 정상 실행됐지만 현재 조건에서 근거가 없다는 뜻입니다. "
        "`실패`는 인증·통신·파싱 등 오류로 검색 자체를 완료하지 못한 상태이므로 서로 합치지 않습니다."
    )

    direct_items = [item for item in run.results if _is_direct_price(item)]
    reference_items = [item for item in run.results if not _is_direct_price(item)]

    c1, c2, c3 = st.columns(3)
    c1.metric("Source", f"{len(run.source_statuses)}개")
    c2.metric("A/B 직접가격 근거", f"{len(direct_items)}건")
    c3.metric("참고/제외 근거", f"{len(reference_items)}건")

    st.subheader("2. A/B 직접가격 근거")
    if direct_items:
        st.dataframe(
            pd.DataFrame([_evidence_row(item) for item in direct_items]),
            use_container_width=True,
            hide_index=True,
            column_config={
                "가격": st.column_config.NumberColumn(format="%d"),
                "원문": st.column_config.LinkColumn("원문"),
            },
        )
    else:
        st.info("현재 검색에서 A/B + 직접가격 Evidence Type 조건을 충족한 근거가 없습니다.")

    st.subheader("3. C/D·기타 참고근거")
    if reference_items:
        st.dataframe(
            pd.DataFrame([_evidence_row(item) for item in reference_items]),
            use_container_width=True,
            hide_index=True,
            column_config={
                "가격": st.column_config.NumberColumn(format="%d"),
                "원문": st.column_config.LinkColumn("원문"),
            },
        )
        st.caption(
            "이 표의 가격은 동일모델 직접 가격범위에 자동 투입되지 않습니다. C/D, 비직접 Evidence Type, "
            "비교범위 제한 등 이유를 등급·Evidence Type·비교범위 열에서 확인하세요."
        )
    else:
        st.info("별도 참고/제외 근거가 없습니다.")
else:
    st.info("검색조건을 입력하면 source별 실행상태와 근거 분류를 표시합니다.")
