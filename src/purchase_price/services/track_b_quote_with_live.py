"""One Track B lookup that also checks the days after the collected index, for any screen.

The price search page has always merged a small live G2B lookup (``track_b_live_gap_fill``) into
the indexed trades, so a model searched there showed e.g. 97 trades while the quote review page,
which used the index only, showed 93 for the same model. Both screens now count the same trades.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.collectors.g2b_shopping import G2B_SHOPPING_BASE_URL
from purchase_price.config import get_settings
from purchase_price.schemas import ProductQuery
from purchase_price.services.track_b_db_quote_comparison import (
    TrackBQuoteComparison,
    lookup_track_b_quote,
)
from purchase_price.services.track_b_live_gap_fill import (
    TrackBLiveGapFill,
    fetch_live_gap,
    indexed_detail_codes,
    live_gap_window,
    merge_live_gap,
)
from purchase_price.services.track_b_serving_snapshot import open_track_b_serving_snapshot

LIVE_TIMEOUT_SECONDS = 8.0

LiveFetcher = Callable[..., TrackBLiveGapFill]


def _today() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def run_live_gap_fill(
    query: ProductQuery,
    *,
    detail_codes: tuple[str, ...],
    data_as_of: str | None,
    quote_unit_price: Decimal | None,
    today: date | None = None,
) -> TrackBLiveGapFill:
    """Live G2B lookup for the days after the collected index; never raises."""

    window = live_gap_window(data_as_of, today or _today())
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
        with PublicDataPortalClient(
            service_key, timeout_seconds=LIVE_TIMEOUT_SECONDS, max_retries=0
        ) as client:
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


def lookup_track_b_quote_with_live(
    query: ProductQuery,
    *,
    quote_unit_price: Decimal | None,
    live_fetcher: LiveFetcher = run_live_gap_fill,
) -> tuple[TrackBQuoteComparison, TrackBLiveGapFill]:
    """Indexed trades plus the live days after ``data_as_of``, the same as the price search page.

    When the serving index is unavailable this falls back to ``lookup_track_b_quote`` (which may
    use the development SQL DB) and skips the live step.
    """

    data_as_of: str | None = None
    detail_codes: tuple[str, ...] = ()
    with open_track_b_serving_snapshot() as snapshot:
        indexed = snapshot.lookup(query, quote_unit_price=quote_unit_price)
        data_as_of = getattr(snapshot, "data_as_of", None)
        session = getattr(snapshot, "session", None)
        if session is not None and (query.model_name or "").strip():
            try:
                detail_codes = indexed_detail_codes(session, query)
            except Exception:
                detail_codes = ()
    if indexed.status in {"unavailable", "not_ingested"}:
        return lookup_track_b_quote(query, quote_unit_price=quote_unit_price), TrackBLiveGapFill(
            "not_applicable", "거래가격 인덱스 없음"
        )
    live = live_fetcher(
        query,
        detail_codes=detail_codes,
        data_as_of=data_as_of,
        quote_unit_price=quote_unit_price,
    )
    return merge_live_gap(indexed, live), live
