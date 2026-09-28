from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import streamlit as st

from purchase_price.evidence_domain import IdentityEvidenceStatus, PriceEvidenceStatus
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_search_policy import (
    G2B_DEFAULT_LOOKBACK_DAYS,
    G2B_LOOKBACK_OPTIONS,
    g2b_lookback_label,
)
from purchase_price.services.market_survey_export import build_market_survey_workbook
from purchase_price.services.matching import normalize_text
from purchase_price.services.mfds_identity_index import (
    MfdsIdentityLookup,
    MfdsIdentityRecord,
)
from purchase_price.services.mfds_identity_presenter import (
    MFDS_PRODUCT_INFO_DATASET_URL,
    mfds_identity_status,
    mfds_item_authorization_type,
)
from purchase_price.services.mfds_identity_r2 import (
    lookup_mfds_identity_from_r2,
    lookup_same_mfds_product_from_r2,
)
from purchase_price.services.mfds_identity_status import (
    MfdsIdentityCollectionStatus,
    format_status_updated_at,
    get_mfds_identity_collection_status,
)
from purchase_price.services.mfds_workspace import (
    MfdsWorkspaceResult,
    research_mfds_for_workspace,
)
from purchase_price.services.pricing import assess_prices
from purchase_price.services.purchase_review import build_purchase_review_input
from purchase_price.services.purchase_workspace_handoff import (
    PURCHASE_WORKSPACE_HANDOFF_SESSION_KEY,
    parse_purchase_workspace_handoff,
)
from purchase_price.services.track_b_r2_quote_index import open_track_b_serving_snapshot
from purchase_price.services.unified_search_intent import (
    UnifiedSearchInterpretation,
    interpret_unified_search,
)
from purchase_price.ui.market_research import (
    render_market_reference_summary,
    render_procurement_research,
    run_market_research,
)
from purchase_price.ui.purchase_workspace import (
    build_purchase_workspace_stats,
    build_quote_position_message,
    supplier_rows,
)
from purchase_price.ui.quote_review_state import (
    QUOTE_REVIEW_STATE_SESSION_KEY,
    QuoteReviewState,
)
from purchase_price.ui.quote_review_steps import _store_extraction
from purchase_price.ui.runtime_secrets import hydrate_streamlit_runtime_secrets
from purchase_price.ui.track_b_transactions import (
    candidate_counts,
    has_transaction_candidates,
    model_price_group_rows,
    transaction_rows,
)
from purchase_price.ui.widgets import (
    evidence_rows,
    render_evidence_table,
    render_observation_cards,
    render_source_status,
)

HOME_SEARCH_STATE_KEY = "home_unified_search_result"
HOME_SEARCH_DETAILS_KEY = "home_search_details"
HOME_WORKSPACE_VIEW_KEY = "home_workspace_view"
WORKSPACE_VIEWS = {
    "price": "💰 가격 비교",
    "supplier": "🏢 업체·조달",
    "compare": "🔁 동일품목 비교",
}


def _parse_quote(value: str) -> Decimal | None:
    if not value.strip():
        return None
    try:
        return Decimal(value.replace(",", "").strip())
    except InvalidOperation as exc:
        raise ValueError("견적 단가는 숫자로 입력하세요.") from exc


def _identity_hydration(
    raw_search: str,
    *,
    product_name: str,
    manufacturer: str,
    model_name: str,
    specification: str,
) -> tuple[str, str, str, str, MfdsIdentityLookup | None]:
    if (
        not raw_search
        or product_name.strip()
        or manufacturer.strip()
        or model_name.strip()
        or specification.strip()
    ):
        return product_name, manufacturer, model_name, specification, None

    identity = lookup_mfds_identity_from_r2(raw_search)
    if identity.status != "success" or not identity.records:
        return product_name, manufacturer, model_name, specification, identity
    if identity.match_type not in {"permit", "udi", "model"}:
        return product_name, manufacturer, model_name, specification, identity

    products = identity.product_names
    models = identity.model_names
    return (
        products[0] if len(products) == 1 else product_name,
        manufacturer,
        models[0] if len(models) == 1 else model_name,
        specification,
        identity,
    )


def _match_grade_value(candidate: object) -> str:
    grade = getattr(candidate, "match_grade", None)
    return str(getattr(grade, "value", grade) or "").strip().upper()


def _strict_candidates_compat(track_b: object) -> tuple[object, ...]:
    return tuple(
        candidate
        for candidate in tuple(getattr(track_b, "candidates", ()) or ())
        if _match_grade_value(candidate) in {"A", "B"}
    )


def _split_transaction_rows_compat(track_b: object) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    rows = transaction_rows(track_b)
    direct = [row for row in rows if row.get("비교수준") == "동일 모델"]
    references = [row for row in rows if row.get("비교수준") != "동일 모델"]
    return direct, references


def _build_mfds_procurement_crosslinks(
    records,
    *,
    track_b_snapshot,
    current_model: str = "",
) -> list[dict[str, object]]:
    unique: dict[tuple[str, str, str], object] = {}
    for item in records:
        model = str(getattr(item, "model_name", "") or "").strip()
        if not model:
            continue
        key = (
            str(getattr(item, "permit_number", "") or "").strip(),
            model,
            str(getattr(item, "registered_company", "") or "").strip(),
        )
        unique.setdefault(key, item)

    items = list(unique.values())
    queries = tuple(
        ProductQuery(
            product_name=str(getattr(item, "product_name", "") or "").strip(),
            model_name=str(getattr(item, "model_name", "") or "").strip(),
        )
        for item in items
    )
    comparisons = track_b_snapshot.lookup_model_summaries(queries)

    rows: list[dict[str, object]] = []
    for item, comparison in zip(items, comparisons, strict=True):
        model = str(getattr(item, "model_name", "") or "").strip()
        company = str(getattr(item, "registered_company", "") or "").strip()
        direct = _strict_candidates_compat(comparison)
        prices = sorted(
            Decimal(str(candidate.price))
            for candidate in direct
            if getattr(candidate, "price", None) is not None
        )
        suppliers = sorted(
            {
                str(getattr(candidate, "supplier", "") or "").strip()
                for candidate in direct
                if str(getattr(candidate, "supplier", "") or "").strip()
            }
        )
        dates = sorted(
            str(getattr(candidate, "transaction_date", "") or "")
            for candidate in direct
            if getattr(candidate, "transaction_date", None)
        )
        rows.append(
            {
                "유형": mfds_item_authorization_type(item).value,
                "식약처 품목번호": getattr(item, "permit_number", None) or "",
                "모델": model,
                "현재 모델": "현재 모델" if normalize_text(model) == normalize_text(current_model) else "",
                "품목 책임주체": company,
                "UDI-DI": getattr(item, "udi_di", None) or "",
                "나라장터 상태": comparison.evidence_status.value,
                "나라장터 직접거래": (
                    len(direct)
                    if comparison.evidence_status != PriceEvidenceStatus.UNAVAILABLE
                    else None
                ),
                "나라장터 가격범위": (
                    f"{prices[0]:,.0f} ~ {prices[-1]:,.0f}원"
                    if prices
                    else "조회 불가"
                    if comparison.evidence_status == PriceEvidenceStatus.UNAVAILABLE
                    else "직접 동일성 확인 거래 0건"
                ),
                "최근거래": dates[-1] if dates else "",
                "실제 조달 공급업체": " / ".join(suppliers[:5]),
            }
        )
    return rows


def _load_mfds_collection_status() -> MfdsIdentityCollectionStatus:
    return get_mfds_identity_collection_status()


def _render_mfds_collection_status() -> None:
    status = _load_mfds_collection_status()
    if status.status == "unavailable":
        return

    if status.first_backfill_complete:
        label = "식약처 데이터 · 1차 전체수집 완료 · 자동 갱신 중"
    elif status.progress_percent is not None:
        label = f"식약처 데이터 수집 중 · {status.progress_percent:.1f}%"
    else:
        label = "식약처 데이터 수집 상태"

    with st.expander(label, expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("검색 인덱스", f"{status.row_count:,}행")
        if status.source_total_count:
            c2.metric("원천 전체", f"{status.source_total_count:,}행")
        else:
            c2.metric("원천 전체", "확인 중")
        c3.metric("다음 수집 위치", f"page {status.next_page:,}" if status.next_page else "미확인")
        c4.metric(
            "수집 모드",
            "일일 rolling refresh" if status.first_backfill_complete else "고속 백필",
        )
        if status.progress_fraction is not None:
            st.progress(status.progress_fraction)
        updated_at = format_status_updated_at(status.updated_at)
        if updated_at:
            st.caption(f"최근 인덱스 갱신 · {updated_at}")
        if status.first_backfill_complete:
            st.caption(
                "첫 전체 수집 이후에는 하루 1회 20,000행 단위 rolling refresh로 자동 전환합니다. "
                "식약처 API에 변경일자 delta 조건이 확인되기 전까지는 변경분만 받는 진짜 증분수집으로 표시하지 않습니다."
            )
        else:
            st.caption(
                "현재는 하루 2회, 실행당 최대 100,000행을 20,000행 checkpoint 단위로 저장합니다."
            )


def _ambiguous_identity_candidates(identity: MfdsIdentityLookup) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for item in identity.records:
        key = (
            str(item.product_name or "").strip(),
            str(item.permit_number or "").strip(),
            str(item.model_name or "").strip(),
            str(item.registered_company or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "품목": key[0] or "미확인",
                "식약처 품목번호": key[1] or "미확인",
                "유형": mfds_item_authorization_type(item).value,
                "모델": key[2] or "미확인",
                "품목 책임주체": key[3] or "미확인",
                "등급": str(item.grade or "").strip() or "미확인",
                "UDI-DI": str(item.udi_di or "").strip() or "미확인",
            }
        )
    return rows


def _candidate_identity_records(identity: MfdsIdentityLookup) -> list[MfdsIdentityRecord]:
    unique: dict[tuple[str, str, str, str], MfdsIdentityRecord] = {}
    for item in identity.records:
        key = (
            str(item.product_name or "").strip(),
            str(item.permit_number or "").strip(),
            str(item.model_name or "").strip(),
            str(item.registered_company or "").strip(),
        )
        unique.setdefault(key, item)
    return list(unique.values())


def _identity_selection_token(record: MfdsIdentityRecord) -> str:
    return "|".join(
        (
            normalize_text(record.permit_number),
            normalize_text(record.model_name),
            normalize_text(record.registered_company),
            normalize_text(record.product_name),
        )
    )


def _selected_identity_from_token(
    identity: MfdsIdentityLookup | None,
    token: str,
) -> MfdsIdentityRecord | None:
    cleaned = str(token or "").strip()
    if not cleaned or not isinstance(identity, MfdsIdentityLookup):
        return None
    matches = [
        record
        for record in identity.records
        if _identity_selection_token(record) == cleaned
    ]
    return matches[0] if len(matches) == 1 else None


def _render_identity_candidate_selection(state: dict[str, Any]) -> None:
    identity = state.get("mfds_identity")
    st.divider()
    st.caption("검색 후보 선택")
    st.subheader(state.get("heading") or state.get("search_text") or "검색 결과")
    st.warning(
        "동일 모델명이 여러 식약처 품목번호 또는 품목 책임주체에 연결되어 자동으로 하나를 선택하지 않습니다."
    )
    if not isinstance(identity, MfdsIdentityLookup) or not identity.records:
        st.info("후보 identity를 표시할 수 없습니다.")
        return

    candidates = _candidate_identity_records(identity)
    st.dataframe(
        _ambiguous_identity_candidates(identity),
        use_container_width=True,
        hide_index=True,
    )
    selected_index = st.selectbox(
        "조사할 제품 identity 선택",
        options=list(range(len(candidates))),
        format_func=lambda index: (
            f"{candidates[index].product_name or '품목 미확인'} · "
            f"{candidates[index].model_name or '모델 미확인'} · "
            f"[{mfds_item_authorization_type(candidates[index]).value}] "
            f"{candidates[index].permit_number or '품목번호 미확인'} · "
            f"{candidates[index].registered_company or '책임주체 미확인'}"
        ),
        key="workspace_v3_identity_candidate",
    )
    st.caption(
        "후보 선택 전에는 나라장터 직접가격을 특정 제품의 가격으로 연결하지 않습니다. "
        "품목 책임주체는 식약처 제품관계이며 나라장터 제조사 조건으로 자동 주입하지 않습니다."
    )
    if st.button("선택한 identity로 구매조사", type="primary"):
        selected = candidates[int(selected_index)]
        with st.status("선택한 제품 identity의 가격·조달근거를 조사하고 있습니다...", expanded=False) as status:
            resolved = _execute_search(
                search_text=state.get("search_text") or selected.model_name or "",
                product_name=selected.product_name or "",
                manufacturer="",
                model_name=selected.model_name or "",
                specification="",
                quote_text="",
                lookback_days=G2B_DEFAULT_LOOKBACK_DAYS,
                selected_identity=selected,
            )
            st.session_state[HOME_SEARCH_STATE_KEY] = resolved
            st.query_params["q"] = state.get("search_text") or selected.model_name or ""
            st.query_params["view"] = "price"
            st.query_params["identity"] = _identity_selection_token(selected)
            status.update(label="제품 identity 선택 완료", state="complete")
        st.rerun()


def _execute_search(
    *,
    search_text: str,
    product_name: str,
    manufacturer: str,
    model_name: str,
    specification: str,
    quote_text: str,
    lookback_days: int,
    selected_identity: MfdsIdentityRecord | None = None,
    selected_identity_token: str = "",
) -> dict[str, Any]:
    raw_search = search_text.strip()
    if selected_identity is None:
        (
            product_name,
            manufacturer,
            model_name,
            specification,
            indexed_identity,
        ) = _identity_hydration(
            raw_search,
            product_name=product_name,
            manufacturer=manufacturer,
            model_name=model_name,
            specification=specification,
        )
        token_identity = _selected_identity_from_token(
            indexed_identity,
            selected_identity_token,
        )
        if token_identity is not None:
            selected_identity = token_identity
            product_name = token_identity.product_name or product_name
            model_name = token_identity.model_name or model_name
            indexed_identity = MfdsIdentityLookup(
                "success",
                raw_search or model_name,
                "model",
                (token_identity,),
            )
    else:
        product_name = selected_identity.product_name or product_name
        model_name = selected_identity.model_name or model_name
        indexed_identity = MfdsIdentityLookup(
            "success",
            raw_search or model_name,
            "model",
            (selected_identity,),
        )
    if (
        isinstance(indexed_identity, MfdsIdentityLookup)
        and mfds_identity_status(indexed_identity) == IdentityEvidenceStatus.AMBIGUOUS
        and indexed_identity.match_type == "model"
    ):
        return {
            "route": "candidate_selection",
            "search_text": raw_search,
            "heading": raw_search,
            "mfds_identity": indexed_identity,
        }

    interpretation = interpret_unified_search(
        search_text=raw_search,
        product_name=product_name,
        manufacturer=manufacturer,
        model_name=model_name,
        specification=specification,
    )
    resolved_model = interpretation.model_name
    resolved_product = interpretation.product_name
    resolved_manufacturer = interpretation.manufacturer
    resolved_specification = interpretation.specification
    if (
        not resolved_product
        and not resolved_model
        and not resolved_manufacturer
        and not resolved_specification
    ):
        raise ValueError("품목 또는 모델명을 입력하세요.")

    quote = _parse_quote(quote_text)
    review_input = build_purchase_review_input(
        product_name=resolved_product,
        manufacturer=resolved_manufacturer,
        model_name=resolved_model,
        specification=resolved_specification,
        quote_unit_price=quote,
    )
    if review_input is None:
        raise ValueError("검색조건을 확인하세요.")
    query = review_input.to_product_query()

    model_probe_used = False
    with open_track_b_serving_snapshot() as track_b_snapshot:
        track_b = track_b_snapshot.lookup(
            query,
            quote_unit_price=review_input.quote_unit_price,
        )
        if (
            raw_search
            and not interpretation.model_name
            and not product_name.strip()
            and track_b.status == "success_0"
        ):
            model_probe_input = build_purchase_review_input(
                product_name=raw_search,
                manufacturer=resolved_manufacturer,
                model_name=raw_search,
                specification=resolved_specification,
                quote_unit_price=quote,
            )
            if model_probe_input is not None:
                model_probe_query = model_probe_input.to_product_query()
                model_probe = track_b_snapshot.lookup(
                    model_probe_query,
                    quote_unit_price=model_probe_input.quote_unit_price,
                )
                if has_transaction_candidates(model_probe):
                    track_b = model_probe
                    query = model_probe_query
                    model_probe_used = True

        identity_product = (
            indexed_identity.product_names[0]
            if isinstance(indexed_identity, MfdsIdentityLookup)
            and len(indexed_identity.product_names) == 1
            else resolved_product
        )
        exact_identity_records = (
            indexed_identity.records
            if isinstance(indexed_identity, MfdsIdentityLookup)
            and indexed_identity.status == "success"
            and indexed_identity.match_type == "permit"
            else ()
        )
        exact_identity_crosslinks = _build_mfds_procurement_crosslinks(
            exact_identity_records,
            track_b_snapshot=track_b_snapshot,
            current_model=query.model_name or "",
        )
        same_product_identity = (
            lookup_same_mfds_product_from_r2(identity_product) if identity_product else ()
        )
        mfds_procurement_crosslinks = _build_mfds_procurement_crosslinks(
            same_product_identity,
            track_b_snapshot=track_b_snapshot,
            current_model=query.model_name or "",
        )

    mfds = research_mfds_for_workspace(query, track_b)

    run, discovery, market_bundle = run_market_research(
        query,
        lookback_days=int(lookback_days),
        research_pages_per_term=1,
        research_request_budget=18,
        procurement_detail_limit=4,
    )
    rows = transaction_rows(track_b)
    direct_rows, reference_rows = _split_transaction_rows_compat(track_b)
    strict_count, reference_count = candidate_counts(track_b)
    return {
        "route": "workspace",
        "search_text": raw_search,
        "heading": (
            raw_search
            if isinstance(indexed_identity, MfdsIdentityLookup)
            and indexed_identity.match_type == "permit"
            else resolved_model or resolved_product or raw_search
        ),
        "review_input": review_input,
        "query": query,
        "track_b": track_b,
        "rows": rows,
        "direct_rows": direct_rows,
        "reference_rows": reference_rows,
        "strict_count": strict_count,
        "reference_count": reference_count,
        "model_probe_used": model_probe_used,
        "interpretation": interpretation,
        "run": run,
        "discovery": discovery,
        "market_bundle": market_bundle,
        "mfds": mfds,
        "mfds_identity": indexed_identity,
        "exact_identity_crosslinks": exact_identity_crosslinks,
        "same_product_identity": same_product_identity,
        "mfds_procurement_crosslinks": mfds_procurement_crosslinks,
    }


def _render_search_interpretation(
    interpretation: UnifiedSearchInterpretation,
) -> None:
    if not interpretation.auto_hydrated:
        return

    with st.container(border=True):
        st.markdown("**검색어 해석**")
        c1, c2, c3 = st.columns(3)
        c1.caption("품명")
        c1.write(interpretation.product_name or "미확인")
        c2.caption("제조사")
        c2.write(interpretation.manufacturer or "미확인")
        c3.caption("모델")
        c3.write(interpretation.model_name or "미확인")

        if interpretation.mapping_verified:
            st.success(
                "검증된 모델 매핑을 검색 편의용으로 적용했습니다. "
                "공식 동일제품 판정은 아래 A/B 근거에서 별도로 확인합니다."
            )
        else:
            st.info(
                "등록된 모델 검색 힌트로 입력을 구조화했습니다. "
                "이 해석 자체는 공식 조달분류나 동일제품 확정 근거가 아닙니다."
            )


def _money_text(value: Decimal | None) -> str:
    return f"{value:,.0f}원" if value is not None else "근거 없음"


def _render_search_result(state: dict[str, Any]) -> None:
    heading = state["heading"]
    review_input = state["review_input"]
    query = state["query"]
    track_b = state["track_b"]
    direct_rows = state.get("direct_rows")
    reference_rows = state.get("reference_rows")
    if not isinstance(direct_rows, list) or not isinstance(reference_rows, list):
        direct_rows, reference_rows = _split_transaction_rows_compat(track_b)
    strict_count = len(direct_rows)
    reference_count = len(reference_rows)
    run = state["run"]
    discovery = state["discovery"]
    market_bundle = state["market_bundle"]
    mfds = state.get("mfds")
    indexed_identity = state.get("mfds_identity")
    exact_identity_crosslinks = list(state.get("exact_identity_crosslinks") or [])
    same_product_identity = tuple(state.get("same_product_identity") or ())
    mfds_procurement_crosslinks = list(state.get("mfds_procurement_crosslinks") or [])
    interpretation = state.get("interpretation")
    quote_key = str(heading or "result").strip()
    default_quote = (
        f"{review_input.quote_unit_price:f}"
        if review_input.quote_unit_price is not None
        else ""
    )

    st.divider()
    st.caption("구매조사 워크스페이스")
    st.subheader(heading)
    if state.get("origin") == "quote":
        st.caption("견적서 품목에서 이어진 조사 · 견적단가를 비교기준으로 유지합니다.")

    st.info(
        "Safety 자동조회는 아직 공식 회수·판매중지 API 연결 전입니다. "
        "현재 화면에 경고가 없더라도 공식 안전정보 확인을 대체하지 않습니다."
    )

    if isinstance(indexed_identity, MfdsIdentityLookup) and indexed_identity.status == "success":
        with st.container(border=True):
            st.markdown("**식약처 누적 인덱스에서 검색어 확인**")
            i1, i2, i3, i4 = st.columns(4)
            i1.caption("검색 기준")
            i1.write(
                {
                    "permit": "식약처 품목번호",
                    "udi": "UDI-DI",
                    "model": "모델",
                    "company": "품목 책임주체",
                    "product": "품목",
                }.get(indexed_identity.match_type, indexed_identity.match_type or "미확인")
            )
            i2.caption("식약처 품목번호")
            i2.write(" / ".join(indexed_identity.permit_numbers[:5]) or "미확인")
            i3.caption("모델")
            i3.write(" / ".join(indexed_identity.model_names[:5]) or "미확인")
            i4.caption("품목 책임주체")
            i4.write(" / ".join(indexed_identity.companies[:5]) or "미확인")
            if indexed_identity.match_type == "permit":
                st.success(
                    f"식약처 품목번호 exact 일치 · 등록 모델 {len(indexed_identity.model_names)}개를 모델별 나라장터 직접가격과 교차조회합니다."
                )
                if len(indexed_identity.model_names) > 1:
                    st.caption(
                        "복수 모델 품목번호입니다. 하나를 대표모델로 임의 선택하지 않으며 아래 모델별 가격표를 기준으로 확인합니다."
                    )
            elif indexed_identity.match_type in {"udi", "model"}:
                st.caption("식약처 공식 identity exact 검색 결과입니다.")

    if isinstance(interpretation, UnifiedSearchInterpretation):
        _render_search_interpretation(interpretation)

    st.markdown("### 구매판단 요약")
    with st.form(f"workspace_quote_context::{quote_key}"):
        q1, q2, q3, q4, q5 = st.columns([2.2, 1.2, 1.2, 3.0, 1.2])
        quote_text = q1.text_input(
            "내 견적가",
            value=default_quote,
            placeholder="선택 · 숫자만 입력",
            key=f"workspace_quote_price::{quote_key}",
        )
        quote_unit = q2.text_input(
            "단위",
            placeholder="예: 대 / 개",
            key=f"workspace_quote_unit::{quote_key}",
        )
        vat_status = q3.selectbox(
            "VAT",
            options=["미확인", "포함", "별도"],
            key=f"workspace_quote_vat::{quote_key}",
        )
        quote_conditions = q4.text_input(
            "설치·운송 등 조건",
            placeholder="예: 설치 포함 · 운송 포함",
            key=f"workspace_quote_conditions::{quote_key}",
        )
        q5.form_submit_button("비교 반영", use_container_width=True)

    try:
        workspace_quote = _parse_quote(quote_text)
    except ValueError:
        workspace_quote = review_input.quote_unit_price
        st.warning("내 견적가는 숫자로 입력하세요. 직전 검색 기준값으로 표시합니다.")

    stats = build_purchase_workspace_stats(
        track_b=track_b,
        market_bundle=market_bundle,
        quote_unit_price=workspace_quote,
    )
    st.caption(
        build_quote_position_message(
            quote_unit_price=workspace_quote,
            stats=stats,
            unit=quote_unit,
            vat_status="" if vat_status == "미확인" else vat_status,
            conditions=quote_conditions,
        )
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    if getattr(track_b, "evidence_status", None) == PriceEvidenceStatus.UNAVAILABLE:
        c1.metric("직접 동일성 확인 거래", "조회 불가")
    else:
        c1.metric("직접 동일성 확인 거래", f"{stats.direct_count}건")
    if stats.min_price is not None and stats.max_price is not None:
        c2.metric(
            "직접가격 범위",
            f"{stats.min_price:,.0f} ~ {stats.max_price:,.0f}원",
        )
    elif getattr(track_b, "evidence_status", None) == PriceEvidenceStatus.UNAVAILABLE:
        c2.metric("직접가격 범위", "조회 불가")
    else:
        c2.metric("직접가격 범위", "직접근거 미확인")
    c3.metric("실제 조달 공급업체", f"{stats.supplier_count}개")

    if isinstance(indexed_identity, MfdsIdentityLookup) and indexed_identity.status == "success":
        mfds_metric = "품목번호 확인"
    elif isinstance(mfds, MfdsWorkspaceResult) and mfds.status in {"success", "success_0"}:
        if mfds.exact_ambiguous:
            mfds_metric = "복수 품목번호"
        elif mfds.exact_confirmed:
            mfds_metric = "exact 확인"
        elif mfds.records:
            mfds_metric = "품목 확인"
        else:
            mfds_metric = "0건"
    elif isinstance(mfds, MfdsWorkspaceResult) and mfds.status == "failure":
        mfds_metric = "조회 실패"
    else:
        mfds_metric = "대상 아님"
    c4.metric("식약처 품목정보", mfds_metric)
    c5.metric("공개조달 Research", f"{stats.research_count}건")

    if isinstance(mfds, MfdsWorkspaceResult) and mfds.exact_records:
        with st.container(border=True):
            st.markdown("**식약처 품목 identity**")
            i1, i2, i3 = st.columns(3)
            i1.caption("품목 / 모델")
            i1.write(
                " / ".join(
                    part
                    for part in (
                        mfds.exact_records[0].product_name,
                        mfds.exact_records[0].model_name,
                    )
                    if part
                )
                or "미확인"
            )
            i2.caption("식약처 품목번호")
            i2.write(" / ".join(mfds.permit_numbers) or "미확인")
            permit_dates = sorted(
                {
                    item.permit_date.isoformat()
                    for item in mfds.exact_records
                    if item.permit_date is not None
                }
            )
            i3.caption("식약처 처리일")
            i3.write(" / ".join(permit_dates) or "미확인")

    if (
        isinstance(indexed_identity, MfdsIdentityLookup)
        and indexed_identity.status == "success"
        and indexed_identity.match_type == "permit"
    ):
        st.markdown("#### 식약처 품목번호 기준 모델·조달가격 연결")
        if exact_identity_crosslinks:
            st.dataframe(
                exact_identity_crosslinks,
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "식약처 품목번호에 연결된 각 모델을 개별적으로 나라장터 A/B 직접거래와 교차조회합니다. "
                "식약처 품목 책임주체와 실제 조달 납품업체는 서로 다른 관계입니다."
            )
        else:
            st.info("식약처 품목정보는 확인됐지만 등록 모델 기준 나라장터 A/B 직접가격은 아직 확인되지 않았습니다.")

    if stats.median_price is not None:
        q1, q2, q3 = st.columns(3)
        q1.metric("직접가격 중앙값", _money_text(stats.median_price))
        q2.metric("최근 직접거래", stats.latest_transaction_date or "미확인")
        if review_input.quote_unit_price is not None:
            delta = stats.quote_vs_median_percent
            q3.metric(
                "현재 견적",
                _money_text(review_input.quote_unit_price),
                None if delta is None else f"{delta:+.1f}% vs 중앙값",
            )
        else:
            q3.metric("현재 견적", "미입력")

    if stats.direct_count:
        st.success(
            "A/B 동일성 확인 거래만 직접가격 범위에 포함했습니다. "
            "수량·총액·규격·납품조건은 가격 비교 영역에서 확인하세요."
        )
    elif stats.reference_count:
        st.warning(
            f"직접 비교 가능한 A/B 거래는 없고 참고거래가 {stats.reference_count}건 있습니다. "
            "참고가격은 A/B 직접가격 범위에 포함하지 않습니다."
        )
    elif stats.research_count:
        st.info(
            "납품요구 직접가격은 없지만 입찰·사전규격 등 Research 근거가 있습니다."
        )
    else:
        st.info("현재 연결된 공개 근거에서 가격·조달자료를 확인하지 못했습니다.")

    if stats.demand_institution_count:
        st.caption(f"A/B 직접거래 수요기관 {stats.demand_institution_count}개 확인")
    track_b_data_as_of = str(getattr(track_b, "data_as_of", "") or "").strip()
    if track_b_data_as_of:
        st.caption(f"나라장터 serving index 기준시각 · {track_b_data_as_of}")

    export_identity_rows: list[dict[str, object]] = []
    if isinstance(indexed_identity, MfdsIdentityLookup) and indexed_identity.records:
        export_identity_rows = [
            {
                "유형": mfds_item_authorization_type(item).value,
                "식약처 품목번호": item.permit_number or "미확인",
                "품목": item.product_name or "미확인",
                "모델": item.model_name or "미확인",
                "품목 책임주체": item.registered_company or "미확인",
                "UDI-DI": item.udi_di or "미확인",
                "식약처 처리일": item.permit_date or "미확인",
                "등급": item.grade or "미확인",
                "Source": MFDS_PRODUCT_INFO_DATASET_URL,
                "원문근거해시": (item.source_payload_sha256 or "")[:16] or "미확인",
            }
            for item in indexed_identity.records
        ]

    export_research_rows = [
        {"근거구분": "Track B 참고거래", **row}
        for row in reference_rows
    ]
    if run.results:
        export_research_rows.extend(
            {
                "근거구분": "공개시장 Research",
                "가격": row["단가"],
                "거래일": row["거래일"] or "미확인",
                "자료성격": row["자료성격"],
                "Source": row["출처"],
                "원문": row["URL"],
            }
            for row in evidence_rows(run.results)
        )

    export_payload = build_market_survey_workbook(
        search_identity={
            "검색어": state.get("search_text") or heading,
            "품목": getattr(query, "product_name", None) or "미확인",
            "제조사": getattr(query, "manufacturer", None) or "미확인",
            "모델": getattr(query, "model_name", None) or "미확인",
            "규격": getattr(query, "specification", None) or "미확인",
            "식약처 품목번호": (
                " / ".join(indexed_identity.permit_numbers)
                if isinstance(indexed_identity, MfdsIdentityLookup)
                else "미확인"
            ) or "미확인",
        },
        quote_context={
            "내 견적가": workspace_quote,
            "단위": quote_unit.strip() or "미확인",
            "VAT": vat_status,
            "설치·운송 등 조건": quote_conditions.strip() or "미확인",
        },
        direct_rows=direct_rows,
        research_rows=export_research_rows,
        supplier_rows=supplier_rows(track_b),
        identity_rows=export_identity_rows,
        data_as_of=getattr(track_b, "data_as_of", None),
    )
    safe_export_name = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in str(heading or "market_survey")
    ).strip("_") or "market_survey"
    st.download_button(
        "시장조사표 Excel 내려받기",
        data=export_payload,
        file_name=f"시장조사표_{safe_export_name}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"workspace_market_survey_export::{quote_key}",
        use_container_width=False,
    )
    st.caption(
        "Excel은 A/B 직접근거와 C/Research를 분리하고 Source·원문근거를 보존합니다. "
        "연결 Source가 신뢰 가능한 data_as_of를 제공하지 않으면 임의 날짜를 만들지 않고 '미확인'으로 기록합니다."
    )

    query_view = str(st.query_params.get("view") or "").strip()
    if query_view not in WORKSPACE_VIEWS:
        query_view = str(st.session_state.get(HOME_WORKSPACE_VIEW_KEY) or "price")
    if query_view not in WORKSPACE_VIEWS:
        query_view = "price"
    current_label = WORKSPACE_VIEWS[query_view]
    selected_label = st.segmented_control(
        "구매조사 영역",
        options=list(WORKSPACE_VIEWS.values()),
        default=current_label,
        selection_mode="single",
        key="workspace_v3_segment",
        label_visibility="collapsed",
    )
    selected_label = selected_label or current_label
    selected_view = next(
        key for key, label in WORKSPACE_VIEWS.items() if label == selected_label
    )
    st.session_state[HOME_WORKSPACE_VIEW_KEY] = selected_view
    if str(st.query_params.get("view") or "") != selected_view:
        st.query_params["view"] = selected_view

    if selected_view == "price":
        st.markdown("#### 나라장터 동일제품 직접거래")
        if state["model_probe_used"]:
            st.caption("입력어가 모델명과 일치해 모델 기준 결과를 우선 표시합니다.")

        if direct_rows:
            st.dataframe(
                direct_rows,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "가격": st.column_config.TextColumn("대당단가"),
                    "총액": st.column_config.TextColumn("거래총액"),
                    "금액검증": st.column_config.TextColumn("단가×수량 검증"),
                },
            )
            st.success(f"요약과 동일한 A/B 직접거래 {strict_count}건입니다.")
            grouped_rows = model_price_group_rows(track_b)
            if grouped_rows:
                st.markdown("#### 모델·규격·조건별 직접가격")
                st.dataframe(grouped_rows, use_container_width=True, hide_index=True)
                st.caption(
                    "A/B 직접근거만 집계합니다. C/Research 참고가격은 직접가격 범위에 합산하지 않습니다."
                )
        elif track_b.status == "unavailable":
            st.warning("가격 검색 인덱스에 연결하지 못했습니다.")
        elif track_b.status == "not_ingested":
            st.info("수집 자료의 빠른 가격 인덱스를 만드는 중입니다.")
        else:
            st.info("요약과 동일하게 A/B 동일제품 직접거래는 0건입니다.")

        if reference_rows:
            st.warning(
                f"검색 참고거래 {reference_count}건은 실제 관측 거래지만 동일제품으로 확정되지 않았습니다. "
                "직접가격·시장범위·공급업체 집계에는 포함하지 않습니다."
            )
            with st.expander(
                f"검색 참고거래 {reference_count}건 보기 · 동일제품 직접가격 아님",
                expanded=False,
            ):
                st.dataframe(
                    reference_rows,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "가격": st.column_config.TextColumn("관측 단가"),
                        "총액": st.column_config.TextColumn("거래총액"),
                        "금액검증": st.column_config.TextColumn("단가×수량 검증"),
                    },
                )
                st.caption(
                    "품목·분류 또는 검색어 수준의 참고근거입니다. 모델·규격·옵션 동일성이 확인되기 전에는 직접 비교하지 않습니다."
                )

        if not direct_rows and run.results:
            public_rows = evidence_rows(run.results)
            with st.expander("기타 공개 시장가격 보기 · 직접가격 아님", expanded=False):
                st.dataframe(
                    [
                        {
                            "가격": row["단가"],
                            "출처": row["출처"],
                            "거래일": row["거래일"] or "미확인",
                            "자료성격": row["자료성격"],
                            "URL": row["URL"],
                        }
                        for row in public_rows
                    ],
                    use_container_width=True,
                    hide_index=True,
                    column_config={"가격": st.column_config.NumberColumn("가격", format="%d원")},
                )

        st.divider()
        st.markdown("#### 참고근거 · Research")
        st.markdown("#### 공개조달 Research·근거")
        render_market_reference_summary(
            discovery,
            query=query,
            quote_unit_price=review_input.quote_unit_price,
        )
        render_procurement_research(market_bundle)
        render_source_status(run)
        if run.results:
            assessment = assess_prices(run.results, review_input.quote_unit_price)
            m1, m2, m3 = st.columns(3)
            m1.metric("직접가격 근거", f"{assessment.observed_count}건")
            m2.metric("독립 출처", f"{assessment.source_count}개")
            m3.metric("근거 신뢰도", assessment.confidence)
            render_observation_cards(run.results)
            render_evidence_table(run.results)
        else:
            st.caption("엄격한 동일제품 직접가격은 현재 조사 범위에서 확인되지 않았습니다.")

    elif selected_view == "supplier":
        st.markdown("#### 식약처 품목·Identity")
        if isinstance(indexed_identity, MfdsIdentityLookup):
            if indexed_identity.status == "success" and indexed_identity.records:
                st.markdown("##### 누적 Identity Index")
                st.dataframe(
                    [
                        {
                            "유형": mfds_item_authorization_type(item).value,
                            "식약처 품목번호": item.permit_number or "",
                            "품목": item.product_name or "",
                            "모델": item.model_name or "",
                            "품목 책임주체": item.registered_company or "",
                            "UDI-DI": item.udi_di or "",
                            "식약처 처리일": item.permit_date or "",
                            "등급": item.grade or "",
                            "Source": MFDS_PRODUCT_INFO_DATASET_URL,
                            "원문근거해시": (item.source_payload_sha256 or "")[:16],
                        }
                        for item in indexed_identity.records
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
                st.caption(
                    "식약처 공식 제품정보를 수집한 누적 인덱스입니다. 품목 책임주체는 제조·수입 제품관계이며 실제 납품업체와 구분합니다."
                )
            elif mfds_identity_status(indexed_identity) == IdentityEvidenceStatus.NOT_FOUND_IN_COVERAGE:
                st.info("현재 수집된 식약처 자료 범위에서 일치 identity를 찾지 못했습니다.")
            elif indexed_identity.status == "not_ingested":
                st.info("식약처 Identity Index를 아직 사용할 수 없습니다.")
            elif indexed_identity.status == "unavailable":
                st.warning("식약처 Identity Index를 현재 읽을 수 없습니다.")

        if not isinstance(mfds, MfdsWorkspaceResult):
            st.info("식약처 조회 상태를 확인할 수 없습니다.")
        elif mfds.status == "not_applicable":
            st.info("현재 조달분류 기준으로 의료기기 자동조회 대상이 아닙니다.")
        elif mfds.status == "not_configured":
            st.warning("식약처 API 서비스키가 연결되지 않아 자동조회를 실행하지 못했습니다.")
        elif mfds.status == "failure":
            st.warning(
                f"식약처 조회 실패 · {mfds.error_type or '오류'} · "
                f"{mfds.error_message or '상세 미확인'}"
            )
            st.caption("API 실패를 등록 0건으로 해석하지 않습니다.")
        else:
            m1c, m2c, m3c = st.columns(3)
            m1c.metric("조회된 등록모델", f"{len(mfds.records)}건")
            m2c.metric("국내 정상 후보", f"{len(mfds.active_records)}건")
            if mfds.exact_ambiguous:
                m3c.metric("exact 모델", "복수 허가 · 확인 필요")
            elif mfds.exact_confirmed:
                m3c.metric("exact 모델", "확인")
            else:
                m3c.metric("exact 모델", "미확인")

            if mfds.exact_records:
                st.markdown("##### 입력 모델과 exact 일치")
                st.dataframe(
                    [
                        {
                            "품목": item.product_name or "",
                            "모델": item.model_name or "",
                            "식약처 품목번호": item.permit_number or "",
                            "식약처 처리일": item.permit_date.isoformat() if item.permit_date else "",
                            "업종": item.industry_type or "",
                            "수출전용": item.export_only,
                            "취소상태": item.cancellation_status or "",
                        }
                        for item in mfds.exact_records
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
                if mfds.permit_numbers:
                    st.caption("Safety 공식 확인키 · " + " / ".join(mfds.permit_numbers))

            st.info(
                "형명정보 API의 INDT_NM은 '업종'이며 업체명이 아닙니다. "
                "품목 책임주체는 누적 Identity Index의 공식 제품정보에 포함된 제조·수입업체 필드를 사용하며 실제 조달 납품업체와 구분합니다."
            )

            if mfds.business_records:
                st.markdown("##### 업체명 힌트 업허가 교차확인")
                st.dataframe(
                    [
                        {
                            "업체": item.company_name or "",
                            "업종": item.industry_type or "",
                            "상태": item.business_status or "",
                            "업 허가·신고 번호": item.business_permit_number or "",
                            "주소": item.address or "",
                            "현재사용가능": item.is_active,
                        }
                        for item in mfds.business_records
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
                st.caption(
                    "사용자/견적의 제조사·업체명 힌트에 대한 업허가 확인입니다. "
                    "해당 모델의 공식 제조·수입업체 관계를 자동 확정하지 않습니다."
                )

        st.page_link("pages/4_의료기기_조회.py", label="의료기기 상세 조회 화면 열기", icon="🏥")

        st.divider()
        if isinstance(indexed_identity, MfdsIdentityLookup) and indexed_identity.companies:
            st.markdown("#### 식약처 품목 책임주체")
            st.dataframe(
                [
                    {
                        "업체": company,
                        "근거": "식약처 제품정보 · 제조/수입 제품관계",
                    }
                    for company in indexed_identity.companies
                ],
                use_container_width=True,
                hide_index=True,
            )
            st.caption("아래 나라장터 실제 납품업체와 의미가 다릅니다.")

        st.markdown("#### 실제 조달 공급업체")
        procurement_suppliers = supplier_rows(track_b)
        if procurement_suppliers:
            st.dataframe(
                procurement_suppliers,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "최저단가": st.column_config.NumberColumn("최저단가", format="%d원"),
                    "최고단가": st.column_config.NumberColumn("최고단가", format="%d원"),
                },
            )
            st.caption(
                "A/B 동일제품으로 확인된 나라장터 납품요구의 공급업체만 집계합니다. "
                "한 번의 납품실적이 공식 총판관계를 의미하지는 않습니다."
            )
        elif getattr(track_b, "evidence_status", None) == PriceEvidenceStatus.UNAVAILABLE:
            st.warning("나라장터 가격 인덱스를 조회할 수 없어 조달 납품업체 상태를 확인하지 못했습니다.")
        else:
            st.info("직접 동일성 확인 거래 기준 조달 납품업체 0개입니다.")

        if isinstance(mfds, MfdsWorkspaceResult) and mfds.business_records:
            st.markdown("#### 식약처 업허가 교차확인")
            st.dataframe(
                [
                    {
                        "업체": item.company_name or "",
                        "업종": item.industry_type or "",
                        "상태": item.business_status or "",
                        "업 허가·신고 번호": item.business_permit_number or "",
                        "근거": "식약처 업허가 · 모델 공급관계 미확정",
                    }
                    for item in mfds.business_records
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.caption(
                "식약처 제조·수입 업체명 자동 연결은 company-bearing 제품 Source의 "
                "공식 역검색 계약 확인 후 추가합니다."
            )

    else:
        if (
            isinstance(indexed_identity, MfdsIdentityLookup)
            and indexed_identity.status == "success"
            and indexed_identity.match_type == "permit"
        ):
            st.markdown("#### 검색한 식약처 품목번호 → 등록모델 → 나라장터 가격")
            if exact_identity_crosslinks:
                st.dataframe(
                    exact_identity_crosslinks,
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("검색한 식약처 품목번호의 모델은 확인됐지만 나라장터 A/B 직접거래 연결은 확인되지 않았습니다.")

        st.markdown("#### 동일 품목 → 품목 책임주체 → 모델 → 식약처 품목번호 → 나라장터 가격")
        active_live_keys: set[tuple[str, str]] = set()
        if isinstance(mfds, MfdsWorkspaceResult) and mfds.status in {"success", "success_0"}:
            active_live_keys = {
                (
                    normalize_text(item.permit_number),
                    normalize_text(item.model_name),
                )
                for item in mfds.active_records
                if item.permit_number and item.model_name
            }
        priced_active_crosslinks = [
            row
            for row in mfds_procurement_crosslinks
            if int(row.get("나라장터 직접거래") or 0) > 0
            and (
                normalize_text(str(row.get("식약처 품목번호") or "")),
                normalize_text(str(row.get("모델") or "")),
            )
            in active_live_keys
        ]
        if priced_active_crosslinks:
            st.dataframe(
                priced_active_crosslinks,
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "동일품목 비교에서는 나라장터 A/B 직접근거가 있고 식약처 live에서 국내 정상 상태를 확인한 모델만 기본 표시합니다. "
                "취소·취하 또는 수출전용 상태는 기본 비교에서 제외하며, 현재 검색모델은 별도 표시합니다. "
                "품목 책임주체와 조달 납품업체는 별도 관계입니다."
            )
        elif same_product_identity and not active_live_keys:
            st.info(
                "동일품목 등록정보는 확인됐지만 식약처 live 상태를 확인하지 못해 "
                "취소·취하·수출전용 여부를 추정하지 않고 기본 비교표를 표시하지 않습니다."
            )
        elif same_product_identity:
            st.info(
                "국내 정상 상태가 확인된 동일품목 중 나라장터 A/B 직접가격이 있는 모델을 확인하지 못했습니다."
            )
        else:
            st.caption("식약처 누적 인덱스가 채워지면 품목번호별 모델·품목 책임주체·나라장터 직접가격을 연결합니다.")

        st.markdown("#### 식약처 live 동일품목 등록장비")
        if isinstance(mfds, MfdsWorkspaceResult) and mfds.active_competitor_records:
            st.dataframe(
                [
                    {
                        "모델": item.model_name or "",
                        "상품명": item.trade_name or "",
                        "식약처 품목번호": item.permit_number or "",
                        "식약처 처리일": item.permit_date.isoformat() if item.permit_date else "",
                        "업종": item.industry_type or "",
                    }
                    for item in mfds.active_competitor_records
                ],
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "동일 식약처 품목의 국내 정상 등록모델입니다. "
                "임상적 대체 가능성·성능동등성·수가조건을 자동 판정하지 않습니다."
            )
        elif isinstance(mfds, MfdsWorkspaceResult) and mfds.status in {"success", "success_0"}:
            st.info("현재 조회 결과에서 다른 국내 정상 등록모델을 확인하지 못했습니다.")
        else:
            st.info("식약처 품목 조회가 완료되면 국내 정상 동일품목 후보를 표시합니다.")
        st.page_link("pages/4_의료기기_조회.py", label="의료기기 상세 조회 화면 열기", icon="🏥")



hydrate_streamlit_runtime_secrets()
st.set_page_config(page_title="구매가격 검색", page_icon="🔎", layout="wide")
st.markdown(
    '<span id="unified-search-runtime-v3" style="display:none">unified-search-runtime-v3</span>'
    '<span id="unified-search-runtime-v4" style="display:none">unified-search-runtime-v4</span>'
    '<span id="purchase-workspace-runtime-v1" style="display:none">purchase-workspace-runtime-v1</span>'
    '<span id="purchase-workspace-runtime-v2" style="display:none">purchase-workspace-runtime-v2</span>'
    '<span id="purchase-workspace-mfds-v1" style="display:none">purchase-workspace-mfds-v1</span>'
    '<span id="purchase-workspace-mfds-v2" style="display:none">purchase-workspace-mfds-v2</span>'
    '<span id="purchase-workspace-quote-v1" style="display:none">purchase-workspace-quote-v1</span>'
    '<span id="purchase-workspace-v3-shell" style="display:none">purchase-workspace-v3-shell</span>',
    unsafe_allow_html=True,
)

st.markdown(
    """
<style>
.block-container {max-width: 1180px; padding-top: 2.2rem;}
[data-testid="stForm"] {border: 0; padding: 0;}
[data-testid="stFileUploader"] {margin-top: 0.2rem;}
.home-kicker {text-align:center; color:#6b7280; font-size:0.95rem; margin-bottom:0.15rem;}
.home-title {text-align:center; font-size:2.35rem; font-weight:750; margin:0.2rem 0 0.35rem 0;}
.home-subtitle {text-align:center; color:#6b7280; margin-bottom:1.6rem;}
.home-section {margin-top:1.15rem;}
</style>
""",
    unsafe_allow_html=True,
)

existing_result = isinstance(st.session_state.get(HOME_SEARCH_STATE_KEY), dict)
handoff_pending = PURCHASE_WORKSPACE_HANDOFF_SESSION_KEY in st.session_state
if not existing_result and not handoff_pending:
    st.markdown('<div class="home-kicker">공개 조달·시장근거 기반 구매검토</div>', unsafe_allow_html=True)
    st.markdown('<div class="home-title">무엇을 조사할까요?</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="home-subtitle">모델명만 입력해도 알려진 모델 힌트를 안전하게 구조화해 가격·공급·조달근거를 함께 찾습니다.</div>',
        unsafe_allow_html=True,
    )
    
    _render_mfds_collection_status()

handoff_payload = st.session_state.pop(PURCHASE_WORKSPACE_HANDOFF_SESSION_KEY, None)
handoff = parse_purchase_workspace_handoff(handoff_payload)
if handoff is not None:
    try:
        with st.status("견적서 품목의 가격·등록·공급근거를 조사하고 있습니다...", expanded=False) as status:
            search_state = _execute_search(
                search_text="",
                product_name=handoff.product_name,
                manufacturer=handoff.manufacturer,
                model_name=handoff.model_name,
                specification=handoff.specification,
                quote_text=(
                    str(handoff.quote_unit_price)
                    if handoff.quote_unit_price is not None
                    else ""
                ),
                lookback_days=G2B_DEFAULT_LOOKBACK_DAYS,
            )
            search_state["origin"] = "quote"
            st.session_state[HOME_SEARCH_STATE_KEY] = search_state
            status.update(label="견적 품목 구매조사 완료", state="complete")
    except ValueError as exc:
        st.warning(f"견적 품목 연결 실패: {exc}")

search_state = st.session_state.get(HOME_SEARCH_STATE_KEY)
shared_query = str(st.query_params.get("q") or "").strip()
if not isinstance(search_state, dict) and shared_query and handoff is None:
    try:
        with st.status("공유된 검색조건을 복원하고 있습니다...", expanded=False) as status:
            search_state = _execute_search(
                search_text=shared_query,
                product_name="",
                manufacturer="",
                model_name="",
                specification="",
                quote_text="",
                lookback_days=G2B_DEFAULT_LOOKBACK_DAYS,
                selected_identity_token=str(st.query_params.get("identity") or ""),
            )
            st.session_state[HOME_SEARCH_STATE_KEY] = search_state
            status.update(label="검색결과 복원 완료", state="complete")
            st.rerun()
    except ValueError as exc:
        st.warning(f"공유된 검색조건을 복원하지 못했습니다: {exc}")

search_state = st.session_state.get(HOME_SEARCH_STATE_KEY)
result_mode = isinstance(search_state, dict)
default_query = (
    str(search_state.get("search_text") or search_state.get("heading") or "")
    if result_mode
    else str(st.query_params.get("q") or "")
)

uploaded = None
if result_mode:
    with st.form("home_unified_search_compact"):
        search_col, button_col, reset_col = st.columns([7.4, 1.3, 1.3], gap="small")
        search_text = search_col.text_input(
            "통합 검색",
            value=default_query,
            placeholder="모델명 · 식약처 품목번호 · UDI-DI · 품목 · 업체",
            label_visibility="collapsed",
        )
        submitted = button_col.form_submit_button("검색", type="primary", use_container_width=True)
        reset_requested = reset_col.form_submit_button("새 검색", use_container_width=True)
        product_name = ""
        manufacturer = ""
        model_name = ""
        specification = ""
        quote_text = ""
        lookback_days = G2B_DEFAULT_LOOKBACK_DAYS

    if reset_requested:
        st.session_state.pop(HOME_SEARCH_STATE_KEY, None)
        st.session_state.pop(HOME_WORKSPACE_VIEW_KEY, None)
        st.query_params.clear()
        st.rerun()

    with st.expander("견적서 업로드 · 상세 검색", expanded=False):
        st.caption("결과 화면에서는 검색 보조기능을 접어두고 구매조사 결과를 우선 표시합니다.")
        uploaded = st.file_uploader(
            "견적서 업로드",
            type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"],
            label_visibility="collapsed",
            key="home_quote_upload_result",
        )
else:
    with st.form("home_unified_search"):
        search_col, button_col = st.columns([8, 1.35], gap="small")
        search_text = search_col.text_input(
            "통합 검색",
            value=default_query,
            placeholder="모델명 · 식약처 품목번호 · UDI-DI · 품목 · 업체",
            label_visibility="collapsed",
        )
        submitted = button_col.form_submit_button("검색", type="primary", use_container_width=True)

        st.caption(
            "한 줄 검색은 식약처 누적 인덱스의 품목번호·UDI·모델과 검증된 제품 힌트를 우선 해석합니다. "
            "정확한 품명·제조사·모델을 알고 있으면 아래 조건에서 직접 수정할 수 있습니다."
        )

        with st.expander("정확도 높이기 · 상세 검색조건", expanded=False):
            a1, a2 = st.columns(2)
            product_name = a1.text_input("품명", placeholder="예: 가스마취기")
            manufacturer = a2.text_input("제조사", placeholder="예: Getinge / Maquet")
            model_name = a1.text_input("모델명", placeholder="예: FLOW-C")
            specification = a2.text_input("규격", placeholder="선택")
            quote_text = a1.text_input("현재 견적 단가", placeholder="선택 · 예: 66000000")
            lookback_days = a2.selectbox(
                "나라장터 검색기간",
                options=G2B_LOOKBACK_OPTIONS,
                index=G2B_LOOKBACK_OPTIONS.index(G2B_DEFAULT_LOOKBACK_DAYS),
                format_func=g2b_lookback_label,
            )

    st.markdown('<div class="home-section"></div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("**견적서로 바로 시작**")
        st.caption("PDF · Excel · 이미지 견적서를 올리면 품목을 추출하고 같은 형식으로 거래가격을 찾습니다.")
        uploaded = st.file_uploader(
            "견적서 업로드",
            type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"],
            label_visibility="collapsed",
            key="home_quote_upload",
        )

if uploaded is not None:
    if QUOTE_REVIEW_STATE_SESSION_KEY not in st.session_state:
        st.session_state[QUOTE_REVIEW_STATE_SESSION_KEY] = QuoteReviewState()
    quote_state: QuoteReviewState = st.session_state[QUOTE_REVIEW_STATE_SESSION_KEY]
    if quote_state.file_name != uploaded.name or quote_state.extraction is None:
        with st.spinner("견적서에서 품목을 추출하고 있습니다..."):
            _store_extraction(uploaded, quote_state)
    st.switch_page("pages/2_견적_검토.py")

if submitted:
    try:
        with st.status("가격·거래근거를 조사하고 있습니다...", expanded=False) as status:
            search_state = _execute_search(
                search_text=search_text,
                product_name=product_name,
                manufacturer=manufacturer,
                model_name=model_name,
                specification=specification,
                quote_text=quote_text,
                lookback_days=int(lookback_days),
            )
            st.session_state[HOME_SEARCH_STATE_KEY] = search_state
            st.session_state[HOME_SEARCH_DETAILS_KEY] = False
            st.query_params["q"] = search_text.strip()
            st.query_params["view"] = "price"
            st.query_params.pop("identity", None)
            status.update(label="추가 자료 확인 완료", state="complete")
            st.rerun()
    except ValueError as exc:
        st.warning(str(exc))
        st.stop()


search_state = st.session_state.get(HOME_SEARCH_STATE_KEY)
if isinstance(search_state, dict):
    if search_state.get("route") == "candidate_selection":
        _render_identity_candidate_selection(search_state)
    else:
        _render_search_result(search_state)

st.caption(
    "검색 참고 가격은 실제 관측값이지만 동일제품으로 확정된 가격은 아닙니다. "
    "모델·규격·VAT·설치·옵션 조건이 확인된 경우에만 직접 비교합니다."
)
