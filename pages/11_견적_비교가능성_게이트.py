from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from purchase_price.collectors.registry import build_collectors
from purchase_price.config import get_settings
from purchase_price.services.pricing import assess_prices
from purchase_price.services.quote_comparability import (
    QuoteComparabilityContext,
    evaluate_quote_comparability_candidate,
)
from purchase_price.services.quote_comparable_approval import (
    QuoteComparableApproval,
    apply_quote_comparable_approval,
    create_quote_comparable_approval,
    quote_evidence_pair_key,
)
from purchase_price.services.quote_condition_comparison import build_quote_condition_profile
from purchase_price.services.quote_extraction import (
    QuoteExtractionError,
    extract_quote_file,
    parse_quote_decimal,
    quote_item_query,
)
from purchase_price.services.search import search_all

_RUN_KEY = "quote_comparability_last_run"
_APPROVALS_KEY = "quote_comparability_session_approvals"

st.set_page_config(page_title="견적 비교가능성 게이트", page_icon="🚦", layout="wide")
st.title("견적가격 비교가능성 안전게이트")
st.caption(
    "외부 가격을 현재 견적과 직접 비교하기 전에 제품동일성·가격근거 의미·수량·단위·상업조건·"
    "기준일을 모두 확인합니다. 후보 통과 후에도 담당자가 원문과 조건을 명시적으로 승인한 "
    "현재 session의 quote/evidence pair만 `QUOTE_COMPARABLE`로 평가합니다."
)

settings = get_settings()
g2b_enabled = bool((settings.resolved_g2b_service_key or "").strip())

with st.expander("통과 및 승인 계약", expanded=False):
    st.markdown(
        """
### 1단계 · 자동 candidate gate

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

### 2단계 · 담당자 명시적 승인

candidate를 통과한 **특정 외부근거의 원문과 견적조건을 담당자가 직접 확인**하고 승인합니다.
승인은 현재 Streamlit session의 해당 quote/evidence pair에만 적용됩니다.

- 원본 public source의 `comparison_scope`를 영구 변경하지 않음
- 견적가·수량·단위·상업조건·기준일 또는 외부근거가 바뀌면 기존 승인 재사용 불가
- 승인 후에만 `assess_prices`가 견적의 상단/하단/범위내 위치를 계산
- 승인 취소 가능
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

condition_row = edited_conditions.iloc[0]
current_context = QuoteComparabilityContext(
    quote_unit_price=parse_quote_decimal(quote_price_text),
    quantity=parse_quote_decimal(quantity_text),
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

if st.button("2. 외부 근거 비교가능성 검사", type="primary", use_container_width=True):
    run = search_all(
        quote_item_query(selected),
        build_collectors(g2b_lookback_days=int(g2b_lookback_days)),
    )
    st.session_state[_RUN_KEY] = {
        "selected_index": selected_index,
        "lookback_days": int(g2b_lookback_days),
        "context": current_context,
        "results": tuple(run.results),
        "errors": tuple(run.errors),
    }

saved_run = st.session_state.get(_RUN_KEY)
if not isinstance(saved_run, dict):
    st.stop()

saved_context = saved_run.get("context")
saved_results = saved_run.get("results")
saved_errors = saved_run.get("errors")
if not isinstance(saved_context, QuoteComparabilityContext) or not isinstance(saved_results, tuple):
    st.session_state.pop(_RUN_KEY, None)
    st.stop()

inputs_changed = (
    saved_run.get("selected_index") != selected_index
    or saved_run.get("lookback_days") != int(g2b_lookback_days)
    or saved_context != current_context
)
if inputs_changed:
    st.warning(
        "마지막 검사 이후 품목·검색기간·견적가·수량·단위·조건 또는 기준일이 변경되었습니다. "
        "아래 결과는 이전 입력 기준이며 승인하기 전에 `외부 근거 비교가능성 검사`를 다시 실행하세요."
    )

if saved_errors:
    st.warning("일부 출처 조회 실패: " + " / ".join(str(item) for item in saved_errors))
if not saved_results:
    st.info("현재 연결된 공개가격 source에서 검사할 근거를 찾지 못했습니다.")
    st.stop()

approvals = st.session_state.get(_APPROVALS_KEY)
if not isinstance(approvals, dict):
    approvals = {}
    st.session_state[_APPROVALS_KEY] = approvals

result_rows: list[dict[str, object]] = []
candidate_indices: list[int] = []
approved_indices: list[int] = []
assessment_items = []

for index, evidence in enumerate(saved_results):
    decision = evaluate_quote_comparability_candidate(saved_context, evidence)
    pair_key = quote_evidence_pair_key(saved_context, evidence)
    approval = approvals.get(pair_key)
    applied = evidence
    approval_status = "미승인"

    if isinstance(approval, QuoteComparableApproval):
        try:
            applied = apply_quote_comparable_approval(saved_context, evidence, approval)
            approval_status = f"승인됨 · {approval.short_key}"
            approved_indices.append(index)
        except ValueError:
            approvals.pop(pair_key, None)
            approval = None

    if decision.eligible_candidate:
        candidate_indices.append(index)

    assessment_items.append(applied)
    result_rows.append(
        {
            "상태": decision.status_label,
            "승인": approval_status,
            "출처": evidence.source_name,
            "가격": float(evidence.price),
            "등급": evidence.match_grade.value,
            "Evidence Type": evidence.evidence_type.value,
            "원본 비교범위": evidence.comparison_scope.value,
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

st.subheader("3. Candidate gate 결과")
if candidate_indices:
    st.success(
        f"총 {len(result_rows)}건 중 {len(candidate_indices)}건이 `quote_comparable 후보` 조건을 모두 충족했습니다."
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
st.caption(
    "`원본 비교범위`는 public source record의 상태입니다. 아래 승인은 원본을 변경하지 않고 현재 session의 "
    "특정 quote/evidence pair에만 임시 적용됩니다."
)

st.subheader("4. 담당자 원문 확인 및 명시적 승인")
if inputs_changed:
    st.info("입력이 변경되어 현재는 승인할 수 없습니다. 최신 입력으로 검사를 다시 실행하세요.")
elif not candidate_indices:
    st.info("승인 가능한 candidate가 없습니다. 보류사유를 먼저 확인하세요.")
else:
    candidate_labels = {
        index: (
            f"{saved_results[index].source_name} · {saved_results[index].price:,.0f}원 · "
            f"{saved_results[index].source_record_id or '근거ID 없음'}"
        )
        for index in candidate_indices
    }
    approval_index = st.selectbox(
        "승인 검토할 근거",
        options=candidate_indices,
        format_func=lambda index: candidate_labels[index],
        key="quote_comparability_approval_index",
    )
    evidence = saved_results[approval_index]
    decision = evaluate_quote_comparability_candidate(saved_context, evidence)
    pair_key = quote_evidence_pair_key(saved_context, evidence)
    existing_approval = approvals.get(pair_key)

    c1, c2 = st.columns(2)
    with c1:
        st.write(f"**출처:** {evidence.source_name}")
        st.write(f"**근거ID:** {evidence.source_record_id or '미확인'}")
        st.write(f"**가격:** {evidence.price:,.0f} {evidence.currency}")
        st.write(f"**제품등급:** {evidence.match_grade.value}")
        if evidence.source_url:
            st.link_button("외부 원문 열기", evidence.source_url)
    with c2:
        condition_rows = [
            {
                "조건": item.label,
                "견적": item.quote_value,
                "외부근거": item.evidence_value,
                "판정": item.status.value,
            }
            for item in decision.condition_comparison.comparisons
        ]
        st.dataframe(pd.DataFrame(condition_rows), use_container_width=True, hide_index=True)

    if isinstance(existing_approval, QuoteComparableApproval):
        st.success(
            f"이 pair는 현재 session에서 승인되어 있습니다. 승인키 {existing_approval.short_key}, "
            f"승인시각 {existing_approval.approved_at.isoformat()}"
        )
        if existing_approval.reviewer_note:
            st.caption(f"확인 메모: {existing_approval.reviewer_note}")
        if st.button("이 pair 승인 취소", use_container_width=True):
            approvals.pop(pair_key, None)
            st.rerun()
    else:
        confirmed = st.checkbox(
            "외부 원문과 견적 원문을 직접 확인했고, 위 제품·수량·단위·6개 상업조건·기준일이 "
            "현재 견적과 직접 단가비교 가능한 동일 조건임을 확인했습니다.",
            value=False,
        )
        reviewer_note = st.text_input(
            "확인 메모 (선택)",
            placeholder="예: 계약상세 원문과 견적서 원문 대조",
            help="실제 병원 내부정보·개인정보·secret을 입력하지 마세요. 현재 session에만 사용합니다.",
        )
        if st.button(
            "선택 pair를 현재 session에서 QUOTE_COMPARABLE로 승인",
            type="primary",
            disabled=not confirmed,
            use_container_width=True,
        ):
            try:
                approval = create_quote_comparable_approval(
                    saved_context,
                    evidence,
                    reviewer_confirmed=confirmed,
                    reviewer_note=reviewer_note,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                approvals[approval.pair_key] = approval
                st.rerun()

st.subheader("5. 승인 반영 견적 위치")
assessment = assess_prices(assessment_items, saved_context.quote_unit_price)
if approved_indices and assessment.quote_position is not None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("승인된 직접비교 근거", f"{assessment.quote_comparable_count}건")
    c2.metric(
        "직접비교 하단",
        f"{assessment.quote_comparable_low:,.0f}원"
        if assessment.quote_comparable_low is not None
        else "산정불가",
    )
    c3.metric(
        "직접비교 상단",
        f"{assessment.quote_comparable_high:,.0f}원"
        if assessment.quote_comparable_high is not None
        else "산정불가",
    )
    c4.metric("현재 견적 위치", assessment.quote_position)
    st.success(assessment.message)
    st.caption(
        "이 판정은 현재 session에서 담당자가 명시적으로 승인한 quote/evidence pair에만 근거합니다. "
        "새 session이나 변경된 견적에는 승인을 다시 확인해야 합니다."
    )
else:
    st.info(
        "아직 현재 session에서 승인된 quote/evidence pair가 없어 견적의 높고 낮음을 판정하지 않습니다. "
        "관측가격은 존재하더라도 승인 전에는 `observed_only`로 유지됩니다."
    )

st.warning(
    "이 기능은 구매결정을 자동화하지 않습니다. 승인 후의 `상단 초과/하단 미만/범위 내`는 확인된 "
    "공개가격 근거와의 위치만 표시하며 적정/부적정 또는 구매 권고를 의미하지 않습니다."
)
