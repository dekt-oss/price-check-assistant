from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.collectors.g2b_shopping import G2BShoppingPage, unwrap_g2b_page
from purchase_price.services.g2b_market_models import (
    G2BResearchRecord,
    G2BResearchSource,
    ResearchAmountType,
    ResearchAttachment,
)

G2B_BID_BASE_URL = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
G2B_BID_THING_SEARCH_OPERATION = "getBidPblancListInfoThngPPSSrch"
G2B_BID_THING_ITEM_OPERATION = "getBidPblancListInfoThngPurchsObjPrdct"

G2B_AWARD_BASE_URL = "https://apis.data.go.kr/1230000/as/ScsbidInfoService"
G2B_AWARD_THING_SEARCH_OPERATION = "getScsbidListSttusThngPPSSrch"

G2B_PRESPEC_BASE_URL = "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService"
G2B_PRESPEC_THING_SEARCH_OPERATION = "getPublicPrcureThngInfoThngPPSSrch"

# PPS PPSSrch endpoints are documented/observed with short date-window limits. Use 30 calendar
# days at most per request instead of relying on a long-range call that can fail with code=07/10.
G2B_RESEARCH_MAX_WINDOW_DAYS = 30


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _first(record: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = record.get(name)
        if value not in (None, ""):
            return value
    return None


def _decimal(value: Any) -> Decimal | None:
    text = _text(value)
    if text is None:
        return None
    cleaned = text.replace(",", "").replace("원", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _date(value: Any) -> date | None:
    text = _text(value)
    if text is None:
        return None
    normalized = text.replace("-", "").replace("/", "").replace(":", "").replace(" ", "")
    for size, fmt in ((8, "%Y%m%d"), (12, "%Y%m%d%H%M"), (14, "%Y%m%d%H%M%S")):
        if len(normalized) >= size:
            try:
                return datetime.strptime(normalized[:size], fmt).date()
            except ValueError:
                pass
    return None


def _windows(begin: date, end: date) -> tuple[tuple[date, date], ...]:
    if begin > end:
        raise ValueError("begin must not be after end")
    windows: list[tuple[date, date]] = []
    cursor = begin
    while cursor <= end:
        window_end = min(end, cursor + timedelta(days=G2B_RESEARCH_MAX_WINDOW_DAYS - 1))
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return tuple(windows)


def _bid_record_id(record: Mapping[str, Any]) -> str:
    notice = _text(record.get("bidNtceNo")) or "unknown"
    order = _text(record.get("bidNtceOrd")) or ""
    return f"bid:{notice}:{order}"


def _award_record_id(record: Mapping[str, Any]) -> str:
    notice = _text(record.get("bidNtceNo")) or "unknown"
    order = _text(record.get("bidNtceOrd")) or ""
    classification = _text(record.get("bidClsfcNo")) or ""
    rebid = _text(record.get("rbidNo")) or ""
    return f"award:{notice}:{order}:{classification}:{rebid}"


def _prespec_record_id(record: Mapping[str, Any]) -> str:
    return f"prespec:{_text(record.get('bfSpecRgstNo')) or 'unknown'}"


def _bid_attachments(record: Mapping[str, Any]) -> tuple[ResearchAttachment, ...]:
    attachments: list[ResearchAttachment] = []
    seen: set[str] = set()
    for index in range(1, 11):
        url = _text(record.get(f"ntceSpecDocUrl{index}"))
        if not url or url in seen:
            continue
        seen.add(url)
        attachments.append(
            ResearchAttachment(name=_text(record.get(f"ntceSpecFileNm{index}")), url=url)
        )
    for index in range(1, 6):
        url = _text(record.get(f"sptDscrptDocUrl{index}"))
        if not url or url in seen:
            continue
        seen.add(url)
        attachments.append(ResearchAttachment(name=None, url=url))
    return tuple(attachments)


def parse_bid_notice(record: Mapping[str, Any], *, search_term: str) -> G2BResearchRecord:
    """Parse a broad bid notice as research context, never as a transacted unit price."""

    amount = _decimal(record.get("presmptPrce"))
    return G2BResearchRecord(
        source_type=G2BResearchSource.BID_NOTICE,
        source_record_id=_bid_record_id(record),
        title=_text(record.get("bidNtceNm")),
        institution=_text(_first(record, "dminsttNm", "ntceInsttNm")),
        published_date=_date(_first(record, "bidNtceDt", "rgstDt")),
        bid_notice_no=_text(record.get("bidNtceNo")),
        bid_notice_order=_text(record.get("bidNtceOrd")),
        amount=amount,
        amount_type=(
            ResearchAmountType.ESTIMATED_PRICE if amount is not None else ResearchAmountType.UNKNOWN
        ),
        source_url=_text(record.get("bidNtceDtlUrl")),
        attachments=_bid_attachments(record),
        search_term=search_term,
    )


def parse_award(record: Mapping[str, Any], *, search_term: str) -> G2BResearchRecord:
    """Parse an award result; `sucsfbidAmt` is a total unless item-level evidence proves otherwise."""

    amount = _decimal(record.get("sucsfbidAmt"))
    return G2BResearchRecord(
        source_type=G2BResearchSource.AWARD,
        source_record_id=_award_record_id(record),
        title=_text(record.get("bidNtceNm")),
        institution=_text(_first(record, "dminsttNm", "ntceInsttNm")),
        published_date=_date(_first(record, "fnlSucsfDate", "rlOpengDt")),
        bid_notice_no=_text(record.get("bidNtceNo")),
        bid_notice_order=_text(record.get("bidNtceOrd")),
        amount=amount,
        amount_type=(ResearchAmountType.AWARD_TOTAL if amount is not None else ResearchAmountType.UNKNOWN),
        supplier=_text(_first(record, "bidwinnrNm", "sucsfbidCorpNm")),
        search_term=search_term,
    )


def parse_prespec(record: Mapping[str, Any], *, search_term: str) -> G2BResearchRecord:
    """Parse pre-specification research; allocated budget is context, not a market unit price."""

    amount = _decimal(record.get("asignBdgtAmt"))
    title = _text(_first(record, "bfSpecNm", "prdctClsfcNoNm", "prdctDtlList"))
    return G2BResearchRecord(
        source_type=G2BResearchSource.PRESPEC,
        source_record_id=_prespec_record_id(record),
        title=title,
        institution=_text(_first(record, "rlDminsttNm", "orderInsttNm")),
        published_date=_date(_first(record, "rgstDt", "rcptDt")),
        bid_notice_no=_text(record.get("bidNtceNoList")),
        prespec_no=_text(record.get("bfSpecRgstNo")),
        product_name=_text(record.get("prdctClsfcNoNm")),
        amount=amount,
        amount_type=(ResearchAmountType.BUDGET_AMOUNT if amount is not None else ResearchAmountType.UNKNOWN),
        search_term=search_term,
    )


class _BaseMarketSourceClient:
    def __init__(
        self,
        service_key: str,
        *,
        base_url: str,
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
        client: PublicDataPortalClient | None = None,
    ) -> None:
        self.base_url = base_url
        self.client = client or PublicDataPortalClient(
            service_key,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )

    def _page(self, operation: str, **params: Any) -> G2BShoppingPage:
        return unwrap_g2b_page(self.client.get_json(self.base_url, operation, **params))


class G2BBidResearchClient(_BaseMarketSourceClient):
    def __init__(
        self,
        service_key: str,
        *,
        base_url: str = G2B_BID_BASE_URL,
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
        client: PublicDataPortalClient | None = None,
    ) -> None:
        super().__init__(
            service_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            client=client,
        )

    def fetch_page(
        self,
        *,
        keyword: str,
        begin: date,
        end: date,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> G2BShoppingPage:
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("keyword is required")
        return self._page(
            G2B_BID_THING_SEARCH_OPERATION,
            inqryDiv="1",
            inqryBgnDt=f"{begin:%Y%m%d}0000",
            inqryEndDt=f"{end:%Y%m%d}2359",
            bidNtceNm=keyword,
            pageNo=page_no,
            numOfRows=num_of_rows,
        )

    def search(
        self,
        *,
        keyword: str,
        begin: date,
        end: date,
        max_pages_per_window: int = 2,
        num_of_rows: int = 100,
    ) -> tuple[tuple[G2BResearchRecord, ...], int]:
        return _search_pages(
            windows=_windows(begin, end),
            fetch=lambda w_begin, w_end, page_no: self.fetch_page(
                keyword=keyword,
                begin=w_begin,
                end=w_end,
                page_no=page_no,
                num_of_rows=num_of_rows,
            ),
            parse=lambda raw: parse_bid_notice(raw, search_term=keyword),
            max_pages_per_window=max_pages_per_window,
            num_of_rows=num_of_rows,
        )


class G2BAwardResearchClient(_BaseMarketSourceClient):
    def __init__(
        self,
        service_key: str,
        *,
        base_url: str = G2B_AWARD_BASE_URL,
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
        client: PublicDataPortalClient | None = None,
    ) -> None:
        super().__init__(
            service_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            client=client,
        )

    def fetch_page(
        self,
        *,
        keyword: str,
        begin: date,
        end: date,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> G2BShoppingPage:
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("keyword is required")
        return self._page(
            G2B_AWARD_THING_SEARCH_OPERATION,
            inqryDiv="1",
            inqryBgnDt=f"{begin:%Y%m%d}0000",
            inqryEndDt=f"{end:%Y%m%d}2359",
            bidNtceNm=keyword,
            pageNo=page_no,
            numOfRows=num_of_rows,
        )

    def search(
        self,
        *,
        keyword: str,
        begin: date,
        end: date,
        max_pages_per_window: int = 2,
        num_of_rows: int = 100,
    ) -> tuple[tuple[G2BResearchRecord, ...], int]:
        return _search_pages(
            windows=_windows(begin, end),
            fetch=lambda w_begin, w_end, page_no: self.fetch_page(
                keyword=keyword,
                begin=w_begin,
                end=w_end,
                page_no=page_no,
                num_of_rows=num_of_rows,
            ),
            parse=lambda raw: parse_award(raw, search_term=keyword),
            max_pages_per_window=max_pages_per_window,
            num_of_rows=num_of_rows,
        )


class G2BPrespecResearchClient(_BaseMarketSourceClient):
    def __init__(
        self,
        service_key: str,
        *,
        base_url: str = G2B_PRESPEC_BASE_URL,
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
        client: PublicDataPortalClient | None = None,
    ) -> None:
        super().__init__(
            service_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            client=client,
        )

    def fetch_page(
        self,
        *,
        keyword: str,
        begin: date,
        end: date,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> G2BShoppingPage:
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("keyword is required")
        # `bfSpecNm` is the pre-specification-name search term on the PPSSrch operation. This
        # contract is kept behind this adapter so a live probe can change it without affecting
        # callers if PPS revises the parameter surface.
        return self._page(
            G2B_PRESPEC_THING_SEARCH_OPERATION,
            inqryDiv="1",
            inqryBgnDt=f"{begin:%Y%m%d}0000",
            inqryEndDt=f"{end:%Y%m%d}2359",
            bfSpecNm=keyword,
            pageNo=page_no,
            numOfRows=num_of_rows,
        )

    def search(
        self,
        *,
        keyword: str,
        begin: date,
        end: date,
        max_pages_per_window: int = 2,
        num_of_rows: int = 100,
    ) -> tuple[tuple[G2BResearchRecord, ...], int]:
        return _search_pages(
            windows=_windows(begin, end),
            fetch=lambda w_begin, w_end, page_no: self.fetch_page(
                keyword=keyword,
                begin=w_begin,
                end=w_end,
                page_no=page_no,
                num_of_rows=num_of_rows,
            ),
            parse=lambda raw: parse_prespec(raw, search_term=keyword),
            max_pages_per_window=max_pages_per_window,
            num_of_rows=num_of_rows,
        )


def _search_pages(
    *,
    windows: tuple[tuple[date, date], ...],
    fetch: Any,
    parse: Any,
    max_pages_per_window: int,
    num_of_rows: int,
) -> tuple[tuple[G2BResearchRecord, ...], int]:
    if max_pages_per_window < 1 or num_of_rows < 1:
        raise ValueError("page bounds must be positive")

    records: list[G2BResearchRecord] = []
    seen: set[str] = set()
    request_count = 0
    for window_begin, window_end in windows:
        fetched = 0
        for page_no in range(1, max_pages_per_window + 1):
            request_count += 1
            page = fetch(window_begin, window_end, page_no)
            if not page.items:
                break
            fetched += len(page.items)
            for raw in page.items:
                record = parse(raw)
                if record.source_record_id in seen:
                    continue
                seen.add(record.source_record_id)
                records.append(record)
            if page.total_count is not None and fetched >= page.total_count:
                break
            if len(page.items) < num_of_rows:
                break
    return tuple(records), request_count
