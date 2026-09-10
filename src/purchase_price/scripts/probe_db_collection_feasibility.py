from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping

from purchase_price.clients.data_go_kr import (
    PublicDataClientError,
    PublicDataPortalClient,
    PublicDataTransportError,
)
from purchase_price.collectors.g2b_shopping import (
    G2B_SHOPPING_BASE_URL,
    G2BShoppingOperation,
    unwrap_g2b_page,
)
from purchase_price.config import get_settings
from purchase_price.services.g2b_catalog import G2B_CATALOG_BASE_URL

UNIT10_OPERATION = "getPrdctClsfcNoUnit10Info02"
GOLDEN_DETAIL_CODES = (
    "4110449801",  # 이산화탄소배양기
    "4227250101",  # 가스마취기
    "4227220901",  # 인공호흡기
    "4110630701",  # 유전자증폭기
    "4321150301",  # 노트북컴퓨터
    "4321210501",  # 레이저프린터
    "4321151501",  # 워크스테이션
)

# Gate 0 deliberately tests one large page without assuming that 999 is supported.
PROBE_LARGE_PAGE_SIZE = 999
DEVELOPMENT_DAILY_TRAFFIC_LIMIT = 1000


@dataclass(frozen=True)
class ProbeResult:
    operation: str
    case: str
    status: str
    elapsed_ms: int
    request_params: dict[str, Any]
    total_count: int | None = None
    item_count: int | None = None
    page_no: int | None = None
    num_of_rows: int | None = None
    result_code: str | None = None
    result_msg: str | None = None
    observed_fields: tuple[str, ...] = ()
    sample: dict[str, Any] | None = None
    error_type: str | None = None
    error_message: str | None = None


def _safe_text(value: Any, *, limit: int = 300) -> str:
    text = str(value or "").replace("\n", " ").strip()
    # Defensive second line of protection: never persist a serviceKey query value.
    text = re.sub(r"(?i)(serviceKey=)[^&\s\"']+", r"\1***", text)
    return text[:limit]


def classify_exception(exc: Exception) -> str:
    if isinstance(exc, PublicDataTransportError):
        return "TRANSPORT_ERROR"

    text = _safe_text(exc).upper()
    if any(
        token in text
        for token in (
            "PERMISSION_DENIED",
            "SERVICE_ACCESS_DENIED",
            "SERVICE_KEY_IS_NOT_REGISTERED",
            "SERVICE_KEY_IS_NULL",
            "AUTH",
            "CODE=20",
            "CODE=30",
        )
    ):
        return "AUTH_ERROR"
    if any(
        token in text
        for token in (
            "LIMITED_NUMBER_OF_SERVICE_REQUESTS",
            "RATE",
            "CODE=22",
            "CODE=23",
        )
    ):
        return "RATE_LIMIT"
    if any(
        token in text
        for token in (
            "INVALID_REQUEST_PARAMETER",
            "INVALID PARAMETER",
            "필수값",
            "CODE=10",
            "RESULTCODE=08",
        )
    ):
        return "INVALID_PARAMETER"
    return "SOURCE_ERROR"


def _response_header(payload: Mapping[str, Any]) -> tuple[str | None, str | None]:
    response = payload.get("response", payload)
    if not isinstance(response, Mapping):
        return None, None
    header = response.get("header")
    if not isinstance(header, Mapping):
        return None, None
    code = _safe_text(header.get("resultCode")) or None
    msg = _safe_text(header.get("resultMsg")) or None
    return code, msg


def _first_item_summary(item: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not item:
        return None
    allow = (
        "cntrctDlvrReqNo",
        "cntrctDlvrReqChgOrd",
        "prdctSno",
        "prdctIdntNo",
        "prdctIdntNoNm",
        "dtilPrdctClsfcNo",
        "dtilPrdctClsfcNoNm",
        "prdctUprc",
        "prdctQty",
        "prdctAmt",
        "prdctUnit",
        "dminsttNm",
        "corpNm",
        "fnlCntrctDlvrReqChgOrdYn",
        "rgstDt",
        "chgDt",
        "mkrNm",
        "mnfcturNm",
        "spec",
        "cntrctPrce",
        "vat",
    )
    return {key: item[key] for key in allow if key in item and item[key] not in (None, "")}


def run_page_probe(
    *,
    client: PublicDataPortalClient,
    base_url: str,
    operation: str,
    case: str,
    params: dict[str, Any],
) -> ProbeResult:
    started = perf_counter()
    try:
        payload = client.get_json(base_url, operation, **params)
        page = unwrap_g2b_page(payload)
    except (PublicDataClientError, PublicDataTransportError, ValueError) as exc:
        return ProbeResult(
            operation=operation,
            case=case,
            status=classify_exception(exc),
            elapsed_ms=round((perf_counter() - started) * 1000),
            request_params=dict(params),
            error_type=type(exc).__name__,
            error_message=_safe_text(exc),
        )

    code, msg = _response_header(payload)
    status = "ZERO_RESULT" if page.total_count == 0 or (page.total_count is None and not page.items) else "SUCCESS"
    first = page.items[0] if page.items else None
    return ProbeResult(
        operation=operation,
        case=case,
        status=status,
        elapsed_ms=round((perf_counter() - started) * 1000),
        request_params=dict(params),
        total_count=page.total_count,
        item_count=len(page.items),
        page_no=page.page_no,
        num_of_rows=page.num_of_rows,
        result_code=code,
        result_msg=msg,
        observed_fields=tuple(sorted(first.keys())) if first else (),
        sample=_first_item_summary(first),
    )


def _code_from_item(item: Mapping[str, Any]) -> str:
    for key in ("dtilPrdctClsfcNo", "prdctClsfcNo", "prdctClsfcNoUnit10"):
        value = str(item.get(key) or "").strip()
        if len(value) == 10 and value.isdigit():
            return value
    return ""


def probe_unit10(client: PublicDataPortalClient, *, base_url: str) -> dict[str, Any]:
    results: list[ProbeResult] = []
    results.append(
        run_page_probe(
            client=client,
            base_url=base_url,
            operation=UNIT10_OPERATION,
            case="unfiltered_page_1",
            params={"pageNo": 1, "numOfRows": 1},
        )
    )
    results.append(
        run_page_probe(
            client=client,
            base_url=base_url,
            operation=UNIT10_OPERATION,
            case="large_page_999",
            params={"pageNo": 1, "numOfRows": PROBE_LARGE_PAGE_SIZE},
        )
    )

    # The exact selector name is itself part of the feasibility question. We test the most
    # conservative official-code-shaped selector and verify that the response actually contains
    # the requested code; a normal response that ignores the selector is not counted as verified.
    golden: dict[str, dict[str, Any]] = {}
    for detail_code in GOLDEN_DETAIL_CODES:
        result = run_page_probe(
            client=client,
            base_url=base_url,
            operation=UNIT10_OPERATION,
            case=f"golden_{detail_code}",
            params={"pageNo": 1, "numOfRows": 10, "prdctClsfcNo": detail_code},
        )
        results.append(result)
        matched = False
        if result.status in {"SUCCESS", "ZERO_RESULT"} and result.sample:
            matched = _code_from_item(result.sample) == detail_code
        golden[detail_code] = {
            "request_status": result.status,
            "exact_code_observed_in_first_item": matched,
            "verification": "VERIFIED" if matched else "미검증",
        }

    unfiltered = results[0]
    full_enumeration = (
        "VERIFIED"
        if unfiltered.status in {"SUCCESS", "ZERO_RESULT"} and unfiltered.total_count is not None
        else "미검증"
    )
    return {
        "operation": UNIT10_OPERATION,
        "full_enumeration": full_enumeration,
        "total_count": unfiltered.total_count,
        "max_tested_num_of_rows": (
            PROBE_LARGE_PAGE_SIZE if results[1].status in {"SUCCESS", "ZERO_RESULT"} else 1
        ),
        "golden_codes": golden,
        "probes": [asdict(row) for row in results],
    }


def _track_a_field_contract(result: ProbeResult) -> dict[str, Any]:
    fields = set(result.observed_fields)
    groups = {
        "request_no": ("cntrctDlvrReqNo",),
        "change_order": ("cntrctDlvrReqChgOrd",),
        "line_no": ("prdctSno",),
        "product_id": ("prdctIdntNo",),
        "unit_price": ("prdctUprc", "dlvrUprc", "cntrctUprc"),
        "quantity": ("prdctQty",),
        "unit": ("prdctUnit", "unitNm"),
        "institution": ("dminsttNm", "dminsttCd"),
        "supplier": ("corpNm", "bizrno"),
        "final_flag": ("fnlCntrctDlvrReqChgOrdYn",),
    }
    return {
        name: [key for key in aliases if key in fields]
        for name, aliases in groups.items()
    }


def probe_track_a(client: PublicDataPortalClient, *, base_url: str, end: date) -> dict[str, Any]:
    begin = end - timedelta(days=6)
    base_params = {
        "pageNo": 1,
        "numOfRows": 1,
        "inqryBgnDate": begin.strftime("%Y%m%d"),
        "inqryEndDate": end.strftime("%Y%m%d"),
    }
    first = run_page_probe(
        client=client,
        base_url=base_url,
        operation=G2BShoppingOperation.DELIVERY_REQUEST_DETAILS.value,
        case="date_only_7d",
        params=base_params,
    )
    large = run_page_probe(
        client=client,
        base_url=base_url,
        operation=G2BShoppingOperation.DELIVERY_REQUEST_DETAILS.value,
        case="date_only_7d_page_999",
        params={**base_params, "numOfRows": PROBE_LARGE_PAGE_SIZE},
    )
    year_begin = end - timedelta(days=364)
    year = run_page_probe(
        client=client,
        base_url=base_url,
        operation=G2BShoppingOperation.DELIVERY_REQUEST_DETAILS.value,
        case="date_only_365d_window",
        params={
            "pageNo": 1,
            "numOfRows": 1,
            "inqryBgnDate": year_begin.strftime("%Y%m%d"),
            "inqryEndDate": end.strftime("%Y%m%d"),
        },
    )
    effective_page = PROBE_LARGE_PAGE_SIZE if large.status in {"SUCCESS", "ZERO_RESULT"} else 1
    seven_day_pages = (
        math.ceil(first.total_count / effective_page)
        if first.total_count is not None and effective_page > 0
        else None
    )
    return {
        "operation": G2BShoppingOperation.DELIVERY_REQUEST_DETAILS.value,
        "date_only_contract": "VERIFIED" if first.status in {"SUCCESS", "ZERO_RESULT"} else "미검증",
        "window_365d": "ACCEPTED" if year.status in {"SUCCESS", "ZERO_RESULT"} else year.status,
        "max_tested_num_of_rows": effective_page,
        "field_contract": _track_a_field_contract(first),
        "stable_key_candidate": "cntrctDlvrReqNo + cntrctDlvrReqChgOrd + prdctSno",
        "stable_key_verified": (
            "VERIFIED"
            if all(_track_a_field_contract(first)[key] for key in ("request_no", "change_order", "line_no"))
            else "미검증"
        ),
        "seven_day_total_count": first.total_count,
        "estimated_pages_per_7d_window": seven_day_pages,
        "probes": [asdict(first), asdict(large), asdict(year)],
    }


def _track_b_params(*, begin: date, end: date, detail_code: str | None, rows: int, final: str | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {
        "pageNo": 1,
        "numOfRows": rows,
        "inqryDiv": "1",
        "inqryBgnDate": begin.strftime("%Y%m%d"),
        "inqryEndDate": end.strftime("%Y%m%d"),
        "inqryPrdctDiv": "2",
    }
    if detail_code:
        params["dtilPrdctClsfcNo"] = detail_code
    if final is not None:
        params["fnlCntrctDlvrReqChgOrdYn"] = final
    return params


def probe_track_b(client: PublicDataPortalClient, *, base_url: str, end: date) -> dict[str, Any]:
    begin = end - timedelta(days=364)
    operation = G2BShoppingOperation.SPECIFIC_ITEM_PROCUREMENTS.value
    exact_results: list[ProbeResult] = []
    for detail_code in GOLDEN_DETAIL_CODES:
        exact_results.append(
            run_page_probe(
                client=client,
                base_url=base_url,
                operation=operation,
                case=f"exact_code_{detail_code}",
                params=_track_b_params(begin=begin, end=end, detail_code=detail_code, rows=1),
            )
        )

    date_only = run_page_probe(
        client=client,
        base_url=base_url,
        operation=operation,
        case="date_only_without_product_selector",
        params=_track_b_params(begin=begin, end=end, detail_code=None, rows=1),
    )
    large = run_page_probe(
        client=client,
        base_url=base_url,
        operation=operation,
        case=f"exact_code_{GOLDEN_DETAIL_CODES[0]}_page_999",
        params=_track_b_params(
            begin=begin,
            end=end,
            detail_code=GOLDEN_DETAIL_CODES[0],
            rows=PROBE_LARGE_PAGE_SIZE,
        ),
    )
    final_y = run_page_probe(
        client=client,
        base_url=base_url,
        operation=operation,
        case=f"exact_code_{GOLDEN_DETAIL_CODES[0]}_final_Y",
        params=_track_b_params(
            begin=begin,
            end=end,
            detail_code=GOLDEN_DETAIL_CODES[0],
            rows=PROBE_LARGE_PAGE_SIZE,
            final="Y",
        ),
    )

    exact_ok = all(row.status in {"SUCCESS", "ZERO_RESULT"} for row in exact_results)
    first_nonempty = next((row for row in exact_results if row.observed_fields), exact_results[0])
    contract = _track_a_field_contract(first_nonempty)
    stable = all(contract[key] for key in ("request_no", "change_order", "line_no"))
    explicit_price_fields = contract["unit_price"]
    return {
        "operation": operation,
        "exact_10_digit_contract": "VERIFIED" if exact_ok else "미검증",
        "date_only_without_selector": date_only.status,
        "date_only_rejected_as_required": date_only.status == "INVALID_PARAMETER",
        "window_days_tested": 365,
        "max_tested_num_of_rows": (
            PROBE_LARGE_PAGE_SIZE if large.status in {"SUCCESS", "ZERO_RESULT"} else 1
        ),
        "all_change_orders_without_final_filter": (
            "ACCEPTED" if large.status in {"SUCCESS", "ZERO_RESULT"} else "미검증"
        ),
        "final_y_total_count": final_y.total_count,
        "no_final_filter_total_count": large.total_count,
        "stable_key_candidate": "cntrctDlvrReqNo + cntrctDlvrReqChgOrd + prdctSno",
        "stable_key_fields_observed": "VERIFIED" if stable else "미검증",
        "explicit_unit_price_fields_observed": explicit_price_fields or ["미검증"],
        "golden_counts": {row.case.removeprefix("exact_code_"): row.total_count for row in exact_results},
        "probes": [asdict(row) for row in [*exact_results, date_only, large, final_y]],
    }


def probe_track_c(client: PublicDataPortalClient, *, base_url: str, end: date) -> dict[str, Any]:
    begin = end - timedelta(days=6)
    operations = (
        G2BShoppingOperation.MAS_CONTRACT_PRODUCTS.value,
        G2BShoppingOperation.SHOPPING_MALL_PRODUCTS.value,
    )
    results: list[ProbeResult] = []
    # Do not guess unverified registration/change parameter names. The two known operations are
    # checked for their minimum request contract; rgstDt/chgDt incremental selectors remain
    # explicitly unverified until a live/documented parameter contract is observed.
    for operation in operations:
        results.append(
            run_page_probe(
                client=client,
                base_url=base_url,
                operation=operation,
                case="bounded_date_window_candidate",
                params={
                    "pageNo": 1,
                    "numOfRows": 1,
                    "inqryBgnDate": begin.strftime("%Y%m%d"),
                    "inqryEndDate": end.strftime("%Y%m%d"),
                },
            )
        )
    return {
        "operations_tested": list(operations),
        "registration_increment_contract": "미검증",
        "change_increment_contract": "미검증",
        "three_party_vs_general_unit_separation": "미검증",
        "note": (
            "PR-DB0 does not invent rgstDt/chgDt request parameter names. Add the exact live/documented "
            "contract only after a successful service probe."
        ),
        "probes": [asdict(row) for row in results],
    }


def _budget(track_a: Mapping[str, Any], track_b: Mapping[str, Any]) -> dict[str, Any]:
    a_pages = track_a.get("estimated_pages_per_7d_window")
    a_30 = a_pages * 30 if isinstance(a_pages, int) else None
    golden_counts = track_b.get("golden_counts")
    page_size = track_b.get("max_tested_num_of_rows")
    golden_backfill = None
    if isinstance(golden_counts, Mapping) and isinstance(page_size, int) and page_size > 0:
        known = [value for value in golden_counts.values() if isinstance(value, int)]
        if len(known) == len(GOLDEN_DETAIL_CODES):
            golden_backfill = sum(math.ceil(value / page_size) for value in known)
    measured = [value for value in (a_30, golden_backfill) if isinstance(value, int)]
    subtotal = sum(measured) if len(measured) == 2 else None
    return {
        "development_daily_limit_documented": DEVELOPMENT_DAILY_TRAFFIC_LIMIT,
        "track_a_30d_calls_if_daily_7d_replay": a_30 if a_30 is not None else "미검증",
        "track_b_golden_7_code_one_year_backfill_calls": (
            golden_backfill if golden_backfill is not None else "미검증"
        ),
        "track_c_30d_calls": "미검증",
        "unit10_full_dictionary_calls": "미검증",
        "measured_subtotal_excluding_unverified_tracks": subtotal if subtotal is not None else "미검증",
        "production_limit": "활용사례 등록 후 증설 신청 가능; 실제 승인량 미검증",
        "warning": "This is a feasibility budget, not authorization to consume the full daily quota.",
    }


def build_report(*, end: date) -> dict[str, Any]:
    settings = get_settings()
    shopping_key = (settings.resolved_g2b_shopping_service_key or "").strip()
    catalog_key = (settings.resolved_g2b_catalog_service_key or "").strip()

    report: dict[str, Any] = {
        "schema_version": 1,
        "verified_at": datetime.now(UTC).isoformat(),
        "end_date": end.isoformat(),
        "secret_sources": {
            "shopping": settings.g2b_shopping_key_source,
            "catalog": settings.g2b_catalog_key_source,
        },
        "secrets_present": {"shopping": bool(shopping_key), "catalog": bool(catalog_key)},
        "hosted_postgresql": {
            "status": "미검증",
            "required_roles": ["collector_writer", "streamlit_reader", "migration_admin"],
            "streamlit_read_only_smoke": "미검증",
        },
    }

    if catalog_key:
        with PublicDataPortalClient(
            catalog_key,
            timeout_seconds=settings.g2b_request_timeout_seconds,
            max_retries=settings.g2b_max_retries,
        ) as catalog_client:
            report["unit10_dictionary"] = probe_unit10(
                catalog_client,
                base_url=settings.g2b_catalog_base_url or G2B_CATALOG_BASE_URL,
            )
    else:
        report["unit10_dictionary"] = {
            "operation": UNIT10_OPERATION,
            "status": "AUTH_ERROR",
            "reason": "catalog service key is not configured",
        }

    if shopping_key:
        with PublicDataPortalClient(
            shopping_key,
            timeout_seconds=settings.g2b_request_timeout_seconds,
            max_retries=settings.g2b_max_retries,
        ) as shopping_client:
            shopping_base = settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL
            report["track_a"] = probe_track_a(shopping_client, base_url=shopping_base, end=end)
            report["track_b"] = probe_track_b(shopping_client, base_url=shopping_base, end=end)
            report["track_c"] = probe_track_c(shopping_client, base_url=shopping_base, end=end)
    else:
        missing = {"status": "AUTH_ERROR", "reason": "shopping service key is not configured"}
        report["track_a"] = dict(missing)
        report["track_b"] = dict(missing)
        report["track_c"] = dict(missing)

    report["call_budget"] = _budget(report["track_a"], report["track_b"])
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bounded live probe for DB Collection PR-DB0")
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    report = build_report(end=args.end_date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"db0_probe_output={args.output}")
    print(f"verified_at={report['verified_at']}")
    print(f"unit10={report['unit10_dictionary'].get('full_enumeration', report['unit10_dictionary'].get('status'))}")
    print(f"track_a={report['track_a'].get('date_only_contract', report['track_a'].get('status'))}")
    print(f"track_b={report['track_b'].get('exact_10_digit_contract', report['track_b'].get('status'))}")
    print(f"track_c_registration={report['track_c'].get('registration_increment_contract', report['track_c'].get('status'))}")
    # Feasibility measurement records HOLD/failure as data; CI success must not be confused with
    # live API acceptance success. Schema/contract errors are enforced by offline tests.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
