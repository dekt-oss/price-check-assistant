from __future__ import annotations

import hashlib
import tempfile
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from purchase_price.services.quote_extraction import QuoteExtractionError, extract_quote_file
from purchase_price.services.quote_extraction_diagnostics import (
    diagnose_quote_extraction,
    diagnose_quote_extraction_error,
)
from purchase_price.services.quote_uat_review import (
    build_redacted_uat_summary,
    compare_review_rows,
    quote_item_to_review_row,
    redacted_uat_summary_json,
)
from purchase_price.services.quote_uat_strategy import (
    UAT_STRATEGY_LABELS,
    default_uat_strategy,
    uat_strategy_options,
)

st.set_page_config(page_title="견적추출 UAT", page_icon="🧪", layout="wide")
st.title("견적추출 UAT")
st.caption(
    "샘플 또는 비식별 처리한 실제 견적을 여러 건 업로드해 자동 추출값과 담당자 원문 대조값을 비교합니다. "
    "업로드 원본과 수정한 정답값은 서버에 영구 저장하지 않으며, 다운로드 결과는 비식별 통계만 포함합니다."
)
st.warning(
    "이 화면은 공개 PoC 검증용입니다. 병원명·담당자·연락처·사업자정보·내부 결재정보 등 식별정보나 "
    "외부 공개가 곤란한 내용을 제거·치환한 견적 사본만 사용하세요. 실제 본원 구매단가 DB나 비공개 계약자료를 "
    "업로드하는 용도가 아닙니다."
)

with st.expander("UAT 운영 원칙", expanded=False):
    st.write(
        "- 최소 5건의 샘플 또는 비식별 실제 견적을 담당자가 원문 대조 완료해야 1차 UAT 표본 목표를 충족합니다.\n"
        "- release gate는 `xlsx`, `xls`, `pdf_text`, `pdf_ocr`, `pdf_commercial` 5개 표본 분류를 모두 요구합니다.\n"
        "- `image_ocr`은 PNG/JPG/JPEG 직접 업로드 경로의 추가 UAT 표본으로 집계하며 기존 5개 release gate를 대체하지 않습니다.\n"
        "- PDF의 텍스트/OCR 분류는 실제 추출 경로로 기본 제안하지만, `pdf_commercial`은 상업조건이 포함된 PDF를 담당자가 원문 대조할 때만 직접 선택합니다.\n"
        "- `pdf_commercial`은 배송·설치·옵션·보증·유지보수·기타조건 중 최소 1개를 정답표에서 실제 원문 기준으로 확인해야 release gate 표본으로 인정됩니다.\n"
        "- 자동 추출값을 그대로 정답으로 간주하지 않습니다. 원문을 보고 수정한 뒤 `원문 대조 완료`를 체크하세요.\n"
        "- 품목이 누락됐으면 정답표에 행을 추가하고, 잘못 추출된 품목은 정답표에서 삭제하세요.\n"
        "- 품목 FP는 원문에 없는데 추출된 품목, FN은 원문에는 있는데 누락된 품목입니다.\n"
        "- 한 품목의 추가/누락이 뒤 행 전체의 필드 오류로 번지지 않도록 순서를 보존해 행을 정렬한 뒤 필드 정확도를 계산합니다.\n"
        "- 이 화면의 통계는 parser 성능 측정용이며 가격 적정성 판정이나 `QUOTE_COMPARABLE` 승인과 무관합니다.\n"
        "- 텍스트 레이어가 없는 스캔 PDF와 PNG/JPG/JPEG는 로컬 Tesseract(kor+eng) OCR을 사용합니다.\n"
        "- PDF OCR은 앞 12페이지까지만 처리하며, 외부 Vision API로 견적 원문을 전송하지 않습니다."
    )

uploaded_files = st.file_uploader(
    "UAT 견적 파일",
    type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"],
    accept_multiple_files=True,
    help="PDF · Excel · PNG/JPG/JPEG를 지원합니다. 가능하면 서로 다른 업체/양식의 샘플 또는 비식별 견적을 5건 이상 선택하세요.",
)

_UI_COLUMNS = {
    "product_name": "제품명",
    "manufacturer": "제조사",
    "model_name": "모델명",
    "specification": "규격",
    "quantity": "수량",
    "unit": "단위",
    "unit_price": "단가",
    "total_amount": "총액",
    "vat_status": "VAT",
    "delivery_condition": "배송",
    "installation_condition": "설치",
    "option_condition": "옵션",
    "warranty_condition": "보증",
    "maintenance_condition": "유지보수",
    "other_conditions": "기타조건",
}
_REVERSE_UI_COLUMNS = {label: field for field, label in _UI_COLUMNS.items()}


def _review_frame(items: tuple[object, ...]) -> pd.DataFrame:
    rows = [quote_item_to_review_row(item) for item in items]
    if not rows:
        rows = [{field: None for field in _UI_COLUMNS}]
    return pd.DataFrame(rows).rename(columns=_UI_COLUMNS)


def _expected_rows(frame: pd.DataFrame) -> list[dict[str, object]]:
    normalized = frame.rename(columns=_REVERSE_UI_COLUMNS)
    rows: list[dict[str, object]] = []
    for row in normalized.to_dict(orient="records"):
        if not any(pd.notna(value) and str(value).strip() for value in row.values()):
            continue
        rows.append(row)
    return rows


def _rate_text(value: object) -> str:
    return "N/A" if value is None else f"{float(value):.1%}"


def _seconds_text(value: object) -> str:
    return "N/A" if value is None else f"{float(value):.2f}초"


confirmed_metrics = []

for case_index, uploaded in enumerate(uploaded_files or (), start=1):
    case_id = f"UAT-{case_index:03d}"
    payload = uploaded.getvalue()
    fingerprint = hashlib.sha256(payload).hexdigest()[:12]
    case_key = f"{case_index}_{fingerprint}"
    suffix = Path(uploaded.name).suffix.casefold()

    extraction_error: QuoteExtractionError | None = None
    extraction_started = time.perf_counter()
    with tempfile.NamedTemporaryFile(delete=True, suffix=suffix) as tmp:
        tmp.write(payload)
        tmp.flush()
        path = Path(tmp.name)
        try:
            extraction = extract_quote_file(path)
            diagnostics = diagnose_quote_extraction(path, extraction)
            actual_items = extraction.items
            warnings = extraction.warnings
        except QuoteExtractionError as exc:
            extraction_error = exc
            diagnostics = diagnose_quote_extraction_error(path, exc)
            actual_items = ()
            warnings = (str(exc),)
    processing_seconds = time.perf_counter() - extraction_started

    with st.expander(
        f"{case_id} · {uploaded.name} · {diagnostics.strategy_label}",
        expanded=case_index == 1,
    ):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("자동 추출 품목", len(actual_items))
        c2.metric("경고", len(warnings))
        c3.metric("추출 경로", diagnostics.strategy_label)
        c4.metric("parser 처리시간", _seconds_text(processing_seconds))

        strategy_values = tuple(strategy.value for strategy in diagnostics.strategies)
        strategy_options = uat_strategy_options(file_kind=diagnostics.file_kind)
        suggested_strategy = default_uat_strategy(
            file_kind=diagnostics.file_kind,
            extraction_strategies=strategy_values,
        )
        uat_strategy = st.selectbox(
            "UAT 표본 분류",
            options=strategy_options,
            index=strategy_options.index(suggested_strategy),
            format_func=lambda value: f"{UAT_STRATEGY_LABELS[value]} · {value}",
            key=f"quote_uat_strategy_{case_key}",
            disabled=len(strategy_options) == 1,
            help=(
                "release gate 집계에는 이 canonical 분류가 사용됩니다. 실제 parser 추출 경로는 위에 별도로 표시됩니다. "
                "pdf_commercial은 배송·설치·옵션·보증·유지보수 등 상업조건을 포함한 PDF를 원문 대조하는 표본에만 선택하세요."
            ),
        )
        if uat_strategy == "pdf_commercial":
            st.info(
                "`pdf_commercial`은 자동 추론하지 않습니다. 상업조건이 포함된 PDF를 담당자가 원문과 대조하고, "
                "배송·설치·옵션·보증·유지보수·기타조건 중 최소 1개를 정답표에 확인해야 표본으로 인정됩니다."
            )

        if extraction_error is not None:
            st.error(str(extraction_error))
        for warning in warnings:
            if extraction_error is None:
                st.warning(warning)

        st.markdown("**자동 추출값**")
        auto_frame = _review_frame(actual_items)
        if actual_items:
            st.dataframe(auto_frame, use_container_width=True, hide_index=True)
        else:
            st.info("자동 추출 품목이 없습니다. 아래 정답표에 원문 기준 품목을 직접 추가하세요.")

        st.markdown("**담당자 원문 대조 정답표**")
        st.caption(
            "원문을 직접 확인해 수정하세요. 누락 품목은 행 추가, 오인 품목은 행 삭제가 가능합니다. "
            "빈 값은 해당 필드 정확도 계산에서 제외됩니다. 배송·설치·옵션·보증·유지보수·기타조건도 원문에 "
            "명시된 경우 그대로 대조하세요."
        )
        reviewed = st.data_editor(
            auto_frame,
            key=f"quote_uat_editor_{case_key}",
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            column_config={
                "수량": st.column_config.NumberColumn(format="%.4f"),
                "단가": st.column_config.NumberColumn(format="%.0f"),
                "총액": st.column_config.NumberColumn(format="%.0f"),
            },
        )
        expected_rows = _expected_rows(reviewed)

        review_seconds_input = st.number_input(
            "담당자 원문 대조 소요시간(초, 선택)",
            min_value=0.0,
            value=0.0,
            step=10.0,
            key=f"quote_uat_review_seconds_{case_key}",
            help="수작업 대비 시간절감 측정용입니다. 측정하지 않았으면 0으로 두세요.",
        )
        review_seconds = float(review_seconds_input) if review_seconds_input > 0 else None

        confirmed = st.checkbox(
            "원문 대조 완료 — 이 케이스를 UAT 통계에 포함",
            key=f"quote_uat_confirmed_{case_key}",
        )
        if confirmed:
            metric = compare_review_rows(
                case_id=case_id,
                strategy=uat_strategy,
                actual_items=actual_items,
                expected_rows=expected_rows,
                extraction_failed=extraction_error is not None,
                processing_seconds=processing_seconds,
                review_seconds=review_seconds,
            )
            confirmed_metrics.append(metric)
            m1, m2, m3, m4, m5, m6 = st.columns(6)
            m1.metric("품목 precision", _rate_text(metric.item_precision))
            m2.metric("품목 recall", _rate_text(metric.item_recall))
            m3.metric("오인 품목 FP", metric.false_positive_item_count)
            m4.metric("누락 품목 FN", metric.false_negative_item_count)
            m5.metric("필드 오류", metric.field_errors)
            m6.metric("상업조건 채점", metric.commercial_scored_fields)
            st.caption(f"parser 처리시간: {_seconds_text(metric.processing_seconds)}")
            if uat_strategy == "pdf_commercial" and metric.commercial_scored_fields == 0:
                st.warning(
                    "이 케이스는 `pdf_commercial`로 선택됐지만 채점된 상업조건 ground truth가 없습니다. "
                    "release gate의 commercial 표본으로 인정되지 않습니다."
                )
            if metric.status == "PASS":
                st.success("현재 ground truth 기준으로 품목 대응과 평가 필드가 모두 일치합니다.")
            elif metric.extraction_failed:
                st.error("추출 자체가 실패했습니다. 실패 원인과 원문 유형을 함께 기록하세요.")
            else:
                fields = ", ".join(metric.error_fields) or "필드 오류 없음"
                st.warning(
                    "검토 필요: "
                    f"FP {metric.false_positive_item_count} / FN {metric.false_negative_item_count} / "
                    f"필드 오류 {fields}"
                )

st.divider()
st.subheader("UAT 집계")
summary = build_redacted_uat_summary(confirmed_metrics, minimum_cases=5)

s1, s2, s3, s4, s5, s6 = st.columns(6)
s1.metric("원문 대조 완료", summary["total_confirmed_cases"])
s2.metric("추출 실패", summary["extraction_failures"])
s3.metric("품목 precision", _rate_text(summary["item_precision"]))
s4.metric("품목 recall", _rate_text(summary["item_recall"]))
s5.metric("전체 필드 오류율", _rate_text(summary["field_error_rate"]))
s6.metric("상업조건 채점", summary["commercial_scored_fields"])

f1, f2, f3 = st.columns(3)
f1.metric("오인 품목 FP", summary["false_positive_items"])
f2.metric("누락 품목 FN", summary["false_negative_items"])
f3.metric("평균 원문대조 시간", _seconds_text(summary["average_review_seconds"]))
st.caption(f"평균 parser 처리시간: {_seconds_text(summary['average_processing_seconds'])}")

if summary["minimum_case_target_met"]:
    st.success("샘플 또는 비식별 실제 견적 최소 5건 UAT 표본 목표를 충족했습니다.")
else:
    remaining = 5 - int(summary["total_confirmed_cases"])
    st.info(f"1차 UAT 표본 목표까지 원문 대조 완료 견적 {remaining}건이 더 필요합니다.")

release_gate = summary["release_gate"]
covered = ", ".join(release_gate["covered_strategies"]) or "없음"
missing = ", ".join(release_gate["missing_strategies"]) or "없음"
st.caption(f"release gate 표본 분류 · 충족: {covered} · 미충족: {missing}")
if release_gate["release_ready"]:
    st.success("견적추출 UAT release gate를 충족했습니다.")
else:
    blockers = " / ".join(release_gate["blockers"]) or "미확인"
    st.warning(f"견적추출 UAT release gate 미충족: {blockers}")

if confirmed_metrics:
    st.markdown("**케이스별 비식별 결과**")
    st.dataframe(
        pd.DataFrame(metric.to_redacted_dict() for metric in confirmed_metrics),
        use_container_width=True,
        hide_index=True,
    )

    strategy_metrics = summary["strategy_metrics"]
    if strategy_metrics:
        st.markdown("**UAT 표본 분류별 집계**")
        strategy_frame = pd.DataFrame.from_dict(strategy_metrics, orient="index").reset_index()
        strategy_frame = strategy_frame.rename(columns={"index": "strategy"})
        st.dataframe(strategy_frame, use_container_width=True, hide_index=True)

    st.download_button(
        "비식별 UAT 결과 JSON 다운로드",
        data=redacted_uat_summary_json(confirmed_metrics, minimum_cases=5),
        file_name="quote-extraction-uat-redacted.json",
        mime="application/json",
    )

st.caption(
    "UAT 결과 파일에는 실제 파일명·견적 원문·제품/업체 식별값·규격·가격·배송·설치·옵션·보증·유지보수·기타조건의 "
    "실제 값을 포함하지 않습니다. 자동 추출값 및 수정값은 현재 Streamlit 세션에서만 사용합니다."
)