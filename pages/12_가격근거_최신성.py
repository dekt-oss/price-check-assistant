from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from purchase_price.collectors.registry import build_collectors
from purchase_price.services.evidence_freshness import evaluate_evidence_freshness
from purchase_price.services.purchase_review import build_purchase_review_input
from purchase_price.services.search import search_all

st.set_page_config(page_title="가격근거 최신성", page_icon="🕒", layout="wide")
st.title("공개가격 근거 최신성 확인")
st.caption(
    "거래일이 있으면 거래일을, 없으면 수집/검증일을 기준으로 근거의 경과일수를 계산합니다. "
    "검토기한은 시장의 절대 규칙이 아니라 이번 검토에서 사용자가 선택하는 정책입니다."
)

with st.form("freshness-review-form"):
    c1, c2 = st.columns(2)
    with c1:
        product_name = st.text_input("제품명", placeholder="예: 약품냉장고")
        manufacturer = st.text_input("제조사", placeholder="예: GMS")
    with c2:
        model_name = st.text_input("모델명", placeholder="예: GMSR-182")
        specification = st.text_input("규격", placeholder="예: 182L")
    c3, c4 = st.columns(2)
    with c3:
        review_window_days = st.selectbox(
            "재검토 기준",
            options=[30, 90, 180, 365],
            index=2,
            format_func=lambda days: f"{days}일 초과 시 재검토 필요",
        )
    with c4:
        as_of_date = st.date_input("판정 기준일", value=date.today())
    submitted = st.form_submit_button("가격근거 최신성 확인", type="primary")

if submitted:
    review_input = build_purchase_review_input(
        product_name=product_name,
        manufacturer=manufacturer,
        model_name=model_name,
        specification=specification,
    )
    if review_input is None:
        st.warning("제품 식별정보를 하나 이상 입력하세요.")
        st.stop()

    run = search_all(review_input.to_product_query(), build_collectors())
    if run.errors:
        st.warning("일부 출처 조회 실패: " + " / ".join(run.errors))
    if not run.results:
        st.info("현재 연결된 공개가격 source에서 최신성을 확인할 근거를 찾지 못했습니다.")
        st.stop()

    rows: list[dict[str, object]] = []
    review_needed = 0
    for evidence in run.results:
        freshness = evaluate_evidence_freshness(
            evidence,
            as_of_date=as_of_date,
            review_window_days=int(review_window_days),
        )
        if freshness.needs_review:
            review_needed += 1
        rows.append(
            {
                "상태": freshness.status.value,
                "출처": evidence.source_name,
                "가격": float(evidence.price),
                "등급": evidence.match_grade.value,
                "Evidence Type": evidence.evidence_type.value,
                "기준일 종류": freshness.basis_kind,
                "근거 기준일": freshness.basis_date.isoformat(),
                "경과일": freshness.age_days,
                "검토기준": f"{freshness.review_window_days}일",
                "현재 비교범위": evidence.comparison_scope.value,
                "근거ID": evidence.source_record_id or "",
                "URL": evidence.source_url or "",
            }
        )

    st.subheader("근거 최신성 결과")
    c1, c2, c3 = st.columns(3)
    c1.metric("확인 근거", f"{len(rows)}건")
    c2.metric("재검토/오류", f"{review_needed}건")
    c3.metric("사용한 검토기준", f"{review_window_days}일")

    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        column_config={"가격": st.column_config.NumberColumn(format="%d")},
    )
    st.info(
        "`재검토 필요`는 가격이 틀렸다는 뜻이 아니라 선택한 검토기한을 넘었다는 뜻입니다. "
        "이 화면은 최신성을 표시할 뿐 MatchGrade·신뢰도·ComparisonScope를 자동 변경하지 않습니다."
    )
else:
    st.info("제품을 입력하고 검토기한을 선택하면 각 공개가격 근거의 나이를 확인할 수 있습니다.")
