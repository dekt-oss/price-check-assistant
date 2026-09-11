from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import statistics
from datetime import date, timedelta
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
from purchase_price.storage.r2 import canonical_json_bytes

PAGE_SIZE = 999
SIZE_SAMPLE_CODES = 10
SIZE_SAMPLE_ROWS = 20
TRACK = "MEDICAL_DIAGNOSTICS"


def _classify_exception(exc: Exception) -> str:
    if isinstance(exc, PublicDataTransportError):
        return "TRANSPORT_ERROR"
    if isinstance(exc, PublicDataClientError):
        text = str(exc).lower()
        if any(token in text for token in ("auth", "service key", "인증", "등록되지 않은")):
            return "AUTH_ERROR"
        if any(token in text for token in ("rate", "quota", "limit", "초과")):
            return "RATE_LIMIT"
        if any(token in text for token in ("필수값", "parameter", "invalid", "잘못")):
            return "INVALID_PARAMETER"
        return "SOURCE_ERROR"
    return "SOURCE_ERROR"


def _track_b_params(*, code: str, end: date, rows: int) -> dict[str, Any]:
    begin = end - timedelta(days=364)
    return {
        "pageNo": 1,
        "numOfRows": rows,
        "inqryDiv": "1",
        "inqryBgnDate": begin.strftime("%Y%m%d"),
        "inqryEndDate": end.strftime("%Y%m%d"),
        "inqryPrdctDiv": "2",
        "dtilPrdctClsfcNo": code,
    }


def _load_enabled_codes(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    enabled: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if row.get("collect_track") != TRACK:
            continue
        if row.get("review_status") != "COLLECT_ENABLED":
            continue
        if str(row.get("enabled") or "").strip().lower() not in {"true", "1", "yes"}:
            raise RuntimeError("COLLECT_ENABLED row must have enabled=true")
        code = str(row.get("detail_code_or_segment") or "").strip()
        if len(code) != 10 or not code.isdigit():
            raise RuntimeError(f"Domain01 enabled code must be exact 10 digits: {code!r}")
        if code in seen:
            raise RuntimeError(f"Duplicate Domain01 enabled code: {code}")
        seen.add(code)
        enabled.append({"code": code, "name": str(row.get("official_name") or "").strip()})
    if not enabled:
        raise RuntimeError("No Domain01 COLLECT_ENABLED codes found")
    return enabled


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1))
    return ordered[index]


def probe(*, allowlist_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    settings = get_settings()
    shopping_key = (settings.resolved_g2b_shopping_service_key or "").strip()
    if not shopping_key:
        raise RuntimeError("G2B shopping/data.go.kr key is not configured")

    enabled = _load_enabled_codes(allowlist_path)
    client = PublicDataPortalClient(
        shopping_key,
        timeout_seconds=settings.g2b_request_timeout_seconds,
        max_retries=settings.g2b_max_retries,
    )
    shopping_url = settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL
    operation = G2BShoppingOperation.SPECIFIC_ITEM_PROCUREMENTS.value
    end = date.today()
    begin = end - timedelta(days=364)
    started = perf_counter()

    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    request_seconds: list[float] = []
    for entry in enabled:
        code = entry["code"]
        t0 = perf_counter()
        try:
            payload = client.get_json(
                shopping_url,
                operation,
                **_track_b_params(code=code, end=end, rows=1),
            )
            page = unwrap_g2b_page(payload)
            if page.total_count is None:
                raise PublicDataClientError("Track B response did not expose totalCount")
        except Exception as exc:  # diagnostic probe: classify, never convert to zero
            failures.append(
                {
                    "code": code,
                    "name": entry["name"],
                    "status": _classify_exception(exc),
                    "error_type": type(exc).__name__,
                }
            )
            continue
        request_seconds.append(perf_counter() - t0)
        count = int(page.total_count)
        results.append(
            {
                "code": code,
                "name": entry["name"],
                "status": "ZERO_RESULT" if count == 0 else "SUCCESS",
                "total_count": count,
                "backfill_api_calls": max(1, math.ceil(count / PAGE_SIZE)),
            }
        )

    compressed_sizes: list[int] = []
    raw_sizes: list[int] = []
    nonzero = [row for row in results if int(row["total_count"]) > 0]
    nonzero.sort(key=lambda row: (-int(row["total_count"]), str(row["code"])))
    storage_sample_failures: list[dict[str, str]] = []
    for row in nonzero[:SIZE_SAMPLE_CODES]:
        try:
            payload = client.get_json(
                shopping_url,
                operation,
                **_track_b_params(code=str(row["code"]), end=end, rows=SIZE_SAMPLE_ROWS),
            )
            page = unwrap_g2b_page(payload)
        except Exception as exc:
            storage_sample_failures.append(
                {
                    "code": str(row["code"]),
                    "status": _classify_exception(exc),
                    "error_type": type(exc).__name__,
                }
            )
            continue
        for item in page.items:
            canonical = canonical_json_bytes(item)
            raw_sizes.append(len(canonical))
            compressed_sizes.append(len(gzip.compress(canonical, compresslevel=6, mtime=0)))

    complete = not failures
    total_rows = sum(int(row["total_count"]) for row in results) if complete else None
    total_calls = sum(int(row["backfill_api_calls"]) for row in results) if complete else None
    gzip_mean = statistics.mean(compressed_sizes) if compressed_sizes else None
    gzip_median = statistics.median(compressed_sizes) if compressed_sizes else None
    gzip_p90 = _percentile([float(value) for value in compressed_sizes], 0.90)

    storage_estimate = None
    if total_rows is not None and gzip_mean is not None:
        storage_estimate = {
            "record_body_gb_mean": round(total_rows * gzip_mean / 1e9, 4),
            "record_body_gb_median": round(total_rows * float(gzip_median) / 1e9, 4),
            "record_body_gb_p90": round(total_rows * float(gzip_p90) / 1e9, 4),
            "note": "Canonical per-record gzip body only; R2 object/envelope metadata overhead is not included.",
        }

    report: dict[str, Any] = {
        "status": "SUCCESS" if complete and not storage_sample_failures else "PARTIAL_SUCCESS",
        "domain": TRACK,
        "source_operation": operation,
        "window_begin": begin.isoformat(),
        "window_end": end.isoformat(),
        "enabled_code_count": len(enabled),
        "successful_count_probes": len(results),
        "count_probe_failures": failures,
        "zero_result_codes": sum(1 for row in results if row["status"] == "ZERO_RESULT"),
        "exact_track_b_rows_one_year": total_rows,
        "exact_track_b_api_calls_page999": total_calls,
        "days_at_800_calls_per_day": math.ceil(total_calls / 800) if total_calls is not None else None,
        "days_at_900_calls_per_day": math.ceil(total_calls / 900) if total_calls is not None else None,
        "probe_request_count": len(results) + len(failures) + min(SIZE_SAMPLE_CODES, len(nonzero)),
        "request_seconds_mean": round(statistics.mean(request_seconds), 3) if request_seconds else None,
        "request_seconds_median": round(statistics.median(request_seconds), 3) if request_seconds else None,
        "raw_record_size_sample": {
            "codes": min(SIZE_SAMPLE_CODES, len(nonzero)),
            "records": len(compressed_sizes),
            "sample_failures": storage_sample_failures,
            "canonical_bytes_mean": round(statistics.mean(raw_sizes), 1) if raw_sizes else None,
            "gzip_bytes_mean": round(gzip_mean, 1) if gzip_mean is not None else None,
            "gzip_bytes_median": round(float(gzip_median), 1) if gzip_median is not None else None,
            "gzip_bytes_p90": round(float(gzip_p90), 1) if gzip_p90 is not None else None,
        },
        "storage_estimate": storage_estimate,
        "elapsed_seconds": round(perf_counter() - started, 2),
    }
    return report, results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allowlist", default="data/pps_collect_tracks.csv")
    parser.add_argument("--output", default="artifacts/domain01-volume/report.json")
    parser.add_argument("--per-code-output", default="artifacts/domain01-volume/per_code.json")
    args = parser.parse_args()

    report, results = probe(allowlist_path=Path(args.allowlist))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    per_code = Path(args.per_code_output)
    per_code.parent.mkdir(parents=True, exist_ok=True)
    per_code.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "SUCCESS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
