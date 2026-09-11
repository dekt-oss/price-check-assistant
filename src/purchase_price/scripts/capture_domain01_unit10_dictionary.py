from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.collectors.g2b_shopping import unwrap_g2b_page
from purchase_price.config import get_settings
from purchase_price.services.g2b_catalog import G2B_CATALOG_BASE_URL

UNIT10_OPERATION = "getPrdctClsfcNoUnit10Info02"
PAGE_SIZE = 999
DOMAIN_PRIMARY_SEGMENTS = ("41", "42")
SAFE_FIELDS = (
    "dtilPrdctClsfcNo",
    "dtilPrdctClsfcNoNm",
    "useYn",
    "chgDate",
    "prdctClsfcNo",
    "prdctClsfcNoNm",
    "prdctClsfcNoEngNm",
    "dtilPrdctClsfcNoEngNm",
    "description",
)


def _safe_item(item: dict[str, Any]) -> dict[str, Any]:
    return {key: item.get(key) for key in SAFE_FIELDS if key in item}


def capture_dictionary() -> tuple[dict[str, Any], list[dict[str, Any]]]:
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

    page_count = max(1, math.ceil(first.total_count / PAGE_SIZE))
    items = list(first.items)
    for page_no in range(2, page_count + 1):
        payload = client.get_json(
            settings.g2b_catalog_base_url or G2B_CATALOG_BASE_URL,
            UNIT10_OPERATION,
            pageNo=page_no,
            numOfRows=PAGE_SIZE,
        )
        page = unwrap_g2b_page(payload)
        items.extend(page.items)

    rows: list[dict[str, Any]] = []
    segment_counts: Counter[str] = Counter()
    active_segment_counts: Counter[str] = Counter()
    invalid_code_count = 0
    for raw in items:
        code = str(raw.get("dtilPrdctClsfcNo") or "").strip()
        if len(code) != 10 or not code.isdigit():
            invalid_code_count += 1
            continue
        row = _safe_item(raw)
        row["dtilPrdctClsfcNo"] = code
        segment = code[:2]
        row["segment"] = segment
        rows.append(row)
        segment_counts[segment] += 1
        if str(raw.get("useYn") or "").strip().upper() == "Y":
            active_segment_counts[segment] += 1

    rows.sort(key=lambda row: str(row["dtilPrdctClsfcNo"]))
    summary = {
        "status": "SUCCESS",
        "operation": UNIT10_OPERATION,
        "total_count": first.total_count,
        "captured_valid_codes": len(rows),
        "invalid_code_count": invalid_code_count,
        "page_size": PAGE_SIZE,
        "request_count": page_count,
        "elapsed_seconds": round(perf_counter() - started, 2),
        "domain": "MEDICAL_DIAGNOSTICS",
        "primary_segments": list(DOMAIN_PRIMARY_SEGMENTS),
        "primary_segment_counts": {
            segment: {
                "all": segment_counts[segment],
                "active": active_segment_counts[segment],
            }
            for segment in DOMAIN_PRIMARY_SEGMENTS
        },
        "note": (
            "This capture is an official Unit10 dictionary snapshot only. "
            "No row is collect-enabled by this probe. Domain review is required."
        ),
    }
    return summary, rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="artifacts/domain01-unit10/unit10_dictionary.json",
    )
    parser.add_argument(
        "--summary-output",
        default="artifacts/domain01-unit10/summary.json",
    )
    args = parser.parse_args()

    summary, rows = capture_dictionary()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "summary": summary,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    summary_output = Path(args.summary_output)
    summary_output.parent.mkdir(parents=True, exist_ok=True)
    summary_output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
