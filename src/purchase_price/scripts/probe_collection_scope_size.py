from __future__ import annotations

import json
import math
from collections import Counter
from time import perf_counter

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.collectors.g2b_shopping import unwrap_g2b_page
from purchase_price.config import get_settings
from purchase_price.services.g2b_catalog import G2B_CATALOG_BASE_URL

UNIT10_OPERATION = "getPrdctClsfcNoUnit10Info02"
PAGE_SIZE = 999
TARGET_SEGMENTS = ("23", "27", "39", "41", "42", "43", "44", "46")


def main() -> int:
    settings = get_settings()
    key = (settings.resolved_g2b_catalog_service_key or "").strip()
    if not key:
        raise RuntimeError("G2B catalog/data.go.kr key is not configured")

    client = PublicDataPortalClient(
        key,
        timeout_seconds=settings.g2b_request_timeout_seconds,
        max_retries=settings.g2b_max_retries,
    )
    started = perf_counter()
    first_payload = client.get_json(
        settings.g2b_catalog_base_url or G2B_CATALOG_BASE_URL,
        UNIT10_OPERATION,
        pageNo=1,
        numOfRows=PAGE_SIZE,
    )
    first = unwrap_g2b_page(first_payload)
    if first.total_count is None:
        raise RuntimeError("Unit10 dictionary response did not expose totalCount")

    pages = max(1, math.ceil(first.total_count / PAGE_SIZE))
    items = list(first.items)
    for page_no in range(2, pages + 1):
        payload = client.get_json(
            settings.g2b_catalog_base_url or G2B_CATALOG_BASE_URL,
            UNIT10_OPERATION,
            pageNo=page_no,
            numOfRows=PAGE_SIZE,
        )
        page = unwrap_g2b_page(payload)
        items.extend(page.items)

    segment_all: Counter[str] = Counter()
    segment_active: Counter[str] = Counter()
    active_total = 0
    valid_codes = 0
    for item in items:
        code = str(item.get("dtilPrdctClsfcNo") or "").strip()
        if len(code) != 10 or not code.isdigit():
            continue
        valid_codes += 1
        segment = code[:2]
        segment_all[segment] += 1
        use_yn = str(item.get("useYn") or "").strip().upper()
        if use_yn == "Y":
            active_total += 1
            segment_active[segment] += 1

    target_all = sum(segment_all[segment] for segment in TARGET_SEGMENTS)
    target_active = sum(segment_active[segment] for segment in TARGET_SEGMENTS)
    report = {
        "status": "SUCCESS",
        "operation": UNIT10_OPERATION,
        "total_count": first.total_count,
        "collected_count": len(items),
        "valid_10_digit_codes": valid_codes,
        "active_codes": active_total,
        "page_size": PAGE_SIZE,
        "request_count": pages,
        "elapsed_seconds": round(perf_counter() - started, 2),
        "target_segments": list(TARGET_SEGMENTS),
        "target_codes_all": target_all,
        "target_codes_active": target_active,
        "target_share_of_active_pct": (
            round(target_active / active_total * 100, 2) if active_total else None
        ),
        "segment_counts": {
            segment: {
                "all": segment_all[segment],
                "active": segment_active[segment],
            }
            for segment in TARGET_SEGMENTS
        },
        "track_b_minimum_one_year_calls_if_one_page_each": target_active,
        "development_limit_days_minimum_at_1000_calls_per_day": round(target_active / 1000, 2),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
