from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import streamlit as st

from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_search_policy import (
    G2B_DEFAULT_LOOKBACK_DAYS,
    G2B_LOOKBACK_OPTIONS,
    g2b_lookback_label,
)
from purchase_price.services.mfds_identity_index import MfdsIdentityLookup
from purchase_price.services.mfds_identity_r2 import (
    lookup_mfds_identity_from_r2,
    lookup_same_mfds_product_from_r2,
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
from purchase_price.services.track_b_r2_quote_index import lookup_track_b_quote_from_r2
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
    companies = identity.companies
    return (
        products[0] if len(products) == 1 else product_name,
        companies[0] if len(companies) == 1 else manufacturer,
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


def _build_mfds_procurement_crosslinks(records, *, limit: int = 25) -> list[dict[str, object]]:
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

    rows: list[dict[str, object]] = []
    for item in list(unique.values())[:limit]:
        model = str(getattr(item, "model_name", "") or "").strip()
        product = str(getattr(item, "product_name", "") or "").strip()
        company = str(getattr(item, "registered_company", "") or "").strip()
        comparison = lookup_track_b_quote_from_r2(
            ProductQuery(
                product_name=product,
                model_name=model,
            ),
            quote_unit_price=None,
        )
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
                "허가번호": getattr(item, "permit_number", None) or "",
                "모델": model,
                "식약처 등록업체": company,
                "UDI-DI": getattr(item, "udi_di", None) or "",
                "나라장터 직접거래": len(direct),
                "나라장터 가격범위": (
                    f"{prices[0]:,.0f} ~ {prices[-1]:,.0f}원" if prices else "직접근거 없음"
                ),
                "최근거래": dates[-1] if dates else "",
                "실제 조달 공급업체": " / ".join(suppliers[:5]),
            }
        )
    return rows


def _execute_search(
    *,
    search_text: str,
    product_name: str,
    manufacturer: str,
    model_name: str,
    specification: str,
    quote_text: str,
    lookback_days: int,
) -> dict[str, Any]:
    raw_search = search_text.strip()
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

    track_b = lookup_track_b_quote_from_r2(query, quote_unit_price=review_input.quote_unit_price)
    model_probe_used = False
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
            model_probe = lookup_track_b_quote_from_r2(
                model_probe_query,
                quote_unit_price=model_probe_input.quote_unit_price,
            )
            if has_transaction_candidates(model_probe):
                track_b = model_probe
                query = model_probe_query
                model_probe_used = True

    mfds = research_mfds_for_workspace(query, track_b)
    identity_product = (
        indexed_identity.product_names[0]
        if isinstance(indexed_identity, MfdsIdentityLookup)
        and len(indexed_identity.product_names) == 1
        else resolved_product
    )
    same_product_identity = (
        lookup_same_mfds_product_from_r2(identity_product) if identity_product else ()
    )
    mfds_procurement_crosslinks = _build_mfds_procurement_crosslinks(
        same_product_identity,
        limit=25,
    )

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
        "heading": resolved_model or resolved_product or raw_search,
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
    same_product_identity = tuple(state.get("same_product_identity") or ())
    mfds_procurement_crosslinks = list(state.get("mfds_procurement_crosslinks") or [])
    interpretation = state.get("interpretation")
    stats = build_purchase_workspace_stats(
        track_b=track_b,
        market_bundle=market_bundle,
        quote_unit_price=review_input.quote_unit_price,
    )

    st.divider()
    st.caption("구매조사 워크스페이스")
    st.subheader(heading)
    if state.get("origin") == "quote":
        st.caption("견적서 품목에서 이어진 조사 · 견적단가를 비교기준으로 유지합니다.")

    st.info(
        "Safety 자동조회는 아직 공식 회수·판매중지 API 연결 전입니다. "
        "현재 화면에 경고가 없다는 사실을 '안전함'으로 해석하지 않습니다."
    )

    if isinstance(indexed_identity, MfdsIdentityLookup) and indexed_identity.status == "success":
        with st.container(border=True):
            st.markdown("**식약처 누적 인덱스에서 검색어 확인**")
            i1, i2, i3, i4 = st.columns(4)
            i1.caption("검색 기준")
            i1.write(
                {
                    "permit": "허가번호",
                    "udi": "UDI-DI",
                    "model": "모델",
                    "company": "등록업체",
                    "product": "품목",
                }.get(indexed_identity.match_type, indexed_identity.match_type or "미확인")
            )
            i2.caption("허가번호")
            i2.write(" / ".join(indexed_identity.permit_numbers[:5]) or "미확인")
            i3.caption("모델")
            i3.write(" / ".join(indexed_identity.model_names[:5]) or "미확인")
            i4.caption("식약처 등록업체")
            i4.write(" / ".join(indexed_identity.companies[:5]) or "미확인")

    if isinstance(interpretation, UnifiedSearchInterpretation):
        _render_search_interpretation(interpretation)

    st.markdown("**구매조사 메뉴**")
    st.caption(
        "직접가격과 참고거래를 분리해서 표시합니다. 식약처 허가정보와 공급근거도 같은 제품 identity에서 확인합니다."
    )
    summary_tab, price_tab, mfds_tab, supplier_tab, competitor_tab, research_tab = st.tabs(
        [
            "📌 요약",
            "💰 거래가격",
            "🏥 식약처·허가",
            "🏢 공급사",
            "🔁 경쟁장비",
            "📚 Research·근거",
        ]
    )

    with summary_tab:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("동일제품 거래", f"{stats.direct_count}건")
        if stats.min_price is not None and stats.max_price is not None:
            c2.metric(
                "직접가격 범위",
                f"{stats.min_price:,.0f} ~ {stats.max_price:,.0f}원",
            )
        else:
            c2.metric("직접가격 범위", "근거 없음")
        c3.metric("실제 조달 공급업체", f"{stats.supplier_count}개")

        if isinstance(indexed_identity, MfdsIdentityLookup) and indexed_identity.status == "success":
            mfds_metric = "허가 확인"
        elif isinstance(mfds, MfdsWorkspaceResult) and mfds.status in {"success", "success_0"}:
            if mfds.exact_ambiguous:
                mfds_metric = "복수 허가"
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
        c4.metric("식약처 등록", mfds_metric)
        c5.metric("공개조달 Research", f"{stats.research_count}건")

        if isinstance(mfds, MfdsWorkspaceResult) and mfds.exact_records:
            with st.container(border=True):
                st.markdown("**식약처 허가 identity**")
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
                i2.caption("허가번호")
                i2.write(" / ".join(mfds.permit_numbers) or "미확인")
                permit_dates = sorted(
                    {
                        item.permit_date.isoformat()
                        for item in mfds.exact_records
                        if item.permit_date is not None
                    }
                )
                i3.caption("허가일")
                i3.write(" / ".join(permit_dates) or "미확인")

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
                "수량·총액·규격·납품조건은 거래가격 탭에서 확인하세요."
            )
        elif stats.reference_count:
            st.warning(
                f"직접 비교 가능한 A/B 거래는 없고 참고거래가 {stats.reference_count}건 있습니다. "
                "참고가격은 적정가격 범위에 합산하지 않습니다."
            )
        elif stats.research_count:
            st.info(
                "납품요구 직접가격은 없지만 입찰·사전규격 등 Research 근거가 있습니다."
            )
        else:
            st.info("현재 연결된 공개 근거에서 가격·조달자료를 확인하지 못했습니다.")

        if stats.demand_institution_count:
            st.caption(f"A/B 직접거래 수요기관 {stats.demand_institution_count}개 확인")

    with price_tab:
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

    with mfds_tab:
        st.markdown("#### 식약처 허가·등록정보")
        if isinstance(indexed_identity, MfdsIdentityLookup):
            if indexed_identity.status == "success" and indexed_identity.records:
                st.markdown("##### 누적 Identity Index")
                st.dataframe(
                    [
                        {
                            "허가번호": item.permit_number or "",
                            "품목": item.product_name or "",
                            "모델": item.model_name or "",
                            "식약처 등록업체": item.registered_company or "",
                            "UDI-DI": item.udi_di or "",
                            "허가일": item.permit_date or "",
                            "등급": item.grade or "",
                        }
                        for item in indexed_identity.records
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
                st.caption(
                    "식약처 공식 제품정보를 수집한 누적 인덱스입니다. 등록업체는 제조·수입 관계이며 실제 납품업체와 구분합니다."
                )
            elif indexed_identity.status == "not_ingested":
                st.info("식약처 Identity Index 첫 백필이 아직 완료되지 않았습니다.")
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
                            "허가번호": item.permit_number or "",
                            "허가일": item.permit_date.isoformat() if item.permit_date else "",
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
                "업체 관계는 누적 Identity Index의 공식 제품정보에 포함된 제조·수입업체 필드를 우선 사용합니다."
            )

            if mfds.business_records:
                st.markdown("##### 업체명 힌트 업허가 교차확인")
                st.dataframe(
                    [
                        {
                            "업체": item.company_name or "",
                            "업종": item.industry_type or "",
                            "상태": item.business_status or "",
                            "업허가번호": item.business_permit_number or "",
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

    with supplier_tab:
        if isinstance(indexed_identity, MfdsIdentityLookup) and indexed_identity.companies:
            st.markdown("#### 식약처 제품 등록업체")
            st.dataframe(
                [
                    {
                        "업체": company,
                        "근거": "식약처 제품정보 · 제조/수입 등록관계",
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
        else:
            st.info("A/B 동일제품 기준으로 확인된 조달 공급업체가 없습니다.")

        if isinstance(mfds, MfdsWorkspaceResult) and mfds.business_records:
            st.markdown("#### 식약처 업허가 교차확인")
            st.dataframe(
                [
                    {
                        "업체": item.company_name or "",
                        "업종": item.industry_type or "",
                        "상태": item.business_status or "",
                        "업허가번호": item.business_permit_number or "",
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

    with competitor_tab:
        st.markdown("#### 동일 품목 → 허가번호 → 모델 → 등록업체 → 나라장터 가격")
        if mfds_procurement_crosslinks:
            st.dataframe(
                mfds_procurement_crosslinks,
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                f"식약처 누적 인덱스 동일품목 {len(same_product_identity)}행 중 모델 기준 최대 25개를 나라장터 A/B 직접근거와 교차조회합니다."
            )
        elif same_product_identity:
            st.info("동일품목 등록정보는 있으나 모델 기준 나라장터 교차조회 결과를 만들 수 없습니다.")
        else:
            st.caption("식약처 누적 인덱스가 채워지면 허가별 모델·등록업체·나라장터 직접가격을 연결합니다.")

        st.markdown("#### 식약처 live 동일품목 등록장비")
        if isinstance(mfds, MfdsWorkspaceResult) and mfds.active_competitor_records:
            st.dataframe(
                [
                    {
                        "모델": item.model_name or "",
                        "상품명": item.trade_name or "",
                        "허가번호": item.permit_number or "",
                        "허가일": item.permit_date.isoformat() if item.permit_date else "",
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

    with research_tab:
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


hydrate_streamlit_runtime_secrets()
st.set_page_config(page_title="구매가격 검색", page_icon="🔎", layout="wide")
st.markdown(
    '<span id="unified-search-runtime-v3" style="display:none">unified-search-runtime-v3</span>'
    '<span id="unified-search-runtime-v4" style="display:none">unified-search-runtime-v4</span>'
    '<span id="purchase-workspace-runtime-v1" style="display:none">purchase-workspace-runtime-v1</span>'
    '<span id="purchase-workspace-runtime-v2" style="display:none">purchase-workspace-runtime-v2</span>'
    '<span id="purchase-workspace-mfds-v1" style="display:none">purchase-workspace-mfds-v1</span>'
    '<span id="purchase-workspace-quote-v1" style="display:none">purchase-workspace-quote-v1</span>',
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
div[data-testid="stTabs"] [data-baseweb="tab-list"] {
  gap: 0.45rem;
  padding: 0.45rem;
  background: #f6f7f9;
  border: 1px solid #e5e7eb;
  border-radius: 0.8rem;
  flex-wrap: wrap;
}
div[data-testid="stTabs"] button[data-baseweb="tab"] {
  min-height: 2.75rem;
  padding: 0.55rem 0.9rem;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 0.65rem;
  font-weight: 650;
}
div[data-testid="stTabs"] button[data-baseweb="tab"][aria-selected="true"] {
  background: #fff1f2;
  border-color: #ff4b4b;
  color: #b42318;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.08);
}
div[data-testid="stTabs"] [data-baseweb="tab-highlight"] {display:none;}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown('<div class="home-kicker">공개 조달·시장근거 기반 구매검토</div>', unsafe_allow_html=True)
st.markdown('<div class="home-title">무엇을 조사할까요?</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="home-subtitle">모델명만 입력해도 알려진 모델 힌트를 안전하게 구조화해 가격·공급·조달근거를 함께 찾습니다.</div>',
    unsafe_allow_html=True,
)

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

with st.form("home_unified_search"):
    search_col, button_col = st.columns([8, 1.35], gap="small")
    with search_col:
        search_text = st.text_input(
            "통합 검색",
            placeholder="품목·모델·허가번호·제조사  예) DFM100, 수허 24-1234호, Philips Efficia DFM100",
            label_visibility="collapsed",
        )
    with button_col:
        submitted = st.form_submit_button("검색", type="primary", use_container_width=True)

    st.caption(
        "한 줄 검색은 식약처 누적 인덱스의 허가번호·UDI·모델과 검증된 제품 힌트를 우선 해석합니다. "
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
            status.update(label="추가 자료 확인 완료", state="complete")
    except ValueError as exc:
        st.warning(str(exc))
        st.stop()

search_state = st.session_state.get(HOME_SEARCH_STATE_KEY)
if isinstance(search_state, dict):
    _render_search_result(search_state)

st.caption(
    "검색 참고 가격은 실제 관측값이지만 동일제품으로 확정된 가격은 아닙니다. "
    "모델·규격·VAT·설치·옵션 조건이 확인된 경우에만 직접 비교합니다."
)
