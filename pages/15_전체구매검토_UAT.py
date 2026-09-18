from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from purchase_price.scripts.summarize_real_quote_uat import (
    render_summary_markdown,
    summarize_real_uat,
)
from purchase_price.services.real_quote_uat_entry import (
    CORRECTNESS_OPTIONS,
    ERROR_SIGNAL_OPTIONS,
    EVIDENCE_OPTIONS,
    SAMPLE_CLASSES,
    TRACE_OPTIONS,
    completeness,
    default_entry_rows,
    normalize_entry_rows,
    render_review_csv,
)

st.set_page_config(page_title="전체 구매검토 UAT", page_icon="📊", layout="wide")
st.title("전체 구매검토 UAT")
st.caption(
    "실제 구매검토를 수행한 뒤 제품식별·비교판정·직접가격 근거·추적성·시간절감만 비식별 형태로 기록합니다. "
    "견적 원문, 업체명, 제품명, 모델명, 단가, 병원 내부정보는 입력하지 않습니다."
)

st.info(
    "권장 사용법: 다른 탭에서 통합 검색/견적 검토를 실제로 수행한 뒤 이 화면에는 결과 지표만 기록하세요. "
    "최소 5건부터 시작하고, 서로 다른 Excel·PDF·OCR·검색 사례를 섞어 보는 것이 좋습니다."
)

with st.expander("항목 의미", expanded=False):
    st.markdown(
        """
- **제품식별 FP**: 다른 제품인데 동일제품으로 잘못 판단한 경우
- **제품식별 FN**: 실제 동일제품인데 보수적으로 놓친 경우
- **비교판정 FP**: 비교 불가능한 조건인데 직접비교 가능으로 잘못 승인된 경우
- **비교판정 FN**: 실제 비교 가능한데 보류된 경우
- **0건/실패 구분**: API 정상 0건과 API 오류가 화면에서 정확히 구분됐는지
- **직접가격 근거**: A/B 직접가격 근거를 실제로 확보했는지
- **근거ID/URL/Fingerprint 추적**: 나중에 같은 공개근거를 다시 확인할 수 있는지
- **수작업 분 / 시스템 분**: 동일 검토를 수작업으로 했을 때와 시스템 사용 시 소요시간
- **재사용가치**: 실제 업무에서 다시 사용할 의향·효용을 1~5로 평가

미평가는 실패나 성공으로 계산하지 않습니다. FP/FN을 하나의 accuracy 숫자로 합치지 않습니다.
        """.strip()
    )

if "real_quote_uat_rows" not in st.session_state:
    st.session_state["real_quote_uat_rows"] = pd.DataFrame(default_entry_rows(5))

edited = st.data_editor(
    st.session_state["real_quote_uat_rows"],
    key="real_quote_uat_editor",
    use_container_width=True,
    hide_index=True,
    num_rows="dynamic",
    column_config={
        "검토완료": st.column_config.CheckboxColumn(
            "검토완료",
            help="원문/공개근거 대조까지 끝난 케이스만 체크하세요.",
            default=False,
        ),
        "케이스ID": st.column_config.TextColumn(
            "케이스ID",
            help="실제 파일명 대신 REAL-001 같은 비식별 ID를 사용하세요.",
        ),
        "표본유형": st.column_config.SelectboxColumn(
            "표본유형",
            options=list(SAMPLE_CLASSES),
            required=True,
        ),
        "공개사용승인": st.column_config.CheckboxColumn(
            "공개사용승인",
            help="공개 저장 가능한 표본인지 여부입니다. 실제 내부 견적이면 보통 체크하지 않습니다.",
            default=False,
        ),
        "제품식별 FP": st.column_config.SelectboxColumn(
            "제품식별 FP", options=list(ERROR_SIGNAL_OPTIONS), required=True
        ),
        "제품식별 FN": st.column_config.SelectboxColumn(
            "제품식별 FN", options=list(ERROR_SIGNAL_OPTIONS), required=True
        ),
        "비교판정 FP": st.column_config.SelectboxColumn(
            "비교판정 FP", options=list(ERROR_SIGNAL_OPTIONS), required=True
        ),
        "비교판정 FN": st.column_config.SelectboxColumn(
            "비교판정 FN", options=list(ERROR_SIGNAL_OPTIONS), required=True
        ),
        "0건/실패 구분": st.column_config.SelectboxColumn(
            "0건/실패 구분", options=list(CORRECTNESS_OPTIONS), required=True
        ),
        "직접가격 근거": st.column_config.SelectboxColumn(
            "직접가격 근거", options=list(EVIDENCE_OPTIONS), required=True
        ),
        "근거ID 추적": st.column_config.SelectboxColumn(
            "근거ID 추적", options=list(TRACE_OPTIONS), required=True
        ),
        "원문URL 추적": st.column_config.SelectboxColumn(
            "원문URL 추적", options=list(TRACE_OPTIONS), required=True
        ),
        "Fingerprint 추적": st.column_config.SelectboxColumn(
            "Fingerprint 추적", options=list(TRACE_OPTIONS), required=True
        ),
        "수작업 분": st.column_config.NumberColumn(
            "수작업 분", min_value=0.0, step=1.0, format="%.1f"
        ),
        "시스템 분": st.column_config.NumberColumn(
            "시스템 분", min_value=0.0, step=1.0, format="%.1f"
        ),
        "재사용가치(1~5)": st.column_config.NumberColumn(
            "재사용가치(1~5)", min_value=1, max_value=5, step=1, format="%d"
        ),
        "검토메모": st.column_config.TextColumn(
            "검토메모",
            help="오류 원인/보류 이유를 비식별 형태로 짧게 남기세요.",
        ),
    },
)

st.session_state["real_quote_uat_rows"] = edited

try:
    reviewed_rows = normalize_entry_rows(edited.to_dict(orient="records"))
except ValueError as exc:
    st.error(f"UAT 입력 오류: {exc}")
    reviewed_rows = []

st.divider()
st.subheader("실제 구매검토 UAT 집계")

if not reviewed_rows:
    st.info("검토완료가 체크된 케이스가 아직 없습니다.")
else:
    summary = summarize_real_uat(reviewed_rows)
    completion = completeness(reviewed_rows)

    row1 = st.columns(6)
    row1[0].metric("검토완료 표본", summary["sample_count"])
    row1[1].metric("Critical FP", summary["critical_false_positive_count"])
    row1[2].metric("Critical 오류", summary["critical_error_count"])
    direct_rate = summary["direct_evidence_hit_rate_percent"]
    row1[3].metric(
        "직접가격 확보율",
        "N/A" if direct_rate is None else f"{direct_rate:.1f}%",
    )
    trace_rate = summary["traceability_success_rate_percent"]
    row1[4].metric(
        "근거 추적 성공률",
        "N/A" if trace_rate is None else f"{trace_rate:.1f}%",
    )
    reuse = summary["reuse_value_average_1_to_5"]
    row1[5].metric("재사용 가치", "N/A" if reuse is None else f"{reuse:.2f} / 5")

    row2 = st.columns(5)
    row2[0].metric("제품식별 FN", summary["identity_false_negative_count"])
    row2[1].metric("비교판정 FN", summary["comparison_false_negative_count"])
    row2[2].metric(
        "평균 수작업 시간",
        "N/A"
        if summary["manual_minutes_average"] is None
        else f"{summary['manual_minutes_average']:.1f}분",
    )
    row2[3].metric(
        "평균 시스템 시간",
        "N/A"
        if summary["system_minutes_average"] is None
        else f"{summary['system_minutes_average']:.1f}분",
    )
    row2[4].metric(
        "평균 시간절감",
        "N/A"
        if summary["time_saved_minutes_average"] is None
        else f"{summary['time_saved_minutes_average']:.1f}분",
    )

    if summary["critical_error_count"] > 0:
        st.error(
            "Critical 오류가 확인됐습니다. 제품식별/비교판정 false positive 또는 "
            "API 정상0건·실패 오분류를 먼저 수정해야 합니다."
        )
    elif summary["conservative_false_negative_signal_count"] > 0:
        st.warning(
            "False negative 신호가 있습니다. 실제 반복 사례인지 확인하기 전까지 matching/비교 규칙을 자동 완화하지 않습니다."
        )
    else:
        st.success("현재 완료 표본에서는 critical false positive / 0건·실패 오분류가 확인되지 않았습니다.")

    if completion["minimum_case_target_met"]:
        st.success("1차 실제 구매검토 UAT 최소 5건 표본 목표를 충족했습니다.")
    else:
        remaining = 5 - int(completion["sample_count"])
        st.info(f"1차 표본 목표까지 검토완료 케이스 {remaining}건이 더 필요합니다.")

    incomplete_messages = []
    if completion["identity_not_evaluated"]:
        incomplete_messages.append(
            f"제품식별 미평가 {completion['identity_not_evaluated']}건"
        )
    if completion["comparison_not_evaluated"]:
        incomplete_messages.append(
            f"비교판정 미평가 {completion['comparison_not_evaluated']}건"
        )
    if completion["zero_failure_not_evaluated"]:
        incomplete_messages.append(
            f"0건/실패 구분 미평가 {completion['zero_failure_not_evaluated']}건"
        )
    if completion["direct_evidence_not_evaluated"]:
        incomplete_messages.append(
            f"직접가격 근거 미평가 {completion['direct_evidence_not_evaluated']}건"
        )
    if completion["notes_missing"]:
        incomplete_messages.append(f"검토메모 누락 {completion['notes_missing']}건")
    if incomplete_messages:
        st.warning("UAT 완결성 확인: " + " / ".join(incomplete_messages))

    st.markdown("**비식별 케이스 데이터**")
    display_columns = [
        "case_id",
        "sample_class",
        "false_positive_identity",
        "false_negative_identity",
        "false_positive_comparison",
        "false_negative_comparison",
        "direct_evidence_found",
        "manual_minutes",
        "system_minutes",
        "time_saved_minutes",
        "reuse_value_1_to_5",
        "reviewer_notes",
    ]
    st.dataframe(
        pd.DataFrame(reviewed_rows)[display_columns],
        use_container_width=True,
        hide_index=True,
    )

    csv_data = render_review_csv(reviewed_rows)
    json_data = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    markdown_data = render_summary_markdown(summary)

    d1, d2, d3 = st.columns(3)
    with d1:
        st.download_button(
            "비식별 UAT CSV",
            data=csv_data,
            file_name="real-quote-uat-reviewed.csv",
            mime="text/csv",
        )
    with d2:
        st.download_button(
            "요약 JSON",
            data=json_data,
            file_name="real-quote-uat-summary.json",
            mime="application/json",
        )
    with d3:
        st.download_button(
            "요약 Markdown",
            data=markdown_data,
            file_name="real-quote-uat-summary.md",
            mime="text/markdown",
        )

st.caption(
    "이 화면의 다운로드에는 견적 원문·파일명·업체명·제품명·모델명·실제 단가·내부 구매정보가 포함되지 않습니다. "
    "FP/FN 및 시간 지표는 실제 담당자 원문/공개근거 대조 후 기록해야 합니다."
)
