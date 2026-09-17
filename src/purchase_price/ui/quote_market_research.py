from __future__ import annotations

import re
from dataclasses import replace

import streamlit as st

from purchase_price.services.g2b_search_policy import (
    G2B_DEFAULT_LOOKBACK_DAYS,
    G2B_LOOKBACK_OPTIONS,
    g2b_lookback_label,
)
from purchase_price.services.price_conditions import build_price_condition_profile
from purchase_price.services.pricing import assess_prices
from purchase_price.services.quote_extraction import parse_quote_decimal, quote_item_query
from purchase_price.services.track_b_db_quote_comparison import (
    TrackBIdentitySuggestion,
    TrackBQuoteCandidate,
    TrackBReferenceCandidate,
    lookup_track_b_quote,
)
from purchase_price.ui.market_research import (
    render_external_research_links,
    render_market_alternative_candidates,
    render_market_reference_summary,
    render_model_price_research_summary,
    render_procurement_research,
    run_market_research,
)
from purchase_price.ui.quote_review_contract import build_manual_quote_item
from purchase_price.ui.quote_review_state import QuoteReviewState
from purchase_price.ui.quote_review_steps import _store_extraction
from purchase_price.ui.widgets import (
    render_condition_table,
    render_evidence_table,
    render_observation_cards,
    render_source_status,
)

_FILENAME_SUFFIX_RE = re.compile(
    r"(?:^|[\s._-]+)(?:견적서?|quotation|estimate)"
    r"(?:[\s._-]*(?:\d+|v\d+|rev\d+|최종|final|copy|복사본))*$",
    re.IGNORECASE,
)


def _money(value) -> str:
    return f"{value:,.0f}원" if value is not None else "미확인"


def _quantity_unit(quantity, unit: str | None) -> str:
    if quantity is None and not unit:
        return "미확인"
    quantity_text = "" if quantity is None else f"{quantity:g}"
    return " ".join(part for part in (quantity_text, unit or "") if part) or "미확인"


def _comparison_label(candidate: TrackBQuoteCandidate) -> str:
    if candidate.match_grade.value in {"A", "B"}:
        return "동일 모델"
    return "동일 품목 참고"


def _track_b_candidate_rows(
    candidates: tuple[TrackBQuoteCandidate, ...],
) -> list[dict[str, object]]:
    return [
        {
            "가격": float(candidate.price),
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
            "가격": float(candidate.price),
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
    state.comparability_context.clear()
    state.approvals.clear()


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
    st.warning(
        "자동 추출 결과가 없습니다. 다른 검토 모드로 이동할 필요 없이 이 화면에서 핵심 품목정보를 입력하면 "
        "저장 직후 시장조사를 시작합니다."
    )
    if product_candidate:
        st.info(
            f"OCR이 품목 행을 확정하지 못해 파일명에서 품명 후보 `{product_candidate}`를 미리 채웠습니다. "
            "파일명 기반 후보이며 OCR 확정값이나 공식 제품식별값은 아닙니다. 확인 후 저장하세요."
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
        unit_price = c1.text_input("견적 단가", placeholder="예: 66000000")
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
                value="" if item.unit_price is None else format(item.unit_price, "f"),
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


def _ensure_track_b_comparison(state: QuoteReviewState) -> None:
    if not state.items:
        return
    for index, item in enumerate(state.items):
        if index not in state.track_b_db:
            state.track_b_db[index] = lookup_track_b_quote(
                quote_item_query(item), quote_unit_price=item.unit_price
            )


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
        query = quote_item_query(item)
        progress.progress(
            (done - 1) / total,
            text=(
                f"{index + 1}/{len(state.items)} · "
                f"{item.product_name or item.model_name or '미확인 품목'} 조사 중"
            ),
        )
        run, discovery, market_bundle = run_market_research(
            query,
            lookback_days=state.lookback_days,
            research_pages_per_term=1,
            research_request_budget=18,
            procurement_detail_limit=4,
        )
        state.search_runs[index] = run
        state.discoveries[index] = discovery
        state.market_bundles[index] = market_bundle
    progress.progress(1.0, text="추가 공개자료 조사를 완료했습니다.")
    return True


def _render_transaction_table(rows: list[dict[str, object]]) -> None:
    st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
        column_config={
            "가격": st.column_config.NumberColumn("가격", format="%d원"),
        },
    )


def _render_item_result(state: QuoteReviewState, index: int) -> None:
    item = state.items[index]
    query = quote_item_query(item)
    run = state.search_runs.get(index)
    discovery = state.discoveries.get(index)
    market_bundle = state.market_bundles.get(index)
    track_b = state.track_b_db.get(index)

    with st.container(border=True):
        title = item.product_name or item.model_name or f"품목 {index + 1}"
        st.subheader(f"{index + 1}. {title}")
        identity_text = " · ".join(
            part for part in (item.manufacturer, item.model_name, item.specification) if part
        )
        st.caption(identity_text or "추가 식별정보 없음")

        price_col, info_col = st.columns([1.25, 3.75])
        price_col.metric("견적 단가", _money(item.unit_price))
        info_col.caption(
            "아래 표는 실제 수집된 거래가격을 우선 보여줍니다. 동일성이 충분하지 않은 행은 "
            "'검색 참고'로 표시하며 견적 적정성 판정에는 자동 사용하지 않습니다."
        )

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


def render_quote_market_research(state: QuoteReviewState) -> None:
    st.caption(
        "견적서 품목별로 가격 · 판매처 · 구매처 · 거래일을 먼저 보여줍니다. "
        "검증 과정과 세부 근거는 필요할 때만 펼쳐볼 수 있습니다."
    )

    uploaded = st.file_uploader(
        "견적서 파일",
        type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"],
        key="quote_auto_market_upload",
    )
    if uploaded is not None and (state.file_name != uploaded.name or state.extraction is None):
        _store_extraction(uploaded, state)
        state.lookback_days = G2B_DEFAULT_LOOKBACK_DAYS

    if state.extraction is None:
        st.caption(
            "PDF · Excel(.xlsx/.xls) · PNG · JPG/JPEG 견적서를 올리면 품목을 추출하고 거래가격을 검색합니다."
        )
        return

    top1, top2, top3 = st.columns([1, 2.5, 1])
    top1.metric("추출 품목", f"{len(state.items)}건")
    top2.caption(f"파일: {state.file_name or '-'}")
    if top3.button("새 견적서"):
        st.session_state.pop("quote_review_state", None)
        st.rerun()

    if state.diagnostics is not None:
        st.caption(f"추출 경로: {state.diagnostics.strategy_label}")

    if state.extraction.warnings:
        with st.expander(f"추출 경고 {len(state.extraction.warnings)}건", expanded=False):
            for warning in state.extraction.warnings:
                st.warning(warning)

    if not state.items:
        _render_inline_manual_item_form(state)
        return

    _render_compact_item_editor(state)
    _ensure_track_b_comparison(state)

    st.subheader("가격 · 거래 이력")
    for index in range(len(state.items)):
        _render_item_result(state, index)

    missing_market = [
        index for index in range(len(state.items)) if index not in state.search_runs
    ]
    if missing_market:
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
        else:
            if st.button("추가 공개자료 더 찾기", key="quote_auto_start_external_research"):
                if _ensure_market_research(state):
                    st.rerun()

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
