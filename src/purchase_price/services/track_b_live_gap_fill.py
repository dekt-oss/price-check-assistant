"""Fill the gap between the collected Track B index and today with a small live G2B lookup.

The R2 serving index is the primary source of direct procurement prices. It is refreshed by the
rolling collector, so it lags behind today by days or weeks (`data_as_of`). For a single search
this module asks the live `getSpcifyPrdlstPrcureInfoList` operation only for:

* the window `data_as_of + 1 .. today` (capped), and
* the 10-digit detail codes under which the same model already appears in the index.

Live rows go through the exact same normalization, model filter and identity grading as indexed
rows, are labelled as not-yet-collected, and are merged with the indexed candidates by stable
delivery-line identity (a newer live change order supersedes the indexed row). Any failure
leaves the indexed result untouched.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from purchase_price.collectors.g2b_shopping import (
    G2B_SHOPPING_BASE_URL,
    G2BShoppingOperation,
    unwrap_g2b_page,
)
from purchase_price.models import TrackBDeliveryLine
from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_track_b_normalization import (
    normalize_track_b_page,
    project_latest_track_b_records,
)
from purchase_price.services.product_matching import equivalent_model_keys
from purchase_price.services.track_b_db_quote_comparison import (
    TrackBQuoteCandidate,
    TrackBQuoteComparison,
    _candidate_from_row,
    _line_from_record,
)

LIVE_OPERATION = G2BShoppingOperation.SPECIFIC_ITEM_PROCUREMENTS.value
LIVE_TRANSACTION_TYPE = "나라장터 납품요구 · 실시간 보강(수집 전)"
LIVE_PAGE_SIZE = 999
MAX_GAP_DAYS = 62
MAX_DETAIL_CODES = 3
DEFAULT_REQUEST_BUDGET = 6
_SOURCE_ID = re.compile(r"^delivery:(?P<delivery>.+)\|change:(?P<change>[^|]+)\|line:(?P<line>.+)$")


class _JsonClient(Protocol):
    def get_json(self, base_url: str, endpoint: str, **params: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class TrackBLiveGapFill:
    status: str  # success | success_0 | up_to_date | not_applicable | failure
    reason: str = ""
    begin_date: str | None = None
    end_date: str | None = None
    detail_codes: tuple[str, ...] = ()
    candidates: tuple[TrackBQuoteCandidate, ...] = ()
    rows_seen: int = 0
    request_count: int = 0
    truncated_window: bool = False
    error_type: str | None = None


def live_gap_window(
    data_as_of: str | None,
    today: date,
    *,
    max_days: int = MAX_GAP_DAYS,
) -> tuple[date, date, bool] | None:
    """(begin, end, truncated) for the uncollected days, or None when there is no gap."""

    if not data_as_of:
        return None
    try:
        covered_through = date.fromisoformat(str(data_as_of)[:10])
    except ValueError:
        return None
    begin = covered_through + timedelta(days=1)
    if begin > today:
        return None
    earliest = today - timedelta(days=max_days - 1)
    truncated = begin < earliest
    return (max(begin, earliest), today, truncated)


def indexed_detail_codes(
    session: Session,
    query: ProductQuery,
    *,
    limit: int = MAX_DETAIL_CODES,
) -> tuple[str, ...]:
    """Detail codes under which this exact model already appears in the serving index."""

    model_keys = tuple(key for key in equivalent_model_keys(query.model_name) if key)
    if not model_keys:
        return ()
    rows = session.execute(
        select(TrackBDeliveryLine.detail_code, func.count())
        .where(TrackBDeliveryLine.model_key.in_(model_keys))
        .where(TrackBDeliveryLine.identity_conflict.is_(False))
        .group_by(TrackBDeliveryLine.detail_code)
        .order_by(func.count().desc(), TrackBDeliveryLine.detail_code)
        .limit(limit)
    ).all()
    return tuple(str(code) for code, _count in rows if code and len(str(code)) == 10)


def _live_page_envelope(
    *,
    detail_code: str,
    begin: date,
    end: date,
    page_no: int,
    page_size: int,
    total_count: int | None,
    items: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    # Same `g2b-track-b-page-v1` envelope the collector stores, so the shared normalizer applies.
    return {
        "schema": "g2b-track-b-page-v1",
        "source": "data.go.kr/G2B ShoppingMallPrdctInfoService",
        "operation": LIVE_OPERATION,
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


def _live_params(*, detail_code: str, begin: date, end: date, page_no: int) -> dict[str, Any]:
    # Like the collector, omit fnlCntrctDlvrReqChgOrdYn so change-order history is preserved.
    return {
        "pageNo": page_no,
        "numOfRows": LIVE_PAGE_SIZE,
        "inqryDiv": "1",
        "inqryBgnDate": begin.strftime("%Y%m%d"),
        "inqryEndDate": end.strftime("%Y%m%d"),
        "inqryPrdctDiv": "2",
        "dtilPrdctClsfcNo": detail_code,
    }


def fetch_live_gap(
    query: ProductQuery,
    *,
    detail_codes: Sequence[str],
    window: tuple[date, date, bool],
    client: _JsonClient,
    quote_unit_price: Decimal | None = None,
    base_url: str = G2B_SHOPPING_BASE_URL,
    request_budget: int = DEFAULT_REQUEST_BUDGET,
) -> TrackBLiveGapFill:
    begin, end, truncated = window
    codes = tuple(dict.fromkeys(code for code in detail_codes if code))[:MAX_DETAIL_CODES]
    common = {
        "begin_date": begin.isoformat(),
        "end_date": end.isoformat(),
        "detail_codes": codes,
        "truncated_window": truncated,
    }
    if not codes:
        return TrackBLiveGapFill("not_applicable", "수집 이력에 이 모델의 세부품명번호가 없음", **common)

    records = []
    requests = 0
    rows_seen = 0
    try:
        for code in codes:
            page_no = 1
            while requests < request_budget:
                payload = client.get_json(
                    base_url,
                    LIVE_OPERATION,
                    **_live_params(detail_code=code, begin=begin, end=end, page_no=page_no),
                )
                requests += 1
                page = unwrap_g2b_page(payload)
                items = tuple(dict(item) for item in page.items)
                rows_seen += len(items)
                envelope = _live_page_envelope(
                    detail_code=code,
                    begin=begin,
                    end=end,
                    page_no=page_no,
                    page_size=LIVE_PAGE_SIZE,
                    total_count=page.total_count,
                    items=items,
                )
                normalized = normalize_track_b_page(
                    envelope,
                    raw_object_key=f"live:{code}:{begin.isoformat()}:{end.isoformat()}:{page_no}",
                )
                records.extend(normalized.records)
                if len(items) < LIVE_PAGE_SIZE:
                    break
                page_no += 1
    except Exception as exc:  # live data is optional; never break the indexed result
        return TrackBLiveGapFill(
            "failure",
            "실시간 조회 실패",
            rows_seen=rows_seen,
            request_count=requests,
            error_type=type(exc).__name__,
            **common,
        )

    model_keys = set(equivalent_model_keys(query.model_name))
    candidates: list[TrackBQuoteCandidate] = []
    for record in project_latest_track_b_records(records):
        try:
            line = _line_from_record(record)
        except Exception:
            continue
        # Same identity filter as the serving SQL before grading.
        if not line.model_key or line.model_key not in model_keys:
            continue
        candidate = _candidate_from_row(
            line,
            query,
            quote_unit_price=quote_unit_price,
            include_conditions=True,
            condition_columns_available=True,
        )
        if candidate is not None:
            candidates.append(dataclasses.replace(candidate, transaction_type=LIVE_TRANSACTION_TYPE))

    return TrackBLiveGapFill(
        "success" if candidates else "success_0",
        "",
        candidates=tuple(candidates),
        rows_seen=rows_seen,
        request_count=requests,
        **common,
    )


def _line_identity(source_record_id: str) -> tuple[tuple[str, str], int] | None:
    match = _SOURCE_ID.match(source_record_id or "")
    if not match:
        return None
    change = match.group("change")
    return (match.group("delivery"), match.group("line")), int(change) if change.isdigit() else -1


def merge_live_gap(
    indexed: TrackBQuoteComparison,
    live: TrackBLiveGapFill,
) -> TrackBQuoteComparison:
    """Indexed candidates plus live ones, deduped by delivery line; newest change order wins."""

    if live.status != "success" or not live.candidates:
        return indexed
    best: dict[Any, tuple[int, int, TrackBQuoteCandidate]] = {}
    order = 0
    for source_rank, pool in ((0, indexed.candidates), (1, live.candidates)):
        for candidate in pool:
            parsed = _line_identity(candidate.source_record_id)
            key = parsed[0] if parsed else ("raw", candidate.source_record_id)
            change = parsed[1] if parsed else -1
            current = best.get(key)
            # Prefer the higher change order; on a tie keep the indexed (collected) row.
            if current is None or change > current[0]:
                best[key] = (change, order if current is None else current[1], candidate)
            order += 1
    merged = tuple(
        candidate
        for _change, _order, candidate in sorted(best.values(), key=lambda item: item[1])
    )
    merged = tuple(
        sorted(merged, key=lambda candidate: candidate.transaction_date or "", reverse=True)
    )
    status = indexed.status
    if status == "success_0" and merged:
        status = "success"
    added = sum(1 for candidate in merged if candidate.transaction_type == LIVE_TRANSACTION_TYPE)
    return dataclasses.replace(
        indexed,
        status=status,
        candidates=merged,
        examined=indexed.examined + added,
    )
