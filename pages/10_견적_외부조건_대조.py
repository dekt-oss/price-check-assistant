from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings
from purchase_price.services.price_conditions import build_price_condition_profile
from purchase_price.services.quote_condition_comparison import (
    build_quote_condition_profile,
    compare_quote_to_evidence_conditions,
)
from purchase_price.services.quote_extraction import (
    QuoteExtractionError,
    extract_quote_file,
    quote_item_query,
)
from purchase_price.services.search import search_all

st.set_page_config(page_title="견적·외부조건 대조", page_icon="⚖️", layout="wide")
st.title("견적조건 ↔ 외부 가격조건 대조")
st.caption(
    "견적서에 명시된 조건과 외부 가격근거의 조건을 항목별로 `일치 / 충돌 / 미확인`으로 비교합니다. "
    "이 화면은 조건검토 보조이며 자동으로 구매 적정성이나 `quote_comparable`을 확정하지 않습니다."
)

settings = get_settings()
g2b_enabled = bool((settings.resolved_g2b_service_key or "").strip())

uploaded = st.file_uploader("견적서 업로드", type=["xlsx", "xls", "pdf"])
g2b_lookback_days = st.selectbox(
    "나라장터 검색기간",
    options=[30, 90, 180, 365],
    index=1,
    format_func=lambda days: f"최근 {days}일",
    disabled=not g2b_enabled,
)

if uploaded is None:
    st.info("견적서를 업로드하면 품목 하나를 선택해 외부 가격조건과 대조할 수 있습니다.")
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
    st.info("대조할 견적 품목을 자동 추출하지 못했습니다.")
    st.stop()

labels = {
    index: f"{index + 1}행 · {item.model_name or item.product_name or '식별정보 미입력'}"
    for index, item in enumerate(extraction.items)
}
selected_index = st.selectbox(
    "조건을 대조할 품목",
    options=list(labels),
    format_func=lambda index: labels[index],
)
selected = extraction.items[selected_index]

st.subheader("1. 견적서 조건 확인·수정")
quote_condition_rows = pd.DataFrame(
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
    quote_condition_rows,
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
)
st.caption(
    "빈 값은 조건이 없다는 의미가 아니라 견적서에서 자동 확인되지 않았다는 의미입니다. "
    "필요하면 원문을 보고 직접 보완하세요."
)

if st.button("2. 외부 가격조건 대조", type="primary", use_container_width=True):
    row = edited_conditions.iloc[0]
    quote_profile = build_quote_condition_profile(
        vat=row.get("VAT"),
        delivery=row.get("배송"),
        installation=row.get("설치"),
        options=row.get("옵션"),
        warranty=row.get("보증"),
        maintenance=row.get("유지보수"),
    )

    collectors = build_collectors(g2b_lookback_days=int(g2b_lookback_days))
    run = search_all(quote_item_query(selected), collectors)

    if run.errors:
        st.warning("일부 출처 조회 실패: " + " / ".join(run.errors))
    if not run.results:
        st.info("현재 연결된 공개가격 source에서 조건을 대조할 근거를 찾지 못했습니다.")
        st.stop()

    st.subheader("3. 근거별 조건 대조")
    rows: list[dict[str, object]] = []
    detail_rows: list[dict[str, object]] = []
    for evidence in run.results:
        evidence_profile = build_price_condition_profile(evidence)
        comparison = compare_quote_to_evidence_conditions(quote_profile, evidence_profile)
        rows.append(
            {
                "출처": evidence.source_name,
                "가격": float(evidence.price),
                "등급": evidence.match_grade.value,
                "현재 비교범위": evidence.comparison_scope.value,
                "조건대조": comparison.status_label,
                "일치": comparison.match_count,
                "충돌": comparison.conflict_count,
                "미확인": comparison.unknown_count,
                "6축 완전일치": "예" if comparison.fully_aligned else "아니오",
                "거래일": evidence.transaction_date.isoformat() if evidence.transaction_date else "",
                "근거ID": evidence.source_record_id or "",
                "URL": evidence.source_url or "",
            }
        )
        for item in comparison.comparisons:
            detail_rows.append(
                {
                    "출처": evidence.source_name,
                    "조건": item.label,
                    "견적서": item.quote_value,
                    "외부근거": item.evidence_value,
                    "판정": item.status.value,
                }
            )

    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        column_config={"가격": st.column_config.NumberColumn(format="%d")},
    )

    with st.expander("조건별 상세 비교", expanded=False):
        st.dataframe(pd.DataFrame(detail_rows), use_container_width=True, hide_index=True)

    st.warning(
        "`6축 완전일치=예`도 현재는 검토 신호일 뿐입니다. 수량·단위·구성범위·거래시점 등 추가 조건과 "
        "source 신뢰성을 별도 검증하기 전에는 기존 `comparison_scope`를 자동으로 `quote_comparable`로 "
        "변경하지 않습니다."
    )
