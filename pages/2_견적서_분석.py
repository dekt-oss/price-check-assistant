from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path

import pandas as pd
import streamlit as st

from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.device_research_handoff import (
    DEVICE_RESEARCH_HANDOFF_SESSION_KEY,
    QUOTE_REVIEW_ROWS_SESSION_KEY,
    build_device_research_prefill,
)
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
g2b_enabled = bool((settings.resolved_g2b_service_key or "").strip())
mfds_enabled = bool((settings.resolved_mfds_service_key or "").strip())

with st.expander("현재 지원 범위", expanded=False):
    st.write(
        "- `.xlsx`, `.xls`: 품목/제조사/모델/규격/수량/단가/금액 헤더를 찾아 자동 추출합니다.\n"
        "- `.pdf`: 업로드는 가능하지만 아직 자동 추출하지 않습니다.\n"
        "- 추출값은 검색 전에 반드시 화면에서 확인·수정할 수 있습니다.\n"
        "- 모델 동일성과 가격판정 안전게이트는 통합검색과 동일한 규칙을 사용합니다.\n"
        "- 추출 행의 제품명·제조사·모델명·규격만 의료기기 시장조사로 넘길 수 있습니다.\n"
        "- 페이지 이동 중에는 수정한 견적 행을 현재 Streamlit 세션에만 임시 유지합니다."
    )

if not g2b_enabled:
    st.warning(
        "나라장터 서비스키가 설정되지 않아 G2B live 검색이 비활성화되어 있습니다. "
        "Streamlit Secrets에 `G2B_SERVICE_KEY = \"...\"`를 저장하세요. "
        "기존 DATA_GO_KR_SERVICE_KEY가 있으면 하위호환으로 사용합니다."
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


quote_rows: list[dict[str, object]] | None = None

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

    quote_rows = [
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
    st.session_state[QUOTE_REVIEW_ROWS_SESSION_KEY] = quote_rows
else:
    saved_rows = st.session_state.get(QUOTE_REVIEW_ROWS_SESSION_KEY)
    if isinstance(saved_rows, list) and saved_rows:
        quote_rows = saved_rows
        st.info(
            "의료기기 시장조사 페이지에서 돌아온 현재 세션의 견적 행을 복원했습니다. "
            "업로드 원본 파일은 저장하지 않았으며, 새 파일을 업로드하면 새 추출 결과로 교체됩니다."
        )

if quote_rows:
    st.subheader("1. 추출 결과 확인")
    st.caption(
        "자동 추출값은 확정값이 아닙니다. 특히 제조사·모델명·규격과 견적단가를 확인한 뒤 "
        "필요하면 직접 수정하세요."
    )
    edited = st.data_editor(
        pd.DataFrame(quote_rows),
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
    st.session_state[QUOTE_REVIEW_ROWS_SESSION_KEY] = edited.to_dict(orient="records")

    selected_count = int(edited["검색"].fillna(False).sum())
    st.caption(f"외부가격 검색 대상: {selected_count}개")

    st.subheader("2. 의료기기 시장조사 연결")
    st.caption(
        "의료기기로 확인할 행을 하나 선택해 식약처 등록·동일품목 경쟁장비·공급사 조사 화면으로 "
        "넘깁니다. 견적서 표기의 제품명/제조사/모델명은 공식 식약처 identity가 아니므로 이동 후 "
        "반드시 확인·수정합니다. 견적가격·총액·파일정보는 의료기기 조사 화면에 전달하지 않습니다."
    )

    handoff_labels: dict[int, str] = {}
    for index, row in edited.iterrows():
        prefill = build_device_research_prefill(
            product_name=_edited_text(row.get("제품명")),
            manufacturer=_edited_text(row.get("제조사")),
            model_name=_edited_text(row.get("모델명")),
            specification=_edited_text(row.get("규격")),
        )
        if prefill is None:
            continue
        label = prefill.model_name or prefill.product_name or prefill.manufacturer or "식별정보 입력 행"
        handoff_labels[int(index)] = f"{int(index) + 1}행 · {label}"

    if handoff_labels:
        handoff_index = st.selectbox(
            "시장조사할 견적 품목",
            options=list(handoff_labels),
            format_func=lambda index: handoff_labels[index],
        )
        if not mfds_enabled:
            st.warning("식약처 서비스키가 설정되지 않아 의료기기 시장조사 연결이 비활성화됩니다.")

        if st.button(
            "선택 품목 의료기기 시장조사",
            disabled=not mfds_enabled,
            use_container_width=True,
        ):
            selected_row = edited.loc[handoff_index]
            prefill = build_device_research_prefill(
                product_name=_edited_text(selected_row.get("제품명")),
                manufacturer=_edited_text(selected_row.get("제조사")),
                model_name=_edited_text(selected_row.get("모델명")),
                specification=_edited_text(selected_row.get("규격")),
            )
            if prefill is None:
                st.warning("선택 행에 의료기기 시장조사로 넘길 식별정보가 없습니다.")
            else:
                st.session_state[DEVICE_RESEARCH_HANDOFF_SESSION_KEY] = (
                    prefill.to_session_payload()
                )
                st.switch_page("pages/4_의료기기_시장조사.py")
    else:
        st.info("제품명·제조사·모델명·규격 중 하나 이상 입력하면 시장조사로 연결할 수 있습니다.")

    if st.button(
        "3. 선택 품목 외부가격 비교",
        type="primary",
        disabled=selected_count == 0,
    ):
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
                if not run.results and not run.errors:
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

        st.subheader("4. 견적 품목별 비교 결과")
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

        st.subheader("5. 품목별 근거자료")
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
