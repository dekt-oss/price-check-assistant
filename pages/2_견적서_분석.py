from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path

import pandas as pd
import streamlit as st

from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL, SOURCE_NAME
from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings
from purchase_price.services.device_research_handoff import (
    DEVICE_RESEARCH_HANDOFF_SESSION_KEY,
    QUOTE_REVIEW_ROWS_SESSION_KEY,
    build_device_research_prefill,
)
from purchase_price.services.g2b_search_policy import (
    G2B_DEFAULT_LOOKBACK_DAYS,
    G2B_LOOKBACK_OPTIONS,
    g2b_lookback_label,
)
from purchase_price.services.g2b_unmapped_discovery import discover_unmapped_g2b_candidates
from purchase_price.services.pricing import assess_prices
from purchase_price.services.purchase_review import build_purchase_review_input
from purchase_price.services.quote_extraction import (
    QuoteExtractionError,
    extract_quote_file,
    parse_quote_decimal,
)
from purchase_price.services.quote_extraction_diagnostics import (
    diagnose_quote_extraction,
    diagnose_quote_extraction_error,
)
from purchase_price.services.search import search_all

st.set_page_config(page_title="견적서 분석", page_icon="📄", layout="wide")
st.title("견적서 분석")
st.caption(
    "견적서에서 품목을 추출한 뒤 담당자가 내용을 확인·수정하고, 기존 공개가격 검색 엔진으로 "
    "품목별 근거를 조회합니다. 업로드 파일은 임시 영역에서만 처리하며 영구 저장하지 않습니다."
)

settings = get_settings()
g2b_service_key = (settings.resolved_g2b_service_key or "").strip()
g2b_enabled = bool(g2b_service_key)
mfds_enabled = bool((settings.resolved_mfds_service_key or "").strip())

with st.expander("현재 지원 범위", expanded=False):
    st.write(
        "- `.xlsx`, `.xls`: 품목/제조사/모델/규격/수량/단가/금액 헤더를 찾아 자동 추출합니다.\n"
        "- `.pdf`: 텍스트 레이어가 있으면 표 선/셀 구조 → 단어 X/Y 좌표 → 텍스트 fallback 순서로 처리합니다.\n"
        "- 텍스트 레이어가 없는 스캔 PDF만 로컬 Tesseract(kor+eng) OCR을 사용하며, 외부 Vision API로 문서를 전송하지 않습니다.\n"
        "- 로컬 OCR은 자원 보호를 위해 앞 12페이지까지만 처리하며 인식값은 반드시 원문과 대조합니다.\n"
        "- PDF 표는 문서 레이아웃에 따라 열이 어긋날 수 있어 추출값을 반드시 확인·수정합니다.\n"
        "- 모델 동일성과 가격판정 안전게이트는 통합검색과 동일한 규칙을 사용합니다.\n"
        "- verified mapping이 있으면 나라장터 직접가격을 조회합니다. mapping이 없으면 실제 나라장터 후보 탐색을 별도로 수행하되 직접가격으로 자동 승격하지 않습니다.\n"
        "- 추출 행의 제품명·제조사·모델명·규격만 의료기기 시장조사로 넘길 수 있습니다.\n"
        "- 페이지 이동 중에는 수정한 견적 행을 현재 Streamlit 세션에만 임시 유지합니다."
    )

if not g2b_enabled:
    st.warning(
        "나라장터 서비스키가 설정되지 않아 G2B live 검색이 비활성화되어 있습니다. "
        "Streamlit Secrets에 G2B source-specific 또는 DATA_GO_KR_MARKET_SERVICE_KEY를 설정하세요."
    )

uploaded = st.file_uploader("PDF 또는 Excel 견적서", type=["pdf", "xlsx", "xls"])
g2b_lookback_days = st.selectbox(
    "나라장터 검색기간",
    options=G2B_LOOKBACK_OPTIONS,
    index=G2B_LOOKBACK_OPTIONS.index(G2B_DEFAULT_LOOKBACK_DAYS),
    format_func=g2b_lookback_label,
    disabled=not g2b_enabled,
    help=(
        "기본은 최근 1년이며 2·3·5년까지 조회할 수 있습니다. verified mapping이 있는 품목은 "
        "직접가격으로, mapping이 없는 품목은 bounded 후보 탐색으로 조회합니다."
    ),
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
        quote_path = Path(tmp.name)

        try:
            extraction = extract_quote_file(quote_path)
        except QuoteExtractionError as exc:
            diagnostics = diagnose_quote_extraction_error(quote_path, exc)
            st.warning(str(exc))
            st.caption(f"추출 경로 진단: {diagnostics.strategy_label}")
            with st.expander("추출 진단", expanded=False):
                st.json(diagnostics.to_public_dict())
            st.info(
                "Excel과 텍스트 PDF는 구조 파서를 사용하고, 스캔 PDF는 로컬 OCR을 사용합니다. "
                "현재 오류는 OCR 배포 의존성 또는 문서 인식 실패일 수 있습니다. "
                "가능하면 원본 Excel/텍스트 PDF를 우선 사용하고 자동값은 반드시 원문과 대조하세요."
            )
            st.stop()

        diagnostics = diagnose_quote_extraction(quote_path, extraction)

    st.success(f"{uploaded.name}: {len(extraction.items)}개 품목을 자동 추출했습니다.")
    st.caption(
        f"추출 경로: {diagnostics.strategy_label} · 자동 추출 {diagnostics.extracted_item_count}건 · "
        "담당자 원문 대조 필수"
    )
    with st.expander("추출 진단", expanded=False):
        st.json(diagnostics.to_public_dict())
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
                st.session_state[DEVICE_RESEARCH_HANDOFF_SESSION_KEY] = prefill.to_session_payload()
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
        source_status_runs: list[tuple[str, list[dict[str, object]]]] = []
        discovery_runs: list[tuple[str, str, list[dict[str, object]]]] = []
        discovery_count = 0
        max_discovery_items = 10

        with st.spinner("공개 가격근거와 필요한 나라장터 후보를 조회하고 있습니다..."):
            for _, row in edited[edited["검색"].fillna(False)].iterrows():
                quote_unit_price = parse_quote_decimal(row.get("견적단가"))
                review_input = build_purchase_review_input(
                    product_name=row.get("제품명"),
                    manufacturer=row.get("제조사"),
                    model_name=row.get("모델명"),
                    specification=row.get("규격"),
                    quote_unit_price=quote_unit_price,
                )

                if review_input is None:
                    summary_rows.append(
                        {
                            "제품": "식별정보 미입력 품목",
                            "견적단가": float(quote_unit_price) if quote_unit_price is not None else None,
                            "관측근거": 0,
                            "관측가 하단": None,
                            "관측가 상단": None,
                            "신뢰도": "산정불가",
                            "견적 위치": "-",
                            "상태": "제품 식별정보를 입력해야 검색할 수 있음",
                        }
                    )
                    continue

                label = review_input.model_name or review_input.product_name or "식별정보 미입력 품목"
                query = review_input.to_product_query()
                run = search_all(query, collectors)
                assessment = assess_prices(run.results, review_input.quote_unit_price)

                source_rows = [
                    {
                        "출처": source_status.source_name,
                        "상태": source_status.status_label,
                        "건수": source_status.result_count,
                        "메모": source_status.note or source_status.error or "",
                    }
                    for source_status in run.source_statuses
                ]
                source_status_runs.append((label, source_rows))

                skipped_g2b = next(
                    (
                        source_status
                        for source_status in run.source_statuses
                        if source_status.source_name == SOURCE_NAME and source_status.skipped
                    ),
                    None,
                )
                discovery_summary = ""
                if (
                    skipped_g2b is not None
                    and g2b_enabled
                    and query.product_name.strip()
                    and discovery_count < max_discovery_items
                ):
                    discovery_count += 1
                    discovery = discover_unmapped_g2b_candidates(
                        query,
                        service_key=g2b_service_key,
                        lookback_days=int(g2b_lookback_days),
                        base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
                        timeout_seconds=settings.g2b_request_timeout_seconds,
                        max_retries=settings.g2b_max_retries,
                        pages_per_term_window=1,
                    )
                    candidate_rows = [
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
                    discovery_meta = (
                        f"{discovery.status_label} · 검색어 {', '.join(discovery.terms) or '-'} · "
                        f"API {discovery.request_count}회 · 원자료 {discovery.records_seen}건"
                    )
                    if discovery.error_type:
                        discovery_meta += f" · 오류 {discovery.error_type}"
                    discovery_runs.append((label, discovery_meta, candidate_rows))
                    discovery_summary = f" / 나라장터 후보탐색: {discovery.status_label}"
                elif skipped_g2b is not None and discovery_count >= max_discovery_items:
                    discovery_summary = " / 나라장터 후보탐색: 배치 안전상한(10품목)으로 미실행"

                status = assessment.message
                if run.errors:
                    status += " / 일부 수집기 오류: " + " / ".join(run.errors)
                skipped = [source_status for source_status in run.source_statuses if source_status.skipped]
                if skipped:
                    status += " / " + " / ".join(
                        f"{source_status.source_name}: 미검색 ({source_status.note or '안전조건 미충족'})"
                        for source_status in skipped
                    )
                status += discovery_summary
                if not run.results and not run.errors and not skipped:
                    status = "현재 연결된 공개가격 source를 정상 검색했으나 비교근거 0건"

                summary_rows.append(
                    {
                        "제품": label,
                        "견적단가": (
                            float(review_input.quote_unit_price)
                            if review_input.quote_unit_price is not None
                            else None
                        ),
                        "관측근거": assessment.observed_count,
                        "관측가 하단": float(assessment.low) if assessment.low is not None else None,
                        "관측가 상단": float(assessment.high) if assessment.high is not None else None,
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
            "`미검색`은 API 0건이 아니라 verified mapping이 없어 직접가격 API를 실행하지 않았다는 "
            "뜻입니다. 이 경우 별도 나라장터 후보탐색을 수행할 수 있으며 후보는 검증 전 가격판정에 넣지 않습니다."
        )
        st.info(
            "현재 검증된 외부가격 근거는 대부분 `observed_only`입니다. 따라서 견적단가가 입력돼 있어도 "
            "VAT·배송·설치·옵션·보증 등 거래조건이 `quote_comparable`로 검증되지 않으면 "
            "높다/낮다 판정은 보류합니다."
        )

        st.subheader("5. 출처별 검색상태")
        for label, source_rows in source_status_runs:
            with st.expander(f"{label} 출처 상태"):
                if source_rows:
                    st.dataframe(pd.DataFrame(source_rows), use_container_width=True, hide_index=True)
                else:
                    st.write("실행된 공개가격 source가 없습니다.")

        st.subheader("6. 나라장터 미검증 후보")
        if discovery_runs:
            st.caption(
                "verified mapping이 없는 모델에 대해 나라장터를 실제 탐색한 결과입니다. 모델 토큰이 포함된 "
                "후보만 표시하지만 세부품명/identity 검증 전에는 직접가격 범위에 포함하지 않습니다."
            )
            for label, meta, candidate_rows in discovery_runs:
                with st.expander(f"{label} · {meta}", expanded=bool(candidate_rows)):
                    if candidate_rows:
                        st.dataframe(
                            pd.DataFrame(candidate_rows),
                            use_container_width=True,
                            hide_index=True,
                            column_config={"후보가격": st.column_config.NumberColumn(format="%d")},
                        )
                    else:
                        st.write("선택 기간과 탐색어에서 해당 모델 토큰을 포함한 후보를 찾지 못했습니다.")
        else:
            st.write("별도 나라장터 후보탐색이 필요한 품목이 없었습니다.")

        st.subheader("7. 품목별 검증 근거자료")
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
                    st.write("확보된 검증 공개가격 근거가 없습니다.")
