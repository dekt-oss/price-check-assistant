from decimal import Decimal, InvalidOperation

import pandas as pd
import streamlit as st

from purchase_price.collectors.registry import build_collectors
from purchase_price.schemas import ProductQuery
from purchase_price.services.pricing import assess_prices
from purchase_price.services.search import search_all

st.set_page_config(page_title="통합검색", page_icon="🔎", layout="wide")
st.title("통합검색")
st.caption(
    "현재 공식 제조사 공개가격 source를 사용합니다. 개발용 mock 가격은 기본 비활성화되어 있으며, "
    "근거가 없는 가격은 생성하지 않습니다."
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
    submitted = st.form_submit_button("가격자료 검색", type="primary")

if submitted:
    if not any([product_name, manufacturer, model_name, specification]):
        st.warning("검색조건을 하나 이상 입력하세요.")
        st.stop()

    quote = None
    if quote_text.strip():
        try:
            quote = Decimal(quote_text.replace(",", "").strip())
        except InvalidOperation:
            st.error("견적 단가는 숫자로 입력하세요.")
            st.stop()

    query = ProductQuery(
        product_name=product_name,
        manufacturer=manufacturer,
        model_name=model_name,
        specification=specification,
    )
    run = search_all(query, build_collectors())

    if run.errors:
        st.warning("일부 수집기 오류: " + " / ".join(run.errors))

    if not run.results:
        st.error(
            "현재 연결된 공개가격 source에서 비교자료를 찾지 못했습니다. "
            "비교근거 부족 상태로 처리합니다."
        )
        st.stop()

    assessment = assess_prices(run.results, quote)
    st.subheader("가격 요약")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("관측 직접근거", f"{assessment.observed_count}건")
    c2.metric("관측가 하단", f"{assessment.low:,.0f}원" if assessment.low is not None else "산정불가")
    c3.metric("관측가 상단", f"{assessment.high:,.0f}원" if assessment.high is not None else "산정불가")
    c4.metric("독립 출처", f"{assessment.source_count}개")
    c5.metric("근거 신뢰도", assessment.confidence)

    st.write(assessment.message)
    if quote is not None:
        if assessment.quote_position is None:
            st.info(
                "입력 견적과의 높고 낮음 비교는 보류했습니다. "
                "현재 근거의 VAT·단위·배송·설치·옵션·보증 등 거래조건이 "
                "`quote_comparable`로 검증되지 않았습니다."
            )
        else:
            st.success(f"견적 위치: {assessment.quote_position}")

    rows = [
        {
            "출처": x.source_name,
            "가격": float(x.price),
            "통화": x.currency,
            "등급": x.match_grade.value,
            "Evidence Type": x.evidence_type.value,
            "비교범위": x.comparison_scope.value,
            "자료성격": x.source_type.value,
            "VAT": x.vat_status or "미확인",
            "조건": x.conditions or "",
            "비교메모": x.comparison_note or "",
            "수집일": x.collected_at.isoformat(),
            "URL": x.source_url or "",
        }
        for x in run.results
    ]
    df = pd.DataFrame(rows)
    st.subheader("가격 근거자료")
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={"가격": st.column_config.NumberColumn(format="%d")},
    )
    st.caption(
        "관측 직접근거는 A·B 제품 동일성 + 직접가격 Evidence Type + KRW를 모두 만족해야 합니다. "
        "현재 견적의 높고 낮음 판정은 그중 거래조건까지 명시적으로 `quote_comparable`로 "
        "검증된 근거에만 허용합니다."
    )
