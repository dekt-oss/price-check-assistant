from __future__ import annotations

import dataclasses
import importlib
import sqlite3
import sys
from collections.abc import Mapping
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
from purchase_price.services import g2b_delivery_record as delivery_record_service
from purchase_price.services import mfds_identity_r2 as mfds_identity_r2_service
from purchase_price.services import mfds_item_status_r2 as mfds_item_status_service
from purchase_price.services import mfds_workspace as mfds_workspace_service
from purchase_price.services import track_b_db_quote_comparison as track_b_comparison_service
from purchase_price.services import track_b_live_gap_fill as track_b_live_service
from purchase_price.services import track_b_r2_quote_index as track_b_r2_index_service
from purchase_price.services import track_b_serving_snapshot as track_b_snapshot_service
from purchase_price.services import track_b_supplier_summary as supplier_summary_service
from purchase_price.services.g2b_search_policy import (
    G2B_DEFAULT_LOOKBACK_DAYS,
    G2B_LOOKBACK_OPTIONS,
    g2b_lookback_label,
)
from purchase_price.services.market_survey_export import build_market_survey_workbook
from purchase_price.services.matching import normalize_text
from purchase_price.services.medical_lookup_handoff import (
    MEDICAL_LOOKUP_HANDOFF_KEY,
    build_medical_lookup_handoff,
)
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
    lookup_identity,
    lookup_same_product,
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
)
from purchase_price.services.unified_search_intent import (
    UnifiedSearchInterpretation,
    interpret_unified_search,
)
from purchase_price.ui import result_summary as result_summary_ui
from purchase_price.ui import same_item_compare as same_item_ui
from purchase_price.ui import search_overviews as overview_ui
from purchase_price.ui import track_b_transactions as track_b_transactions_ui
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
    strict_comparison_candidates,
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


_TRACK_B_RELOAD_LOCK = Lock()
# (module, attribute that only the current code has), reloaded in dependency order.
_TRACK_B_RUNTIME_MARKERS = (
    (track_b_comparison_service, "_not_cancelled_clause"),
    (track_b_r2_index_service, "WORKSPACE_LOOKUP_LIMIT"),
    (track_b_snapshot_service, "WORKSPACE_LOOKUP_LIMIT"),
    (track_b_live_service, "DROPS_CANCELLED_LINES"),
    (track_b_transactions_ui, "SOURCE_RECORD_COLUMN"),
    (same_item_ui, "ITEM_STATUS_AWARE"),
)


# Modules whose screen wording changed in the 2026-10 simplification. A Streamlit process that
# was started before the deploy keeps the old copies (the page updates, its imports do not), so the
# cards would show the new layout with the old developer words.
_UI_RUNTIME_MARKERS = (
    ("purchase_price.ui.widgets", "PLAIN_WORDING_2026_10"),
    ("purchase_price.ui.g2b_market_research", "PLAIN_WORDING_2026_10"),
    ("purchase_price.ui.market_research", "PLAIN_WORDING_2026_10"),
    ("purchase_price.ui.same_item_compare", "PLAIN_WORDING_2026_10"),
    ("purchase_price.ui.workspace_header", "PLAIN_WORDING_2026_10B"),
    ("purchase_price.ui.result_summary", "UNIT_AWARE_V2"),
    ("purchase_price.services.g2b_delivery_record", "FIELD_ORDER_V1"),
)


def _refresh_ui_modules() -> None:
    """Reload retained pre-2026-10 UI modules once, in dependency order; never raises."""

    stale = [
        name
        for name, marker in _UI_RUNTIME_MARKERS
        if name in sys.modules and not hasattr(sys.modules[name], marker)
    ]
    if not stale:
        return
    with _TRACK_B_RELOAD_LOCK:
        for name, marker in _UI_RUNTIME_MARKERS:
            module = sys.modules.get(name)
            if module is None or hasattr(module, marker):
                continue
            try:
                importlib.invalidate_caches()
                importlib.reload(module)
            except Exception:
                pass


def _track_b_runtime():
    """Reload Track B lookup modules that Streamlit retained from before a deploy.

    Production kept the pre-#275 modules after the page itself updated (2026-10-05): the
    header showed the new label but still only 50 trades and counted cancelled lines.
    Returns the (snapshot, live gap-fill) modules to use for this search.
    """

    if any(not hasattr(module, marker) for module, marker in _TRACK_B_RUNTIME_MARKERS):
        with _TRACK_B_RELOAD_LOCK:
            for module, marker in _TRACK_B_RUNTIME_MARKERS:
                if hasattr(module, marker):
                    continue
                try:
                    importlib.invalidate_caches()
                    importlib.reload(module)
                except Exception:
                    pass
    return track_b_snapshot_service, track_b_live_service


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
    if isinstance(identity, MfdsIdentityLookup) and identity.status == "success_0" and raw_search:
        # "메디아나" -> "(주)메디아나": accept only an exact company match on a legal-form spelling.
        for variant in overview_ui.company_name_variants(raw_search):
            candidate = _lookup_mfds_identity_runtime(variant)
            if candidate.status == "success" and candidate.match_type == "company":
                identity = candidate
                break
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
    # 500 per model (the comparison maximum): the old 50 default capped counts such as
    # HeartOn A16-DS at "50건" when it has 92 direct trades.
    comparisons = track_b_snapshot.lookup_model_summaries(queries, limit_per_model=500)

    rows: list[dict[str, object]] = []
    for item, comparison in zip(items, comparisons, strict=True):
        model = str(getattr(item, "model_name", "") or "").strip()
        company = str(getattr(item, "registered_company", "") or "").strip()
        direct = _strict_candidates_compat(comparison)
        # The price range uses the model's main unit only (대 vs set are not one range).
        priced = result_summary_ui.split_by_main_unit(direct).kept
        prices = sorted(
            Decimal(str(candidate.price))
            for candidate in priced
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
                    else "같은 제품 거래 0건"
                ),
                "최근거래": dates[-1] if dates else "",
                "실제 조달 공급업체": " / ".join(suppliers[:5]),
            }
        )
    return rows


OVERVIEW_RECORD_LIMIT = 2000


def _identity_index_wide(query_company: str = "", product_name: str = "") -> tuple[MfdsIdentityRecord, ...]:
    """Up to OVERVIEW_RECORD_LIMIT identity rows (the regular lookup stops at 200, which hid
    busy models such as HeartOn A16-DS from a 메디아나 overview). Empty on any failure."""

    module = _mfds_identity_r2_runtime()
    local_index_path = getattr(module, "_local_index_path", None)
    if not callable(local_index_path):
        return ()
    try:
        path = local_index_path(get_settings())
        if path is None:
            return ()
        connection = sqlite3.connect(path)
        try:
            if query_company:
                found = lookup_identity(connection, query_company, limit=OVERVIEW_RECORD_LIMIT)
                return found.records if found.match_type == "company" else ()
            return lookup_same_product(connection, product_name, limit=OVERVIEW_RECORD_LIMIT)
        finally:
            connection.close()
    except Exception:
        return ()


def _build_overview_state(
    raw_search: str,
    identity: MfdsIdentityLookup,
    snapshot_runtime: Any,
) -> dict[str, Any]:
    route = "company_overview" if identity.match_type == "company" else "product_overview"
    records = list(identity.records)
    if route == "product_overview":
        heading = next((r.product_name for r in records if r.product_name), raw_search)
        wide = _identity_index_wide(product_name=heading) or tuple(
            _lookup_same_mfds_product_runtime(heading) or ()
        )
    else:
        heading = next((r.registered_company for r in records if r.registered_company), raw_search)
        wide = _identity_index_wide(query_company=heading)
    if wide:
        records = list(wide)
    with snapshot_runtime.open_track_b_serving_snapshot() as snapshot:
        crosslinks = _build_mfds_procurement_crosslinks(records, track_b_snapshot=snapshot, current_model="")
        supplier = (
            supplier_summary_service.supplier_trade_summary(getattr(snapshot, "session", None), heading)
            if route == "company_overview"
            else None
        )
        data_as_of = str(getattr(snapshot, "data_as_of", "") or "")
    similar_companies: list[dict[str, object]] = []
    if route == "company_overview":
        # "메디아나" can match a small company of exactly that name while the buyer meant
        # "(주)메디아나"; offer other registered legal-form spellings instead of guessing.
        seen = {normalize_text(heading)}
        for variant in overview_ui.company_name_variants(raw_search):
            try:
                found = _lookup_mfds_identity_runtime(variant)
            except Exception:
                continue
            if not isinstance(found, MfdsIdentityLookup) or found.status != "success" or found.match_type != "company":
                continue
            name = next((r.registered_company for r in found.records if r.registered_company), variant)
            if normalize_text(name) in seen:
                continue
            seen.add(normalize_text(name))
            models = {r.model_name for r in found.records if r.model_name}
            similar_companies.append(
                {"name": name, "models": len(models), "more": len(found.records) >= 200}
            )
    return {
        "route": route,
        "search_text": raw_search,
        "heading": heading,
        "similar_companies": similar_companies,
        "overview_records": records,
        "overview_crosslinks": crosslinks,
        "overview_supplier": supplier,
        "overview_record_limit_hit": len(records) >= OVERVIEW_RECORD_LIMIT,
        "track_b_data_as_of": data_as_of,
    }


def _open_model_from_overview(model: str) -> None:
    st.session_state.pop(HOME_SEARCH_STATE_KEY, None)
    st.query_params["q"] = model
    st.query_params.pop("view", None)
    st.rerun()


def _render_overview(state: dict[str, Any]) -> None:
    route = state["route"]
    heading = str(state.get("heading") or "")
    records = list(state.get("overview_records") or [])
    crosslinks = list(state.get("overview_crosslinks") or [])
    priced_models = [
        str(row.get("모델"))
        for row in sorted(crosslinks, key=lambda row: -int(row.get("나라장터 직접거래") or 0))
        if int(row.get("나라장터 직접거래") or 0) > 0
    ]
    all_models = list(dict.fromkeys(priced_models + [str(r.model_name) for r in records if r.model_name]))

    st.divider()
    st.subheader(heading)
    if route == "company_overview":
        st.caption("업체 이름으로 찾은 결과입니다. 표에서 모델을 누르면 그 모델의 가격 조사로 이동합니다.")
        for similar in state.get("similar_companies") or ():
            note_col, button_col = st.columns([4, 1.4], vertical_alignment="center")
            more = " 이상" if similar.get("more") else ""
            note_col.info(
                f"이름이 비슷한 다른 업체도 있습니다: **{similar['name']}** · 등록 모델 {similar['models']}개{more}"
            )
            if button_col.button(
                f"{similar['name']} 보기",
                key=f"overview_similar::{similar['name']}",
                use_container_width=True,
            ):
                _open_model_from_overview(str(similar["name"]))
        product_rows = overview_ui.company_product_rows(records, crosslinks)
        supplier = state.get("overview_supplier") or {}
        supplied = int(supplier.get("trade_count") or 0)
        cards = [
            workspace_header_ui.SummaryCard(
                "items", "식약처 등록 품목", f"{len(product_rows)}개", "제조·수입업체로 등록한 품목", workspace_header_ui.TONE_NEUTRAL
            ),
            workspace_header_ui.SummaryCard(
                "models",
                "등록 모델",
                f"{len(all_models)}개",
                f"그중 나라장터 거래가 있는 모델 {len(priced_models)}개",
                workspace_header_ui.TONE_NEUTRAL,
            ),
            workspace_header_ui.SummaryCard(
                "supply",
                "나라장터 납품 실적",
                f"{supplied}건",
                "이름이 같은 납품업체 기준" if supplied else "이름이 같은 납품업체 없음",
                workspace_header_ui.TONE_OK if supplied else workspace_header_ui.TONE_NEUTRAL,
            ),
        ]
    else:
        st.caption("품목 이름으로 찾은 결과입니다. 표에서 모델을 누르면 그 모델의 가격 조사로 이동합니다.")
        class_rows = overview_ui.classification_rows(records)
        companies = {r.registered_company for r in records if r.registered_company}
        cards = [
            workspace_header_ui.SummaryCard(
                "classes", "분류·등급", f"{len(class_rows)}개", "식약처 분류번호 기준", workspace_header_ui.TONE_NEUTRAL
            ),
            workspace_header_ui.SummaryCard(
                "companies", "제조·수입업체", f"{len(companies)}곳", "식약처 등록 기준", workspace_header_ui.TONE_NEUTRAL
            ),
            workspace_header_ui.SummaryCard(
                "models",
                "등록 모델",
                f"{len(all_models)}개",
                f"그중 나라장터 거래가 있는 모델 {len(priced_models)}개",
                workspace_header_ui.TONE_NEUTRAL,
            ),
        ]
    st.markdown(
        workspace_header_ui.HEADER_CSS + workspace_header_ui.render_cards_html(cards),
        unsafe_allow_html=True,
    )
    collection_status = _load_mfds_collection_status()
    basis = result_summary_ui.short_basis_line(
        track_b_data_as_of=str(state.get("track_b_data_as_of") or "") or None,
        mfds_coverage_percent=(
            collection_status.progress_percent if collection_status.status != "unavailable" else None
        ),
        mfds_complete=bool(
            collection_status.status != "unavailable" and collection_status.first_backfill_complete
        ),
    )
    if state.get("overview_record_limit_hit"):
        basis += f" · 등록 모델이 많아 {OVERVIEW_RECORD_LIMIT}개까지만 봄"
    if basis:
        st.caption(basis)

    model_rows = result_summary_ui.overview_model_rows(crosslinks)
    if model_rows:
        st.markdown(f"#### 모델별 나라장터 거래 · 전체 {len(all_models)}개 중 {len(model_rows)}개")
        event = st.dataframe(
            model_rows,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=f"overview_models::{route}::{heading}",
        )
        selected = list(getattr(getattr(event, "selection", None), "rows", []) or [])
        if selected and 0 <= selected[0] < len(model_rows):
            _open_model_from_overview(str(model_rows[selected[0]]["모델"]))
        st.caption("행을 누르면 그 모델의 가격 조사로 이동합니다.")
    else:
        st.info("등록 모델을 찾지 못했습니다.")

    with st.expander("전체 보기 · 품목별 · 다른 모델 고르기", expanded=False):
        if all_models:
            pick_col, button_col = st.columns([4, 1.4], vertical_alignment="bottom")
            chosen = pick_col.selectbox("다른 모델 고르기", options=all_models, key=f"overview_pick::{route}")
            if button_col.button("이 모델 조사", key=f"overview_open::{route}", use_container_width=True):
                _open_model_from_overview(chosen)
        if route == "company_overview":
            st.markdown("##### 식약처에 등록한 품목")
            st.dataframe(result_summary_ui.display_rows(product_rows), use_container_width=True, hide_index=True)
            st.markdown(f"##### 등록 모델 전체 {len(all_models)}개")
            st.dataframe(
                result_summary_ui.display_rows(overview_ui.company_model_rows(records, crosslinks)),
                use_container_width=True,
                hide_index=True,
            )
            st.markdown("##### 나라장터 납품 실적")
            supplier_row = overview_ui.supplier_summary_row(state.get("overview_supplier"), heading)
            if supplier_row:
                st.dataframe([supplier_row], use_container_width=True, hide_index=True)
                st.caption(
                    "식약처 자료와 나라장터 자료에는 서로 맞춰 볼 사업자등록번호가 없어, 이름이 같은 "
                    "납품업체를 같은 회사로 단정하지 않습니다."
                )
            elif (state.get("overview_supplier") or {}).get("status") == "unavailable":
                st.warning("나라장터 납품 실적을 조회하지 못했습니다.")
            else:
                st.info("나라장터 거래에서 이름이 같은 납품업체를 찾지 못했습니다.")
        else:
            st.markdown("##### 분류번호·등급별")
            st.dataframe(result_summary_ui.display_rows(class_rows), use_container_width=True, hide_index=True)
            st.markdown("##### 업체별 모델과 나라장터 가격")
            only_priced = st.checkbox("거래가 있는 모델만", value=True, key="overview_product_priced")
            view = same_item_ui.build_same_item_rows(crosslinks, None, include_unpriced=not only_priced)
            if view.rows:
                st.dataframe(
                    result_summary_ui.display_rows(view.rows),
                    use_container_width=True,
                    hide_index=True,
                )
                notes = [
                    same_item_ui.hidden_note(view),
                    "판매 가능 여부는 모델을 골라 가격 조사 화면에서 확인합니다",
                ]
                st.caption(". ".join(note for note in notes if note))
            else:
                st.info("조건에 맞는 모델이 없습니다. " + (same_item_ui.hidden_note(view) or ""))


def _render_medical_lookup_link(indexed_identity: object, mfds: object, query: object) -> None:
    """Link to the medical-device page with only the identified product's identity fields."""

    handoff = build_medical_lookup_handoff(
        identity_records=(
            indexed_identity.records
            if isinstance(indexed_identity, MfdsIdentityLookup) and indexed_identity.status == "success"
            else ()
        ),
        model_info_records=(
            mfds.exact_records
            if isinstance(mfds, MfdsWorkspaceResult) and not mfds.exact_ambiguous
            else ()
        ),
        query_product_name=str(getattr(query, "product_name", "") or ""),
        query_model_name=str(getattr(query, "model_name", "") or ""),
    )
    if not handoff.is_empty:
        st.session_state[MEDICAL_LOOKUP_HANDOFF_KEY] = handoff.to_state()
    st.page_link(
        "pages/4_의료기기_조회.py",
        label="이 제품을 의료기기 상세에서 열기",
        icon="🏥",
    )


def _load_mfds_collection_status() -> MfdsIdentityCollectionStatus:
    return get_mfds_identity_collection_status()


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
    st.caption("같은 이름의 제품이 여러 개입니다")
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
            "같은 모델명이 여러 허가번호나 여러 업체에 등록돼 있어 자동으로 하나를 고르지 않았습니다. 아래에서 찾는 제품을 고르세요."
        )
    if not isinstance(identity, MfdsIdentityLookup) or not identity.records:
        st.info("후보 제품을 표시할 수 없습니다.")
        return

    candidates = _candidate_identity_records(identity)
    st.dataframe(
        result_summary_ui.display_rows(_ambiguous_identity_candidates(identity)),
        use_container_width=True,
        hide_index=True,
    )
    selected_index = st.selectbox(
        "조사할 제품 고르기",
        options=list(range(len(candidates))),
        format_func=lambda index: (
            f"{candidates[index].product_name or '품목 미확인'} · "
            f"{candidates[index].model_name or '모델 미확인'} · "
            f"[{mfds_item_authorization_type(candidates[index]).value}] "
            f"{candidates[index].permit_number or '품목번호 미확인'} · "
            f"{candidates[index].registered_company or '업체 미확인'}"
        ),
        key="workspace_v3_identity_candidate",
    )
    st.caption(
        "제품을 고르기 전에는 나라장터 거래가를 어느 제품의 가격으로도 보여주지 않습니다."
    )
    if st.button("이 제품으로 조사", type="primary"):
        selected = candidates[int(selected_index)]
        with st.status("고른 제품의 거래가와 허가정보를 찾고 있습니다...", expanded=False) as status:
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
            st.query_params.pop("view", None)
            st.query_params["identity"] = _identity_selection_token(selected)
            status.update(label="조사 완료", state="complete")
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
    snapshot_runtime, live_runtime = _track_b_runtime()
    merge_live_gap = live_runtime.merge_live_gap
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
    if (
        selected_identity is None
        and isinstance(indexed_identity, MfdsIdentityLookup)
        and indexed_identity.status == "success"
        and indexed_identity.match_type in {"company", "product"}
    ):
        # A company or product-name match is not one product (#221 9.4-9.5): show an
        # overview instead of a product workspace with the company injected as manufacturer.
        return _build_overview_state(raw_search, indexed_identity, snapshot_runtime)
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
    with snapshot_runtime.open_track_b_serving_snapshot() as track_b_snapshot:
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
        st.markdown("**검색어를 이렇게 풀었습니다**")
        c1, c2, c3 = st.columns(3)
        c1.caption("품명")
        c1.write(interpretation.product_name or "미확인")
        c2.caption("제조사")
        c2.write(interpretation.manufacturer or "미확인")
        c3.caption("모델")
        c3.write(interpretation.model_name or "미확인")

        if interpretation.mapping_verified:
            st.success(
                "확인된 모델 정보로 검색어를 풀었습니다. 같은 제품인지는 거래마다 따로 확인합니다."
            )
        else:
            st.info(
                "등록된 모델 힌트로 검색어를 풀었습니다. 이 풀이만으로 같은 제품이라고 보지는 않습니다."
            )


def _money_text(value: Decimal | None) -> str:
    return f"{value:,.0f}원" if value is not None else "근거 없음"


def _render_diagnostic_markers(state: dict[str, Any]) -> None:
    """Hidden spans the production smoke reads; they never show on screen."""

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


QUOTE_ITEM_RESULTS_SESSION_KEY = "quote_item_results_v1"


def _main_unit_view(track_b: Any) -> tuple[Any, Any]:
    """Track B limited to the most common unit (대 vs set...) for medians and ranges.

    Prices in different units are never mixed into one median; the other-unit trades stay in
    the tables. Returns (track_b for stats, unit split).
    """

    split = result_summary_ui.split_by_main_unit(strict_comparison_candidates(track_b))
    if not split.mixed:
        return track_b, split
    other = {id(candidate) for candidate in split.other}
    try:
        kept = tuple(c for c in tuple(getattr(track_b, "candidates", ()) or ()) if id(c) not in other)
        return dataclasses.replace(track_b, candidates=kept), split
    except TypeError:
        return track_b, split


def _quote_item_summary(result: dict[str, Any]) -> dict[str, object]:
    if result.get("route") != "workspace":
        return {"needs_choice": True}
    stats_track_b, _split = _main_unit_view(result.get("track_b"))
    stats = build_purchase_workspace_stats(
        track_b=stats_track_b,
        market_bundle=None,
        quote_unit_price=None,
    )
    return {"median_price": stats.median_price, "direct_count": stats.direct_count}


def _open_quote_item(quote_state: QuoteReviewState, index: int, file_name: str) -> None:
    item = quote_state.items[index]
    try:
        with st.status(f"{index + 1}번 품목을 조사하고 있습니다...", expanded=False) as status:
            result = _execute_search(
                search_text=(item.model_name or item.product_name or ""),
                product_name="",
                manufacturer="",
                model_name="",
                specification="",
                quote_text=(str(item.unit_price) if item.unit_price is not None else ""),
                lookback_days=quote_state.lookback_days,
            )
            status.update(label=f"{index + 1}번 품목 조사 완료", state="complete")
    except ValueError as exc:
        st.warning(f"{index + 1}번 품목은 품명이나 모델명이 없어 조사하지 못했습니다. ({exc})")
        return
    result["origin"] = "quote"
    result["quote_file_name"] = file_name
    result["quote_item_index"] = index
    st.session_state[HOME_SEARCH_STATE_KEY] = result
    st.rerun()


def _render_quote_items(state: dict[str, Any]) -> None:
    """Uploaded quote: one row per item; clicking a row opens that item below."""

    quote_state = st.session_state.get(QUOTE_REVIEW_STATE_SESSION_KEY)
    if not isinstance(quote_state, QuoteReviewState) or not quote_state.items:
        st.page_link("pages/2_견적_검토.py", label="견적서 전체 품목 · 상세 검증 열기", icon="📋")
        return
    file_name = str(state.get("quote_file_name") or quote_state.file_name or "견적서")
    cache = st.session_state.get(QUOTE_ITEM_RESULTS_SESSION_KEY)
    if not isinstance(cache, dict) or cache.get("file") != file_name:
        cache = {"file": file_name, "results": {}}
        st.session_state[QUOTE_ITEM_RESULTS_SESSION_KEY] = cache
    current_index = state.get("quote_item_index")
    if isinstance(current_index, int):
        cache["results"][current_index] = _quote_item_summary(state)

    st.divider()
    st.markdown(f"**견적서 {file_name}** · 품목 {len(quote_state.items)}개")
    rows = result_summary_ui.quote_item_rows(quote_state.items, cache["results"])
    event = st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"quote_items::{file_name}",
    )
    selected = list(getattr(getattr(event, "selection", None), "rows", []) or [])
    if selected and 0 <= selected[0] < len(quote_state.items) and selected[0] != current_index:
        _open_quote_item(quote_state, selected[0], file_name)
    note_col, link_col = st.columns([3, 2], vertical_alignment="center")
    note_col.caption(
        "행을 누르면 그 품목의 결과가 아래에 나옵니다."
        + (f" 지금은 {current_index + 1}번 품목입니다." if isinstance(current_index, int) else "")
    )
    with link_col:
        st.page_link("pages/2_견적_검토.py", label="추출 내용 확인·수정 · 상세 검증", icon="📋")


def _render_mfds_collection_status_body(status: MfdsIdentityCollectionStatus) -> None:
    if status.status == "unavailable":
        st.caption("식약처 자료 수집 상태를 읽지 못했습니다.")
        return
    c1, c2, c3 = st.columns(3)
    c1.metric("모은 식약처 자료", f"{status.row_count:,}행")
    c2.metric(
        "식약처 전체",
        f"{status.source_total_count:,}행" if status.source_total_count else "확인 중",
    )
    c3.metric(
        "진행률",
        "완료" if status.first_backfill_complete else (
            f"{status.progress_percent:.1f}%" if status.progress_percent is not None else "확인 중"
        ),
    )
    updated_at = format_status_updated_at(status.updated_at)
    if updated_at:
        st.caption(f"마지막 갱신 · {updated_at}")


DELIVERY_RECORD_CACHE_KEY = "delivery_record_cache_v1"


def _render_delivery_record(row: Mapping[str, object], *, view_key: str, close_key: str) -> None:
    """The archived public API record of one same-product trade, in plain labels."""

    record_id = str(row.get("원천기록") or "")
    ref = delivery_record_service.parse_record_ref(record_id, row.get("원문근거키"))
    with st.container(border=True):
        if ref is None:
            st.info("이 거래는 원문 위치 정보가 없어 원문을 열 수 없습니다.")
            return
        head_col, close_col = st.columns([5, 1], vertical_alignment="center")
        head_col.markdown(f"**조달청 공개 원문 · 납품요구 {ref.label}**")
        if close_col.button("닫기", key=close_key, type="tertiary"):
            st.session_state.pop(view_key, None)
            st.rerun()
        cache = st.session_state.setdefault(DELIVERY_RECORD_CACHE_KEY, {})
        lookup = cache.get(record_id)
        if lookup is None:
            with st.spinner("보관해 둔 조달청 원문을 읽고 있습니다..."):
                lookup = delivery_record_service.load_delivery_record(ref)
            if lookup.status != "failure":
                cache[record_id] = lookup
        if lookup.status == "found":
            st.dataframe(
                [{"항목": label, "내용": value} for label, value in lookup.fields],
                use_container_width=True,
                hide_index=True,
                # Tall enough for every field, so 단가·수량·단위 are never below a scroll fold.
                height=35 * (len(lookup.fields) + 1) + 3,
            )
            st.caption(
                f"공공데이터포털 '{delivery_record_service.G2B_SHOPPING_DATASET_NAME}'가 공개한 기록을 "
                f"수집할 때 그대로 보관한 원본입니다 (원본 확인값 {(ref.payload_hash or '')[:12]})."
            )
        elif lookup.status == "not_archived":
            st.info("최근 며칠 사이 실시간으로 받은 거래라 아직 원문을 보관하지 않았습니다. 아래 번호로 확인하세요.")
        elif lookup.status == "not_found":
            st.warning("보관한 원문에서 이 줄을 찾지 못했습니다. 아래 번호로 확인하세요.")
        else:
            st.warning(f"원문을 읽지 못했습니다 ({lookup.error_type or '오류'}). 잠시 뒤 다시 여세요.")
        st.caption(
            "나라장터 화면은 거래마다 고유 주소가 없어 바로 열 수 없습니다. 납품요구번호로 찾아 확인하세요."
        )
        number_col, link_col = st.columns([2, 3], vertical_alignment="center")
        number_col.code(ref.delivery_number, language=None)
        link_col.link_button(
            "출처 데이터셋 보기 (공공데이터포털)",
            delivery_record_service.G2B_SHOPPING_DATASET_URL,
        )


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
    head_title, head_action = st.columns([5.2, 1.6], vertical_alignment="bottom")
    head_title.subheader(heading)
    identity_slot = head_title.container()
    _render_diagnostic_markers(state)

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
    st.markdown(
        '<span id="purchase-research-deferred-v1" '
        + f'data-status="{research_status}" '
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

    # ── 0단계 · 결론: 내 견적가 한 칸 + 결론 문장 + 가격대 막대 + 카드 4장 ──
    price_key = f"workspace_quote_price::{quote_key}"
    unit_key = f"workspace_quote_unit::{quote_key}"
    vat_key = f"workspace_quote_vat::{quote_key}"
    conditions_key = f"workspace_quote_conditions::{quote_key}"
    if price_key not in st.session_state:
        st.session_state[price_key] = default_quote
    quote_col, _spacer = st.columns([2.2, 5])
    quote_text = quote_col.text_input(
        "내 견적가 (원)",
        key=price_key,
        placeholder="선택 · 숫자만 입력, 예: 2100000",
    )
    quote_unit = str(st.session_state.get(unit_key) or "")
    vat_status = str(st.session_state.get(vat_key) or "미확인")
    quote_conditions = str(st.session_state.get(conditions_key) or "")
    try:
        workspace_quote = _parse_quote(quote_text)
    except ValueError:
        workspace_quote = review_input.quote_unit_price
        st.warning("내 견적가는 숫자로만 입력하세요. 직전 값으로 비교합니다.")

    stats_track_b, unit_split = _main_unit_view(track_b)
    stats = build_purchase_workspace_stats(
        track_b=stats_track_b,
        market_bundle=market_bundle,
        quote_unit_price=workspace_quote,
    )
    track_b_unavailable = (
        getattr(track_b, "evidence_status", None) == PriceEvidenceStatus.UNAVAILABLE
    )
    conclusion = result_summary_ui.build_conclusion(
        stats,
        quote_unit_price=workspace_quote,
        unavailable=track_b_unavailable,
        unit=unit_split.main_unit,
    )
    st.markdown(result_summary_ui.render_conclusion_html(conclusion), unsafe_allow_html=True)
    unit_note = result_summary_ui.unit_note(unit_split)
    if unit_note:
        st.caption(unit_note)

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
    mfds_complete = bool(
        collection_status.status != "unavailable" and collection_status.first_backfill_complete
    )
    identity_text = workspace_header_ui.identity_line(
        product_name=identity_product,
        permit_numbers=identity_permits,
        permit_type=identity_permit_type,
        companies=identity_companies,
        procurement_product=workspace_header_ui.procurement_product_name(direct_rows),
        procurement_maker=workspace_header_ui.most_common_text(direct_rows, "제조사"),
    )
    procurement_spec = workspace_header_ui.most_common_text(direct_rows, "규격") or ""
    with identity_slot:
        if identity_text:
            st.caption(identity_text)
        if "부품" in procurement_spec:
            st.warning(
                f"나라장터 규격상 **부품**입니다 · 규격: {procurement_spec}. "
                "아래 거래가는 본체가 아니라 이 부품의 가격입니다."
            )

    price_header_card = workspace_header_ui.price_card(stats, unavailable=track_b_unavailable)
    if getattr(track_b, "status", "") == "partial" and stats.direct_count:
        # More matching trades exist than one lookup returns; say what the summary covers.
        price_header_card = dataclasses.replace(
            price_header_card,
            note=price_header_card.note + f" · 최근 {stats.direct_count}건 기준 (더 오래된 거래 있음)",
        )
    # Instant 판매 가능/취소 status from the item-status index (fail-closed while it is still
    # being collected: active is definitive, inactive only after a verified full cycle).
    item_status_lookup = mfds_item_status_service.lookup_item_status_from_r2(
        [
            *identity_permits,
            *(row.get("식약처 품목번호") for row in mfds_procurement_crosslinks),
        ]
    )
    item_status_labels: dict[str, str] = {}
    for status_key, item_status in item_status_lookup.statuses.items():
        label = mfds_item_status_service.item_status_label(
            item_status, cycle_verified=item_status_lookup.cycle_verified
        )
        if label:
            item_status_labels[status_key] = label
    identity_status_label = next(
        (
            item_status_labels["".join(permit.split())]
            for permit in identity_permits
            if "".join(permit.split()) in item_status_labels
        ),
        None,
    )
    mfds_header_card = workspace_header_ui.mfds_card(
        mfds_metric,
        permit_numbers=identity_permits,
        companies=identity_companies,
        coverage_percent=mfds_coverage,
        model_count=len(mfds.records) if isinstance(mfds, MfdsWorkspaceResult) else None,
        active_model_count=(
            len(mfds.active_records) if isinstance(mfds, MfdsWorkspaceResult) else None
        ),
    )
    if identity_status_label:
        mfds_header_card = dataclasses.replace(
            mfds_header_card,
            note=f"{result_summary_ui.plain_status(identity_status_label)} · {mfds_header_card.note}",
        )
    header_cards = [
        price_header_card,
        # Who supplied the product does not depend on the unit, so count every same-product trade.
        workspace_header_ui.supplier_card(
            stats
            if not unit_split.mixed
            else build_purchase_workspace_stats(track_b=track_b, market_bundle=None, quote_unit_price=None)
        ),
        mfds_header_card,
        workspace_header_ui.safety_card(safety_status_value),
    ]
    st.markdown(
        workspace_header_ui.HEADER_CSS + workspace_header_ui.render_cards_html(header_cards),
        unsafe_allow_html=True,
    )

    if isinstance(mfds, MfdsWorkspaceResult) and mfds.status == "deferred":
        _left, _middle, mfds_button_col, _right = st.columns(4)
        if mfds_button_col.button(
            (
                "판매 가능·취소 여부 확인 (약 30초)"
                if isinstance(indexed_identity, MfdsIdentityLookup)
                and indexed_identity.status == "success"
                else "식약처에서 확인 (약 30초)"
            ),
            key=f"workspace_header_mfds_model_info::{quote_key}",
            type="tertiary",
            help="식약처 모델 목록에서 판매 가능·취소 상태와 같은 품목의 다른 모델을 불러옵니다. 가격 결과는 그대로입니다.",
        ):
            with st.status(
                "식약처 모델 목록을 확인하고 있습니다. 가격 결과는 그대로 유지됩니다...",
                expanded=False,
            ) as header_mfds_progress:
                refreshed = dict(state)
                refreshed["mfds"] = _run_deferred_mfds_model_info(state)
                st.session_state[HOME_SEARCH_STATE_KEY] = refreshed
                header_mfds_progress.update(label="식약처 확인 완료", state="complete")
            st.rerun()

    live_note: str | None = None
    live_checked_until: str | None = None
    live_failed = False
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
            live_checked_until = str(getattr(live, "end_date", "") or "") or None
            if live_added:
                live_note = f"나라장터 실시간 확인 {live_window}: 수집 전 거래 {live_added}건 추가"
            else:
                live_note = f"나라장터 실시간 확인 {live_window}: 조회된 {live_found}건 모두 이미 반영"
        elif live_status == "success_0":
            live_checked_until = str(getattr(live, "end_date", "") or "") or None
            live_note = f"나라장터 실시간 확인 {live_window}: 새 거래 0건"
        elif live_status == "failure":
            live_failed = True
            live_note = "나라장터 실시간 확인 실패, 수집해 둔 자료만 표시"
        elif live_status == "not_applicable" and getattr(live, "reason", ""):
            live_note = f"실시간 확인 안 함({live.reason})"
        if live_note and getattr(live, "truncated_window", False):
            live_note += " (최근 62일만 조회)"
        basis_text = result_summary_ui.short_basis_line(
            track_b_data_as_of=track_b_data_as_of,
            live_checked_until=live_checked_until,
            live_failed=live_failed,
            mfds_coverage_percent=mfds_coverage,
            mfds_complete=mfds_complete,
        )
        if basis_text:
            st.caption(basis_text)
    elif track_b_index_updated_at:
        st.caption(f"자료 기준 · 나라장터 자료 갱신 {track_b_index_updated_at}")

    # ── Excel (header button) ──
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
        "Excel로 저장",
        data=export_payload,
        file_name=f"시장조사표_{safe_export_name}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"workspace_market_survey_export::{quote_key}",
        use_container_width=True,
        help="같은 제품 거래, 참고 자료, 납품업체, 식약처 정보와 원문 위치를 모두 담은 시장조사표입니다.",
    )

    # ── 1단계 ① 얼마에 거래됐나 ──
    st.markdown("#### 얼마에 거래됐나")
    if (
        isinstance(indexed_identity, MfdsIdentityLookup)
        and indexed_identity.status == "success"
        and indexed_identity.match_type == "permit"
        and len(indexed_identity.model_names) > 1
    ):
        st.caption(
            f"이 허가번호에는 모델 {len(indexed_identity.model_names)}개가 있어, 아래 표를 모델별로 나눴습니다."
        )
    if state["model_probe_used"]:
        st.caption("검색어가 모델명과 같아 그 모델의 거래를 보여줍니다.")
    if direct_rows:
        all_groups = result_summary_ui.unit_group_rows(direct_rows, limit=len(direct_rows))
        if all_groups:
            st.dataframe(
                all_groups[: result_summary_ui.SUMMARY_ROW_LIMIT],
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "단위(대·set 등)와 거래조건이 같은 거래끼리 묶었습니다. 가격은 모두 1단위 가격이며, "
                "거래 총액 합계 ÷ 총수량과는 다를 수 있습니다."
                + (
                    f" {len(all_groups)}가지 중 거래가 많은 {result_summary_ui.SUMMARY_ROW_LIMIT}가지만 보여줍니다."
                    if len(all_groups) > result_summary_ui.SUMMARY_ROW_LIMIT
                    else ""
                )
            )
        record_view_key = f"workspace_record_view::{quote_key}"
        record_table_key = f"workspace_direct_table::{quote_key}"
        record_applied_key = f"workspace_direct_table_applied::{quote_key}"
        # A row picked in the full table (previous run) opens its record above the table.
        table_state = st.session_state.get(record_table_key)
        picked_rows = list(
            ((table_state or {}).get("selection") or {}).get("rows") or []
        ) if isinstance(table_state, Mapping) else []
        picked = picked_rows[0] if picked_rows else None
        if picked != st.session_state.get(record_applied_key):
            st.session_state[record_applied_key] = picked
            if picked is not None and 0 <= picked < len(direct_rows):
                st.session_state[record_view_key] = str(direct_rows[picked].get("원천기록") or "")

        median_price = stats.median_price
        outliers = result_summary_ui.price_outlier_rows(direct_rows, median_price)
        if outliers and median_price is not None:
            st.warning(
                f"중앙값과 3배 넘게 차이 나는 거래가 {len(outliers)}건 있습니다. "
                "단위(세트·대)나 계약 방식이 다른 거래일 수 있으니 조달청 원문을 확인하세요."
            )
            for index, row in enumerate(outliers[: result_summary_ui.OUTLIER_SHOWN]):
                line_col, button_col = st.columns([5, 1.2], vertical_alignment="center")
                line_col.caption(result_summary_ui.outlier_line(row, median_price, unit_split.main_unit))
                if row.get("원천기록") and button_col.button(
                    "원문 보기",
                    key=f"workspace_outlier_record::{quote_key}::{index}",
                    type="tertiary",
                ):
                    st.session_state[record_view_key] = str(row["원천기록"])

        rows_by_record = {
            str(row.get("원천기록") or ""): row for row in direct_rows if row.get("원천기록")
        }
        selected_record = str(st.session_state.get(record_view_key) or "")
        if selected_record in rows_by_record:
            _render_delivery_record(
                rows_by_record[selected_record],
                view_key=record_view_key,
                close_key=f"workspace_record_close::{quote_key}",
            )

        with st.expander(f"같은 제품 거래 {strict_count}건 전체 보기", expanded=False):
            st.dataframe(
                # 거래 총액 → 수량 → 1단위 가격 순서라 세트 거래도 헷갈리지 않습니다.
                result_summary_ui.trade_table_rows(direct_rows),
                use_container_width=True,
                hide_index=True,
                on_select="rerun",
                selection_mode="single-row",
                key=record_table_key,
            )
            st.caption(
                "행을 누르면 그 거래의 조달청 공개 원문(사업명·계약 방법·납품 기한 등)이 위에 열립니다. "
                "모든 항목은 Excel에도 들어 있습니다."
            )
    elif track_b.status == "unavailable":
        st.warning("가격 자료에 연결하지 못했습니다.")
    elif track_b.status == "not_ingested":
        st.info("가격 자료를 준비하는 중입니다. 잠시 뒤 다시 검색하세요.")
    else:
        st.info("이 모델과 같은 제품으로 확인된 나라장터 거래가 없습니다.")

    if (
        isinstance(indexed_identity, MfdsIdentityLookup)
        and indexed_identity.status == "success"
        and indexed_identity.match_type == "permit"
        and exact_identity_crosslinks
    ):
        with st.expander(
            f"이 허가번호의 모델 {len(exact_identity_crosslinks)}개별 거래 보기",
            expanded=False,
        ):
            st.dataframe(
                result_summary_ui.display_rows(exact_identity_crosslinks),
                use_container_width=True,
                hide_index=True,
            )

    if reference_rows:
        with st.expander(
            f"비슷한 품목 거래 {reference_count}건 보기 · 같은 제품인지 확인 안 됨, 비교에서 제외",
            expanded=False,
        ):
            st.dataframe(
                result_summary_ui.display_rows(reference_rows),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "대당 단가": st.column_config.TextColumn("표기 금액 (미검증)"),
                    "총액": st.column_config.TextColumn("거래총액"),
                },
            )
            st.caption(
                "품목명이나 분류가 비슷한 거래입니다. 모델·규격이 같은지 확인되기 전에는 가격 비교에 쓰지 않습니다."
            )

    # ── 1단계 ② 누가 파는가 ──
    st.markdown("#### 누가 파는가")
    procurement_suppliers = supplier_rows(track_b)
    if procurement_suppliers:
        st.dataframe(
            result_summary_ui.supplier_summary_rows(procurement_suppliers),
            use_container_width=True,
            hide_index=True,
        )
        hidden_suppliers = len(procurement_suppliers) - result_summary_ui.SUMMARY_ROW_LIMIT
        st.caption(
            "같은 제품을 나라장터에 납품한 업체입니다. 납품 실적이 있다고 공식 총판이라는 뜻은 아닙니다."
            + (f" 나머지 {hidden_suppliers}곳은 Excel에 있습니다." if hidden_suppliers > 0 else "")
        )
    elif track_b_unavailable:
        st.warning("나라장터 가격 자료를 읽지 못해 납품업체를 확인하지 못했습니다.")
    else:
        st.caption("같은 제품 거래가 없어 납품업체도 없습니다.")

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
        with st.expander(
            f"식약처에 같은 품목으로 등록한 제조·수입업체 {len(company_summaries)}곳 보기",
            expanded=False,
        ):
            st.caption(
                "식약처에 등록한 제조·수입업체는 위 납품업체와 다른 관계입니다. 이름이 비슷해도 같은 회사로 보지 않습니다."
            )
            st.dataframe(
                [
                    {
                        "제조·수입업체": item.company_name,
                        "등록 모델": item.registered_model_count,
                        "허가 건수": item.permit_count,
                        "최근 허가일": item.latest_permit_date or "",
                        "대표 모델": " / ".join(item.representative_models),
                        "거래가 있는 모델": item.direct_price_model_count,
                        "납품업체(나라장터)": " / ".join(item.procurement_suppliers),
                        "판매 상태": result_summary_ui.plain_status(item.live_status),
                    }
                    for item in company_summaries
                ],
                use_container_width=True,
                hide_index=True,
            )
            selected_company = st.selectbox(
                "업체 하나 자세히 보기",
                options=[item.company_name for item in company_summaries],
                key=f"workspace_company_drilldown::{quote_key}",
            )
            detail_rows = company_identity_rows(
                same_product_identity,
                selected_company,
                active_live_keys=company_active_keys,
            )
            if detail_rows:
                st.dataframe(
                    result_summary_ui.display_rows(detail_rows),
                    use_container_width=True,
                    hide_index=True,
                )
            _render_business_license_lookup(selected_company, quote_key)

    # ── 1단계 ③ 같은 품목의 다른 모델 ──
    identity_known = (
        isinstance(indexed_identity, MfdsIdentityLookup) and indexed_identity.status == "success"
    )
    if mfds_procurement_crosslinks or identity_known:
        st.markdown("#### 같은 품목의 다른 모델")
        live_loaded = isinstance(mfds, MfdsWorkspaceResult) and mfds.status in {"success", "success_0"}
        current_keys = (
            [(item.permit_number, item.model_name) for item in indexed_identity.records]
            if identity_known
            else ()
        )
        summary_view = same_item_ui.build_same_item_rows(
            mfds_procurement_crosslinks,
            same_item_ui.live_status_index(mfds.records if live_loaded else None),
            current_keys=current_keys,
            item_status_labels=item_status_labels,
            reference_price=stats.median_price,
        )
        current_note = same_item_ui.current_model_note(summary_view)
        if current_note:
            st.info(current_note)
        if summary_view.rows:
            st.dataframe(
                result_summary_ui.same_item_summary_rows(summary_view.rows),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "식약처에 같은 품목으로 등록된 모델 중 나라장터 거래가 있는 모델입니다. ▶ 표시는 검색한 모델입니다. "
                "성능이나 대체 가능 여부는 판단하지 않습니다."
            )
            gap_note = same_item_ui.price_gap_note(summary_view)
            if gap_note:
                st.warning(gap_note)
        elif not current_note:
            st.caption("같은 품목의 다른 모델 중 나라장터 거래가 있는 모델이 아직 없습니다.")

        if mfds_procurement_crosslinks:
            with st.expander(
                f"같은 품목 모델 전체 {len(mfds_procurement_crosslinks)}개 보기",
                expanded=False,
            ):
                filter_priced, filter_inactive = st.columns(2)
                only_priced = filter_priced.checkbox(
                    "거래가 있는 모델만",
                    value=True,
                    key=f"workspace_same_item_priced::{quote_key}",
                )
                include_inactive = filter_inactive.checkbox(
                    "취소·수출 전용 모델도 보기",
                    value=False,
                    key=f"workspace_same_item_inactive::{quote_key}",
                )
                full_view = same_item_ui.build_same_item_rows(
                    mfds_procurement_crosslinks,
                    same_item_ui.live_status_index(mfds.records if live_loaded else None),
                    include_unpriced=not only_priced,
                    include_inactive=include_inactive,
                    current_keys=current_keys,
                    item_status_labels=item_status_labels,
                    reference_price=stats.median_price,
                )
                if full_view.rows:
                    current_note = same_item_ui.current_model_note(full_view)
                    if current_note:
                        st.info(current_note)
                    st.dataframe(
                        result_summary_ui.display_rows(full_view.rows),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info("조건에 맞는 모델이 없습니다.")
                notes = [same_item_ui.hidden_note(full_view), *same_item_ui.status_notes(full_view)]
                st.caption(". ".join(note for note in notes if note) or "모든 모델을 표시했습니다.")

                if isinstance(mfds, MfdsWorkspaceResult) and mfds.active_competitor_records:
                    st.markdown(
                        f"##### 식약처 모델 목록의 같은 품목 판매 가능 모델 {len(mfds.active_competitor_records)}개"
                    )
                    st.caption("이 목록에는 업체·가격 정보가 없습니다.")
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
        _render_medical_lookup_link(indexed_identity, mfds, query)

    # ── 2단계 · 상세 자료 (한 묶음) ──
    with st.expander("상세 자료 · 견적 조건 · 안전정보 · 식약처 원자료 · 자료 기준", expanded=False):
        st.markdown("##### 견적 조건")
        st.caption("조건을 적으면 Excel 시장조사표에 함께 기록됩니다.")
        q1, q2, q3 = st.columns([1.2, 1.2, 3.0])
        q1.text_input("단위", placeholder="예: 대 / 개", key=unit_key)
        q2.selectbox("VAT", options=["미확인", "포함", "별도"], key=vat_key)
        q3.text_input("설치·운송 등 조건", placeholder="예: 설치 포함 · 운송 포함", key=conditions_key)
        if workspace_quote is not None:
            st.caption(
                "적어 둔 조건 · "
                + " · ".join(
                    (
                        f"단위 {quote_unit.strip()}" if quote_unit.strip() else "단위 미확인",
                        f"VAT {vat_status}" if vat_status != "미확인" else "VAT 미확인",
                        quote_conditions.strip() or "설치·운송 조건 미확인",
                    )
                )
                + ". 나라장터 거래가 같은 조건이었는지는 따로 확인해야 합니다."
            )

        st.markdown("##### 안전정보 확인 내역")
        safety_text = f"{workspace_header_ui.safety_card(safety_status_value).value} · {safety_state.message}"
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
            st.caption(f"식약처 회수·판매중지 확인 시각 · {safety_state.checked_at}")
        if safety_state.search_keys:
            st.caption("확인에 쓴 값 · " + " / ".join(safety_state.search_keys))
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
                "회수 기록에는 허가번호가 없어 '관련 안전정보'로 표시합니다. 적용 범위는 원문에서 확인하세요."
            )
        safety_cols = st.columns(3)
        safety_cols[0].link_button("회수·판매중지 확인", MFDS_RECALL_PAGE_URL, use_container_width=True)
        safety_cols[1].link_button("행정처분 확인", MFDS_ADMIN_SANCTION_PAGE_URL, use_container_width=True)
        safety_cols[2].link_button("안전성서한 확인", MFDS_SAFETY_LETTER_PAGE_URL, use_container_width=True)

        st.markdown("##### 식약처 원자료")
        _render_mfds_raw_details(indexed_identity, mfds)
        if not (mfds_procurement_crosslinks or identity_known) and isinstance(mfds, MfdsWorkspaceResult):
            _render_medical_lookup_link(indexed_identity, mfds, query)

        if isinstance(interpretation, UnifiedSearchInterpretation):
            _render_search_interpretation(interpretation)

        st.markdown("##### 자료 기준")
        full_basis = workspace_header_ui.data_basis_line(
            track_b_data_as_of=track_b_data_as_of,
            live_note=live_note,
            mfds_coverage_percent=mfds_coverage,
            mfds_complete=mfds_complete,
        )
        if full_basis:
            st.caption(full_basis)
        _render_mfds_collection_status_body(collection_status)
        st.caption(
            "거래가는 실제 나라장터 거래에서 같은 제품으로 확인된 것만 씁니다. 모델·규격·VAT·설치·옵션 "
            "조건이 같은지는 따로 확인해야 하며, 이 화면은 견적이 비싼지 싼지 판정하지 않습니다."
        )

    # ── 필요할 때만 · 입찰·계약 참고자료 (안에 펼침이 있어 묶음 밖에 둠) ──
    st.markdown("##### 입찰·계약 참고자료")
    if research_status in {"pending", "failure"}:
        if research_status == "pending":
            st.caption(
                "입찰·낙찰·사전규격·계약 자료는 필요할 때만 불러옵니다(수십 초). 위 거래가와는 별개입니다."
            )
            research_button_label = "입찰·계약 참고자료 불러오기"
        else:
            st.warning("참고자료 조회에 실패했습니다. 위 거래가·업체·식약처 정보는 그대로입니다.")
            research_button_label = "입찰·계약 참고자료 다시 불러오기"
        if st.button(research_button_label, key=f"workspace_research_load::{quote_key}"):
            try:
                with st.status(
                    "위 결과는 그대로 둔 채 입찰·계약 참고자료를 불러오고 있습니다...",
                    expanded=False,
                ) as research_progress:
                    enriched_state = _execute_deferred_research(state)
                    st.session_state[HOME_SEARCH_STATE_KEY] = enriched_state
                    research_progress.update(label="입찰·계약 참고자료 불러오기 완료", state="complete")
                st.rerun()
            except Exception as exc:
                failed_state = dict(state)
                failed_state["research_status"] = "failure"
                failed_state["research_error_type"] = type(exc).__name__
                st.session_state[HOME_SEARCH_STATE_KEY] = failed_state
                st.warning(
                    "입찰·계약 참고자료를 불러오지 못했습니다. 위 거래가는 그대로 쓸 수 있습니다. "
                    f"({type(exc).__name__})"
                )
    else:
        st.caption("같은 제품 거래가 아닌 참고자료입니다. 가격 비교·판정에는 쓰지 않습니다.")
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
            m1.metric("공개 가격 근거", f"{assessment.observed_count}건")
            m2.metric("서로 다른 출처", f"{assessment.source_count}개")
            m3.metric("근거 신뢰도", assessment.confidence)
            render_observation_cards(run.results)
            render_evidence_table(run.results)
        else:
            st.caption("공개 자료에서 같은 제품의 가격은 찾지 못했습니다.")


def _render_business_license_lookup(selected_company: str, quote_key: str) -> None:
    business_cache_key = "workspace_company_business_lookup::" + normalize_text(selected_company)
    if st.button("이 업체 식약처 업허가 확인", key=f"workspace_company_business_button::{quote_key}"):
        business_lookup = getattr(mfds_workspace_service, "lookup_mfds_business_license", None)
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
            st.warning("업허가 조회 기능을 지금 쓸 수 없습니다. 페이지를 새로 고친 뒤 다시 시도하세요.")
    selected_business_lookup = st.session_state.get(business_cache_key)
    if selected_business_lookup is None:
        return
    if selected_business_lookup.status == "success":
        filter_left, filter_right = st.columns(2)
        include_inactive = filter_left.checkbox(
            "폐업·휴업·취소 업허가도 보기",
            value=False,
            key=f"workspace_company_business_inactive::{quote_key}",
        )
        include_partial = filter_right.checkbox(
            "이름 일부만 같은 다른 업체도 보기",
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
                "이름이 정확히 같은 업허가가 없어 이름 일부가 같은 업체를 보여줍니다. "
                "다른 회사일 수 있으니 주소·허가번호로 확인하세요."
            )
        if license_view.rows:
            st.dataframe(list(license_view.rows), use_container_width=True, hide_index=True)
        else:
            st.info("현재 조건에 맞는 식약처 업허가가 없습니다.")
        hidden_notes = []
        if license_view.hidden_inactive_count:
            hidden_notes.append(f"폐업·휴업·취소 {license_view.hidden_inactive_count}건")
        if license_view.hidden_partial_count:
            hidden_notes.append(f"이름 일부만 같은 다른 업체 {license_view.hidden_partial_count}건")
        st.caption(
            "업허가가 있어도 특정 모델의 판매점·총판이라는 뜻은 아닙니다."
            + (f" 숨긴 결과 · {', '.join(hidden_notes)}" if hidden_notes else "")
        )
    elif selected_business_lookup.status == "success_0":
        st.info("이 업체 이름으로 확인된 식약처 업허가가 없습니다.")
    elif selected_business_lookup.status == "not_configured":
        st.warning("식약처 업허가 서비스키가 연결되지 않아 조회하지 못했습니다.")
    elif selected_business_lookup.status == "failure":
        st.warning(
            "식약처 업허가 조회 실패 · "
            f"{selected_business_lookup.error_type or '오류'} · "
            f"{selected_business_lookup.error_message or '상세 미확인'}"
        )


def _render_mfds_raw_details(indexed_identity: object, mfds: object) -> None:
    if isinstance(indexed_identity, MfdsIdentityLookup):
        if indexed_identity.status == "success" and indexed_identity.records:
            st.dataframe(
                [
                    {
                        "허가 구분": mfds_item_authorization_type(item).value,
                        "허가번호": item.permit_number or "",
                        "품목": item.product_name or "",
                        "모델": item.model_name or "",
                        "제조·수입업체(식약처)": item.registered_company or "",
                        "UDI-DI": item.udi_di or "",
                        "허가일": item.permit_date or "",
                        "등급": item.grade or "",
                        "출처": MFDS_PRODUCT_INFO_DATASET_URL,
                        "원문 확인값": (item.source_payload_sha256 or "")[:16],
                    }
                    for item in indexed_identity.records
                ],
                use_container_width=True,
                hide_index=True,
            )
            st.caption("식약처 공식 제품정보입니다. 제조·수입업체는 실제 납품업체와 다른 관계입니다.")
        elif mfds_identity_status(indexed_identity) == IdentityEvidenceStatus.NOT_FOUND_IN_COVERAGE:
            st.caption("지금까지 모은 식약처 자료에서 이 모델의 등록정보를 찾지 못했습니다.")
        elif indexed_identity.status == "not_ingested":
            st.caption("식약처 제품정보를 아직 쓸 수 없습니다.")
        elif indexed_identity.status == "unavailable":
            st.warning("식약처 제품정보를 지금 읽을 수 없습니다.")

    if not isinstance(mfds, MfdsWorkspaceResult):
        return
    if mfds.status == "deferred":
        st.caption("판매 가능·취소 여부는 카드 아래 '식약처에서 확인' 버튼으로 불러옵니다 (약 30초).")
    elif mfds.status == "not_applicable":
        st.caption("나라장터 분류상 의료기기 조회 대상이 아닙니다.")
    elif mfds.status == "not_configured":
        st.warning("식약처 서비스키가 연결되지 않아 조회하지 못했습니다.")
    elif mfds.status == "failure":
        st.warning(
            f"식약처 조회 실패 · {mfds.error_type or '오류'} · {mfds.error_message or '상세 미확인'}. "
            "조회 실패를 '등록 0건'으로 보지 않습니다."
        )
    else:
        m1c, m2c, m3c = st.columns(3)
        m1c.metric("같은 품목 등록 모델", f"{len(mfds.records)}건")
        m2c.metric("그중 판매 가능", f"{len(mfds.active_records)}건")
        if mfds.exact_ambiguous:
            m3c.metric("이 모델명", "허가 여러 건 · 확인 필요")
        elif mfds.exact_confirmed:
            m3c.metric("이 모델명", "등록 확인")
        else:
            m3c.metric("이 모델명", "못 찾음")
        if mfds.exact_records:
            st.dataframe(
                [
                    {
                        "품목": item.product_name or "",
                        "모델": item.model_name or "",
                        "허가번호": item.permit_number or "",
                        "허가일": item.permit_date.isoformat() if item.permit_date else "",
                        "업종": item.industry_type or "",
                        "수출 전용": item.export_only,
                        "취소 상태": item.cancellation_status or "",
                    }
                    for item in mfds.exact_records
                ],
                use_container_width=True,
                hide_index=True,
            )
        if mfds.business_records:
            hint_view = build_business_license_view(
                mfds.business_records,
                str(getattr(mfds, "business_query", "") or ""),
            )
            if hint_view.rows:
                st.caption("입력한 업체명의 식약처 업허가 (이 모델의 제조·수입 관계를 뜻하지 않음)")
                st.dataframe(list(hint_view.rows), use_container_width=True, hide_index=True)


hydrate_streamlit_runtime_secrets()
_refresh_ui_modules()
st.set_page_config(page_title="가격 조사", page_icon="🔎", layout="wide")
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
    '<span id="purchase-workspace-runtime-v13" style="display:none">purchase-workspace-runtime-v13</span>'
    '<span id="purchase-workspace-runtime-v14" style="display:none">purchase-workspace-runtime-v14</span>'
    '<span id="purchase-workspace-runtime-v15" style="display:none">purchase-workspace-runtime-v15</span>'
    '<span id="purchase-workspace-runtime-v16" style="display:none">purchase-workspace-runtime-v16</span>'
    '<span id="purchase-workspace-runtime-v17" style="display:none">purchase-workspace-runtime-v17</span>'
    '<span id="purchase-workspace-mfds-v1" style="display:none">purchase-workspace-mfds-v1</span>'
    '<span id="purchase-workspace-mfds-v2" style="display:none">purchase-workspace-mfds-v2</span>'
    '<span id="purchase-workspace-quote-v1" style="display:none">purchase-workspace-quote-v1</span>'
    '<span id="purchase-workspace-v3-shell" style="display:none">purchase-workspace-v3-shell</span>'
    '<span id="purchase-simple-result-v1" style="display:none">purchase-simple-result-v1</span>',
    unsafe_allow_html=True,
)

st.markdown(
    """
<style>
.block-container {max-width: 1180px; padding-top: 2.2rem;}
[data-testid="stForm"] {border: 0; padding: 0;}
[data-testid="stFileUploader"] {margin-top: 0.2rem;}
.home-title {text-align:center; font-size:2.35rem; font-weight:750; margin:1.2rem 0 0.35rem 0;}
.home-subtitle {text-align:center; color:#6b7280; margin-bottom:1.4rem;}
.home-section {margin-top:1.15rem;}
</style>
""",
    unsafe_allow_html=True,
)

existing_result = isinstance(st.session_state.get(HOME_SEARCH_STATE_KEY), dict)
handoff_pending = PURCHASE_WORKSPACE_HANDOFF_SESSION_KEY in st.session_state
if not existing_result and not handoff_pending:
    st.markdown('<div class="home-title">무엇을 조사할까요?</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="home-subtitle">모델명, 품목명, 업체명 중 하나만 넣으면 나라장터 거래가와 식약처 허가정보를 함께 찾습니다.</div>',
        unsafe_allow_html=True,
    )

handoff_payload = st.session_state.pop(PURCHASE_WORKSPACE_HANDOFF_SESSION_KEY, None)
handoff = parse_purchase_workspace_handoff(handoff_payload)
if handoff is not None:
    try:
        with st.status("견적서 품목의 거래가·허가정보를 찾고 있습니다...", expanded=False) as status:
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
            status.update(label="견적 품목 조사 완료", state="complete")
    except ValueError as exc:
        st.warning(f"견적 품목을 조사하지 못했습니다: {exc}")

search_state = st.session_state.get(HOME_SEARCH_STATE_KEY)
shared_query = str(st.query_params.get("q") or "").strip()
if not isinstance(search_state, dict) and shared_query and handoff is None:
    try:
        with st.status("공유된 검색을 다시 불러오고 있습니다...", expanded=False) as status:
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
            status.update(label="검색 결과를 불러왔습니다", state="complete")
            st.rerun()
    except ValueError as exc:
        st.warning(f"공유된 검색을 불러오지 못했습니다: {exc}")

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
            placeholder="모델명 · 품목명 · 업체명 · 허가번호",
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
        st.session_state.pop(QUOTE_ITEM_RESULTS_SESSION_KEY, None)
        st.query_params.clear()
        st.rerun()

    with st.expander("다른 견적서 올리기", expanded=False):
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
            placeholder="모델명 · 품목명 · 업체명 · 허가번호",
            label_visibility="collapsed",
        )
        submitted = button_col.form_submit_button("검색", type="primary", use_container_width=True)
        st.caption("예: HeartOn A16-DS · 심장충격기 · (주)메디아나")

        with st.expander("조건 직접 입력", expanded=False):
            a1, a2 = st.columns(2)
            product_name = a1.text_input("품명", placeholder="예: 가스마취기")
            manufacturer = a2.text_input("제조사", placeholder="예: Getinge / Maquet")
            model_name = a1.text_input("모델명", placeholder="예: FLOW-C")
            specification = a2.text_input("규격", placeholder="선택")
            quote_text = a1.text_input("내 견적가", placeholder="선택 · 예: 66000000")
            lookback_days = a2.selectbox(
                "나라장터 검색기간",
                options=G2B_LOOKBACK_OPTIONS,
                index=G2B_LOOKBACK_OPTIONS.index(G2B_DEFAULT_LOOKBACK_DAYS),
                format_func=g2b_lookback_label,
            )

    st.markdown('<div class="home-section"></div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("**견적서로 시작하기**")
        st.caption("PDF · Excel · 사진 견적서를 올리면 품목을 뽑아 품목마다 거래가를 찾습니다.")
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
        with st.spinner("견적서에서 품목을 뽑고 있습니다..."):
            _store_extraction(uploaded, quote_state)
        st.session_state.pop(QUOTE_AUTO_ROUTE_FILE_SESSION_KEY, None)
        st.session_state.pop(QUOTE_ITEM_RESULTS_SESSION_KEY, None)

    if quote_state.items:
        already_routed = st.session_state.get(QUOTE_AUTO_ROUTE_FILE_SESSION_KEY) == uploaded.name
        if not already_routed:
            item = quote_state.items[0]
            try:
                with st.status(
                    f"품목 {len(quote_state.items)}개를 찾았습니다. 1번 품목을 조사하고 있습니다...",
                    expanded=False,
                ) as status:
                    quote_result = _execute_search(
                        search_text=(item.model_name or item.product_name or ""),
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
                    status.update(label="1번 품목 조사 완료", state="complete")
                st.rerun()
            except ValueError as exc:
                st.session_state[QUOTE_AUTO_ROUTE_FILE_SESSION_KEY] = uploaded.name
                st.warning(
                    "1번 품목에 품명이나 모델명이 없어 바로 조사하지 못했습니다. "
                    f"아래 '견적 상세 검증'에서 추출 내용을 확인하세요. ({exc})"
                )
                st.page_link("pages/2_견적_검토.py", label="견적 상세 검증 열기", icon="📋")
    else:
        st.warning(
            "견적서에서 품목을 찾지 못했습니다. 모델명을 검색창에 직접 넣거나, "
            "'견적 상세 검증'에서 품목을 직접 입력하세요."
        )
        st.page_link("pages/2_견적_검토.py", label="견적 상세 검증 열기", icon="📋")

if submitted:
    try:
        with st.status("거래가와 허가정보를 찾고 있습니다...", expanded=False) as status:
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
            st.query_params.pop("view", None)
            st.query_params.pop("identity", None)
            status.update(label="조사 완료", state="complete")
            st.rerun()
    except ValueError as exc:
        st.warning(str(exc))
        st.stop()


search_state = st.session_state.get(HOME_SEARCH_STATE_KEY)
if isinstance(search_state, dict):
    if search_state.get("origin") == "quote":
        _render_quote_items(search_state)
    if search_state.get("route") == "candidate_selection":
        _render_identity_candidate_selection(search_state)
    elif search_state.get("route") in overview_ui.OVERVIEW_ROUTES:
        _render_overview(search_state)
    else:
        _render_search_result(search_state)
