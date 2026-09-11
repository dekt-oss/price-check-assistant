from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.collectors.g2b_shopping import (
    G2B_SHOPPING_BASE_URL,
    G2BShoppingOperation,
    unwrap_g2b_page,
)
from purchase_price.config import get_settings
from purchase_price.services.g2b_catalog import G2B_CATALOG_BASE_URL
from purchase_price.storage.r2 import R2RawEvidenceStore, RawObjectRef

UNIT10_OPERATION = "getPrdctClsfcNoUnit10Info02"
TRACK_B_OPERATION = G2BShoppingOperation.SPECIFIC_ITEM_PROCUREMENTS.value
PAGE_SIZE = 999
# Collection priority follows the hospital-use scope: medical -> lab -> IT -> office -> tools/safety/electrical.
TARGET_SEGMENTS = ("42", "41", "43", "44", "23", "27", "46", "39")
MAX_REQUEST_BUDGET = 900


class JsonClient(Protocol):
    def get_json(self, base_url: str, operation: str, **params: Any) -> dict[str, Any]: ...


class RawStore(Protocol):
    def put_public_json(self, *, source_operation: str, payload: object) -> RawObjectRef: ...


@dataclass(frozen=True)
class CollectionCursor:
    code_index: int
    page_no: int = 1


@dataclass(frozen=True)
class CollectionSummary:
    status: str
    started_at: str
    finished_at: str
    begin_date: str
    end_date: str
    target_segments: tuple[str, ...]
    target_code_count: int
    start_cursor: CollectionCursor
    next_cursor: CollectionCursor
    request_budget: int
    dictionary_requests: int
    track_b_requests: int
    total_requests: int
    codes_completed: int
    pages_stored: int
    rows_seen: int
    r2_objects_created: int
    r2_objects_reused: int
    r2_stored_bytes_created: int
    first_object_key: str | None
    last_object_key: str | None
    stop_reason: str
    error_type: str | None = None
    error_message: str | None = None


def _fetch_dictionary(
    client: JsonClient,
    *,
    base_url: str,
    page_size: int = PAGE_SIZE,
) -> tuple[list[dict[str, Any]], int]:
    first_payload = client.get_json(base_url, UNIT10_OPERATION, pageNo=1, numOfRows=page_size)
    first = unwrap_g2b_page(first_payload)
    if first.total_count is None:
        raise RuntimeError("Unit10 dictionary response did not expose totalCount")
    page_count = max(1, math.ceil(first.total_count / page_size))
    items = [dict(item) for item in first.items]
    for page_no in range(2, page_count + 1):
        payload = client.get_json(
            base_url,
            UNIT10_OPERATION,
            pageNo=page_no,
            numOfRows=page_size,
        )
        page = unwrap_g2b_page(payload)
        items.extend(dict(item) for item in page.items)
    return items, page_count


def _target_codes(items: list[dict[str, Any]], segments: tuple[str, ...]) -> list[str]:
    by_segment: dict[str, set[str]] = {segment: set() for segment in segments}
    for item in items:
        code = str(item.get("dtilPrdctClsfcNo") or "").strip()
        use_yn = str(item.get("useYn") or "").strip().upper()
        if len(code) != 10 or not code.isdigit() or use_yn != "Y":
            continue
        segment = code[:2]
        if segment in by_segment:
            by_segment[segment].add(code)
    return [code for segment in segments for code in sorted(by_segment[segment])]


def _track_b_params(
    *,
    detail_code: str,
    begin: date,
    end: date,
    page_no: int,
    page_size: int = PAGE_SIZE,
) -> dict[str, Any]:
    # Deliberately omit fnlCntrctDlvrReqChgOrdYn. Gate-0 proved that omitting the filter
    # preserves earlier change orders; final-only would destroy supersession history.
    return {
        "pageNo": page_no,
        "numOfRows": page_size,
        "inqryDiv": "1",
        "inqryBgnDate": begin.strftime("%Y%m%d"),
        "inqryEndDate": end.strftime("%Y%m%d"),
        "inqryPrdctDiv": "2",
        "dtilPrdctClsfcNo": detail_code,
    }


def _page_payload(
    *,
    detail_code: str,
    begin: date,
    end: date,
    page_no: int,
    page_size: int,
    total_count: int | None,
    items: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    # Keep the hashed object deterministic. fetched_at belongs in the run summary rather than
    # the raw payload, otherwise an identical refetch would create a new content-addressed object.
    return {
        "schema": "g2b-track-b-page-v1",
        "source": "data.go.kr/G2B ShoppingMallPrdctInfoService",
        "operation": TRACK_B_OPERATION,
        "request": {
            "detail_code": detail_code,
            "begin_date": begin.isoformat(),
            "end_date": end.isoformat(),
            "page_no": page_no,
            "page_size": page_size,
            "inquiry_div": "1",
            "product_div": "2",
            "final_change_order_filter": "OMITTED",
        },
        "response": {
            "total_count": total_count,
            "page_no": page_no,
            "num_of_rows": page_size,
            "items": [dict(item) for item in items],
        },
    }


def collect_track_b_batch(
    *,
    catalog_client: JsonClient,
    shopping_client: JsonClient,
    store: RawStore,
    catalog_base_url: str,
    shopping_base_url: str,
    begin: date,
    end: date,
    start_cursor: CollectionCursor,
    request_budget: int,
    segments: tuple[str, ...] = TARGET_SEGMENTS,
    page_size: int = PAGE_SIZE,
) -> CollectionSummary:
    if request_budget < 1 or request_budget > MAX_REQUEST_BUDGET:
        raise ValueError(f"request_budget must be between 1 and {MAX_REQUEST_BUDGET}")
    if begin > end:
        raise ValueError("begin must not be after end")
    if start_cursor.code_index < 0 or start_cursor.page_no < 1:
        raise ValueError("invalid start cursor")

    started = datetime.now(UTC)
    dictionary_items, dictionary_requests = _fetch_dictionary(
        catalog_client,
        base_url=catalog_base_url,
        page_size=page_size,
    )
    codes = _target_codes(dictionary_items, segments)
    if start_cursor.code_index > len(codes):
        raise ValueError("start cursor is past the target code list")
    if dictionary_requests >= request_budget:
        raise ValueError(
            "request_budget must leave at least one request after dictionary enumeration"
        )

    remaining = request_budget - dictionary_requests
    track_b_requests = 0
    codes_completed = 0
    pages_stored = 0
    rows_seen = 0
    created = 0
    reused = 0
    created_bytes = 0
    first_key: str | None = None
    last_key: str | None = None
    cursor = start_cursor
    stop_reason = "TARGET_COMPLETE"
    status = "SUCCESS"
    error_type: str | None = None
    error_message: str | None = None

    try:
        while cursor.code_index < len(codes):
            code = codes[cursor.code_index]
            page_no = cursor.page_no
            if remaining <= 0:
                stop_reason = "REQUEST_BUDGET_EXHAUSTED"
                status = "PARTIAL_SUCCESS"
                break

            params = _track_b_params(
                detail_code=code,
                begin=begin,
                end=end,
                page_no=page_no,
                page_size=page_size,
            )
            payload = shopping_client.get_json(shopping_base_url, TRACK_B_OPERATION, **params)
            remaining -= 1
            track_b_requests += 1
            page = unwrap_g2b_page(payload)
            total_count = int(page.total_count or 0)
            total_pages = max(1, math.ceil(total_count / page_size))
            if page_no > total_pages:
                raise RuntimeError(
                    f"cursor page {page_no} exceeds total pages {total_pages} for {code}"
                )

            raw_payload = _page_payload(
                detail_code=code,
                begin=begin,
                end=end,
                page_no=page_no,
                page_size=page_size,
                total_count=page.total_count,
                items=page.items,
            )
            ref = store.put_public_json(
                source_operation=f"{TRACK_B_OPERATION}-page",
                payload=raw_payload,
            )
            pages_stored += 1
            rows_seen += len(page.items)
            first_key = first_key or ref.key
            last_key = ref.key
            if ref.created:
                created += 1
                created_bytes += ref.stored_bytes
            else:
                reused += 1

            if page_no >= total_pages:
                codes_completed += 1
                cursor = CollectionCursor(code_index=cursor.code_index + 1, page_no=1)
            else:
                cursor = CollectionCursor(code_index=cursor.code_index, page_no=page_no + 1)
    except Exception as exc:
        status = "PARTIAL_SUCCESS" if pages_stored else "FAILED"
        stop_reason = "SOURCE_OR_STORAGE_ERROR"
        error_type = type(exc).__name__
        error_message = str(exc)[:500]

    finished = datetime.now(UTC)
    return CollectionSummary(
        status=status,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        begin_date=begin.isoformat(),
        end_date=end.isoformat(),
        target_segments=segments,
        target_code_count=len(codes),
        start_cursor=start_cursor,
        next_cursor=cursor,
        request_budget=request_budget,
        dictionary_requests=dictionary_requests,
        track_b_requests=track_b_requests,
        total_requests=dictionary_requests + track_b_requests,
        codes_completed=codes_completed,
        pages_stored=pages_stored,
        rows_seen=rows_seen,
        r2_objects_created=created,
        r2_objects_reused=reused,
        r2_stored_bytes_created=created_bytes,
        first_object_key=first_key,
        last_object_key=last_key,
        stop_reason=stop_reason,
        error_type=error_type,
        error_message=error_message,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect bounded Track B pages into Cloudflare R2")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--request-budget", type=int, default=300)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.days < 1:
        raise ValueError("days must be positive")

    settings = get_settings()
    catalog_key = (settings.resolved_g2b_catalog_service_key or "").strip()
    shopping_key = (settings.resolved_g2b_shopping_service_key or "").strip()
    if not catalog_key or not shopping_key:
        raise RuntimeError("G2B catalog/shopping service keys are not configured")
    if not settings.r2_configured:
        raise RuntimeError("R2 writer configuration is incomplete")

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
    store = R2RawEvidenceStore.from_settings(settings)
    end = args.end_date
    begin = end - timedelta(days=args.days - 1)
    summary = collect_track_b_batch(
        catalog_client=catalog_client,
        shopping_client=shopping_client,
        store=store,
        catalog_base_url=settings.g2b_catalog_base_url or G2B_CATALOG_BASE_URL,
        shopping_base_url=settings.g2b_shopping_base_url or G2B_SHOPPING_BASE_URL,
        begin=begin,
        end=end,
        start_cursor=CollectionCursor(args.start_index, args.start_page),
        request_budget=args.request_budget,
    )
    rendered = json.dumps(asdict(summary), ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if summary.status in {"SUCCESS", "PARTIAL_SUCCESS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
