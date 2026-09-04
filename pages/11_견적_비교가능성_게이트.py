from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings
from purchase_price.services.quote_comparability import (
    QuoteComparabilityContext,
    evaluate_quote_comparability_candidate,
)
from purchase_price.services.quote_condition_comparison import build_quote_condition_profile
from purchase_price.services.quote_extraction import (
    QuoteExtractionError,
    extract_quote_file,
    parse_quote_decimal,
    quote_item_query,
)
from purchase_price.services.search import search_all

st.set_page_config(page_title="견적 비교가능성 게이트", page_icon="🚦", layout="wide")
st.title("견적가격 비교가능성 안전게이트")
st.caption(
    "외부 가격을 현재 견적과 직접 비교하기 전에 제품동일성·가격근거 의미·수량·단위·상업조건·"
    "기준일을 모두 확인합니다. 통과 결과는 `quote_comparable 후보`일 뿐 기존 근거를 자동 승격하지 않습니다."
)

settings = get_settings()
g2b_enabled = bool((settings.resolved_g2b_service_key or "").strip())

with st.expander("통과 조건", expanded=False):
    st.markdown(
        """
- 제품 동일성: **A 또는 B**
- Evidence Type: 실제 단가 성격의 **direct price**
- 통화: **KRW**
- 현재 범위: `observed_only` 또는 이미 검증된 `quote_comparable`
- 견적단가와 외부단가: 양수
- 견적 수량과 외부근거 수량: **둘 다 명시 + 동일**
- 견적 단위와 외부근거 단위: **둘 다 명시 + 동일 표기**
- VAT·배송·설치·옵션·보증·유지보수: **6축 모두 명시 + 일치**
- 견적 기준일과 외부근거 기준일 존재
- 과거 견적 검토 시 견적일 이후의 외부근거는 사용하지 않음

이 조건을 모두 만족해도 source의 최신성 정책과 추가 검증 전에는 `comparison_scope`를 자동 변경하지 않습니다.
        """
    )

uploaded = st.file_uploader("견적서 업로드", type=["xlsx", "xls", "pdf"])
g2b_lookback_days = st.selectbox(
    "나라장터 검색기간",
    options=[30, 90, 180, 365],
    index=1,
    format_func=lambda days: f"최근 {days}일",
    disabled=not g2b_enabled,
)

if uploaded is None:
    st.info("견적서를 업로드하면 품목별 외부 가격근거의 직접 비교 가능 여부를 점검할 수 있습니다.")
    st.stop()

suffix = Path(uploaded.name).suffix
with tempfile.NamedTemporaryFile(delete=True, suffix=suffix) as tmp:
    tmp.write(uploaded.getbuffer())
    tmp.flush()
    try:
        extraction = extract_quote_file(Path(tmp.name))
    except QuoteExtractionError as exc:
        st.error(str(exc))
        st.stop()

for warning in extraction.warnings:
    st.warning(warning)
if not extraction.items:
    st.info("비교가능성을 점검할 견적 품목을 자동 추출하지 못했습니다.")
    st.stop()

labels = {
    index: f"{index + 1}행 · {item.model_name or item.product_name or '식별정보 미입력'}"
    for index, item in enumerate(extraction.items)
}
selected_index = st.selectbox(
    "점검할 견적 품목",
    options=list(labels),
    format_func=lambda index: labels[index],
)
selected = extraction.items[selected_index]

st.subheader("1. 견적 비교조건 확인")
c1, c2, c3 = st.columns(3)
with c1:
    quote_price_text = st.text_input(
        "견적 단가",
        value=str(selected.unit_price) if selected.unit_price is not None else "",
    )
    quantity_text = st.text_input(
        "견적 수량",
        value=str(selected.quantity) if selected.quantity is not None else "",
    )
with c2:
    unit = st.text_input("견적 단위", value=selected.unit)
    date_confirmed = st.checkbox("견적 기준일 확인됨", value=False)
with c3:
    quote_date_value = st.date_input(
        "견적 기준일",
        value=date.today(),
        disabled=not date_confirmed,
    )

condition_df = pd.DataFrame(
    [
        {
            "VAT": selected.vat_status,
            "배송": selected.delivery_condition,
            "설치": selected.installation_condition,
            "옵션": selected.option_condition,
            "보증": selected.warranty_condition,
            "유지보수": selected.maintenance_condition,
        }
    ]
)
edited_conditions = st.data_editor(
    condition_df,
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
)
st.caption("빈 값은 `해당 없음`이 아니라 미확인입니다. 원문에 근거가 있을 때만 보완하세요.")

if st.button("2. 외부 근거 비교가능성 검사", type="primary", use_container_width=True):
    quote_price = parse_quote_decimal(quote_price_text)
    quantity = parse_quote_decimal(quantity_text)
    condition_row = edited_conditions.iloc[0]
    context = QuoteComparabilityContext(
        quote_unit_price=quote_price,
        quantity=quantity,
        unit=unit,
        quote_date=quote_date_value if date_confirmed else None,
        conditions=build_quote_condition_profile(
            vat=condition_row.get("VAT"),
            delivery=condition_row.get("배송"),
            installation=condition_row.get("설치"),
            options=condition_row.get("옵션"),
            warranty=condition_row.get("보증"),
            maintenance=condition_row.get("유지보수"),
        ),
    )

    run = search_all(
        quote_item_query(selected),
        build_collectors(g2b_lookback_days=int(g2b_lookback_days)),
    )
    if run.errors:
        st.warning("일부 출처 조회 실패: " + " / ".join(run.errors))
    if not run.results:
        st.info("현재 연결된 공개가격 source에서 검사할 근거를 찾지 못했습니다.")
        st.stop()

    result_rows: list[dict[str, object]] = []
    candidates = 0
    for evidence in run.results:
        decision = evaluate_quote_comparability_candidate(context, evidence)
        if decision.eligible_candidate:
            candidates += 1
        result_rows.append(
            {
                "상태": decision.status_label,
                "출처": evidence.source_name,
                "가격": float(evidence.price),
                "등급": evidence.match_grade.value,
                "Evidence Type": evidence.evidence_type.value,
                "현재 비교범위": evidence.comparison_scope.value,
                "외부수량": float(evidence.quantity) if evidence.quantity is not None else None,
                "외부단위": evidence.unit or "미확인",
                "상업조건": decision.condition_comparison.status_label,
                "기준일": (
                    decision.evidence_basis_date.isoformat()
                    if decision.evidence_basis_date is not None
                    else "미확인"
                ),
                "견적일과 일수차": decision.date_gap_days,
                "보류사유": decision.reason_text,
                "근거ID": evidence.source_record_id or "",
                "URL": evidence.source_url or "",
            }
        )

    st.subheader("3. 게이트 결과")
    if candidates:
        st.success(
            f"총 {len(result_rows)}건 중 {candidates}건이 `quote_comparable 후보` 조건을 모두 충족했습니다."
        )
    else:
        st.info(
            "현재 근거 중 모든 필수조건을 충족한 `quote_comparable 후보`가 없습니다. "
            "표의 보류사유를 확인하세요."
        )

    st.dataframe(
        pd.DataFrame(result_rows),
        use_container_width=True,
        hide_index=True,
        column_config={"가격": st.column_config.NumberColumn(format="%d")},
    )
    st.warning(
        "이 화면은 승격 후보를 찾는 안전게이트입니다. 통과했다는 이유만으로 원본 "
        "`CollectedPrice.comparison_scope`를 자동으로 변경하거나 견적 높음/낮음을 판정하지 않습니다."
    )
