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
from purchase_price.services.g2b_target_code_snapshot import (
    TargetCodeSnapshotError,
    build_target_code_snapshot,
    load_target_code_snapshot,
    target_codes_from_dictionary,
    write_target_code_snapshot,
)
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
    target_code_source: str
    target_code_snapshot_sha256: str | None
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
    pagination_reconciliations: int = 0
    pagination_contractions: int = 0
    pagination_inconsistencies: int = 0
    last_pagination_event: str | None = None


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


def _resolve_target_codes(
    *,
    catalog_client: JsonClient,
    catalog_base_url: str,
    segments: tuple[str, ...],
    page_size: int,
    snapshot_path: Path | None,
    refresh_snapshot: bool,
) -> tuple[list[str], int, str, str | None]:
    if refresh_snapshot and snapshot_path is None:
        raise ValueError("refresh_target_code_snapshot requires target_code_snapshot_path")

    if snapshot_path is not None and not refresh_snapshot:
        if not snapshot_path.exists():
            raise TargetCodeSnapshotError(
                f"target-code snapshot does not exist: {snapshot_path}; use refresh_target_code_snapshot explicitly"
            )
        snapshot = load_target_code_snapshot(snapshot_path, expected_segments=segments)
        return list(snapshot.codes), 0, "SNAPSHOT", snapshot.sha256

    dictionary_items, dictionary_requests = _fetch_dictionary(
        catalog_client,
        base_url=catalog_base_url,
        page_size=page_size,
    )
    codes = target_codes_from_dictionary(dictionary_items, segments)
    snapshot_sha256: str | None = None
    if snapshot_path is not None:
        snapshot = build_target_code_snapshot(
            dictionary_items=dictionary_items,
            segments=segments,
            dictionary_requests=dictionary_requests,
        )
        write_target_code_snapshot(snapshot_path, snapshot)
        snapshot_sha256 = snapshot.sha256
    return codes, dictionary_requests, "LIVE_DICTIONARY", snapshot_sha256


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


def _is_rate_limit_error(exc: Exception) -> bool:
    message = str(exc).upper()
    return any(
        marker in message
        for marker in (
            "HTTP 429",
            "STATUS=429",
            "CODE=22",
            "RESULTCODE=22",
            "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR",
        )
    )


def _validated_total_pages(
    page: Any,
    *,
    requested_page_no: int,
    page_size: int,
    detail_code: str,
) -> int:
    if page.page_no is not None and page.page_no != requested_page_no:
        raise RuntimeError(
            "G2B response page mismatch: "
            f"requested={requested_page_no} returned={page.page_no} for {detail_code}"
        )
    if page.total_count is None:
        raise RuntimeError(
            f"G2B response missing totalCount for {detail_code} page {requested_page_no}"
        )
    total_count = int(page.total_count)
    if total_count < 0:
        raise RuntimeError(
            f"G2B response has negative totalCount={total_count} for {detail_code} "
            f"page {requested_page_no}"
        )
    return max(1, math.ceil(total_count / page_size))


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
    target_code_snapshot_path: Path | None = None,
    refresh_target_code_snapshot: bool = False,
    explicit_target_codes: tuple[str, ...] | None = None,
) -> CollectionSummary:
    if request_budget < 1 or request_budget > MAX_REQUEST_BUDGET:
        raise ValueError(f"request_budget must be between 1 and {MAX_REQUEST_BUDGET}")
    if begin > end:
        raise ValueError("begin must not be after end")
    if start_cursor.code_index < 0 or start_cursor.page_no < 1:
        raise ValueError("invalid start cursor")

    started = datetime.now(UTC)
    if explicit_target_codes is not None:
        if target_code_snapshot_path is not None or refresh_target_code_snapshot:
            raise ValueError(
                "explicit_target_codes cannot be combined with target-code snapshot options"
            )
        codes = list(explicit_target_codes)
        if not codes:
            raise ValueError("explicit_target_codes must not be empty")
        if len(codes) != len(set(codes)):
            raise ValueError("explicit_target_codes contains duplicates")
        allowed_segments = set(segments)
        for code in codes:
            if len(code) != 10 or not code.isdigit():
                raise ValueError(f"invalid explicit 10-digit target code: {code!r}")
            if code[:2] not in allowed_segments:
                raise ValueError(
                    f"explicit target code {code} is outside configured segments {segments!r}"
                )
        dictionary_requests = 0
        target_code_source = "EXPLICIT_CODES"
        snapshot_sha256 = None
    else:
        codes, dictionary_requests, target_code_source, snapshot_sha256 = _resolve_target_codes(
            catalog_client=catalog_client,
            catalog_base_url=catalog_base_url,
            segments=segments,
            page_size=page_size,
            snapshot_path=target_code_snapshot_path,
            refresh_snapshot=refresh_target_code_snapshot,
        )
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
    pagination_reconciliations = 0
    pagination_contractions = 0
    pagination_inconsistencies = 0
    last_pagination_event: str | None = None
    planned_code_index: int | None = None
    planned_total_pages: int | None = None
    reconciled_code_index: int | None = None

    try:
        while cursor.code_index < len(codes):
            code = codes[cursor.code_index]
            page_no = cursor.page_no
            if planned_code_index != cursor.code_index:
                planned_code_index = cursor.code_index
                planned_total_pages = None
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
            # Count an attempted remote request before awaiting the response: failed requests
            # still consume public-data quota and therefore belong in the bounded budget.
            remaining -= 1
            track_b_requests += 1
            payload = shopping_client.get_json(shopping_base_url, TRACK_B_OPERATION, **params)
            page = unwrap_g2b_page(payload)
            reported_total_pages = _validated_total_pages(
                page,
                requested_page_no=page_no,
                page_size=page_size,
                detail_code=code,
            )

            needs_reconciliation = page_no > reported_total_pages or (
                planned_total_pages is not None
                and reported_total_pages != planned_total_pages
            )
            if needs_reconciliation:
                if reconciled_code_index == cursor.code_index:
                    raise RuntimeError(
                        "G2B pagination changed again after page-1 reconciliation: "
                        f"code={code} page={page_no} reported={reported_total_pages} "
                        f"planned={planned_total_pages}"
                    )
                if remaining <= 0:
                    stop_reason = "REQUEST_BUDGET_EXHAUSTED"
                    status = "PARTIAL_SUCCESS"
                    break

                previous_horizon = planned_total_pages
                pagination_reconciliations += 1
                reconciled_code_index = cursor.code_index
                remaining -= 1
                track_b_requests += 1
                probe_params = _track_b_params(
                    detail_code=code,
                    begin=begin,
                    end=end,
                    page_no=1,
                    page_size=page_size,
                )
                probe_payload = shopping_client.get_json(
                    shopping_base_url,
                    TRACK_B_OPERATION,
                    **probe_params,
                )
                probe_page = unwrap_g2b_page(probe_payload)
                reconciled_total_pages = _validated_total_pages(
                    probe_page,
                    requested_page_no=1,
                    page_size=page_size,
                    detail_code=code,
                )

                # Persist the authoritative page-1 re-probe as public evidence. Content-addressed
                # storage makes an unchanged replay a reuse, while a changed page is retained
                # without deleting any older historical evidence.
                probe_raw_payload = _page_payload(
                    detail_code=code,
                    begin=begin,
                    end=end,
                    page_no=1,
                    page_size=page_size,
                    total_count=probe_page.total_count,
                    items=probe_page.items,
                )
                probe_ref = store.put_public_json(
                    source_operation=f"{TRACK_B_OPERATION}-page",
                    payload=probe_raw_payload,
                )
                pages_stored += 1
                rows_seen += len(probe_page.items)
                first_key = first_key or probe_ref.key
                last_key = probe_ref.key
                if probe_ref.created:
                    created += 1
                    created_bytes += probe_ref.stored_bytes
                else:
                    reused += 1

                if page_no > reconciled_total_pages:
                    pagination_contractions += 1
                    last_pagination_event = (
                        "PAGINATION_CONTRACTED "
                        f"code={code} page={page_no} reported={reported_total_pages} "
                        f"reconciled={reconciled_total_pages} prior={previous_horizon}"
                    )
                    if reconciled_total_pages == 1:
                        codes_completed += 1
                        cursor = CollectionCursor(code_index=cursor.code_index + 1, page_no=1)
                        planned_code_index = None
                        planned_total_pages = None
                        reconciled_code_index = None
                    else:
                        # Page membership may have shifted when totalCount contracted. Page 1 was
                        # just re-probed and persisted, so replay the remaining current pages from
                        # page 2 rather than skipping the code or trusting stale page boundaries.
                        planned_total_pages = reconciled_total_pages
                        cursor = CollectionCursor(code_index=cursor.code_index, page_no=2)
                    continue

                pagination_inconsistencies += 1
                last_pagination_event = (
                    "PAGINATION_RECONCILED "
                    f"code={code} page={page_no} reported={reported_total_pages} "
                    f"reconciled={reconciled_total_pages} prior={previous_horizon}"
                )
                planned_total_pages = reconciled_total_pages
                if page_no > 1 and not page.items:
                    raise RuntimeError(
                        "G2B pagination inconsistency: empty page inside reconciled horizon "
                        f"for {code} page {page_no}/{reconciled_total_pages}"
                    )
            elif planned_total_pages is None:
                planned_total_pages = reported_total_pages

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

            total_pages = planned_total_pages or reported_total_pages
            if page_no >= total_pages:
                codes_completed += 1
                cursor = CollectionCursor(code_index=cursor.code_index + 1, page_no=1)
                planned_code_index = None
                planned_total_pages = None
                reconciled_code_index = None
            else:
                cursor = CollectionCursor(code_index=cursor.code_index, page_no=page_no + 1)
    except Exception as exc:
        # A remote/storage failure is never a successful batch merely because earlier pages
        # were persisted. Keep the resumable cursor, but return a non-zero process status.
        status = "FAILED"
        stop_reason = "RATE_LIMIT_EXHAUSTED" if _is_rate_limit_error(exc) else "SOURCE_OR_STORAGE_ERROR"
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
        target_code_source=target_code_source,
        target_code_snapshot_sha256=snapshot_sha256,
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
        pagination_reconciliations=pagination_reconciliations,
        pagination_contractions=pagination_contractions,
        pagination_inconsistencies=pagination_inconsistencies,
        last_pagination_event=last_pagination_event,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect bounded Track B pages into Cloudflare R2")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--request-budget", type=int, default=300)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument(
        "--target-code-snapshot",
        type=Path,
        default=None,
        help="Validated Unit10 target-code snapshot; when present, normal batches spend zero dictionary requests",
    )
    parser.add_argument(
        "--refresh-target-code-snapshot",
        action="store_true",
        help="Explicitly refresh --target-code-snapshot from the live Unit10 dictionary before collecting",
    )
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
        target_code_snapshot_path=args.target_code_snapshot,
        refresh_target_code_snapshot=args.refresh_target_code_snapshot,
    )
    rendered = json.dumps(asdict(summary), ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if summary.status in {"SUCCESS", "PARTIAL_SUCCESS"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
