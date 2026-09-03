from decimal import Decimal, InvalidOperation

import pandas as pd
import streamlit as st

from purchase_price.collectors.registry import build_collectors
from purchase_price.schemas import ProductQuery
from purchase_price.services.pricing import assess_prices
from purchase_price.services.search import search_all

st.set_page_config(page_title="통합검색", page_icon="🔎", layout="wide")
st.title("통합검색")
st.caption("현재 공식 제조사 공개가격 source와 개발용 샘플 수집기를 함께 사용합니다. 근거가 없는 가격은 생성하지 않습니다.")

with st.form("search-form"):
    c1, c2 = st.columns(2)
    with c1:
        product_name = st.text_input("제품명", placeholder="예: Patient Monitor / 환자감시장치")
        manufacturer = st.text_input("제조사", placeholder="예: ABC Medical")
    with c2:
        model_name = st.text_input("모델명", placeholder="예: GMSR-182")
        specification = st.text_input("규격", placeholder="예: 182L")
    quote_text = st.text_input("현재 견적 단가 (선택)", placeholder="예: 38500000")
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
    run = search_all(query, build_collectors(include_mock=True))

    if run.errors:
        st.warning("일부 수집기 오류: " + " / ".join(run.errors))

    if not run.results:
        st.error("현재 연결된 공개가격 source에서 비교자료를 찾지 못했습니다. 근거 부족 상태로 처리합니다.")
        st.stop()

    assessment = assess_prices(run.results, quote)
    st.subheader("가격 요약")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("직접 비교자료", f"{assessment.comparable_count}건")
    c2.metric("가격 하단", f"{assessment.low:,.0f}원" if assessment.low is not None else "산정불가")
    c3.metric("가격 상단", f"{assessment.high:,.0f}원" if assessment.high is not None else "산정불가")
    c4.metric("비교 신뢰도", assessment.confidence)

    st.write(assessment.message)

    rows = [
        {
            "출처": x.source_name,
            "가격": float(x.price),
            "등급": x.match_grade.value,
            "자료성격": x.source_type.value,
            "VAT": x.vat_status or "미확인",
            "조건": x.conditions or "",
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
        column_config={"가격": st.column_config.NumberColumn(format="₩%d")},
    )
    st.caption("A·B 등급을 직접 비교자료로 사용하며 C·D는 시장범위 참고, X는 가격비교에서 제외합니다.")
