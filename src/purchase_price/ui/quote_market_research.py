from __future__ import annotations

import html
import re
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_search_policy import (
    G2B_DEFAULT_LOOKBACK_DAYS,
    G2B_LOOKBACK_OPTIONS,
    g2b_lookback_label,
)
from purchase_price.services.mfds_identity_r2 import lookup_mfds_identity_from_r2
from purchase_price.services.mfds_recall import lookup_mfds_recall
from purchase_price.services.mfds_workspace import research_mfds_for_workspace
from purchase_price.services.price_conditions import build_price_condition_profile
from purchase_price.services.pricing import assess_prices
from purchase_price.services.purchase_workspace_handoff import (
    PURCHASE_WORKSPACE_HANDOFF_SESSION_KEY,
    build_purchase_workspace_handoff,
)
from purchase_price.services.quote_extraction import parse_quote_decimal, quote_item_query
from purchase_price.services.structured_query_identity import canonicalize_product_query
from purchase_price.services.track_b_db_quote_comparison import (
    TrackBIdentitySuggestion,
    TrackBQuoteCandidate,
    TrackBReferenceCandidate,
)
from purchase_price.services.track_b_quote_with_live import lookup_track_b_quote_with_live

# 금액검증 wording shared with the 가격 조사 tables (one definition, re-exported here).
from purchase_price.ui.amount_check import AMOUNT_CHECK_LABELS, amount_check_label  # noqa: F401
from purchase_price.ui.market_research import (
    render_external_research_links,
    render_market_alternative_candidates,
    render_market_reference_summary,
    render_model_price_research_summary,
    render_procurement_research,
    run_market_research,
)
from purchase_price.ui.quote_item_intelligence import (
    PERMIT_VS_TRADES_NOTE,
    build_quote_item_intelligence_summary,
    mfds_permit_note,
    quote_item_intelligence_rows,
)
from purchase_price.ui.quote_review_contract import build_manual_quote_item
from purchase_price.ui.quote_review_layout import (
    COMPACT_TABLE_COLUMNS as QUOTE_COMPACT_TABLE_COLUMNS,
)
from purchase_price.ui.quote_review_layout import LAYOUT_CSS as QUOTE_REVIEW_LAYOUT_CSS
from purchase_price.ui.quote_review_layout import TABLE_COLUMNS as QUOTE_TABLE_COLUMNS
from purchase_price.ui.quote_review_layout import (
    VERDICT_ORDER,
    VERDICT_TABLE_COLORS,
    QuoteItemComparison,
    build_item_comparison,
    condition_rows,
    condition_table_html,
    detail_card_html,
    rule_sentence,
    summary_cards_html,
    verdict_counts,
)
from purchase_price.ui.quote_review_layout import table_rows as quote_review_table_rows
from purchase_price.ui.quote_review_state import QuoteReviewState
from purchase_price.ui.quote_review_steps import (
    READ_ERROR_SESSION_KEY,
    _store_extraction,
    friendly_read_error,
)
from purchase_price.ui.quote_review_summary import render_purchase_review_summary
from purchase_price.ui.theme import TONE_WARN, notice_html
from purchase_price.ui.track_b_transactions import model_price_group_rows
from purchase_price.ui.widgets import (
    render_condition_table,
    render_evidence_table,
    render_observation_cards,
    render_source_status,
)

QUOTE_REVIEW_ACCEPTANCE_V3 = True
# The handoff to 가격 조사 says it came from 견적서 검토 (2026-10-09).
HANDOFF_SOURCE_V1 = True
QUOTE_AUTO_ROUTE_FILE_SESSION_KEY = "quote_auto_route_file_v1"

_FILENAME_SUFFIX_RE = re.compile(
    r"(?:^|[\s._-]+)(?:견적서?|quotation|estimate)"
    r"(?:[\s._-]*(?:\d+|v\d+|rev\d+|최종|final|copy|복사본))*$",
    re.IGNORECASE,
)


def _money(value) -> str:
    return f"{value:,.0f}원" if value is not None else "미확인"


def _money_input(value) -> str:
    return "" if value is None else f"{value:,.0f}"


def _quantity_unit(quantity, unit: str | None) -> str:
    if quantity is None and not unit:
        return "미확인"
    quantity_text = "" if quantity is None else f"{quantity:g}"
    return " ".join(part for part in (quantity_text, unit or "") if part) or "미확인"


def _condition_text(candidate) -> str:
    parts = [
        str(value).strip()
        for value in (
            getattr(candidate, "contract_delivery_type", None),
            getattr(candidate, "contract_type", None),
            getattr(candidate, "delivery_condition", None),
        )
        if value and str(value).strip()
    ]
    return " · ".join(dict.fromkeys(parts)) if parts else "미확인"


def _comparison_label(candidate: TrackBQuoteCandidate) -> str:
    if candidate.match_grade.value in {"A", "B"}:
        return "동일 모델"
    return "동일 품목 참고"


def _track_b_candidate_rows(
    candidates: tuple[TrackBQuoteCandidate, ...],
) -> list[dict[str, object]]:
    return [
        {
            "가격": _money(candidate.price),
            "총액": _money(getattr(candidate, "total_amount", None)),
            "금액검증": amount_check_label(candidate.amount_check),
            "제조사": getattr(candidate, "manufacturer", None) or "미확인",
            "모델": getattr(candidate, "model_name", None) or "미확인",
            "규격": getattr(candidate, "specification", None) or "미확인",
            "거래조건": _condition_text(candidate),
            "판매처": candidate.supplier or "미확인",
            "구매처": candidate.demand_institution or "미확인",
            "거래일": candidate.transaction_date or "미확인",
            "수량/단위": _quantity_unit(candidate.quantity, candidate.unit),
            "거래기록": candidate.transaction_type,
            "품목/모델": candidate.product_title,
            "비교수준": _comparison_label(candidate),
            "견적 대비": (
                f"{candidate.delta_percent:+.1f}%"
                if candidate.delta_percent is not None
                else "조건 확인"
            ),
        }
        for candidate in candidates
    ]


def _track_b_reference_rows(
    candidates: tuple[TrackBReferenceCandidate, ...],
) -> list[dict[str, object]]:
    return [
        {
            "가격": _money(candidate.price),
            "총액": _money(getattr(candidate, "total_amount", None)),
            "제조사": getattr(candidate, "manufacturer", None) or "미확인",
            "모델": getattr(candidate, "model_name", None) or "미확인",
            "규격": getattr(candidate, "specification", None) or "미확인",
            "거래조건": _condition_text(candidate),
            "판매처": candidate.supplier or "미확인",
            "구매처": candidate.demand_institution or "미확인",
            "거래일": candidate.transaction_date or "미확인",
            "수량/단위": _quantity_unit(candidate.quantity, candidate.unit),
            "거래기록": candidate.transaction_type,
            "품목/모델": candidate.product_title,
            "비교수준": candidate.reference_reason,
            "견적 대비": "참고만",
        }
        for candidate in candidates
    ]


def _track_b_suggestion_rows(
    suggestions: tuple[TrackBIdentitySuggestion, ...],
) -> list[dict[str, str]]:
    return [
        {
            "수집 품목": suggestion.product_title,
            "제조사": suggestion.manufacturer or "미확인",
            "모델명": suggestion.model_name,
            "거래일": suggestion.transaction_date or "미확인",
            "제안 근거": suggestion.match_reason,
        }
        for suggestion in suggestions
    ]


def _clear_research(state: QuoteReviewState) -> None:
    state.search_runs.clear()
    state.discoveries.clear()
    state.market_bundles.clear()
    state.track_b_db.clear()
    state.mfds_workspace.clear()
    state.mfds_identity.clear()
    state.safety_lookup.clear()
    state.item_research_failures.clear()
    state.comparability_context.clear()
    state.approvals.clear()


_STAGE_LABELS = {"Safety": "회수·판매중지"}


def _stage_label(stage: str) -> str:
    return _STAGE_LABELS.get(stage, stage)


def _record_item_failure(
    state: QuoteReviewState,
    index: int,
    stage: str,
    exc: Exception,
) -> None:
    failures = state.item_research_failures.setdefault(index, {})
    failures[stage] = type(exc).__name__


def _clear_item_failure(state: QuoteReviewState, index: int, stage: str) -> None:
    failures = state.item_research_failures.get(index)
    if not failures:
        return
    failures.pop(stage, None)
    if not failures:
        state.item_research_failures.pop(index, None)


def _quote_processing_counts(state: QuoteReviewState) -> tuple[int, int, int, int]:
    total = len(state.items)
    partial_failure = len(state.item_research_failures)
    completed = sum(
        1
        for index in range(total)
        if index in state.track_b_db and index not in state.item_research_failures
    )
    pending = max(total - completed - partial_failure, 0)
    return total, completed, partial_failure, pending


def _retry_failed_stage(state: QuoteReviewState, index: int, stage: str) -> None:
    if stage == "나라장터 가격":
        state.track_b_db.pop(index, None)
        state.mfds_workspace.pop(index, None)
    elif stage == "식약처":
        state.mfds_workspace.pop(index, None)
    elif stage == "추가 공개자료":
        state.search_runs.pop(index, None)
        state.discoveries.pop(index, None)
        state.market_bundles.pop(index, None)
    elif stage == "Safety":
        state.safety_lookup.pop(index, None)
    else:
        return
    _clear_item_failure(state, index, stage)


def _invalidate_item_review(state: QuoteReviewState, index: int) -> None:
    state.item_confirmed[index] = False
    state.item_notes.pop(index, None)
    state.condition_notes.pop(index, None)
    state.identity.pop(index, None)
    _clear_research(state)
    state.step = 2


def _filename_product_candidate(file_name: str) -> str:
    """Return an editable filename-derived product hint, never a verified identity."""

    stem = re.sub(r"\.[^.]+$", "", (file_name or "").strip())
    stem = re.sub(r"^\s*\d+[\s._-]+", "", stem)
    candidate = _FILENAME_SUFFIX_RE.sub("", stem).strip(" ._-()[]")
    candidate = re.sub(r"\s+", " ", candidate)
    if len(candidate) < 3 or not re.search(r"[A-Za-z가-힣]", candidate):
        return ""
    if candidate.casefold() in {"견적", "견적서", "quotation", "estimate", "quote"}:
        return ""
    return candidate


def _render_inline_manual_item_form(state: QuoteReviewState) -> None:
    product_candidate = _filename_product_candidate(state.file_name or "")
    st.markdown(
        notice_html(
            "견적서에서 품목 표를 읽지 못했습니다. 다른 화면으로 옮길 필요 없이 아래에 품명·모델명·견적 단가를 "
            "넣고 저장하면 바로 거래가를 찾습니다.",
            tone=TONE_WARN,
        ),
        unsafe_allow_html=True,
    )
    if product_candidate:
        st.info(
            f"파일 이름에서 품명 후보 `{product_candidate}`를 미리 채웠습니다. "
            "견적서 본문에서 읽은 값이 아니므로 맞는지 확인한 뒤 저장하세요."
        )
    with st.form("quote_auto_manual_item"):
        c1, c2 = st.columns(2)
        product_name = c1.text_input(
            "품명",
            value=product_candidate,
            placeholder="예: 극초단파치료시스템",
        )
        manufacturer = c2.text_input("제조사", placeholder="선택")
        model_name = c1.text_input("모델명", placeholder="선택")
        specification = c2.text_input("규격", placeholder="선택")
        quantity = c1.text_input("수량", placeholder="예: 1")
        unit = c2.text_input("단위", placeholder="예: SET")
        unit_price = c1.text_input("견적 단가", placeholder="예: 66,000,000")
        total_amount = c2.text_input("총액", placeholder="선택")
        vat = c1.text_input("VAT", placeholder="포함/별도/면세 등 선택")
        installation = c2.text_input("설치", placeholder="선택")
        options = c1.text_input("옵션/구성", placeholder="선택")
        warranty = c2.text_input("보증", placeholder="선택")
        submitted = st.form_submit_button("품목 저장 후 시장조사", type="primary")

    if not submitted:
        return

    try:
        item = build_manual_quote_item(
            product_name=product_name,
            manufacturer=manufacturer,
            model_name=model_name,
            specification=specification,
            quantity=parse_quote_decimal(quantity),
            unit=unit,
            unit_price=parse_quote_decimal(unit_price),
            total_amount=parse_quote_decimal(total_amount),
            vat_status=vat,
            delivery_condition="",
            installation_condition=installation,
            option_condition=options,
            warranty_condition=warranty,
            maintenance_condition="",
            other_conditions="",
        )
    except ValueError as exc:
        st.error(str(exc))
        return

    state.items = [item]
    state.item_confirmed = {0: False}
    state.item_notes = {0: "자동 추출 0건 — 통합 견적검토 화면에서 담당자 수동 입력"}
    state.condition_notes = {0: {}}
    state.identity.clear()
    _clear_research(state)
    state.step = 2
    st.success("품목을 저장했습니다. 시장가격 조사를 시작합니다.")
    st.rerun()


def _render_compact_item_editor(state: QuoteReviewState) -> None:
    if not state.items:
        return
    with st.expander("추출 내용 확인·수정", expanded=False):
        st.caption(
            "자동 추출이 틀린 경우 품명·제조사·모델·규격·견적 단가만 수정하세요."
        )
        index = st.selectbox(
            "수정할 품목",
            options=list(range(len(state.items))),
            format_func=lambda i: (
                f"{i + 1}. {state.items[i].product_name or state.items[i].model_name or '미확인 품목'}"
            ),
            key="quote_auto_edit_index",
        )
        item = state.items[int(index)]
        with st.form(f"quote_auto_edit_{index}"):
            c1, c2 = st.columns(2)
            product_name = c1.text_input("품명", value=item.product_name)
            manufacturer = c2.text_input("제조사", value=item.manufacturer)
            model_name = c1.text_input("모델명", value=item.model_name)
            specification = c2.text_input("규격", value=item.specification)
            unit_price = c1.text_input(
                "견적 단가",
                value=_money_input(item.unit_price),
            )
            quantity = c2.text_input(
                "수량",
                value="" if item.quantity is None else format(item.quantity, "f"),
            )
            saved = st.form_submit_button("수정 저장")
        if saved:
            state.items[int(index)] = replace(
                item,
                product_name=product_name.strip(),
                manufacturer=manufacturer.strip(),
                model_name=model_name.strip(),
                specification=specification.strip(),
                unit_price=parse_quote_decimal(unit_price),
                quantity=parse_quote_decimal(quantity),
            )
            _invalidate_item_review(state, int(index))
            st.success("품목을 수정했습니다. 가격을 다시 검색합니다.")
            st.rerun()


def _quote_item_unified_query(state: QuoteReviewState, index: int) -> ProductQuery:
    """Build the external-evidence query with the same identity scope as ordinary search.

    Quote manufacturer/specification remain on the QuoteItem for commercial-condition review.
    They are not retrieval constraints once a model is available, because ordinary one-line
    search resolves the product/model identity without those quote-only hints.
    """

    raw_query = quote_item_query(state.items[index])
    identity = state.mfds_identity.get(index)
    canonical = canonicalize_product_query(raw_query, identity).query
    if canonical.model_name.strip():
        return ProductQuery(
            product_name=canonical.product_name,
            model_name=canonical.model_name,
        )
    if canonical.product_name.strip():
        return ProductQuery(product_name=canonical.product_name)
    return canonical


def _ensure_track_b_comparison(state: QuoteReviewState) -> None:
    if not state.items:
        return
    for index, item in enumerate(state.items):
        if index in state.track_b_db:
            continue
        try:
            # Same trades as the 가격 조사 page: the index plus the live days after it.
            track_b, live = lookup_track_b_quote_with_live(
                _quote_item_unified_query(state, index),
                quote_unit_price=item.unit_price,
            )
            state.track_b_db[index] = track_b
            live_status = getattr(state, "track_b_live_status", None)
            if isinstance(live_status, dict):
                live_status[index] = live.status
        except Exception as exc:
            _record_item_failure(state, index, "나라장터 가격", exc)
            continue
        _clear_item_failure(state, index, "나라장터 가격")


def _ensure_mfds_workspace(state: QuoteReviewState) -> None:
    if not state.items:
        return
    for index, item in enumerate(state.items):
        if index in state.mfds_workspace:
            continue
        track_b = state.track_b_db.get(index)
        if track_b is None:
            continue
        try:
            state.mfds_workspace[index] = research_mfds_for_workspace(
                _quote_item_unified_query(state, index),
                track_b,
            )
        except Exception as exc:
            _record_item_failure(state, index, "식약처", exc)
            continue
        _clear_item_failure(state, index, "식약처")


def _ensure_mfds_identity(state: QuoteReviewState) -> None:
    if not state.items:
        return
    for index, item in enumerate(state.items):
        if index in state.mfds_identity:
            continue
        lookup_key = (item.model_name or item.product_name or "").strip()
        if not lookup_key:
            continue
        state.mfds_identity[index] = lookup_mfds_identity_from_r2(lookup_key)


def _ensure_safety_lookup(state: QuoteReviewState) -> None:
    if not state.items:
        return
    for index, item in enumerate(state.items):
        if index in state.safety_lookup:
            continue
        model_name = (item.model_name or "").strip()
        product_name = (item.product_name or "").strip()
        if not model_name and not product_name:
            continue
        try:
            lookup = lookup_mfds_recall(
                model_name=model_name,
                product_name=product_name,
            )
        except Exception as exc:
            _record_item_failure(state, index, "Safety", exc)
            continue
        state.safety_lookup[index] = lookup
        if lookup.status == "failure":
            failures = state.item_research_failures.setdefault(index, {})
            failures["Safety"] = lookup.error_type or "SafetyLookupError"
        else:
            _clear_item_failure(state, index, "Safety")


def _ensure_market_research(state: QuoteReviewState) -> bool:
    if not state.items:
        return False
    missing = [index for index in range(len(state.items)) if index not in state.search_runs]
    if not missing:
        return False

    progress = st.progress(0, text="추가 공개자료를 조사하고 있습니다...")
    total = len(missing)
    for done, index in enumerate(missing, start=1):
        item = state.items[index]
        query = _quote_item_unified_query(state, index)
        progress.progress(
            (done - 1) / total,
            text=(
                f"{index + 1}/{len(state.items)} · "
                f"{item.product_name or item.model_name or '미확인 품목'} 조사 중"
            ),
        )
        try:
            run, discovery, market_bundle = run_market_research(
                query,
                lookback_days=state.lookback_days,
                research_pages_per_term=1,
                research_request_budget=18,
                procurement_detail_limit=4,
            )
        except Exception as exc:
            _record_item_failure(state, index, "추가 공개자료", exc)
            progress.progress(
                done / total,
                text=f"{index + 1}/{len(state.items)} · 조사 실패 · 다른 품목 계속 진행",
            )
            continue
        state.search_runs[index] = run
        state.discoveries[index] = discovery
        state.market_bundles[index] = market_bundle
        _clear_item_failure(state, index, "추가 공개자료")
    progress.progress(1.0, text="추가 공개자료 조사를 완료했습니다.")
    return True


def _render_transaction_table(rows: list[dict[str, object]]) -> None:
    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
    )


def _render_item_result(state: QuoteReviewState, index: int) -> None:
    item = state.items[index]
    query = _quote_item_unified_query(state, index)
    run = state.search_runs.get(index)
    discovery = state.discoveries.get(index)
    market_bundle = state.market_bundles.get(index)
    track_b = state.track_b_db.get(index)
    mfds = state.mfds_workspace.get(index)
    mfds_identity = state.mfds_identity.get(index)
    safety_lookup = state.safety_lookup.get(index)
    intelligence = build_quote_item_intelligence_summary(
        item=item,
        track_b=track_b,
        mfds_workspace=mfds,
        mfds_identity=mfds_identity,
        safety_lookup=safety_lookup,
    )

    with st.container(border=True):
        title = item.product_name or item.model_name or f"품목 {index + 1}"
        st.subheader(f"{index + 1}. {title}")
        identity_text = " · ".join(
            part for part in (item.manufacturer, item.model_name, item.specification) if part
        )
        st.caption(identity_text or "추가 식별정보 없음")

        status_cols = st.columns(5)
        status_cols[0].metric("같은 제품 거래", f"{intelligence.direct_count}건")
        status_cols[1].metric("식약처 허가 확인", intelligence.identity_status)
        status_cols[2].metric(
            "제조·수입업체",
            f"{len(intelligence.responsible_companies)}개"
            if intelligence.responsible_companies
            else "미확인",
        )
        status_cols[3].metric(
            "납품업체",
            f"{len(intelligence.supplier_names)}개",
        )
        status_cols[4].metric("회수·판매중지", intelligence.safety_status)
        if intelligence.responsible_companies:
            st.caption(
                "제조·수입업체(식약처) · " + " / ".join(intelligence.responsible_companies[:5])
                + " · "
                + intelligence.business_license_status
            )
        if intelligence.supplier_names:
            st.caption("납품업체(나라장터) · " + " / ".join(intelligence.supplier_names[:5]))
        if intelligence.permit_numbers:
            st.caption("허가번호 · " + " / ".join(intelligence.permit_numbers[:5]))
        if safety_lookup is not None and safety_lookup.status in {
            "success",
            "not_authorized",
            "failure",
        }:
            st.warning(intelligence.safety_message)
        else:
            st.caption(
                "회수·판매중지 자동 조회가 연결되지 않은 경우 공식 확인이 끝난 것으로 보지 않습니다."
            )

        price_col, info_col = st.columns([1.25, 3.75])
        price_col.metric("견적 단가", _money(item.unit_price))
        info_col.caption(
            "아래 표는 실제 수집된 거래가격을 우선 보여줍니다. 같은 제품인지 충분히 확인되지 않은 행은 "
            "'검색 참고'로 표시하며 견적 판정에는 쓰지 않습니다."
        )

        failures = state.item_research_failures.get(index, {})
        if failures:
            failure_text = " · ".join(_stage_label(stage) for stage in failures)
            st.warning(
                "이 품목의 일부 조사 단계가 실패했습니다. 다른 품목의 결과는 유지하며 "
                f"실패 단계만 다시 시도할 수 있습니다. 실패한 단계: {failure_text}"
            )

        permit_note = mfds_permit_note(mfds, mfds_identity)
        if permit_note is not None:
            note_level, note_text = permit_note
            {"success": st.success, "warning": st.warning}.get(note_level, st.info)(note_text)
        elif mfds is not None and mfds.status == "failure":
            st.warning("식약처 조회 실패 · 가격검색 결과와 분리해 유지합니다.")

        st.markdown("**나라장터 거래가격**")
        direct_rows = _track_b_candidate_rows(track_b.candidates) if track_b is not None else []
        reference_rows = (
            _track_b_reference_rows(track_b.reference_candidates) if track_b is not None else []
        )
        rows = direct_rows + reference_rows

        if rows:
            _render_transaction_table(rows)
            st.caption(
                f"동일성 확인 거래 {len(direct_rows)}건 · 검색 참고 {len(reference_rows)}건"
            )
            if track_b is not None:
                grouped_rows = model_price_group_rows(track_b)
                if grouped_rows:
                    with st.expander("모델·규격·조건별 거래가 요약", expanded=False):
                        st.dataframe(grouped_rows, use_container_width=True, hide_index=True)
                        st.caption(
                            "같은 제품으로 확인된 거래만 모아 계산합니다. 이름이 비슷한 거래는 합치지 않습니다."
                        )
            if track_b is not None and any(
                candidate.amount_check == "inconsistent" for candidate in track_b.candidates
            ):
                st.warning("일부 거래는 단가×수량과 총액이 일치하지 않아 원문 조건 확인이 필요합니다.")
        elif track_b is None or track_b.status == "unavailable":
            st.warning(
                "가격 검색 인덱스를 아직 사용할 수 없습니다. 인덱스 준비 후 같은 견적서에서 다시 검색할 수 있습니다."
            )
        elif track_b.status == "not_ingested":
            st.info("수집 자료의 빠른 가격 인덱스를 만드는 중입니다.")
        elif track_b.status == "insufficient_identity":
            st.info("품명 또는 모델명을 확인해 주세요.")
        else:
            st.info("현재 수집 범위에서는 이 품목의 거래가격을 찾지 못했습니다.")

        show_details = st.toggle(
            "상세 조사·근거 보기",
            value=False,
            key=f"quote_market_details_{index}",
        )
        if show_details:
            if track_b is not None and track_b.suggestions:
                st.markdown("**모델명 확인 후보**")
                st.dataframe(
                    _track_b_suggestion_rows(track_b.suggestions),
                    use_container_width=True,
                    hide_index=True,
                )

            render_market_reference_summary(
                discovery,
                query=query,
                quote_unit_price=item.unit_price,
                include_model_price_summary=False,
                include_related_candidates=False,
            )

            if run is not None and run.results:
                assessment = assess_prices(run.results, item.unit_price)
                st.markdown("**검증된 동일제품 직접가격 근거**")
                d1, d2, d3 = st.columns(3)
                d1.metric("직접근거", f"{assessment.observed_count}건")
                d2.metric("독립 출처", f"{assessment.source_count}개")
                d3.metric("신뢰도", assessment.confidence)
                render_observation_cards(run.results)
            else:
                st.caption("추가 공개출처의 동일제품 직접가격은 아직 확인되지 않았습니다.")

            render_model_price_research_summary(
                discovery,
                quote_unit_price=item.unit_price,
            )
            render_market_alternative_candidates(discovery, query=query)
            render_procurement_research(market_bundle)
            render_external_research_links(query)

            st.markdown("**비교조건·원문 근거**")
            if run is not None:
                render_source_status(run)
                if run.results:
                    render_evidence_table(run.results)
                    render_condition_table(run.results)
                    profiles = [build_price_condition_profile(evidence) for evidence in run.results]
                    if profiles:
                        average = round(
                            sum(profile.completeness_percent for profile in profiles) / len(profiles)
                        )
                        st.caption(f"직접근거 평균 조건명시율: {average}%")
            st.write(
                {
                    "견적 VAT": item.vat_status or "미확인",
                    "배송": item.delivery_condition or "미확인",
                    "설치": item.installation_condition or "미확인",
                    "옵션/구성": item.option_condition or "미확인",
                    "보증": item.warranty_condition or "미확인",
                    "유지보수": item.maintenance_condition or "미확인",
                }
            )


SELECTED_ITEM_SESSION_KEY = "quote_review_selected_item_v1"
TABLE_VERSION_SESSION_KEY = "quote_review_table_version_v1"
TABLE_ROW_HEIGHT = 44


def _selected_index(total: int) -> int:
    try:
        value = int(st.session_state.get(SELECTED_ITEM_SESSION_KEY, 0))
    except (TypeError, ValueError):
        value = 0
    return min(max(value, 0), max(total - 1, 0))


def _select_item(index: int) -> None:
    """Button callback: runs before the page script, so the table redraws with the new row."""

    st.session_state[SELECTED_ITEM_SESSION_KEY] = index
    st.session_state[TABLE_VERSION_SESSION_KEY] = (
        int(st.session_state.get(TABLE_VERSION_SESSION_KEY, 0)) + 1
    )


def _item_comparisons(state: QuoteReviewState) -> list[QuoteItemComparison]:
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    comparisons: list[QuoteItemComparison] = []
    for index, item in enumerate(state.items):
        failures = state.item_research_failures.get(index, {})
        intelligence = build_quote_item_intelligence_summary(
            item=item,
            track_b=state.track_b_db.get(index),
            mfds_workspace=state.mfds_workspace.get(index),
            mfds_identity=state.mfds_identity.get(index),
            safety_lookup=state.safety_lookup.get(index),
        )
        comparisons.append(
            build_item_comparison(
                index,
                item,
                state.track_b_db.get(index),
                today=today,
                failed="나라장터 가격" in failures,
                safety_status=intelligence.safety_status,
                live_status=(getattr(state, "track_b_live_status", None) or {}).get(index, ""),
            )
        )
    return comparisons


def _verdict_column():
    return st.column_config.MultiselectColumn(
        "판정",
        options=list(VERDICT_ORDER),
        color=[VERDICT_TABLE_COLORS[kind] for kind in VERDICT_ORDER],
        width=86,
    )


def _wide_column_config() -> dict[str, object]:
    return {
        "번호": st.column_config.NumberColumn("번호", width=34, format="%d"),
        "모델": st.column_config.TextColumn("모델", width=110),
        "품명": st.column_config.TextColumn("품명"),
        "수량": st.column_config.TextColumn("수량", width=44),
        "견적 단가": st.column_config.NumberColumn("견적 단가", format="localized", width=78),
        "거래 가운데 값": st.column_config.NumberColumn("거래 가운데 값", format="localized", width=88),
        "차이 %": st.column_config.NumberColumn("차이 %", format="%+.1f%%", width=54),
        "판정": _verdict_column(),
    }


def _compact_column_config() -> dict[str, object]:
    return {
        "모델": st.column_config.TextColumn("모델", width=108),
        "품명": st.column_config.TextColumn("품명"),
        "견적 단가": st.column_config.NumberColumn("견적 단가", format="localized", width=76),
        "거래 가운데 값": st.column_config.NumberColumn("거래 가운데 값", format="localized", width=90),
        "차이 %": st.column_config.NumberColumn("차이 %", format="%+.1f%%", width=58),
        "판정": _verdict_column(),
    }


def _item_grid(
    rows: list[dict[str, object]],
    *,
    name: str,
    version: int,
    selected: int,
    columns: tuple[str, ...],
    config: dict[str, object],
) -> int | None:
    """One selectable grid. Returns the row the reader just picked in it, if that changed."""

    with st.container(key=f"qr_grid_{name}"):
        event = st.dataframe(
            rows,
            key=f"quote_review_table_{name}_{version}",
            on_select="rerun",
            selection_mode="single-row-required",
            selection_default={"selection": {"rows": [selected]}},
            hide_index=True,
            width="stretch",
            row_height=TABLE_ROW_HEIGHT,
            height=TABLE_ROW_HEIGHT * min(len(rows), 10) + 34,
            column_order=columns,
            placeholder="—",
            column_config=config,
        )
    picked = list(getattr(getattr(event, "selection", None), "rows", None) or [])
    seen_key = f"quote_review_grid_seen_{name}_{version}"
    previous = st.session_state.get(seen_key, selected)
    current = int(picked[0]) if picked else previous
    st.session_state[seen_key] = current
    return current if current != previous and 0 <= current < len(rows) else None


def _render_item_table(
    state: QuoteReviewState,
    comparisons: list[QuoteItemComparison],
    selected: int,
) -> int:
    st.markdown(
        '<div class="qr-section-title">품목별 비교표</div>'
        '<div class="qr-section-sub">행을 누르면 그 품목의 비교 결과가 나옵니다.</div>',
        unsafe_allow_html=True,
    )
    version = int(st.session_state.get(TABLE_VERSION_SESSION_KEY, 0))
    rows = quote_review_table_rows(comparisons, state.items)
    # Two grids, one shown at a time by CSS: the full one on wide windows, a shorter one when the
    # side menu leaves little room (a 1024px window), so 판정 never scrolls out of sight.
    wide_pick = _item_grid(
        rows,
        name="wide",
        version=version,
        selected=selected,
        columns=QUOTE_TABLE_COLUMNS,
        config=_wide_column_config(),
    )
    compact_pick = _item_grid(
        rows,
        name="compact",
        version=version,
        selected=selected,
        columns=QUOTE_COMPACT_TABLE_COLUMNS,
        config=_compact_column_config(),
    )
    picked = wide_pick if wide_pick is not None else compact_pick
    if picked is not None and picked != selected:
        selected = picked
        st.session_state[SELECTED_ITEM_SESSION_KEY] = selected
    st.markdown(
        '<div class="qr-foot">금액 단위는 원이고, 견적 단가와 거래 가운데 값은 1단위 가격입니다. 거래 가운데 값은 같은 제품으로 확인된 '
        "나라장터 거래만, 가장 많이 쓰인 단위 하나로 계산합니다. 차이 %가 있어도 거래가 3건 미만이면 판정하지 않습니다.</div>",
        unsafe_allow_html=True,
    )

    item = state.items[selected]
    st.markdown(
        f'<div class="qr-subhead">{selected + 1}번 품목 견적 조건</div>'
        + condition_table_html(condition_rows(item, main_unit=comparisons[selected].main_unit)),
        unsafe_allow_html=True,
    )
    return selected


def _render_detail_card(state: QuoteReviewState, comparison: QuoteItemComparison) -> None:
    total = len(state.items)
    index = comparison.index
    st.markdown(detail_card_html(comparison, total=total), unsafe_allow_html=True)

    item = state.items[index]
    handoff = build_purchase_workspace_handoff(
        product_name=item.product_name,
        manufacturer=item.manufacturer,
        model_name=item.model_name,
        specification=item.specification,
        quote_unit_price=item.unit_price,
    )
    if handoff is not None:
        if st.button(
            "가격 조사에서 이 품목 자세히 보기 →",
            key=f"quote_open_purchase_workspace_{index}",
            type="primary",
            use_container_width=True,
        ):
            st.session_state[PURCHASE_WORKSPACE_HANDOFF_SESSION_KEY] = {**handoff.to_session_payload(), "source": "quote_review"}
            st.switch_page("pages/1_대시보드.py")
    else:
        st.caption("품명이나 모델명이 없어 가격 조사 화면으로 넘길 수 없습니다.")

    previous_col, next_col = st.columns(2)
    previous_col.button(
        "← 이전 품목",
        key="quote_review_previous_item",
        disabled=index <= 0,
        on_click=_select_item,
        args=(index - 1,),
        use_container_width=True,
    )
    next_col.button(
        "다음 품목 →",
        key="quote_review_next_item",
        disabled=index >= total - 1,
        on_click=_select_item,
        args=(index + 1,),
        use_container_width=True,
    )


def _render_empty_state(uploaded) -> None:
    if uploaded is not None:
        reason = html.escape(
            str(st.session_state.get(READ_ERROR_SESSION_KEY) or friendly_read_error(uploaded.name))
        )
        st.markdown(
            notice_html(
                f"{reason} 급하면 <b>가격 조사</b> 화면에서 모델명으로 바로 찾을 수 있습니다.",
                tone=TONE_WARN,
            ),
            unsafe_allow_html=True,
        )
        return
    st.markdown(
        notice_html(
            "견적서 파일을 올리면 품목을 모두 읽어, 품목마다 나라장터에서 같은 제품이 거래된 가격과 "
            "견적 단가를 나란히 보여줍니다. 품목이 여러 개여도 한 번에 비교합니다.",
            tone="info",
            icon="i",
        ),
        unsafe_allow_html=True,
    )


def _render_research_details(state: QuoteReviewState, selected: int) -> None:
    """Older per-item research views, folded so the comparison stays the first thing seen."""

    item = state.items[selected]
    label = item.model_name or item.product_name or f"품목 {selected + 1}"
    with st.expander(f"{selected + 1}번 품목({label}) 가격 · 거래 이력과 조사 자료", expanded=False):
        _render_item_result(state, selected)

    with st.expander("모든 품목 조사 상태", expanded=False):
        if state.diagnostics is not None:
            st.caption(f"견적서를 읽은 방법: {state.diagnostics.strategy_label}")
        integrated_summaries = [
            (
                index,
                state.items[index].product_name
                or state.items[index].model_name
                or f"품목 {index + 1}",
                build_quote_item_intelligence_summary(
                    item=state.items[index],
                    track_b=state.track_b_db.get(index),
                    mfds_workspace=state.mfds_workspace.get(index),
                    mfds_identity=state.mfds_identity.get(index),
                    safety_lookup=state.safety_lookup.get(index),
                ),
            )
            for index in range(len(state.items))
        ]
        st.markdown("### 품목별 조사 상태")
        st.caption(
            "품목마다 나라장터 같은 모델 거래, 식약처 허가 대조, 납품업체, 회수·판매중지 확인 상태를 "
            "한 번에 봅니다. 거래 건수와 가격대는 위 비교표와 같은 기준(최근 거래, 가장 많이 쓰인 단위)입니다."
        )
        st.dataframe(
            quote_item_intelligence_rows(integrated_summaries),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(PERMIT_VS_TRADES_NOTE)

        render_purchase_review_summary(state)

        total, completed, partial_failure, pending = _quote_processing_counts(state)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("전체 품목", f"{total}건")
        c2.metric("정상 처리", f"{completed}건")
        c3.metric("부분 실패", f"{partial_failure}건")
        c4.metric("대기", f"{pending}건")

        if any(index not in state.search_runs for index in range(len(state.items))):
            st.caption("입찰·계약·웹에 공개된 가격 자료를 품목마다 더 찾아볼 수 있습니다. 몇 분 걸릴 수 있습니다.")
            if st.button("추가 공개자료 더 찾기", key="quote_auto_start_external_research"):
                if _ensure_market_research(state):
                    st.rerun()


def _render_failure_retry(state: QuoteReviewState) -> None:
    failed_items = sorted(state.item_research_failures)
    if not failed_items:
        return
    st.warning(
        "일부 품목 조사에 실패했지만 다른 품목의 결과는 유지했습니다. "
        "실패 품목: " + ", ".join(str(index + 1) for index in failed_items)
    )
    with st.expander("실패한 조사만 다시 하기", expanded=True):
        for index in failed_items:
            item = state.items[index]
            label = item.product_name or item.model_name or f"품목 {index + 1}"
            st.markdown(f"**{index + 1}. {label}**")
            failures = dict(state.item_research_failures.get(index, {}))
            retry_columns = st.columns(max(len(failures), 1))
            for column, stage in zip(retry_columns, failures):
                column.caption(f"{_stage_label(stage)} 조사 실패")
                if column.button(
                    f"{_stage_label(stage)} 다시 조사",
                    key=f"quote_retry_{index}_{stage}",
                    use_container_width=True,
                ):
                    _retry_failed_stage(state, index, stage)
                    st.rerun()
    if st.button("실패 품목 전체 다시 조사", key="quote_retry_failed_items"):
        for index in failed_items:
            state.track_b_db.pop(index, None)
            state.mfds_workspace.pop(index, None)
            state.safety_lookup.pop(index, None)
            state.search_runs.pop(index, None)
            state.discoveries.pop(index, None)
            state.market_bundles.pop(index, None)
        state.item_research_failures.clear()
        st.rerun()


def _render_search_settings(state: QuoteReviewState) -> None:
    with st.expander("검색 설정", expanded=False):
        selected_lookback = int(
            st.selectbox(
                "나라장터 검색기간",
                options=G2B_LOOKBACK_OPTIONS,
                index=(
                    G2B_LOOKBACK_OPTIONS.index(state.lookback_days)
                    if state.lookback_days in G2B_LOOKBACK_OPTIONS
                    else G2B_LOOKBACK_OPTIONS.index(G2B_DEFAULT_LOOKBACK_DAYS)
                ),
                format_func=g2b_lookback_label,
                key="quote_auto_lookback",
            )
        )
        if selected_lookback != state.lookback_days:
            state.lookback_days = selected_lookback
            _clear_research(state)
            st.rerun()
        if st.button("가격 다시 검색", key="quote_auto_research_again"):
            _clear_research(state)
            st.rerun()


def _run_external_research_for_empty_items(state: QuoteReviewState) -> None:
    missing_market = [
        index for index in range(len(state.items)) if index not in state.search_runs
    ]
    if not missing_market:
        return
    zero_trade_items = [
        index
        for index in missing_market
        if (
            state.track_b_db.get(index) is None
            or (
                not state.track_b_db[index].candidates
                and not state.track_b_db[index].reference_candidates
            )
        )
    ]
    if zero_trade_items and len(state.items) <= 3:
        st.caption("거래가격이 없는 품목은 입찰·계약·웹 공개자료를 추가로 자동 조사합니다.")
        if _ensure_market_research(state):
            st.rerun()


def render_quote_market_research(state: QuoteReviewState) -> None:
    """견적서 검토: upload, summary cards, item table + selected item, then folded details.

    The table is a summary of several items; each item's full research opens in the 가격 조사
    screen (the same search as a typed model name) through the purchase-workspace handoff.
    """

    st.markdown(QUOTE_REVIEW_LAYOUT_CSS, unsafe_allow_html=True)
    uploaded = st.file_uploader(
        "견적서 파일",
        type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"],
        key="quote_auto_market_upload",
        help="PDF · Excel(.xlsx/.xls) · PNG · JPG/JPEG 견적서를 올릴 수 있습니다.",
    )
    st.caption(
        "올린 파일은 품목을 읽은 뒤 바로 지우고, 원문을 외부 AI 서비스로 보내지 않습니다."
    )
    newly_extracted = bool(
        uploaded is not None
        and (state.file_name != uploaded.name or state.extraction is None)
    )
    if newly_extracted and uploaded is not None:
        with st.spinner("견적서에서 품목을 읽고 있습니다..."):
            _store_extraction(uploaded, state, show_error=False)
        state.lookback_days = G2B_DEFAULT_LOOKBACK_DAYS
        # This page shows every item side by side; it no longer jumps to 가격 조사 with item 1.
        st.session_state.pop(QUOTE_AUTO_ROUTE_FILE_SESSION_KEY, None)
        _select_item(0)

    if state.extraction is None:
        _render_empty_state(uploaded)
        st.caption(
            "PDF · Excel(.xlsx/.xls) · PNG · JPG/JPEG 견적서를 올리면 품목을 추출하고 거래가격을 검색합니다."
        )
        return

    if not state.items:
        _render_inline_manual_item_form(state)
        return

    if any(index not in state.track_b_db for index in range(len(state.items))):
        with st.spinner(f"품목 {len(state.items)}개의 나라장터 거래가와 허가정보를 찾고 있습니다..."):
            _ensure_mfds_identity(state)
            _ensure_track_b_comparison(state)
            _ensure_mfds_workspace(state)
            _ensure_safety_lookup(state)
    else:
        _ensure_mfds_identity(state)
        _ensure_track_b_comparison(state)
        _ensure_mfds_workspace(state)
        _ensure_safety_lookup(state)

    comparisons = _item_comparisons(state)
    st.markdown(
        summary_cards_html(verdict_counts(comparisons), file_name=state.file_name or ""),
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div class="qr-rule"><b>판정 기준</b> · {html.escape(rule_sentence())}</div>',
        unsafe_allow_html=True,
    )

    selected = _selected_index(len(comparisons))
    table_col, detail_col = st.columns([67, 33], gap="small")
    with table_col:
        with st.container(border=True, key="qr_table_card"):
            selected = _render_item_table(state, comparisons, selected)
    with detail_col:
        with st.container(border=True, key="qr_detail_card"):
            _render_detail_card(state, comparisons[selected])

    if state.extraction.warnings:
        with st.expander(f"견적서를 읽을 때 확인할 점 {len(state.extraction.warnings)}건", expanded=False):
            for warning in state.extraction.warnings:
                st.warning(warning)
    _render_compact_item_editor(state)
    _render_failure_retry(state)
    _render_research_details(state, selected)
    _render_search_settings(state)
    _run_external_research_for_empty_items(state)
