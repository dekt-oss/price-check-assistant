from __future__ import annotations

import gzip
import json
import math
import random
import statistics
from collections import defaultdict
from datetime import date, timedelta
from time import perf_counter
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.collectors.g2b_shopping import (
    G2B_SHOPPING_BASE_URL,
    G2BShoppingOperation,
    unwrap_g2b_page,
)
from purchase_price.config import get_settings
from purchase_price.services.g2b_catalog import G2B_CATALOG_BASE_URL
from purchase_price.storage.r2 import canonical_json_bytes

UNIT10_OPERATION = "getPrdctClsfcNoUnit10Info02"
PAGE_SIZE = 999
TARGET_SEGMENTS = ("23", "27", "39", "41", "42", "43", "44", "46")
SAMPLES_PER_SEGMENT = 10
SIZE_SAMPLE_CODES = 10
SIZE_SAMPLE_ROWS = 20
SEED = 20260911


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1))
    return ordered[index]


def _fetch_dictionary(client: PublicDataPortalClient, base_url: str) -> list[dict[str, Any]]:
    first_payload = client.get_json(base_url, UNIT10_OPERATION, pageNo=1, numOfRows=PAGE_SIZE)
    first = unwrap_g2b_page(first_payload)
    if first.total_count is None:
        raise RuntimeError("Unit10 dictionary response did not expose totalCount")
    pages = max(1, math.ceil(first.total_count / PAGE_SIZE))
    items = [dict(item) for item in first.items]
    for page_no in range(2, pages + 1):
        payload = client.get_json(base_url, UNIT10_OPERATION, pageNo=page_no, numOfRows=PAGE_SIZE)
        page = unwrap_g2b_page(payload)
        items.extend(dict(item) for item in page.items)
    return items


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


def main() -> int:
    settings = get_settings()
    catalog_key = (settings.resolved_g2b_catalog_service_key or "").strip()
    shopping_key = (settings.resolved_g2b_shopping_service_key or "").strip()
    if not catalog_key or not shopping_key:
        raise RuntimeError("G2B catalog/shopping key is not configured")

    catalog_client = PublicDataPortalClient(
        catalog_key,
        timeout_seconds=settings.g2b_request_timeout_seconds,
        max_retries=settings.g2b_max_retries,
    )
    shopping_client = PublicDataPortalClient(
        shopping_key,
        timeout_seconds=settings.g2b_request_timeout_seconds,
        max_retries=settings.g2b_max_retries,
    )
    catalog_url = settings.g2b_catalog_base_url or G2B_CATALOG_BASE_URL
    shopping_url = settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL
    end = date.today()

    started = perf_counter()
    items = _fetch_dictionary(catalog_client, catalog_url)
    codes_by_segment: dict[str, list[str]] = defaultdict(list)
    for item in items:
        code = str(item.get("dtilPrdctClsfcNo") or "").strip()
        if len(code) == 10 and code.isdigit() and code[:2] in TARGET_SEGMENTS:
            codes_by_segment[code[:2]].append(code)

    rng = random.Random(SEED)
    sampled: dict[str, list[str]] = {}
    for segment in TARGET_SEGMENTS:
        codes = sorted(set(codes_by_segment[segment]))
        sampled[segment] = rng.sample(codes, min(SAMPLES_PER_SEGMENT, len(codes)))

    operation = G2BShoppingOperation.SPECIFIC_ITEM_PROCUREMENTS.value
    observations: dict[str, list[dict[str, Any]]] = defaultdict(list)
    request_seconds: list[float] = []
    failures: list[dict[str, str]] = []
    for segment in TARGET_SEGMENTS:
        for code in sampled[segment]:
            t0 = perf_counter()
            try:
                payload = shopping_client.get_json(
                    shopping_url,
                    operation,
                    **_track_b_params(code=code, end=end, rows=1),
                )
                page = unwrap_g2b_page(payload)
            except Exception as exc:  # diagnostic probe: record and continue
                failures.append({"segment": segment, "code": code, "error": type(exc).__name__})
                continue
            elapsed = perf_counter() - t0
            request_seconds.append(elapsed)
            count = int(page.total_count or 0)
            observations[segment].append(
                {
                    "code": code,
                    "total_count": count,
                    "estimated_pages": max(1, math.ceil(count / PAGE_SIZE)),
                }
            )

    segment_report: dict[str, dict[str, Any]] = {}
    estimated_rows = 0.0
    estimated_calls = 0.0
    nonzero_codes: list[str] = []
    for segment in TARGET_SEGMENTS:
        rows = observations[segment]
        counts = [int(row["total_count"]) for row in rows]
        pages = [int(row["estimated_pages"]) for row in rows]
        code_count = len(set(codes_by_segment[segment]))
        for row in rows:
            if int(row["total_count"]) > 0:
                nonzero_codes.append(str(row["code"]))
        mean_count = statistics.mean(counts) if counts else 0.0
        mean_pages = statistics.mean(pages) if pages else 0.0
        segment_est_rows = mean_count * code_count
        segment_est_calls = mean_pages * code_count
        estimated_rows += segment_est_rows
        estimated_calls += segment_est_calls
        segment_report[segment] = {
            "code_count": code_count,
            "sample_count": len(rows),
            "zero_result_count": sum(1 for value in counts if value == 0),
            "sample_mean_rows": round(mean_count, 2),
            "sample_median_rows": round(statistics.median(counts), 2) if counts else None,
            "sample_p90_rows": _percentile([float(value) for value in counts], 0.90),
            "sample_max_rows": max(counts) if counts else None,
            "sample_mean_pages": round(mean_pages, 3),
            "estimated_rows": round(segment_est_rows),
            "estimated_api_calls": round(segment_est_calls),
        }

    compressed_sizes: list[int] = []
    raw_sizes: list[int] = []
    for code in nonzero_codes[:SIZE_SAMPLE_CODES]:
        try:
            payload = shopping_client.get_json(
                shopping_url,
                operation,
                **_track_b_params(code=code, end=end, rows=SIZE_SAMPLE_ROWS),
            )
            page = unwrap_g2b_page(payload)
        except Exception:
            continue
        for item in page.items:
            canonical = canonical_json_bytes(item)
            raw_sizes.append(len(canonical))
            compressed_sizes.append(len(gzip.compress(canonical, compresslevel=6, mtime=0)))

    compressed_mean = statistics.mean(compressed_sizes) if compressed_sizes else None
    compressed_median = statistics.median(compressed_sizes) if compressed_sizes else None
    compressed_p90 = _percentile([float(value) for value in compressed_sizes], 0.90)
    storage_estimate = None
    if compressed_mean is not None:
        storage_estimate = {
            "estimated_body_gb_at_sample_mean": round(estimated_rows * compressed_mean / 1e9, 3),
            "estimated_body_gb_at_sample_median": round(
                estimated_rows * float(compressed_median) / 1e9, 3
            ),
            "estimated_body_gb_at_sample_p90": round(
                estimated_rows * float(compressed_p90) / 1e9, 3
            ),
        }

    report = {
        "status": "SUCCESS" if not failures else "PARTIAL_SUCCESS",
        "as_of": end.isoformat(),
        "target_segments": list(TARGET_SEGMENTS),
        "target_code_count": sum(len(set(codes_by_segment[s])) for s in TARGET_SEGMENTS),
        "sampled_code_count": sum(len(rows) for rows in observations.values()),
        "sample_failures": failures,
        "segment_report": segment_report,
        "estimated_track_b_rows_one_year": round(estimated_rows),
        "estimated_track_b_api_calls_one_year": round(estimated_calls),
        "estimated_days_at_1000_calls_per_day": round(estimated_calls / 1000, 2),
        "sample_request_seconds_median": (
            round(statistics.median(request_seconds), 3) if request_seconds else None
        ),
        "sample_request_seconds_mean": (
            round(statistics.mean(request_seconds), 3) if request_seconds else None
        ),
        "raw_record_size_sample": {
            "records": len(compressed_sizes),
            "canonical_bytes_mean": round(statistics.mean(raw_sizes), 1) if raw_sizes else None,
            "gzip_bytes_mean": round(compressed_mean, 1) if compressed_mean is not None else None,
            "gzip_bytes_median": round(float(compressed_median), 1)
            if compressed_median is not None
            else None,
            "gzip_bytes_p90": round(float(compressed_p90), 1)
            if compressed_p90 is not None
            else None,
        },
        "storage_estimate": storage_estimate,
        "warning": (
            "Stratified random sample estimate only. Track B volume is heavy-tailed; hot codes can "
            "move totals materially. Do not use this estimate as an exact backfill count."
        ),
        "elapsed_seconds": round(perf_counter() - started, 2),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
