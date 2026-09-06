from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pandas as pd
import streamlit as st

from purchase_price.schemas import CollectedPrice
from purchase_price.services.price_conditions import UNKNOWN, build_price_condition_profile
from purchase_price.services.pricing import assess_prices
from purchase_price.services.quote_comparability import (
    QuoteComparabilityContext,
    QuoteComparabilityDecision,
    evaluate_quote_comparability_candidate,
)
from purchase_price.services.quote_comparable_approval import (
    QuoteComparableApproval,
    apply_quote_comparable_approval,
    create_quote_comparable_approval,
    quote_evidence_pair_key,
)
from purchase_price.services.quote_condition_comparison import build_quote_condition_profile
from purchase_price.services.quote_extraction import parse_quote_decimal
from purchase_price.ui.quote_review_export import build_record
from purchase_price.ui.quote_review_state import QuoteReviewState, can_enter


def _condition_text(existing: str | None, additions: dict[str, str]) -> str:
    parts = [part.strip() for part in (existing or "").split(";") if part.strip()]
    for label, value in additions.items():
        value = value.strip()
        if not value:
            continue
        prefix = f"{label}=".casefold()
        parts = [part for part in parts if not part.casefold().startswith(prefix)]
        parts.append(f"{label}={value}")
    return ";".join(parts)


def supplement_evidence_conditions(
    evidence: CollectedPrice,
    *,
    source_url: str,
    reviewer_note: str,
    vat_status: str,
    quantity: Decimal | None,
    unit: str,
    delivery: str,
    installation: str,
    options: str,
    warranty: str,
    maintenance: str,
) -> CollectedPrice:
    """Return a review-session copy with human-verified evidence conditions."""
    if not source_url.strip():
        raise ValueError("근거 조건 보완에는 확인한 근거 URL이 필요합니다.")
    if not reviewer_note.strip():
        raise ValueError("근거 조건 보완 메모를 입력하세요.")
    conditions = _condition_text(
        evidence.conditions,
        {
            "배송": delivery,
            "설치": installation,
            "옵션": options,
            "보증": warranty,
            "유지보수": maintenance,
        },
    )
    note = f"담당자 근거조건 보완: {reviewer_note.strip()}"
    existing_note = (evidence.comparison_note or "").strip()
    return replace(
        evidence,
        source_url=source_url.strip(),
        vat_status=vat_status.strip() or evidence.vat_status,
        quantity=quantity if quantity is not None else evidence.quantity,
        unit=unit.strip() or evidence.unit,
        conditions=conditions,
        comparison_note=f"{existing_note} / {note}" if existing_note else note,
    )


def _reason_result(decision: QuoteComparabilityDecision, needles: tuple[str, ...]) -> str:
    matches = [reason for reason in decision.reasons if any(needle in reason for needle in needles)]
    return " / ".join(matches) if matches else "일치"


def condition_diff_rows(
    context: QuoteComparabilityContext,
    evidence: CollectedPrice,
    decision: QuoteComparabilityDecision,
) -> list[dict[str, str]]:
    quote_quantity = (
        f"{context.quantity} {context.unit}" if context.quantity is not None else f"미확인 {context.unit}"
    )
    evidence_quantity = (
        f"{evidence.quantity} {evidence.unit}"
        if evidence.quantity is not None
        else f"미확인 {evidence.unit or '미확인'}"
    )
    rows = [
        {
            "조건": "수량 · 단위",
            "견적": quote_quantity,
            "근거": evidence_quantity,
            "결과": _reason_result(decision, ("수량", "단위")),
        },
        {
            "조건": "통화",
            "견적": "KRW",
            "근거": evidence.currency,
            "결과": _reason_result(decision, ("KRW",)),
        },
    ]
    rows.extend(
        {
            "조건": comparison.label,
            "견적": comparison.quote_value,
            "근거": comparison.evidence_value,
            "결과": comparison.status.value,
        }
        for comparison in decision.condition_comparison.comparisons
    )
    quote_basis = context.quote_date.isoformat() if context.quote_date is not None else "미확인"
    evidence_basis = (
        decision.evidence_basis_date.isoformat()
        if decision.evidence_basis_date is not None
        else "미확인"
    )
    basis_result = _reason_result(decision, ("기준일", "견적일"))
    if basis_result == "일치" and decision.date_gap_days is not None:
        basis_result = f"{decision.date_gap_days}일"
    rows.append(
        {
            "조건": "기준일 차이",
            "견적": quote_basis,
            "근거": evidence_basis,
            "결과": basis_result,
        }
    )
    return rows


def _context_form(state: QuoteReviewState, index: int) -> None:
    item = state.items[index]
    saved = state.comparability_context.get(index)
    with st.form(f"quote_context_{index}"):
        c1, c2 = st.columns(2)
        quote_price = c1.text_input(
            "견적 단가",
            value=(
                format(saved.quote_unit_price, "f")
                if saved is not None and saved.quote_unit_price is not None
                else format(item.unit_price, "f") if item.unit_price is not None else ""
            ),
        )
        quantity = c2.text_input(
            "견적 수량",
            value=(
                format(saved.quantity, "f")
                if saved is not None and saved.quantity is not None
                else format(item.quantity, "f") if item.quantity is not None else ""
            ),
        )
        unit = c1.text_input("견적 단위", value=saved.unit if saved else item.unit)
        quote_date = c2.date_input(
            "견적 기준일",
            value=saved.quote_date if saved and saved.quote_date else date.today(),
        )
        vat = c1.text_input("VAT", value=saved.conditions.vat if saved else item.vat_status)
        delivery = c2.text_input(
            "배송", value=saved.conditions.delivery if saved else item.delivery_condition
        )
        installation = c1.text_input(
            "설치", value=saved.conditions.installation if saved else item.installation_condition
        )
        options = c2.text_input(
            "옵션", value=saved.conditions.options if saved else item.option_condition
        )
        warranty = c1.text_input(
            "보증", value=saved.conditions.warranty if saved else item.warranty_condition
        )
        maintenance = c2.text_input(
            "유지보수", value=saved.conditions.maintenance if saved else item.maintenance_condition
        )
        submitted = st.form_submit_button("견적 비교조건 저장", type="primary")
    if submitted:
        state.reset_downstream(after_step=5)
        state.comparability_context[index] = QuoteComparabilityContext(
            quote_unit_price=parse_quote_decimal(quote_price),
            quantity=parse_quote_decimal(quantity),
            unit=unit.strip(),
            quote_date=quote_date,
            conditions=build_quote_condition_profile(
                vat=vat,
                delivery=delivery,
                installation=installation,
                options=options,
                warranty=warranty,
                maintenance=maintenance,
            ),
        )
        st.success("견적 비교조건을 저장했습니다. 기존 session 승인은 무효화했습니다.")
        st.rerun()


def _render_supplement_form(
    state: QuoteReviewState,
    item_index: int,
    evidence_index: int,
    context: QuoteComparabilityContext,
) -> None:
    run = state.search_runs[item_index]
    evidence = run.results[evidence_index]
    profile = build_price_condition_profile(evidence)
    with st.expander("근거 조건 보완 — 확인한 공개 원문에 근거할 때만", expanded=False):
        with st.form(f"supplement_evidence_{item_index}_{evidence_index}"):
            source_url = st.text_input("확인한 근거 URL", value=evidence.source_url or "")
            note = st.text_input(
                "보완 메모 (필수)", placeholder="예: 계약상세 원문에서 설치 포함 확인"
            )
            c1, c2 = st.columns(2)
            vat = c1.text_input("근거 VAT", value="" if profile.vat == UNKNOWN else profile.vat)
            quantity = c2.text_input(
                "근거 수량",
                value=format(evidence.quantity, "f") if evidence.quantity is not None else "",
            )
            unit = c1.text_input("근거 단위", value=evidence.unit)
            delivery = c2.text_input(
                "근거 배송", value="" if profile.delivery == UNKNOWN else profile.delivery
            )
            installation = c1.text_input(
                "근거 설치", value="" if profile.installation == UNKNOWN else profile.installation
            )
            options = c2.text_input(
                "근거 옵션", value="" if profile.options == UNKNOWN else profile.options
            )
            warranty = c1.text_input(
                "근거 보증", value="" if profile.warranty == UNKNOWN else profile.warranty
            )
            maintenance = c2.text_input(
                "근거 유지보수",
                value="" if profile.maintenance == UNKNOWN else profile.maintenance,
            )
            submitted = st.form_submit_button("근거 조건 보완 사본 반영")
        if submitted:
            try:
                amended = supplement_evidence_conditions(
                    evidence,
                    source_url=source_url,
                    reviewer_note=note,
                    vat_status=vat,
                    quantity=parse_quote_decimal(quantity),
                    unit=unit,
                    delivery=delivery,
                    installation=installation,
                    options=options,
                    warranty=warranty,
                    maintenance=maintenance,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                old_key = quote_evidence_pair_key(context, evidence)
                state.approvals.pop(old_key, None)
                run.results[evidence_index] = amended
                st.success(
                    "원본 객체는 변경하지 않고 현재 검토용 사본에 보완 조건을 반영했습니다."
                )
                st.rerun()


def render_s5(state: QuoteReviewState, index: int) -> None:
    st.subheader('5. 조건 대조 — 근거별로 "같은 조건인가"')
    run = state.search_runs.get(index)
    if run is None:
        st.warning("이 품목의 근거 검색을 먼저 실행하세요.")
        return
    _context_form(state, index)
    context = state.comparability_context.get(index)
    if context is None:
        st.info("견적 비교조건을 저장하면 외부근거 candidate gate 결과가 표시됩니다.")
        return
    if not run.results:
        st.info("대조할 검증 가격근거가 없습니다.")
        return

    decisions = [
        evaluate_quote_comparability_candidate(context, evidence) for evidence in run.results
    ]
    candidate_count = sum(decision.eligible_candidate for decision in decisions)
    rows = []
    for evidence, decision in zip(run.results, decisions, strict=True):
        rows.append(
            {
                "출처": evidence.source_name,
                "단가": float(evidence.price),
                "수량·단위": build_price_condition_profile(evidence).quantity_unit,
                "기준일": (
                    decision.evidence_basis_date.isoformat()
                    if decision.evidence_basis_date
                    else "미확인"
                ),
                "대조 결과": decision.status_label,
                "보류 사유": decision.reason_text,
            }
        )
    st.caption(f"직접 근거 {len(run.results)}건 · 비교가능 후보 {candidate_count}건")
    st.dataframe(
        pd.DataFrame(rows),
        use_container_width=True,
        hide_index=True,
        column_config={"단가": st.column_config.NumberColumn(format="%d")},
    )
    evidence_index = st.radio(
        "대조할 근거 선택",
        options=list(range(len(run.results))),
        format_func=lambda idx: (
            f"{run.results[idx].source_name} · {run.results[idx].price:,.0f}원 · "
            f"{decisions[idx].status_label}"
        ),
        key=f"quote_compare_evidence_{index}",
    )
    evidence = run.results[evidence_index]
    decision = decisions[evidence_index]
    st.dataframe(
        pd.DataFrame(condition_diff_rows(context, evidence, decision)),
        use_container_width=True,
        hide_index=True,
    )
    if decision.eligible_candidate:
        st.success("이 근거는 현재 비교조건에서 승인 가능한 candidate입니다.")
    else:
        st.warning("이 근거는 지금 승인할 수 없습니다. " + decision.reason_text)
    if evidence.source_url:
        st.link_button("근거 원문 열기", evidence.source_url)
    _render_supplement_form(state, index, evidence_index, context)

    allowed, _ = can_enter(6, state)
    if not allowed:
        st.info("6단계 진입이 차단되어 있습니다. 오른쪽 판정 경로의 사유를 확인하세요.")
    if st.button("6. 승인·판정으로", type="primary", disabled=not allowed):
        state.step = 6
        st.rerun()


def _applied_items(state: QuoteReviewState, index: int) -> tuple[list[CollectedPrice], list[int]]:
    context = state.comparability_context[index]
    run = state.search_runs[index]
    applied: list[CollectedPrice] = []
    approved_indices: list[int] = []
    for evidence_index, evidence in enumerate(run.results):
        key = quote_evidence_pair_key(context, evidence)
        approval = state.approvals.get(key)
        if isinstance(approval, QuoteComparableApproval):
            try:
                applied.append(apply_quote_comparable_approval(context, evidence, approval))
            except ValueError:
                state.approvals.pop(key, None)
                applied.append(evidence)
            else:
                approved_indices.append(evidence_index)
        else:
            applied.append(evidence)
    return applied, approved_indices


def render_s6(state: QuoteReviewState, index: int) -> None:
    st.subheader("6. 승인·판정")
    context = state.comparability_context.get(index)
    run = state.search_runs.get(index)
    if context is None or run is None:
        st.error("조건 대조 상태가 없습니다. 5단계에서 다시 확인하세요.")
        return
    decisions = [
        evaluate_quote_comparability_candidate(context, evidence) for evidence in run.results
    ]
    candidates = [idx for idx, decision in enumerate(decisions) if decision.eligible_candidate]
    if not candidates:
        st.info("승인 가능한 candidate가 없습니다.")
        return

    state.reviewer = st.text_input("검토 담당자", value=state.reviewer)
    approval_index = st.selectbox(
        "승인 검토할 근거",
        options=candidates,
        format_func=lambda idx: (
            f"{run.results[idx].source_name} · {run.results[idx].price:,.0f}원 · "
            f"{run.results[idx].source_record_id or '근거ID 없음'}"
        ),
        key=f"quote_approval_candidate_{index}",
    )
    evidence = run.results[approval_index]
    decision = decisions[approval_index]
    pair_key = quote_evidence_pair_key(context, evidence)
    existing = state.approvals.get(pair_key)
    st.dataframe(
        pd.DataFrame(condition_diff_rows(context, evidence, decision)),
        use_container_width=True,
        hide_index=True,
    )
    if evidence.source_url:
        st.link_button("승인 전 외부 원문 열기", evidence.source_url)

    if isinstance(existing, QuoteComparableApproval):
        st.success(f"현재 session 승인됨 · 승인키 {existing.short_key}")
        st.caption(f"승인 메모: {existing.reviewer_note}")
        if st.button("이 pair 승인 취소"):
            state.approvals.pop(pair_key, None)
            st.rerun()
    else:
        confirmed = st.checkbox(
            "견적 원문과 외부 원문을 직접 확인했고 현재 quote/evidence pair가 동일 비교조건임을 "
            "확인했습니다.",
            value=False,
            key=f"quote_approval_confirmed_{index}",
        )
        note = st.text_input(
            "승인 메모 (필수)",
            placeholder="예: 견적서와 계약상세 원문에서 수량·단위·VAT·설치·보증 조건 대조",
            key=f"quote_approval_note_{index}",
        )
        can_approve = confirmed and bool(note.strip()) and bool(state.reviewer.strip())
        if st.button(
            "선택 pair 승인",
            type="primary",
            disabled=not can_approve,
            key=f"approve_quote_pair_{index}",
        ):
            try:
                approval = create_quote_comparable_approval(
                    context,
                    evidence,
                    reviewer_confirmed=confirmed,
                    reviewer_note=f"{state.reviewer.strip()}: {note.strip()}",
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                state.approvals[approval.pair_key] = approval
                st.rerun()

    applied, approved_indices = _applied_items(state, index)
    assessment = assess_prices(applied, context.quote_unit_price)
    st.markdown("**승인 근거 대비 위치**")
    if approved_indices and assessment.quote_position is not None:
        c1, c2, c3 = st.columns(3)
        c1.metric("승인 직접비교 근거", f"{assessment.quote_comparable_count}건")
        c2.metric("현재 견적 위치", assessment.quote_position)
        c3.metric(
            "차이율",
            f"{assessment.difference_rate:.1f}%"
            if assessment.difference_rate is not None
            else "산정불가",
        )
        st.write(assessment.message)
    else:
        st.info("승인된 quote/evidence pair가 없어 견적의 높고 낮음을 판정하지 않습니다.")

    excluded: list[str] = []
    for evidence_index, gate_decision in enumerate(decisions):
        excluded_evidence = run.results[evidence_index]
        key = quote_evidence_pair_key(context, excluded_evidence)
        if not gate_decision.eligible_candidate:
            excluded.append(f"{excluded_evidence.source_name}: {gate_decision.reason_text}")
        elif key not in state.approvals:
            excluded.append(f"{excluded_evidence.source_name}: candidate이나 담당자 미승인")
    discovery = state.discoveries.get(index)
    if discovery is not None and discovery.candidates:
        excluded.append(f"나라장터 미검증 후보 {len(discovery.candidates)}건: 판정에서 제외")
    if excluded:
        with st.expander("판정에서 제외된 근거와 사유", expanded=False):
            for reason in excluded:
                st.write(f"- {reason}")

    st.warning(
        "이 결과는 구매결정이 아닙니다. 승인된 공개가격 근거 대비 위치만 표시하며 "
        "적정/부적정 또는 구매 권고를 의미하지 않습니다."
    )
    record_json = json.dumps(build_record(state), ensure_ascii=False, indent=2)
    st.download_button(
        "검토 기록 JSON 다운로드",
        data=record_json,
        file_name="quote-review-record.json",
        mime="application/json",
    )
