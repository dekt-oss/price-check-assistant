from __future__ import annotations

import argparse
import json
import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

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
            "DEADLINE_HAS_EXPIRED",
            "CODE=20",
            "CODE=30",
            "CODE=31",
        )
    ):
        return "AUTH_ERROR"
    if any(
        token in text
        for token in (
            "LIMITED_NUMBER_OF_SERVICE_REQUESTS",
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
            "CODE=08",
            "CODE=10",
            "RESULTCODE=08",
            "RESULTCODE=10",
        )
    ):
        return "INVALID_PARAMETER"
    if any(token in text for token in ("SERVICETIMEOUT_ERROR", "CODE=05")):
        return "TRANSPORT_ERROR"
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
        "prdctMakrNm",
        "prdctSpecNm",
        "cntrctPrceAmt",
        "vatAplDivNm",
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
    empty = page.total_count == 0 or (page.total_count is None and not page.items)
    first = page.items[0] if page.items else None
    return ProbeResult(
        operation=operation,
        case=case,
        status="ZERO_RESULT" if empty else "SUCCESS",
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


def _fetch_unit10_page(
    client: PublicDataPortalClient,
    *,
    base_url: str,
    page_no: int,
    rows: int,
) -> tuple[ProbeResult, list[dict[str, Any]]]:
    started = perf_counter()
    params = {"pageNo": page_no, "numOfRows": rows}
    try:
        payload = client.get_json(base_url, UNIT10_OPERATION, **params)
        page = unwrap_g2b_page(payload)
    except (PublicDataClientError, PublicDataTransportError, ValueError) as exc:
        return (
            ProbeResult(
                operation=UNIT10_OPERATION,
                case=f"dictionary_page_{page_no}",
                status=classify_exception(exc),
                elapsed_ms=round((perf_counter() - started) * 1000),
                request_params=params,
                error_type=type(exc).__name__,
                error_message=_safe_text(exc),
            ),
            [],
        )

    code, msg = _response_header(payload)
    empty = page.total_count == 0 or (page.total_count is None and not page.items)
    first = page.items[0] if page.items else None
    return (
        ProbeResult(
            operation=UNIT10_OPERATION,
            case=f"dictionary_page_{page_no}",
            status="ZERO_RESULT" if empty else "SUCCESS",
            elapsed_ms=round((perf_counter() - started) * 1000),
            request_params=params,
            total_count=page.total_count,
            item_count=len(page.items),
            page_no=page.page_no,
            num_of_rows=page.num_of_rows,
            result_code=code,
            result_msg=msg,
            observed_fields=tuple(sorted(first.keys())) if first else (),
            sample=_first_item_summary(first),
        ),
        [dict(item) for item in page.items],
    )


def probe_unit10(client: PublicDataPortalClient, *, base_url: str) -> dict[str, Any]:
    first, first_items = _fetch_unit10_page(
        client,
        base_url=base_url,
        page_no=1,
        rows=PROBE_LARGE_PAGE_SIZE,
    )
    if first.status not in {"SUCCESS", "ZERO_RESULT"} or first.total_count is None:
        return {
            "operation": UNIT10_OPERATION,
            "full_enumeration": "미검증",
            "max_tested_num_of_rows": PROBE_LARGE_PAGE_SIZE,
            "golden_codes": {code: "미검증" for code in GOLDEN_DETAIL_CODES},
            "probes": [asdict(first)],
        }

    total_pages = max(1, math.ceil(first.total_count / PROBE_LARGE_PAGE_SIZE))
    probes = [first]
    items = list(first_items)
    for page_no in range(2, total_pages + 1):
        result, page_items = _fetch_unit10_page(
            client,
            base_url=base_url,
            page_no=page_no,
            rows=PROBE_LARGE_PAGE_SIZE,
        )
        probes.append(result)
        if result.status not in {"SUCCESS", "ZERO_RESULT"}:
            return {
                "operation": UNIT10_OPERATION,
                "full_enumeration": "PARTIAL_SUCCESS",
                "total_count": first.total_count,
                "page_count_expected": total_pages,
                "page_count_succeeded": page_no - 1,
                "max_tested_num_of_rows": PROBE_LARGE_PAGE_SIZE,
                "golden_codes": {code: "미검증" for code in GOLDEN_DETAIL_CODES},
                "probes": [asdict(row) for row in probes],
            }
        items.extend(page_items)

    by_code = {
        str(item.get("dtilPrdctClsfcNo") or "").strip(): str(
            item.get("dtilPrdctClsfcNoNm") or ""
        ).strip()
        for item in items
        if str(item.get("dtilPrdctClsfcNo") or "").strip()
    }
    golden = {
        code: {
            "verification": "VERIFIED" if code in by_code else "NOT_FOUND",
            "name": by_code.get(code) or None,
        }
        for code in GOLDEN_DETAIL_CODES
    }
    complete = len(items) >= first.total_count
    return {
        "operation": UNIT10_OPERATION,
        "full_enumeration": "VERIFIED" if complete else "PARTIAL_SUCCESS",
        "total_count": first.total_count,
        "collected_count": len(items),
        "unique_code_count": len(by_code),
        "page_count": total_pages,
        "request_count": total_pages,
        "max_tested_num_of_rows": PROBE_LARGE_PAGE_SIZE,
        "stable_fields": ["dtilPrdctClsfcNo", "dtilPrdctClsfcNoNm", "chgDate", "useYn"],
        "golden_codes": golden,
        "probes": [asdict(row) for row in probes],
    }


def _field_contract(result: ProbeResult) -> dict[str, list[str]]:
    fields = set(result.observed_fields)
    groups = {
        "request_no": ("cntrctDlvrReqNo",),
        "change_order": ("cntrctDlvrReqChgOrd",),
        "line_no": ("prdctSno",),
        "product_id": ("prdctIdntNo",),
        "detail_code": ("dtilPrdctClsfcNo",),
        "unit_price": ("prdctUprc", "dlvrUprc", "cntrctUprc"),
        "quantity": ("prdctQty",),
        "unit": ("prdctUnit", "unitNm"),
        "institution": ("dminsttNm", "dminsttCd"),
        "supplier": ("corpNm", "bizno", "bizrno"),
        "final_flag": ("fnlCntrctDlvrReqChgOrdYn",),
    }
    return {name: [key for key in aliases if key in fields] for name, aliases in groups.items()}


def probe_track_a(client: PublicDataPortalClient, *, base_url: str, end: date) -> dict[str, Any]:
    begin = end - timedelta(days=6)
    basic = {
        "pageNo": 1,
        "numOfRows": 1,
        "inqryBgnDate": begin.strftime("%Y%m%d"),
        "inqryEndDate": end.strftime("%Y%m%d"),
    }
    date_only = run_page_probe(
        client=client,
        base_url=base_url,
        operation=G2BShoppingOperation.DELIVERY_REQUEST_DETAILS.value,
        case="date_only_7d",
        params=basic,
    )
    with_div = run_page_probe(
        client=client,
        base_url=base_url,
        operation=G2BShoppingOperation.DELIVERY_REQUEST_DETAILS.value,
        case="date_only_7d_inqryDiv_1",
        params={**basic, "inqryDiv": "1"},
    )
    accepted = next(
        (row for row in (date_only, with_div) if row.status in {"SUCCESS", "ZERO_RESULT"}),
        None,
    )
    large = (
        run_page_probe(
            client=client,
            base_url=base_url,
            operation=G2BShoppingOperation.DELIVERY_REQUEST_DETAILS.value,
            case="date_only_7d_page_999",
            params={**accepted.request_params, "numOfRows": PROBE_LARGE_PAGE_SIZE},
        )
        if accepted is not None
        else None
    )
    year_params: dict[str, Any] = {
        "pageNo": 1,
        "numOfRows": 1,
        "inqryBgnDate": (end - timedelta(days=364)).strftime("%Y%m%d"),
        "inqryEndDate": end.strftime("%Y%m%d"),
    }
    if accepted is not None and accepted.request_params.get("inqryDiv") is not None:
        year_params["inqryDiv"] = accepted.request_params["inqryDiv"]
    year = run_page_probe(
        client=client,
        base_url=base_url,
        operation=G2BShoppingOperation.DELIVERY_REQUEST_DETAILS.value,
        case="date_only_365d_window",
        params=year_params,
    )

    evidence = large or accepted or date_only
    contract = _field_contract(evidence)
    page_size = (
        PROBE_LARGE_PAGE_SIZE
        if large is not None and large.status in {"SUCCESS", "ZERO_RESULT"}
        else 1
    )
    pages_per_7d = (
        math.ceil(evidence.total_count / page_size)
        if evidence.total_count is not None
        else None
    )
    probes = [date_only, with_div, year]
    if large is not None:
        probes.insert(2, large)
    return {
        "operation": G2BShoppingOperation.DELIVERY_REQUEST_DETAILS.value,
        "date_only_contract": "VERIFIED" if accepted is not None else "HOLD",
        "accepted_extra_params": (
            {
                key: value
                for key, value in accepted.request_params.items()
                if key not in {"pageNo", "numOfRows", "inqryBgnDate", "inqryEndDate"}
            }
            if accepted is not None
            else {}
        ),
        "window_365d": (
            "ACCEPTED" if year.status in {"SUCCESS", "ZERO_RESULT"} else year.status
        ),
        "max_tested_num_of_rows": page_size,
        "field_contract": contract,
        "stable_key_candidate": "cntrctDlvrReqNo + cntrctDlvrReqChgOrd + prdctSno",
        "stable_key_verified": (
            "VERIFIED"
            if all(contract[key] for key in ("request_no", "change_order", "line_no"))
            else "미검증"
        ),
        "seven_day_total_count": evidence.total_count,
        "estimated_pages_per_7d_window": pages_per_7d,
        "probes": [asdict(row) for row in probes],
    }


def _track_b_params(
    *,
    begin: date,
    end: date,
    detail_code: str | None,
    rows: int,
    final: str | None = None,
) -> dict[str, Any]:
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
    exact = [
        run_page_probe(
            client=client,
            base_url=base_url,
            operation=operation,
            case=f"exact_code_{code}",
            params=_track_b_params(begin=begin, end=end, detail_code=code, rows=1),
        )
        for code in GOLDEN_DETAIL_CODES
    ]
    date_only = run_page_probe(
        client=client,
        base_url=base_url,
        operation=operation,
        case="date_only_without_product_selector",
        params=_track_b_params(begin=begin, end=end, detail_code=None, rows=1),
    )
    all_changes = run_page_probe(
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
    final_only = run_page_probe(
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
    exact_ok = all(row.status in {"SUCCESS", "ZERO_RESULT"} for row in exact)
    evidence = next((row for row in exact if row.observed_fields), exact[0])
    contract = _field_contract(evidence)
    return {
        "operation": operation,
        "exact_10_digit_contract": "VERIFIED" if exact_ok else "미검증",
        "date_only_without_selector": date_only.status,
        "date_only_rejected_as_required": date_only.status == "INVALID_PARAMETER",
        "window_days_tested": 365,
        "max_tested_num_of_rows": (
            PROBE_LARGE_PAGE_SIZE
            if all_changes.status in {"SUCCESS", "ZERO_RESULT"}
            else 1
        ),
        "all_change_orders_without_final_filter": (
            "VERIFIED"
            if all_changes.status in {"SUCCESS", "ZERO_RESULT"}
            else "미검증"
        ),
        "final_y_total_count": final_only.total_count,
        "no_final_filter_total_count": all_changes.total_count,
        "change_order_delta": (
            all_changes.total_count - final_only.total_count
            if all_changes.total_count is not None and final_only.total_count is not None
            else "미검증"
        ),
        "stable_key": "cntrctDlvrReqNo + cntrctDlvrReqChgOrd + prdctSno",
        "stable_key_fields_observed": (
            "VERIFIED"
            if all(contract[key] for key in ("request_no", "change_order", "line_no"))
            else "미검증"
        ),
        "explicit_unit_price_fields_observed": contract["unit_price"] or ["미검증"],
        "golden_counts": {
            row.case.removeprefix("exact_code_"): row.total_count for row in exact
        },
        "probes": [asdict(row) for row in [*exact, date_only, all_changes, final_only]],
    }


def probe_track_c(client: PublicDataPortalClient, *, base_url: str, end: date) -> dict[str, Any]:
    begin = end - timedelta(days=6)
    operations = (
        G2BShoppingOperation.MAS_CONTRACT_PRODUCTS.value,
        G2BShoppingOperation.SHOPPING_MALL_PRODUCTS.value,
    )
    results = [
        run_page_probe(
            client=client,
            base_url=base_url,
            operation=operation,
            case="bounded_date_window",
            params={
                "pageNo": 1,
                "numOfRows": 1,
                "inqryBgnDate": begin.strftime("%Y%m%d"),
                "inqryEndDate": end.strftime("%Y%m%d"),
            },
        )
        for operation in operations
    ]
    return {
        "operations_tested": list(operations),
        "registration_increment_contract": "미검증",
        "change_increment_contract": "미검증",
        "three_party_vs_general_unit_separation": "미검증",
        "observed_increment_fields": {
            row.operation: [key for key in ("rgstDt", "chgDt") if key in row.observed_fields]
            for row in results
        },
        "note": (
            "Response fields rgstDt/chgDt do not prove the request selector contract. "
            "Do not implement incremental Track C until the documented/live selector is verified."
        ),
        "probes": [asdict(row) for row in results],
    }


def _budget(
    unit10: Mapping[str, Any],
    track_a: Mapping[str, Any],
    track_b: Mapping[str, Any],
) -> dict[str, Any]:
    dictionary_calls = unit10.get("request_count")
    track_a_daily = track_a.get("estimated_pages_per_7d_window")
    track_a_30 = track_a_daily * 30 if isinstance(track_a_daily, int) else None

    golden_counts = track_b.get("golden_counts")
    page_size = track_b.get("max_tested_num_of_rows")
    track_b_backfill = None
    if isinstance(golden_counts, Mapping) and isinstance(page_size, int) and page_size > 0:
        known = [value for value in golden_counts.values() if isinstance(value, int)]
        if len(known) == len(GOLDEN_DETAIL_CODES):
            track_b_backfill = sum(math.ceil(value / page_size) for value in known)

    return {
        "development_daily_limit_documented": DEVELOPMENT_DAILY_TRAFFIC_LIMIT,
        "unit10_full_dictionary_calls": (
            dictionary_calls if isinstance(dictionary_calls, int) else "미검증"
        ),
        "track_a_30d_calls_if_daily_7d_replay": (
            track_a_30 if track_a_30 is not None else "미검증"
        ),
        "track_b_golden_7_code_one_year_backfill_calls": (
            track_b_backfill if track_b_backfill is not None else "미검증"
        ),
        "track_c_30d_calls": "미검증",
        "full_23609_code_track_b_backfill_calls": "미검증",
        "production_limit": "활용사례 등록 후 증설 신청 가능; 실제 승인량 미검증",
        "warning": (
            "Measured calls are feasibility evidence only. They are not authorization "
            "for an all-industry backfill."
        ),
    }


def build_report(*, end: date) -> dict[str, Any]:
    settings = get_settings()
    shopping_key = (settings.resolved_g2b_shopping_service_key or "").strip()
    catalog_key = (settings.resolved_g2b_catalog_service_key or "").strip()
    report: dict[str, Any] = {
        "schema_version": 2,
        "verified_at": datetime.now(UTC).isoformat(),
        "end_date": end.isoformat(),
        "secret_sources": {
            "shopping": settings.g2b_shopping_key_source,
            "catalog": settings.g2b_catalog_key_source,
        },
        "secrets_present": {
            "shopping": bool(shopping_key),
            "catalog": bool(catalog_key),
        },
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
        ) as client:
            report["unit10_dictionary"] = probe_unit10(
                client,
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
        ) as client:
            base_url = settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL
            report["track_a"] = probe_track_a(client, base_url=base_url, end=end)
            report["track_b"] = probe_track_b(client, base_url=base_url, end=end)
            report["track_c"] = probe_track_c(client, base_url=base_url, end=end)
    else:
        missing = {"status": "AUTH_ERROR", "reason": "shopping service key is not configured"}
        report["track_a"] = dict(missing)
        report["track_b"] = dict(missing)
        report["track_c"] = dict(missing)

    report["call_budget"] = _budget(
        report["unit10_dictionary"],
        report["track_a"],
        report["track_b"],
    )
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bounded live probe for DB Collection PR-DB0"
    )
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    report = build_report(end=args.end_date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"db0_probe_output={args.output}")
    print(f"verified_at={report['verified_at']}")
    print(
        "unit10="
        f"{report['unit10_dictionary'].get('full_enumeration', report['unit10_dictionary'].get('status'))}"
    )
    print(
        "track_a="
        f"{report['track_a'].get('date_only_contract', report['track_a'].get('status'))}"
    )
    print(
        "track_b="
        f"{report['track_b'].get('exact_10_digit_contract', report['track_b'].get('status'))}"
    )
    print(
        "track_c_registration="
        f"{report['track_c'].get('registration_increment_contract', report['track_c'].get('status'))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
