from __future__ import annotations

import importlib
from datetime import datetime
from decimal import Decimal, InvalidOperation
from inspect import signature
from threading import Lock
from time import monotonic
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import streamlit as st

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL
from purchase_price.config import get_settings
from purchase_price.evidence_domain import (
    IdentityEvidenceStatus,
    PriceEvidenceStatus,
    SafetyEvidenceStatus,
)
from purchase_price.schemas import ProductQuery
from purchase_price.services import mfds_identity_r2 as mfds_identity_r2_service
from purchase_price.services import mfds_workspace as mfds_workspace_service
from purchase_price.services.g2b_search_policy import (
    G2B_DEFAULT_LOOKBACK_DAYS,
    G2B_LOOKBACK_OPTIONS,
    g2b_lookback_label,
)
from purchase_price.services.market_survey_export import build_market_survey_workbook
from purchase_price.services.matching import normalize_text
from purchase_price.services.mfds_api_keys import (
    mfds_json_client,
    mfds_model_info_json_client,
    mfds_service_key_candidates,
)
from purchase_price.services.mfds_business_license_view import build_business_license_view
from purchase_price.services.mfds_company_summary import (
    build_registered_company_summaries,
    company_identity_rows,
)
from purchase_price.services.mfds_device_intelligence import (
    MfdsBusinessLicenseClient,
    MfdsModelInfoClient,
)
from purchase_price.services.mfds_identity_corroboration import identity_needs_review
from purchase_price.services.mfds_identity_index import (
    MfdsIdentityLookup,
    MfdsIdentityRecord,
)
from purchase_price.services.mfds_identity_live import lookup_mfds_model_identity_live
from purchase_price.services.mfds_identity_live_policy import should_query_live_mfds_identity
from purchase_price.services.mfds_identity_presenter import (
    MFDS_PRODUCT_INFO_DATASET_URL,
    mfds_identity_status,
    mfds_item_authorization_type,
)
from purchase_price.services.mfds_identity_status import (
    MfdsIdentityCollectionStatus,
    format_status_updated_at,
    get_mfds_identity_collection_status,
)
from purchase_price.services.mfds_model_info_query import model_info_product_name
from purchase_price.services.mfds_recall import lookup_mfds_recall
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
from purchase_price.services.safety_support import (
    MFDS_ADMIN_SANCTION_PAGE_URL,
    MFDS_RECALL_PAGE_URL,
    MFDS_SAFETY_LETTER_PAGE_URL,
    build_manual_safety_check_state,
)
from purchase_price.services.search import SearchRun
from purchase_price.services.structured_query_identity import canonicalize_product_query
from purchase_price.services.track_b_live_gap_fill import (
    LIVE_TRANSACTION_TYPE,
    TrackBLiveGapFill,
    fetch_live_gap,
    indexed_detail_codes,
    live_gap_window,
    merge_live_gap,
)
from purchase_price.services.track_b_serving_snapshot import open_track_b_serving_snapshot
from purchase_price.services.unified_search_intent import (
    UnifiedSearchInterpretation,
    interpret_unified_search,
)
from purchase_price.ui import same_item_compare as same_item_ui
from purchase_price.ui import workspace_header as workspace_header_ui
from purchase_price.ui.market_research import (
    render_market_reference_summary,
    render_procurement_research,
    run_market_research,
)
from purchase_price.ui.production_runtime_compat import (
    mfds_recall_exception_result,
    normalize_mfds_recall_lookup,
    run_market_research_hot_reload_safe,
)
from purchase_price.ui.purchase_workspace_presenter import (
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

_MFDS_IDENTITY_R2_RELOAD_LOCK = Lock()


def _mfds_identity_r2_runtime():
    """Refresh only the leaf R2 adapter when Streamlit retained its pre-cache version."""

    module = mfds_identity_r2_service
    if hasattr(module, "_LOCAL_INDEX_PATH_CACHE"):
        return module

    with _MFDS_IDENTITY_R2_RELOAD_LOCK:
        if hasattr(module, "_LOCAL_INDEX_PATH_CACHE"):
            return module
        try:
            importlib.invalidate_caches()
            return importlib.reload(module)
        except Exception:
            return module


def _lookup_mfds_identity_runtime(query: str):
    module = _mfds_identity_r2_runtime()
    return module.lookup_mfds_identity_from_r2(query)


def _lookup_same_mfds_product_runtime(product_name: str):
    module = _mfds_identity_r2_runtime()
    return module.lookup_same_mfds_product_from_r2(product_name)


def _track_b_live_gap_fill(
    query: ProductQuery,
    *,
    detail_codes: tuple[str, ...],
    data_as_of: str | None,
    quote_unit_price: Decimal | None,
) -> TrackBLiveGapFill:
    """Live G2B lookup for the days after the collected index; never raises."""

    window = live_gap_window(data_as_of, datetime.now(ZoneInfo("Asia/Seoul")).date())
    if window is None:
        return TrackBLiveGapFill("up_to_date" if data_as_of else "not_applicable")
    if not detail_codes:
        return TrackBLiveGapFill(
            "not_applicable",
            "수집 이력에 이 모델의 세부품명번호가 없음",
            begin_date=window[0].isoformat(),
            end_date=window[1].isoformat(),
        )
    settings = get_settings()
    service_key = (settings.resolved_g2b_shopping_service_key or "").strip()
    if not service_key:
        return TrackBLiveGapFill("not_applicable", "나라장터 서비스키 미설정")
    try:
        with PublicDataPortalClient(service_key, timeout_seconds=8.0, max_retries=0) as client:
            return fetch_live_gap(
                query,
                detail_codes=detail_codes,
                window=window,
                client=client,
                quote_unit_price=quote_unit_price,
                base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
            )
    except Exception as exc:
        return TrackBLiveGapFill("failure", "실시간 조회 실패", error_type=type(exc).__name__)


_MFDS_MODEL_INFO_CACHE: dict[tuple[str, str], MfdsWorkspaceResult] = {}


def _run_deferred_mfds_model_info(state: dict[str, Any]) -> MfdsWorkspaceResult:
    """User-initiated 형명 lookup with key fallback; successful results are cached in-process."""

    mfds = state.get("mfds")
    model_name = str(getattr(mfds, "model_name", "") or "")
    product_name = model_info_product_name(
        str(getattr(mfds, "product_name", "") or ""),
        model_name,
        tuple(getattr(state.get("track_b"), "candidates", ()) or ()),
    )
    cache_key = (normalize_text(product_name), normalize_text(model_name))
    cached = _MFDS_MODEL_INFO_CACHE.get(cache_key)
    if cached is not None:
        return cached
    settings = get_settings()
    keys = mfds_service_key_candidates(settings)
    if not keys:
        return MfdsWorkspaceResult(
            status="not_configured",
            product_name=product_name,
            model_name=model_name,
            queried=False,
        )
    result = research_mfds_for_workspace(
        ProductQuery(product_name=product_name, model_name=model_name),
        state.get("track_b"),
        settings=settings,
        model_client=MfdsModelInfoClient(keys[0], client=mfds_model_info_json_client(settings)),
        business_client=MfdsBusinessLicenseClient(keys[0], client=mfds_json_client(settings)),
    )
    if result.status in {"success", "success_0"}:
        _MFDS_MODEL_INFO_CACHE[cache_key] = result
    return result


HOME_SEARCH_STATE_KEY = "home_unified_search_result"
HOME_SEARCH_DETAILS_KEY = "home_search_details"
HOME_WORKSPACE_VIEW_KEY = "home_workspace_view"
QUOTE_AUTO_ROUTE_FILE_SESSION_KEY = "quote_auto_route_file_v1"
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


def _safety_evidence_token(name: str, *, fallback: str = "CHECK_FAILED") -> object:
    """Return a Safety status without requiring a newly-added enum member after hot reload."""

    member = getattr(SafetyEvidenceStatus, name, None)
    if member is not None:
        return member
    fallback_member = getattr(SafetyEvidenceStatus, fallback, None)
    if name == fallback and fallback_member is not None:
        return fallback_member
    return SimpleNamespace(value=name)


def _safety_evidence_value(status: object) -> str:
    return str(getattr(status, "value", status) or "").strip()


def _mfds_recall_error_kind_compat(result: object | None) -> str:
    """Classify Safety failures without importing a newly-added helper after hot reload."""

    if result is None:
        return ""
    status = str(getattr(result, "status", "") or "")
    if status not in {"failure", "not_authorized"}:
        return ""

    error_type = str(getattr(result, "error_type", "") or "")
    error_message = str(getattr(result, "error_message", "") or "").upper()
    if any(
        marker in error_message
        for marker in (
            "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
            "SERVICE_ACCESS_DENIED_ERROR",
            "PERMISSION_DENIED",
            "CODE=30",
        )
    ):
        return "authorization"

    token = error_type.casefold()
    if any(marker in token for marker in ("transport", "timeout", "connect")):
        return "transport"
    if "typeerror" in token:
        return "type_error"
    if "valueerror" in token:
        return "value_error"
    if "publicdataclienterror" in token:
        return "api_error"
    return "other"


def _run_market_research_runtime_compatible(
    query: ProductQuery,
    *,
    lookback_days: int,
    stage_timings: dict[str, float],
):
    """Call the hot-reload guard without assuming its newest signature is loaded."""

    kwargs = {
        "lookback_days": int(lookback_days),
        "research_pages_per_term": 1,
        "research_request_budget": 18,
        "procurement_detail_limit": 4,
    }
    try:
        supports_stage_timings = (
            "stage_timings" in signature(run_market_research_hot_reload_safe).parameters
        )
    except (TypeError, ValueError):
        supports_stage_timings = False

    if supports_stage_timings:
        return run_market_research_hot_reload_safe(
            run_market_research,
            query,
            stage_timings=stage_timings,
            **kwargs,
        )
    return run_market_research_hot_reload_safe(
        run_market_research,
        query,
        **kwargs,
    )


def _build_safety_state_compat(
    safety_lookup: object | None,
    *,
    model_name: str,
    product_name: str,
    permit_numbers: list[str],
):
    """Normalize Safety locally so Streamlit hot reload cannot fall back to stale manual UI."""

    model = str(model_name or "").strip()
    permits = tuple(dict.fromkeys(str(value or "").strip() for value in permit_numbers if str(value or "").strip()))
    search_keys = tuple(
        ([f"모델명: {model}"] if model else [])
        + [f"식약처 품목번호: {value}" for value in permits]
    )
    status = str(getattr(safety_lookup, "status", "") or "") if safety_lookup is not None else ""
    checked_at = getattr(safety_lookup, "checked_at", None) if safety_lookup is not None else None
    records = tuple(getattr(safety_lookup, "records", ()) or ()) if safety_lookup is not None else ()

    if status == "success" and records:
        return SimpleNamespace(
            evidence_status=SafetyEvidenceStatus.AMBER,
            message=(
                "식약처 회수·판매중지 공식 API에서 모델/품목 관련 안전정보가 확인되었습니다. "
                "Service04 응답만으로 exact 품목번호 적용범위를 확정하지 않고 원문 확인이 필요합니다."
            ),
            checked_at=checked_at,
            search_keys=search_keys,
        )
    if status in {"success", "success_0"}:
        return SimpleNamespace(
            evidence_status=SafetyEvidenceStatus.CHECKED_NONE,
            message="현재 연결된 식약처 회수·판매중지 공식 API에서 일치 항목을 확인하지 못했습니다.",
            checked_at=checked_at,
            search_keys=search_keys,
        )
    if status == "not_authorized":
        return SimpleNamespace(
            evidence_status=_safety_evidence_token("NOT_AUTHORIZED"),
            message=(
                "식약처 회수·판매중지 API 호출은 연결됐지만 현재 서비스키의 활용승인이 확인되지 않았습니다. "
                "안전정보 0건으로 해석하지 않습니다."
            ),
            checked_at=checked_at,
            search_keys=search_keys,
        )
    if status == "failure":
        return SimpleNamespace(
            evidence_status=SafetyEvidenceStatus.CHECK_FAILED,
            message="식약처 회수·판매중지 공식 API 조회가 실패했습니다. 0건으로 해석하지 않습니다.",
            checked_at=checked_at,
            search_keys=search_keys,
        )
    if status == "not_configured":
        return SimpleNamespace(
            evidence_status=SafetyEvidenceStatus.NOT_CONNECTED,
            message=(
                "식약처 회수·판매중지 API 서비스키가 현재 Production 런타임에 연결되지 않았습니다. "
                "자동조회 미연결 상태는 공식 안전정보 확인 결과가 아닙니다."
            ),
            checked_at=None,
            search_keys=search_keys,
        )
    return build_manual_safety_check_state(
        model_name=model,
        permit_numbers=permits,
    )




def _lookup_mfds_recall_isolated(*, model_name: str, product_name: str) -> object:
    """Keep Safety source failures from aborting price/procurement search.

    Streamlit Cloud hot reload can temporarily retain an older service function object. Safety is
    an independent evidence axis, so any runtime failure must degrade to CHECK_FAILED/manual
    verification while the price, procurement and quote workflow continues.
    """

    try:
        result = lookup_mfds_recall(
            model_name=model_name,
            product_name=product_name,
        )
    except Exception as exc:
        return mfds_recall_exception_result(
            exc,
            model_name=model_name,
            product_name=product_name,
        )
    return normalize_mfds_recall_lookup(result)


def _identity_hydration(
    raw_search: str,
    *,
    product_name: str,
    manufacturer: str,
    model_name: str,
    specification: str,
) -> tuple[str, str, str, str, MfdsIdentityLookup | None]:
    explicit_fields = any(
        value.strip()
        for value in (product_name, manufacturer, model_name, specification)
    )
    if raw_search and explicit_fields:
        return product_name, manufacturer, model_name, specification, None

    lookup_key = raw_search or model_name.strip() or product_name.strip()
    if not lookup_key:
        return product_name, manufacturer, model_name, specification, None

    identity = _lookup_mfds_identity_runtime(lookup_key)
    base_query = ProductQuery(
        product_name=product_name,
        manufacturer=manufacturer,
        model_name=model_name,
        specification=specification,
    )
    canonical = canonicalize_product_query(base_query, identity)
    return (
        canonical.query.product_name,
        canonical.query.manufacturer,
        canonical.query.model_name,
        canonical.query.specification,
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
                "현재는 하루 4회, 실행당 최대 100,000행을 20,000행 checkpoint 단위로 저장합니다."
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
    if state.get("review_reason") == "weak_model_key":
        st.warning(
            "모델명이 짧거나 숫자 위주라 다른 제품의 모델명과 겹칠 수 있습니다. "
            "제조사나 품목명으로 확인되지 않아 식약처 제품을 자동으로 연결하지 않았습니다. "
            "아래 후보가 찾는 제품이 맞는지 확인하세요."
        )
        st.caption("찾는 제품이 아니면 제조사나 품목명을 함께 입력해 다시 검색하세요.")
    else:
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
    search_started = monotonic()
    search_timings: dict[str, float] = {}
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
    weak_key_review = (
        selected_identity is None
        and isinstance(indexed_identity, MfdsIdentityLookup)
        and identity_needs_review(
            indexed_identity,
            manufacturer=manufacturer,
            product_name=product_name,
        )
    )
    if isinstance(indexed_identity, MfdsIdentityLookup) and indexed_identity.match_type == "model" and (
        mfds_identity_status(indexed_identity) == IdentityEvidenceStatus.AMBIGUOUS or weak_key_review
    ):
        return {
            "route": "candidate_selection",
            "search_text": raw_search,
            "heading": raw_search,
            "mfds_identity": indexed_identity,
            "review_reason": "weak_model_key" if weak_key_review else "ambiguous",
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

    if (
        (not isinstance(indexed_identity, MfdsIdentityLookup) or indexed_identity.status != "success")
        and (query.model_name or "").strip()
        and should_query_live_mfds_identity(_load_mfds_collection_status)
    ):
        live_identity = lookup_mfds_model_identity_live(query.model_name)
        if live_identity.status == "success" and not identity_needs_review(
            live_identity,
            manufacturer=query.manufacturer,
            product_name=query.product_name,
        ):
            indexed_identity = live_identity

    search_timings["identity"] = round(monotonic() - search_started, 3)

    model_probe_used = False
    track_b_started = monotonic()
    track_b_data_as_of: str | None = None
    track_b_index_updated_at: str | None = None
    with open_track_b_serving_snapshot() as track_b_snapshot:
        track_b_data_as_of = getattr(track_b_snapshot, "data_as_of", None)
        track_b_index_updated_at = getattr(track_b_snapshot, "index_updated_at", None)
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

        live_detail_codes: tuple[str, ...] = ()
        if getattr(track_b_snapshot, "session", None) is not None and (query.model_name or "").strip():
            try:
                live_detail_codes = indexed_detail_codes(track_b_snapshot.session, query)
            except Exception:
                live_detail_codes = ()

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
            _lookup_same_mfds_product_runtime(identity_product) if identity_product else ()
        )
        mfds_procurement_crosslinks = _build_mfds_procurement_crosslinks(
            same_product_identity,
            track_b_snapshot=track_b_snapshot,
            current_model=query.model_name or "",
        )
    search_timings["track_b"] = round(monotonic() - track_b_started, 3)

    live_started = monotonic()
    track_b_live = _track_b_live_gap_fill(
        query,
        detail_codes=live_detail_codes,
        data_as_of=track_b_data_as_of,
        quote_unit_price=review_input.quote_unit_price,
    )
    track_b = merge_live_gap(track_b, track_b_live)
    search_timings["track_b_live"] = round(monotonic() - live_started, 3)

    mfds_started = monotonic()
    if isinstance(indexed_identity, MfdsIdentityLookup) and indexed_identity.status == "success":
        # The item number is already confirmed; 형명 is still offered on demand because it is the
        # only source of domestic/cancelled/export status for the same-item comparison.
        identity_record = indexed_identity.records[0] if indexed_identity.records else None
        identity_product_name = (
            str(getattr(identity_record, "product_name", "") or "") or query.product_name or ""
        )
        mfds = MfdsWorkspaceResult(
            status="deferred" if identity_product_name.strip() else "not_applicable",
            product_name=identity_product_name,
            model_name=str(getattr(identity_record, "model_name", "") or "") or query.model_name or "",
            queried=False,
        )
    else:
        # The official model-info (형명) API takes ~30-60 s per page, so it is no longer called
        # during search. The workspace offers it as an explicit, cached follow-up lookup.
        should_query = getattr(mfds_workspace_service, "should_query_mfds", None)
        mfds = MfdsWorkspaceResult(
            status=(
                "deferred"
                if (query.product_name or "").strip()
                and callable(should_query)
                and should_query(query, track_b)
                else "not_applicable"
            ),
            product_name=query.product_name or "",
            model_name=query.model_name or "",
            queried=False,
        )
    search_timings["mfds"] = round(monotonic() - mfds_started, 3)

    safety_started = monotonic()
    safety_lookup = _lookup_mfds_recall_isolated(
        model_name=query.model_name,
        product_name=query.product_name,
    )
    search_timings["safety"] = round(monotonic() - safety_started, 3)

    # Return the fast A/B + identity workspace first. Broad C/Research is intentionally
    # deferred so external procurement APIs cannot block the primary price result.
    research_stage_timings: dict[str, float] = {}
    run = SearchRun()
    discovery = None
    market_bundle = None
    search_timings["research"] = 0.0
    search_timings["total"] = round(monotonic() - search_started, 3)
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
        "safety_lookup": safety_lookup,
        "mfds_identity": indexed_identity,
        "exact_identity_crosslinks": exact_identity_crosslinks,
        "same_product_identity": same_product_identity,
        "mfds_procurement_crosslinks": mfds_procurement_crosslinks,
        "track_b_data_as_of": track_b_data_as_of,
        "track_b_live": track_b_live,
        "track_b_index_updated_at": track_b_index_updated_at,
        "search_timings_seconds": search_timings,
        "research_stage_timings_seconds": research_stage_timings,
        "research_status": "pending",
        "research_lookback_days": int(lookback_days),
    }


def _execute_deferred_research(state: dict[str, Any]) -> dict[str, Any]:
    """Enrich an already-renderable A/B workspace with C/Research evidence."""

    query = state.get("query")
    if not isinstance(query, ProductQuery):
        raise ValueError("심화 Research를 실행할 검색조건이 없습니다.")

    started = monotonic()
    stage_timings: dict[str, float] = {}
    run, discovery, market_bundle = _run_market_research_runtime_compatible(
        query,
        lookback_days=int(state.get("research_lookback_days") or G2B_DEFAULT_LOOKBACK_DAYS),
        stage_timings=stage_timings,
    )
    elapsed = round(monotonic() - started, 3)

    updated = dict(state)
    updated["run"] = run
    updated["discovery"] = discovery
    updated["market_bundle"] = market_bundle
    updated["research_status"] = "complete"
    updated["research_stage_timings_seconds"] = stage_timings
    timings = dict(updated.get("search_timings_seconds") or {})
    timings["research"] = elapsed
    updated["search_timings_seconds"] = timings
    updated.pop("research_error_type", None)
    return updated


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
    run = state.get("run")
    if not isinstance(run, SearchRun):
        run = SearchRun()
    discovery = state.get("discovery")
    market_bundle = state.get("market_bundle")
    research_status = str(state.get("research_status") or "complete")
    mfds = state.get("mfds")
    safety_lookup = state.get("safety_lookup")
    indexed_identity = state.get("mfds_identity")
    exact_identity_crosslinks = list(state.get("exact_identity_crosslinks") or [])
    same_product_identity = tuple(state.get("same_product_identity") or ())
    mfds_procurement_crosslinks = list(state.get("mfds_procurement_crosslinks") or [])
    track_b_data_as_of = str(state.get("track_b_data_as_of") or "").strip() or None
    track_b_index_updated_at = str(state.get("track_b_index_updated_at") or "").strip() or None
    interpretation = state.get("interpretation")
    quote_key = str(heading or "result").strip()
    default_quote = (
        f"{review_input.quote_unit_price:f}"
        if review_input.quote_unit_price is not None
        else ""
    )

    st.divider()
    st.caption("구매조사 워크스페이스")
    head_title, head_action = st.columns([5.2, 1.6], vertical_alignment="bottom")
    head_title.subheader(heading)
    identity_slot = head_title.container()
    timings = state.get("search_timings_seconds")
    if isinstance(timings, dict):
        timing_attrs: list[str] = []
        for key in ("identity", "track_b", "mfds", "safety", "research", "total"):
            try:
                timing_attrs.append(f'data-{key}="{float(timings.get(key, 0.0)):.3f}"')
            except (TypeError, ValueError):
                continue
        st.markdown(
            '<span id="purchase-search-timings-v1" '
            + " ".join(timing_attrs)
            + ' style="display:none"></span>',
            unsafe_allow_html=True,
        )
    research_stage_timings = state.get("research_stage_timings_seconds")
    if isinstance(research_stage_timings, dict):
        stage_attrs: list[str] = []
        for key in (
            "direct_search_all",
            "classification",
            "procurement_research",
            "bid_items",
            "contracts",
            "lifecycle",
            "shopping_discovery",
            "catalog",
            "runner_total",
        ):
            try:
                stage_attrs.append(
                    f'data-{key}="{float(research_stage_timings.get(key, 0.0)):.3f}"'
                )
            except (TypeError, ValueError):
                continue
        st.markdown(
            '<span id="purchase-research-stage-timings-v1" '
            + " ".join(stage_attrs)
            + ' style="display:none"></span>',
            unsafe_allow_html=True,
        )
    if state.get("origin") == "quote":
        st.caption(
            "견적서에서 추출한 품목을 일반 통합검색과 동일한 구매조사 파이프라인으로 조사했습니다. "
            "견적단가는 비교기준으로 유지합니다."
        )
        st.page_link(
            "pages/2_견적_검토.py",
            label="견적 전체 품목 · 추출내용 · 상세 검증 열기",
            icon="📋",
        )

    safety_permit_numbers: list[str] = []
    if isinstance(indexed_identity, MfdsIdentityLookup) and indexed_identity.status == "success":
        safety_permit_numbers.extend(indexed_identity.permit_numbers)
    if isinstance(mfds, MfdsWorkspaceResult):
        safety_permit_numbers.extend(mfds.permit_numbers)
    safety_state = _build_safety_state_compat(
        safety_lookup,
        model_name=str(getattr(query, "model_name", "") or "").strip(),
        product_name=str(getattr(query, "product_name", "") or "").strip(),
        permit_numbers=safety_permit_numbers,
    )
    safety_lookup_status = str(getattr(safety_lookup, "status", "") or "")
    safety_error_kind = _mfds_recall_error_kind_compat(safety_lookup)
    raw_safety_error_type = str(getattr(safety_lookup, "error_type", "") or "")
    safety_error_type = "".join(
        char for char in raw_safety_error_type if char.isalnum() or char in "_-"
    )[:80]
    st.markdown(
        '<span id="purchase-safety-diagnostic-v1" '
        + f'data-status="{safety_lookup_status}" '
        + f'data-error-kind="{safety_error_kind}" '
        + f'data-error-type="{safety_error_type}" '
        + 'style="display:none"></span>',
        unsafe_allow_html=True,
    )
    safety_status_value = _safety_evidence_value(safety_state.evidence_status)
    if workspace_header_ui.safety_needs_banner(safety_status_value):
        banner_text = (
            f"{workspace_header_ui.safety_card(safety_status_value).value} · {safety_state.message}"
        )
        if safety_status_value == "RED":
            st.error(banner_text)
        else:
            st.warning(banner_text)
    cards_slot = st.container()
    notice_slot = st.container()
    details_slot = st.expander("확인 내역 · 안전정보 · 검색어 해석", expanded=False)

    with details_slot:
        st.markdown("##### 안전정보 확인 내역")
        safety_text = f"{safety_status_value} · {safety_state.message}"
        if safety_status_value == "RED":
            st.error(safety_text)
        elif safety_status_value in {
            "AMBER",
            "CHECK_FAILED",
            "NOT_CONNECTED",
            "NOT_AUTHORIZED",
        }:
            st.warning(safety_text)
        else:
            st.info(safety_text)
        if safety_state.checked_at:
            st.caption(f"식약처 회수·판매중지 API 확인시각 · {safety_state.checked_at}")
        if safety_state.search_keys:
            st.caption("공식 안전정보 확인키 · " + " / ".join(safety_state.search_keys))
        recall_records = tuple(getattr(safety_lookup, "records", ()) or ())
        if recall_records:
            st.dataframe(
                [
                    {
                        "모델": item.model_name or "",
                        "제조원": item.manufacturer_name or "",
                        "보고상태": item.report_state_name or "",
                        "회수구분": item.report_kind_name or "",
                        "보고일": item.report_submit_date or "",
                        "회수사유": item.reason or "",
                        "회수품목일련번호": item.recall_item_seq or "",
                    }
                    for item in recall_records
                ],
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "Service04 형명/품목 응답에는 exact 식약처 품목번호가 없어 관련 안전정보로 표시합니다. "
                "허가제품·제조번호 적용범위는 원문에서 확인해야 합니다."
            )
        safety_cols = st.columns(3)
        safety_cols[0].link_button(
            "회수·판매중지 확인",
            MFDS_RECALL_PAGE_URL,
            use_container_width=True,
        )
        safety_cols[1].link_button(
            "행정처분 확인",
            MFDS_ADMIN_SANCTION_PAGE_URL,
            use_container_width=True,
        )
        safety_cols[2].link_button(
            "안전성서한 확인",
            MFDS_SAFETY_LETTER_PAGE_URL,
            use_container_width=True,
        )

    with st.expander("내 견적가와 비교", expanded=bool(default_quote)), st.form(
        f"workspace_quote_context::{quote_key}"
    ):
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
    quote_message = build_quote_position_message(
        quote_unit_price=workspace_quote,
        stats=stats,
        unit=quote_unit,
        vat_status="" if vat_status == "미확인" else vat_status,
        conditions=quote_conditions,
    )
    track_b_unavailable = (
        getattr(track_b, "evidence_status", None) == PriceEvidenceStatus.UNAVAILABLE
    )

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
    elif isinstance(mfds, MfdsWorkspaceResult) and mfds.status == "deferred":
        mfds_metric = "조회 대기"
    else:
        mfds_metric = "대상 아님"
    st.markdown(
        '<span id="purchase-research-deferred-v1" '
        + f'data-status="{research_status}" '
        + 'style="display:none"></span>',
        unsafe_allow_html=True,
    )

    identity_permits: list[str] = []
    identity_companies: list[str] = []
    identity_product: str | None = None
    identity_permit_type: str | None = None
    if isinstance(indexed_identity, MfdsIdentityLookup) and indexed_identity.status == "success":
        identity_permits.extend(indexed_identity.permit_numbers)
        identity_companies.extend(indexed_identity.companies)
        if indexed_identity.records:
            identity_product = indexed_identity.records[0].product_name or None
            identity_permit_type = mfds_item_authorization_type(indexed_identity.records[0]).value
    if isinstance(mfds, MfdsWorkspaceResult) and mfds.exact_records:
        identity_permits.extend(mfds.permit_numbers)
        identity_product = identity_product or mfds.exact_records[0].product_name or None
    collection_status = _load_mfds_collection_status()
    mfds_coverage = (
        None
        if collection_status.status == "unavailable"
        else collection_status.progress_percent
    )
    identity_text = workspace_header_ui.identity_line(
        product_name=identity_product,
        permit_numbers=identity_permits,
        permit_type=identity_permit_type,
        companies=identity_companies,
        procurement_product=workspace_header_ui.procurement_product_name(direct_rows),
        procurement_maker=workspace_header_ui.most_common_text(direct_rows, "제조사"),
    )
    with identity_slot:
        if identity_text:
            st.caption(identity_text)
        if (
            isinstance(indexed_identity, MfdsIdentityLookup)
            and indexed_identity.status == "success"
            and indexed_identity.match_type == "permit"
            and len(indexed_identity.model_names) > 1
        ):
            st.caption(
                f"식약처 품목번호에 등록 모델 {len(indexed_identity.model_names)}개가 있습니다. "
                "대표모델을 임의로 고르지 않고 가격 비교 탭에서 모델별로 보여줍니다."
            )

    header_cards = [
        workspace_header_ui.price_card(stats, unavailable=track_b_unavailable),
        workspace_header_ui.supplier_card(stats),
        workspace_header_ui.mfds_card(
            mfds_metric,
            permit_numbers=identity_permits,
            companies=identity_companies,
            coverage_percent=mfds_coverage,
            model_count=len(mfds.records) if isinstance(mfds, MfdsWorkspaceResult) else None,
            active_model_count=(
                len(mfds.active_records) if isinstance(mfds, MfdsWorkspaceResult) else None
            ),
        ),
        workspace_header_ui.safety_card(safety_status_value),
    ]
    with cards_slot:
        st.markdown(
            workspace_header_ui.HEADER_CSS + workspace_header_ui.render_cards_html(header_cards),
            unsafe_allow_html=True,
        )
        if workspace_quote is not None:
            st.caption(quote_message)

    with notice_slot:
        if isinstance(mfds, MfdsWorkspaceResult) and mfds.status == "deferred":
            if st.button(
                (
                    "국내 정상·취소 상태 불러오기 (약 10~40초)"
                    if isinstance(indexed_identity, MfdsIdentityLookup)
                    and indexed_identity.status == "success"
                    else "식약처 등록정보 불러오기 (약 10~40초)"
                ),
                key=f"workspace_header_mfds_model_info::{quote_key}",
                help="국내 정상·취소 상태와 같은 품목의 등록모델을 식약처 형명정보에서 조회합니다.",
            ):
                with st.status(
                    "식약처 형명정보를 조회하고 있습니다. 가격 결과는 그대로 유지됩니다...",
                    expanded=False,
                ) as header_mfds_progress:
                    refreshed = dict(state)
                    refreshed["mfds"] = _run_deferred_mfds_model_info(state)
                    st.session_state[HOME_SEARCH_STATE_KEY] = refreshed
                    header_mfds_progress.update(label="식약처 형명정보 조회 완료", state="complete")
                st.rerun()
        if not stats.direct_count and not track_b_unavailable:
            if stats.reference_count:
                st.warning(
                    f"동일제품으로 확인된 거래는 없고 참고거래가 {stats.reference_count}건 있습니다. "
                    "참고거래는 가격 범위에 넣지 않았습니다. 가격 비교 탭에서 확인하세요."
                )
            elif stats.research_count:
                st.info("동일제품 거래는 없지만 입찰·사전규격 등 참고근거가 있습니다.")

    live_note: str | None = None
    if track_b_data_as_of:
        live = state.get("track_b_live")
        live_status = str(getattr(live, "status", "") or "")
        live_window = f"{getattr(live, 'begin_date', '')} ~ {getattr(live, 'end_date', '')}"
        if live_status == "success":
            # Count only rows that survived dedupe: the rolling collector may already have
            # ingested part of the window before data_as_of advances.
            live_found = len(getattr(live, "candidates", ()) or ())
            live_added = sum(
                1
                for candidate in tuple(getattr(state.get("track_b"), "candidates", ()) or ())
                if getattr(candidate, "transaction_type", None) == LIVE_TRANSACTION_TYPE
            )
            if live_added:
                live_note = f"나라장터 실시간 보강 {live_window}: 수집 전 거래 {live_added}건 추가"
            else:
                live_note = f"나라장터 실시간 보강 {live_window}: 조회된 {live_found}건 모두 이미 반영"
        elif live_status == "success_0":
            live_note = f"나라장터 실시간 보강 {live_window}: 신규 납품요구 0건"
        elif live_status == "failure":
            live_note = "나라장터 실시간 보강 실패, 수집 자료만 표시"
        elif live_status == "not_applicable" and getattr(live, "reason", ""):
            live_note = f"실시간 보강 안 함({live.reason})"
        if live_note and getattr(live, "truncated_window", False):
            live_note += " (최근 62일만 조회)"
        basis_text = workspace_header_ui.data_basis_line(
            track_b_data_as_of=track_b_data_as_of,
            live_note=live_note,
            mfds_coverage_percent=mfds_coverage,
            mfds_complete=bool(
                collection_status.status != "unavailable"
                and collection_status.first_backfill_complete
            ),
        )
        cards_slot.caption(basis_text)
    elif track_b_index_updated_at:
        cards_slot.caption(
            f"나라장터 serving index 갱신시각 · {track_b_index_updated_at} · "
            "전체 데이터 coverage 기준일은 아직 미확인"
        )

    if isinstance(interpretation, UnifiedSearchInterpretation):
        with details_slot:
            _render_search_interpretation(interpretation)

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
        data_as_of=track_b_data_as_of,
    )
    safe_export_name = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in str(heading or "market_survey")
    ).strip("_") or "market_survey"
    head_action.download_button(
        "시장조사표 Excel 내려받기",
        data=export_payload,
        file_name=f"시장조사표_{safe_export_name}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"workspace_market_survey_export::{quote_key}",
        use_container_width=True,
        help=(
            "Excel은 직접거래와 참고근거를 분리하고 출처·원문근거를 보존합니다. "
            "기준일을 알 수 없는 자료는 '미확인'으로 기록합니다."
        ),
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
                    "식약처 품목번호에 연결된 각 모델을 하나씩 나라장터 동일제품 거래와 대조합니다. "
                    "식약처 품목 책임주체와 실제 조달 납품업체는 서로 다른 관계입니다."
                )
            else:
                st.info("식약처 품목정보는 확인됐지만 등록 모델 기준 나라장터 동일제품 거래가는 아직 확인되지 않았습니다.")

        st.markdown("#### 나라장터 동일제품 직접거래")
        if state["model_probe_used"]:
            st.caption("입력어가 모델명과 일치해 모델 기준 결과를 우선 표시합니다.")

        if direct_rows:
            grouped_rows = model_price_group_rows(track_b)
            if grouped_rows:
                st.markdown("##### 모델·규격·조건별 직접가격")
                st.dataframe(grouped_rows, use_container_width=True, hide_index=True)
            st.markdown(f"##### 거래 {strict_count}건")
            st.dataframe(
                direct_rows,
                use_container_width=True,
                hide_index=True,
                column_order=workspace_header_ui.direct_table_columns(direct_rows),
                column_config={
                    "가격": st.column_config.TextColumn("대당단가"),
                    "총액": st.column_config.TextColumn("거래총액"),
                    "금액검증": st.column_config.TextColumn("단가×수량 검증"),
                },
            )
            st.caption(
                "동일제품으로 확인된 거래만 모았습니다. 단가근거·식별번호·원문키 등 전체 항목은 "
                "시장조사표 Excel에 들어 있습니다."
            )
        elif track_b.status == "unavailable":
            st.warning("가격 검색 인덱스에 연결하지 못했습니다.")
        elif track_b.status == "not_ingested":
            st.info("수집 자료의 빠른 가격 인덱스를 만드는 중입니다.")
        else:
            st.info("검색한 모델과 동일제품으로 확인된 나라장터 거래는 0건입니다.")

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
        st.markdown("#### 참고근거 · 입찰·계약 자료")
        if research_status in {"pending", "failure"}:
            if research_status == "pending":
                st.caption(
                    "입찰·낙찰·사전규격·계약 등 참고자료는 필요할 때 불러옵니다. "
                    "위의 동일제품 거래가는 이 조회와 별개입니다."
                )
                research_button_label = "입찰·계약 참고자료 불러오기"
            else:
                st.warning(
                    "참고자료 조회에 실패했습니다. 동일제품 거래가·업체·식약처 정보는 그대로입니다."
                )
                research_button_label = "입찰·계약 참고자료 다시 조회"

            if st.button(
                research_button_label,
                key=f"workspace_research_load::{quote_key}",
                type="secondary",
            ):
                try:
                    with st.status(
                        "동일제품 거래가는 그대로 둔 채 입찰·계약 참고자료를 조회하고 있습니다...",
                        expanded=False,
                    ) as research_progress:
                        enriched_state = _execute_deferred_research(state)
                        st.session_state[HOME_SEARCH_STATE_KEY] = enriched_state
                        research_progress.update(
                            label="입찰·계약 참고자료 조회 완료",
                            state="complete",
                        )
                    st.rerun()
                except Exception as exc:
                    failed_state = dict(state)
                    failed_state["research_status"] = "failure"
                    failed_state["research_error_type"] = type(exc).__name__
                    st.session_state[HOME_SEARCH_STATE_KEY] = failed_state
                    st.warning(
                        "입찰·계약 참고자료 조회에 실패했습니다. 동일제품 거래가는 그대로 사용할 수 있습니다. "
                        f"({type(exc).__name__})"
                    )

        if research_status not in {"pending", "failure"}:
            st.markdown("##### 입찰·낙찰·계약 참고자료")
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
        st.markdown("#### 실제 납품업체 · 나라장터")
        procurement_suppliers = supplier_rows(track_b)
        if procurement_suppliers:
            st.dataframe(
                procurement_suppliers,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "최저단가": st.column_config.NumberColumn("최저단가(원)", format="localized"),
                    "최고단가": st.column_config.NumberColumn("최고단가(원)", format="localized"),
                },
            )
            st.caption(
                "동일제품으로 확인된 나라장터 납품요구의 납품업체만 모았습니다. "
                "납품실적이 있다고 공식 총판이라는 뜻은 아닙니다."
            )
        elif getattr(track_b, "evidence_status", None) == PriceEvidenceStatus.UNAVAILABLE:
            st.warning("나라장터 가격 인덱스를 조회할 수 없어 조달 납품업체 상태를 확인하지 못했습니다.")
        else:
            st.info("직접 동일성 확인 거래 기준 조달 납품업체 0개입니다.")

        st.divider()
        st.markdown("#### 품목 책임주체 · 식약처에 등록한 제조·수입업체")
        st.caption(
            "위 실제 납품업체와는 다른 관계입니다. 이름이 비슷해도 같은 회사로 자동 간주하지 않습니다."
        )
        company_active_keys: set[tuple[str, str]] | None = None
        if isinstance(mfds, MfdsWorkspaceResult) and mfds.status in {"success", "success_0"}:
            company_active_keys = {
                (
                    normalize_text(item.permit_number),
                    normalize_text(item.model_name),
                )
                for item in mfds.active_records
                if item.permit_number and item.model_name
            }

        company_summaries = build_registered_company_summaries(
            same_product_identity,
            procurement_crosslinks=mfds_procurement_crosslinks,
            active_live_keys=company_active_keys,
        )
        if company_summaries:
            company_metric_cols = st.columns(3)
            company_metric_cols[0].metric("품목 책임주체", f"{len(company_summaries)}개")
            company_metric_cols[1].metric(
                "나라장터 직접가격 보유 업체",
                f"{sum(item.direct_price_model_count > 0 for item in company_summaries)}개",
            )
            company_metric_cols[2].metric(
                (
                    "국내 정상 등록모델"
                    if company_active_keys is not None
                    else "등록모델 · 상태 미확인"
                ),
                f"{sum(item.registered_model_count for item in company_summaries)}건",
            )
            st.dataframe(
                [
                    {
                        "품목 책임주체": item.company_name,
                        "등록모델": item.registered_model_count,
                        "허가건수": item.permit_count,
                        "최근 식약처 처리일": item.latest_permit_date or "",
                        "대표모델": " / ".join(item.representative_models),
                        "나라장터 직접가격 모델": item.direct_price_model_count,
                        "실제 조달 공급업체": " / ".join(item.procurement_suppliers),
                        "상태": item.live_status,
                    }
                    for item in company_summaries
                ],
                use_container_width=True,
                hide_index=True,
            )

            selected_company = st.selectbox(
                "품목 책임주체 상세보기",
                options=[item.company_name for item in company_summaries],
                key=f"workspace_company_drilldown::{quote_key}",
            )
            detail_rows = company_identity_rows(
                same_product_identity,
                selected_company,
                active_live_keys=company_active_keys,
            )
            if detail_rows:
                st.dataframe(detail_rows, use_container_width=True, hide_index=True)

            business_cache_key = (
                "workspace_company_business_lookup::"
                + normalize_text(selected_company)
            )
            if st.button(
                "선택 업체 식약처 업허가 확인",
                key=f"workspace_company_business_button::{quote_key}",
            ):
                business_lookup = getattr(
                    mfds_workspace_service,
                    "lookup_mfds_business_license",
                    None,
                )
                if callable(business_lookup):
                    license_keys = mfds_service_key_candidates(get_settings())
                    st.session_state[business_cache_key] = business_lookup(
                        selected_company,
                        business_client=(
                            MfdsBusinessLicenseClient(
                                license_keys[0],
                                client=mfds_json_client(get_settings()),
                            )
                            if license_keys
                            else None
                        ),
                    )
                else:
                    st.session_state.pop(business_cache_key, None)
                    st.warning(
                        "배포 프로세스가 이전 식약처 모듈을 유지하고 있어 업체 업허가 조회만 "
                        "일시적으로 사용할 수 없습니다. 페이지 재기동 후 다시 확인하세요."
                    )
            selected_business_lookup = st.session_state.get(business_cache_key)
            if selected_business_lookup is not None:
                if selected_business_lookup.status == "success":
                    filter_left, filter_right = st.columns(2)
                    include_inactive = filter_left.checkbox(
                        "폐업·휴업·취소 업허가 포함",
                        value=False,
                        key=f"workspace_company_business_inactive::{quote_key}",
                    )
                    include_partial = filter_right.checkbox(
                        "이름 일부만 같은 다른 업체 포함",
                        value=False,
                        key=f"workspace_company_business_partial::{quote_key}",
                    )
                    license_view = build_business_license_view(
                        selected_business_lookup.records,
                        selected_company,
                        include_inactive=include_inactive,
                        include_partial=include_partial,
                    )
                    if license_view.showing_partial_only:
                        st.warning(
                            "선택 업체와 이름이 정확히 같은 업허가가 없어 이름 일부가 같은 업체를 "
                            "표시합니다. 다른 회사일 수 있으니 주소·허가번호로 확인하세요."
                        )
                    if license_view.rows:
                        st.dataframe(
                            list(license_view.rows),
                            use_container_width=True,
                            hide_index=True,
                        )
                    else:
                        st.info("현재 필터 조건에 맞는 식약처 업허가가 없습니다.")
                    hidden_notes = []
                    if license_view.hidden_inactive_count:
                        hidden_notes.append(
                            f"폐업·휴업·취소 {license_view.hidden_inactive_count}건"
                        )
                    if license_view.hidden_partial_count:
                        hidden_notes.append(
                            f"이름 일부만 같은 다른 업체 {license_view.hidden_partial_count}건"
                        )
                    st.caption(
                        "선택 업체명의 식약처 업허가 조회 결과입니다. "
                        "업허가가 확인되어도 특정 모델의 판매점·총판 관계를 의미하지 않습니다."
                        + (f" 숨긴 결과 · {', '.join(hidden_notes)}" if hidden_notes else "")
                    )
                elif selected_business_lookup.status == "success_0":
                    st.info("선택한 업체명으로 확인된 식약처 업허가 결과가 0건입니다.")
                elif selected_business_lookup.status == "not_configured":
                    st.warning("식약처 업허가 API 서비스키가 연결되지 않아 조회하지 못했습니다.")
                elif selected_business_lookup.status == "failure":
                    st.warning(
                        "식약처 업허가 조회 실패 · "
                        f"{selected_business_lookup.error_type or '오류'} · "
                        f"{selected_business_lookup.error_message or '상세 미확인'}"
                    )
        elif same_product_identity and company_active_keys is not None:
            st.info(
                "같은 식약처 품목의 등록정보는 확인됐지만 국내 정상 상태가 확인된 업체·모델이 없습니다."
            )
        elif same_product_identity:
            st.info(
                "업체는 확인됐지만 국내 정상·취소 상태를 아직 조회하지 않아 현재 판매 중인 업체로 단정하지 않습니다."
            )
        else:
            st.caption(
                "이 모델의 식약처 등록정보가 확인되면 같은 품목의 제조·수입업체를 업체별로 모아 보여줍니다. "
                "식약처 제품정보는 수집 중입니다."
            )

        with st.expander("식약처 등록 상세 · 제품정보와 형명정보 원자료", expanded=False):
            if isinstance(indexed_identity, MfdsIdentityLookup):
                if indexed_identity.status == "success" and indexed_identity.records:
                    st.markdown("##### 식약처 제품정보 (수집 인덱스)")
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
                                "출처": MFDS_PRODUCT_INFO_DATASET_URL,
                                "원문근거해시": (item.source_payload_sha256 or "")[:16],
                            }
                            for item in indexed_identity.records
                        ],
                        use_container_width=True,
                        hide_index=True,
                    )
                    st.caption(
                        "식약처 공식 제품정보를 모아 둔 검색용 인덱스입니다. 품목 책임주체는 제조·수입 관계이며 실제 납품업체와 다릅니다."
                    )
                elif mfds_identity_status(indexed_identity) == IdentityEvidenceStatus.NOT_FOUND_IN_COVERAGE:
                    st.info("현재 수집된 식약처 자료 범위에서 일치하는 등록정보를 찾지 못했습니다.")
                elif indexed_identity.status == "not_ingested":
                    st.info("식약처 제품정보 인덱스를 아직 사용할 수 없습니다.")
                elif indexed_identity.status == "unavailable":
                    st.warning("식약처 제품정보 인덱스를 현재 읽을 수 없습니다.")

            if not isinstance(mfds, MfdsWorkspaceResult):
                st.info("식약처 조회 상태를 확인할 수 없습니다.")
            elif mfds.status == "deferred":
                st.caption(
                    "식약처 형명정보(국내 정상·취소 상태, 같은 품목의 등록모델)는 검색 결과 상단의 "
                    "'식약처 등록정보 불러오기' 버튼으로 조회합니다 (약 10~40초)."
                )
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
                m1c.metric("같은 품목 등록모델", f"{len(mfds.records)}건")
                m2c.metric("그중 국내 정상", f"{len(mfds.active_records)}건")
                if mfds.exact_ambiguous:
                    m3c.metric("이 모델명 일치", "여러 품목번호 · 확인 필요")
                elif mfds.exact_confirmed:
                    m3c.metric("이 모델명 일치", "확인")
                else:
                    m3c.metric("이 모델명 일치", "미확인")

                if mfds.exact_records:
                    st.markdown("##### 검색한 모델과 정확히 일치하는 등록")
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
                        st.caption("안전정보 확인에 쓴 품목번호 · " + " / ".join(mfds.permit_numbers))

                st.caption(
                    "형명정보의 '업종'은 업체명이 아닙니다. 제조·수입업체는 식약처 제품정보에서 가져옵니다."
                )

                if mfds.business_records:
                    st.markdown("##### 입력한 업체명의 식약처 업허가")
                    hint_view = build_business_license_view(
                        mfds.business_records,
                        str(getattr(mfds, "business_query", "") or ""),
                    )
                    if hint_view.showing_partial_only:
                        st.warning(
                            "업체명 힌트와 이름이 정확히 같은 업허가가 없어 이름 일부가 같은 업체를 표시합니다."
                        )
                    if hint_view.rows:
                        st.dataframe(
                            list(hint_view.rows),
                            use_container_width=True,
                            hide_index=True,
                        )
                    hint_hidden = []
                    if hint_view.hidden_inactive_count:
                        hint_hidden.append(f"폐업·휴업·취소 {hint_view.hidden_inactive_count}건")
                    if hint_view.hidden_partial_count:
                        hint_hidden.append(f"이름 일부만 같은 다른 업체 {hint_view.hidden_partial_count}건")
                    st.caption(
                        "사용자/견적의 제조사·업체명 힌트에 대한 업허가 확인입니다. "
                        "해당 모델의 공식 제조·수입업체 관계를 자동 확정하지 않습니다."
                        + (f" 숨긴 결과 · {', '.join(hint_hidden)}" if hint_hidden else "")
                    )

            st.page_link("pages/4_의료기기_조회.py", label="의료기기 상세 조회 화면 열기", icon="🏥")

    else:
        st.markdown("#### 같은 품목의 다른 등록모델과 가격")
        st.caption(
            "식약처에 같은 품목으로 등록된 모델을 품목 책임주체(제조·수입업체)별로 묶고, "
            "모델마다 나라장터 동일제품 거래가를 붙였습니다. ▶ 표시는 검색한 모델입니다. "
            "임상적 대체 가능성·성능 동등성은 판정하지 않습니다."
        )
        filter_priced, filter_inactive = st.columns(2)
        only_priced = filter_priced.checkbox(
            "조달가격 있는 것만",
            value=True,
            key=f"workspace_same_item_priced::{quote_key}",
        )
        include_inactive = filter_inactive.checkbox(
            "취소·취하·수출용 포함",
            value=False,
            key=f"workspace_same_item_inactive::{quote_key}",
        )
        live_loaded = isinstance(mfds, MfdsWorkspaceResult) and mfds.status in {"success", "success_0"}
        same_item_view = same_item_ui.build_same_item_rows(
            mfds_procurement_crosslinks,
            same_item_ui.live_status_index(mfds.records if live_loaded else None),
            include_unpriced=not only_priced,
            include_inactive=include_inactive,
            current_keys=(
                [(item.permit_number, item.model_name) for item in indexed_identity.records]
                if isinstance(indexed_identity, MfdsIdentityLookup) and indexed_identity.status == "success"
                else ()
            ),
        )
        if same_item_view.rows:
            st.dataframe(list(same_item_view.rows), use_container_width=True, hide_index=True)
            notes = [same_item_ui.hidden_note(same_item_view), *same_item_ui.status_notes(same_item_view)]
            st.caption(". ".join(note for note in notes if note) or "모든 모델을 표시했습니다.")
        elif mfds_procurement_crosslinks:
            st.info(
                "현재 필터에 맞는 모델이 없습니다. "
                + (same_item_ui.hidden_note(same_item_view) or "")
            )
        else:
            st.caption(
                "이 모델의 식약처 등록정보가 확인되면 같은 품목의 모델을 업체별로 보여줍니다. "
                "식약처 제품정보는 수집 중입니다."
            )

        if isinstance(mfds, MfdsWorkspaceResult) and mfds.active_competitor_records:
            with st.expander(
                f"식약처 형명정보의 같은 품목 국내 정상 모델 {len(mfds.active_competitor_records)}개 "
                "· 업체·가격 정보 없음",
                expanded=False,
            ):
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
        st.page_link("pages/4_의료기기_조회.py", label="의료기기 상세 조회 화면 열기", icon="🏥")


hydrate_streamlit_runtime_secrets()
st.set_page_config(page_title="구매가격 검색", page_icon="🔎", layout="wide")
st.markdown(
    '<span id="unified-search-runtime-v3" style="display:none">unified-search-runtime-v3</span>'
    '<span id="unified-search-runtime-v4" style="display:none">unified-search-runtime-v4</span>'
    '<span id="purchase-workspace-runtime-v1" style="display:none">purchase-workspace-runtime-v1</span>'
    '<span id="purchase-workspace-runtime-v2" style="display:none">purchase-workspace-runtime-v2</span>'
    '<span id="purchase-workspace-runtime-v5" style="display:none">purchase-workspace-runtime-v5</span>'
    '<span id="purchase-workspace-runtime-v6" style="display:none">purchase-workspace-runtime-v6</span>'
    '<span id="purchase-workspace-runtime-v7" style="display:none">purchase-workspace-runtime-v7</span>'
    '<span id="purchase-workspace-runtime-v8" style="display:none">purchase-workspace-runtime-v8</span>'
    '<span id="purchase-workspace-runtime-v9" style="display:none">purchase-workspace-runtime-v9</span>'
    '<span id="purchase-workspace-runtime-v10" style="display:none">purchase-workspace-runtime-v10</span>'
    '<span id="purchase-workspace-runtime-v11" style="display:none">purchase-workspace-runtime-v11</span>'
    '<span id="purchase-workspace-runtime-v12" style="display:none">purchase-workspace-runtime-v12</span>'
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
                search_text=(handoff.model_name or handoff.product_name),
                product_name="",
                manufacturer="",
                model_name="",
                specification="",
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
        st.session_state.pop(QUOTE_AUTO_ROUTE_FILE_SESSION_KEY, None)
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
    newly_extracted = quote_state.file_name != uploaded.name or quote_state.extraction is None
    if newly_extracted:
        with st.spinner("견적서에서 품목을 추출하고 있습니다..."):
            _store_extraction(uploaded, quote_state)
        st.session_state.pop(QUOTE_AUTO_ROUTE_FILE_SESSION_KEY, None)

    if quote_state.items:
        already_routed = st.session_state.get(QUOTE_AUTO_ROUTE_FILE_SESSION_KEY) == uploaded.name
        if not already_routed:
            item = quote_state.items[0]
            try:
                with st.status(
                    "견적 첫 품목을 일반 통합검색과 동일하게 조사하고 있습니다...",
                    expanded=False,
                ) as status:
                    quote_result = _execute_search(
                        search_text=(item.model_name or item.product_name),
                        product_name="",
                        manufacturer="",
                        model_name="",
                        specification="",
                        quote_text=(
                            str(item.unit_price) if item.unit_price is not None else ""
                        ),
                        lookback_days=quote_state.lookback_days,
                    )
                    quote_result["origin"] = "quote"
                    quote_result["quote_file_name"] = uploaded.name
                    quote_result["quote_item_index"] = 0
                    st.session_state[HOME_SEARCH_STATE_KEY] = quote_result
                    st.session_state[QUOTE_AUTO_ROUTE_FILE_SESSION_KEY] = uploaded.name
                    st.session_state[HOME_SEARCH_DETAILS_KEY] = False
                    st.query_params["view"] = "price"
                    status.update(
                        label="견적 첫 품목 통합 구매조사 완료",
                        state="complete",
                    )
                st.rerun()
            except ValueError as exc:
                st.warning(
                    "첫 품목을 통합검색으로 자동 연결하지 못했습니다. "
                    f"견적 검토 화면에서 추출값을 확인하세요. ({exc})"
                )
                st.switch_page("pages/2_견적_검토.py")
    else:
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
