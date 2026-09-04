from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path

import pandas as pd
import streamlit as st

from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.pricing import assess_prices
from purchase_price.services.quote_extraction import (
    QuoteExtractionError,
    extract_quote_file,
    parse_quote_decimal,
)
from purchase_price.services.search import search_all

st.set_page_config(page_title="견적서 분석", page_icon="📄", layout="wide")
st.title("견적서 분석")
st.caption(
    "견적서에서 품목을 추출한 뒤 담당자가 내용을 확인·수정하고, 기존 공개가격 검색 엔진으로 "
    "품목별 근거를 조회합니다. 업로드 파일은 임시 영역에서만 처리하며 영구 저장하지 않습니다."
)

settings = get_settings()
g2b_enabled = bool((settings.data_go_kr_service_key or "").strip())

with st.expander("현재 지원 범위", expanded=False):
    st.write(
        "- `.xlsx`, `.xls`: 품목/제조사/모델/규격/수량/단가/금액 헤더를 찾아 자동 추출합니다.\n"
        "- `.pdf`: 업로드는 가능하지만 아직 자동 추출하지 않습니다.\n"
        "- 추출값은 검색 전에 반드시 화면에서 확인·수정할 수 있습니다.\n"
        "- 모델 동일성과 가격판정 안전게이트는 통합검색과 동일한 규칙을 사용합니다."
    )

if not g2b_enabled:
    st.warning(
        "공공데이터포털 서비스키가 설정되지 않아 나라장터 live 검색이 비활성화되어 있습니다. "
        "Streamlit 앱 메뉴(⋮) → Settings → Secrets에 "
        '`DATA_GO_KR_SERVICE_KEY = "..."`를 저장하면 식약처와 나라장터가 함께 활성화됩니다.'
    )

uploaded = st.file_uploader("PDF 또는 Excel 견적서", type=["pdf", "xlsx", "xls"])
g2b_lookback_days = st.selectbox(
    "나라장터 검색기간",
    options=[30, 90, 180, 365],
    index=1,
    format_func=lambda days: f"최근 {days}일",
    disabled=not g2b_enabled,
    help="exact model + verified G2B mapping이 있는 품목만 자동 조회합니다.",
)


def _edited_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _money(value: Decimal | None) -> str:
    return f"{value:,.0f}원" if value is not None else "산정불가"


if uploaded is not None:
    suffix = Path(uploaded.name).suffix
    with tempfile.NamedTemporaryFile(delete=True, suffix=suffix) as tmp:
        tmp.write(uploaded.getbuffer())
        tmp.flush()

        try:
            extraction = extract_quote_file(Path(tmp.name))
        except QuoteExtractionError as exc:
            st.warning(str(exc))
            st.info(
                "Excel `.xlsx/.xls`는 자동 추출합니다. PDF는 텍스트형 문서 추출을 별도 단계로 "
                "추가할 예정이며, 스캔 PDF는 OCR 없이 자동판정하지 않습니다."
            )
            st.stop()

    st.success(f"{uploaded.name}: {len(extraction.items)}개 품목을 자동 추출했습니다.")
    for warning in extraction.warnings:
        st.warning(warning)

    if not extraction.items:
        st.stop()

    rows = [
        {
            "검색": True,
            "제품명": item.product_name,
            "제조사": item.manufacturer,
            "모델명": item.model_name,
            "규격": item.specification,
            "수량": float(item.quantity) if item.quantity is not None else None,
            "견적단가": float(item.unit_price) if item.unit_price is not None else None,
            "총액": float(item.total_amount) if item.total_amount is not None else None,
            "원본시트": item.source_sheet,
            "원본행": item.source_row,
        }
        for item in extraction.items
    ]
    st.subheader("1. 추출 결과 확인")
    st.caption(
        "자동 추출값은 확정값이 아닙니다. 특히 제조사·모델명·규격과 견적단가를 확인한 뒤 "
        "필요하면 직접 수정하세요."
    )
    edited = st.data_editor(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        disabled=["원본시트", "원본행"],
        column_config={
            "검색": st.column_config.CheckboxColumn("검색", default=True),
            "견적단가": st.column_config.NumberColumn("견적단가", format="%d"),
            "총액": st.column_config.NumberColumn("총액", format="%d"),
        },
    )

    selected_count = int(edited["검색"].fillna(False).sum())
    st.caption(f"외부가격 검색 대상: {selected_count}개")

    if st.button("2. 선택 품목 외부가격 비교", type="primary", disabled=selected_count == 0):
        collectors = build_collectors(g2b_lookback_days=int(g2b_lookback_days))
        summary_rows: list[dict[str, object]] = []
        detail_runs: list[tuple[str, list[dict[str, object]]]] = []

        with st.spinner("공개 가격근거를 조회하고 있습니다..."):
            for _, row in edited[edited["검색"].fillna(False)].iterrows():
                product_name = _edited_text(row.get("제품명"))
                manufacturer = _edited_text(row.get("제조사"))
                model_name = _edited_text(row.get("모델명"))
                specification = _edited_text(row.get("규격"))
                quote = parse_quote_decimal(row.get("견적단가"))

                label = model_name or product_name or "식별정보 미입력 품목"
                if not any([product_name, manufacturer, model_name, specification]):
                    summary_rows.append(
                        {
                            "제품": label,
                            "견적단가": float(quote) if quote is not None else None,
                            "관측근거": 0,
                            "관측가 하단": None,
                            "관측가 상단": None,
                            "신뢰도": "산정불가",
                            "견적 위치": "-",
                            "상태": "제품 식별정보를 입력해야 검색할 수 있음",
                        }
                    )
                    continue

                query = ProductQuery(
                    product_name=product_name,
                    manufacturer=manufacturer,
                    model_name=model_name,
                    specification=specification,
                )
                run = search_all(query, collectors)
                assessment = assess_prices(run.results, quote)

                status = assessment.message
                if run.errors:
                    status += " / 일부 수집기 오류: " + " / ".join(run.errors)
                if not run.results:
                    status = "현재 연결된 공개가격 source에서 비교근거를 찾지 못함"

                summary_rows.append(
                    {
                        "제품": label,
                        "견적단가": float(quote) if quote is not None else None,
                        "관측근거": assessment.observed_count,
                        "관측가 하단": (
                            float(assessment.low) if assessment.low is not None else None
                        ),
                        "관측가 상단": (
                            float(assessment.high) if assessment.high is not None else None
                        ),
                        "신뢰도": assessment.confidence,
                        "견적 위치": assessment.quote_position or "판정보류",
                        "상태": status,
                    }
                )

                evidence_rows = [
                    {
                        "출처": item.source_name,
                        "가격": float(item.price),
                        "통화": item.currency,
                        "등급": item.match_grade.value,
                        "비교범위": item.comparison_scope.value,
                        "거래일": item.transaction_date.isoformat() if item.transaction_date else "",
                        "VAT": item.vat_status or "미확인",
                        "조건": item.conditions or "",
                        "근거ID": item.source_record_id or "",
                        "URL": item.source_url or "",
                    }
                    for item in run.results
                ]
                detail_runs.append((label, evidence_rows))

        st.subheader("3. 견적 품목별 비교 결과")
        summary_df = pd.DataFrame(summary_rows)
        st.dataframe(
            summary_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "견적단가": st.column_config.NumberColumn(format="%d"),
                "관측가 하단": st.column_config.NumberColumn(format="%d"),
                "관측가 상단": st.column_config.NumberColumn(format="%d"),
            },
        )
        st.info(
            "현재 외부가격 근거는 대부분 `observed_only`입니다. 따라서 견적단가가 입력돼 있어도 "
            "VAT·배송·설치·옵션·보증 등 거래조건이 `quote_comparable`로 검증되지 않으면 "
            "높다/낮다 판정은 보류합니다."
        )

        st.subheader("4. 품목별 근거자료")
        for label, evidence_rows in detail_runs:
            with st.expander(f"{label} 근거 {len(evidence_rows)}건"):
                if evidence_rows:
                    st.dataframe(
                        pd.DataFrame(evidence_rows),
                        use_container_width=True,
                        hide_index=True,
                        column_config={"가격": st.column_config.NumberColumn(format="%d")},
                    )
                else:
                    st.write("확보된 공개가격 근거가 없습니다.")
