from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.collectors.g2b_shopping import G2BShoppingPage, unwrap_g2b_page
from purchase_price.services.g2b_contract_evidence import (
    G2B_CONTRACT_BASE_URL,
    G2B_CONTRACT_PRODUCT_SEARCH_OPERATION,
)
from purchase_price.services.g2b_market_models import (
    G2BResearchRecord,
    G2BResearchSource,
    ResearchAmountType,
)


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
    if not text:
        return None
    normalized = text.replace("-", "").replace("/", "").replace(" ", "")
    for size, fmt in ((8, "%Y%m%d"), (12, "%Y%m%d%H%M"), (14, "%Y%m%d%H%M%S")):
        if len(normalized) >= size:
            try:
                return datetime.strptime(normalized[:size], fmt).date()
            except ValueError:
                pass
    return None


def _notice_no(record: Mapping[str, Any]) -> str | None:
    """Return the official contract notice link, accepting the legacy alias for old fixtures."""

    return _text(_first(record, "ntceNo", "bidNtceNo"))


def _item_sequence(record: Mapping[str, Any]) -> str | None:
    return _text(_first(record, "cntrctDtlSeq", "prdctSeq", "seq"))


def _record_id(record: Mapping[str, Any]) -> str:
    contract_no = _text(record.get("dcsnCntrctNo")) or "unknown"
    notice = _notice_no(record) or ""
    sequence = _item_sequence(record) or ""
    product_id = _text(record.get("prdctIdntNo")) or ""
    return f"contract:{contract_no}:{notice}:{sequence}:{product_id}"


def parse_contract_research(
    record: Mapping[str, Any],
    *,
    search_term: str | None = None,
) -> G2BResearchRecord:
    """Parse one goods-contract record as linked procurement research.

    Contract monetary fields are kept as CONTRACT_TOTAL. They are never divided by bid quantity or
    promoted to UNIT_PRICE here because contract composition, changes, options and line-level scope
    can differ from the bid's purchase-object rows. Raw identity/specification fields are retained
    only as later fingerprinting material.
    """

    raw_amount = _first(
        record,
        "totCntrctAmt",
        "cntrctAmt",
        "dcsnCntrctAmt",
        "thtmCntrctAmt",
    )
    amount = _decimal(raw_amount)
    return G2BResearchRecord(
        source_type=G2BResearchSource.CONTRACT,
        source_record_id=_record_id(record),
        title=_text(_first(record, "cntrctNm", "prdctClsfcNoNm", "prdctNm")),
        institution=_text(_first(record, "cntrctInsttNm", "dminsttNm")),
        published_date=_date(_first(record, "cntrctCnclsDate", "rgstDt")),
        bid_notice_no=_notice_no(record),
        bid_notice_order=_text(record.get("bidNtceOrd")),
        contract_no=_text(record.get("dcsnCntrctNo")),
        product_name=_text(_first(record, "prdctClsfcNoNm", "prdctNm")),
        manufacturer=_text(_first(record, "mnfcturNm", "makrNm", "manufacturer")),
        model_name=_text(_first(record, "modelNm", "mdlNm", "modelName")),
        product_id=_text(record.get("prdctIdntNo")),
        detail_product_code=_text(record.get("dtilPrdctClsfcNo")),
        item_sequence=_item_sequence(record),
        original_specification=_text(
            _first(
                record,
                "prdctSpcfctn",
                "spcfctn",
                "krnPrdctNm",
                "prdctDtlList",
            )
        ),
        quantity=_decimal(_first(record, "prdctQty", "cntrctQty", "qty")),
        unit=_text(_first(record, "prdctUnit", "unitNm", "unit")),
        amount=amount,
        amount_type=(
            ResearchAmountType.CONTRACT_TOTAL if amount is not None else ResearchAmountType.UNKNOWN
        ),
        original_amount_text=_text(raw_amount),
        supplier=_text(
            _first(
                record,
                "cntrctCorpNm",
                "cntrctEntrpsNm",
                "corpNm",
                "bidwinnrNm",
            )
        ),
        delivery_condition=_text(
            _first(record, "dlvryCndtnNm", "dlvrCndtnNm", "dlvryCndtn", "dlvrCndtn")
        ),
        record_change_order=_text(
            _first(record, "cntrctChgOrd", "cntrctDtlChgOrd", "prdctChgOrd")
        ),
        source_url=_text(_first(record, "cntrctDtlInfoUrl", "cntrctInfoUrl")),
        search_term=search_term,
    )


def _date_windows(
    begin: date,
    end: date,
    *,
    max_window_days: int | None = None,
) -> tuple[tuple[date, date], ...]:
    """Split only when the caller has an explicit source-specific window limit.

    The current PPS contract PPSSrch documentation exposes begin/end dates but does not establish
    the 31-day restriction used by some other procurement APIs. Defaulting to one interval avoids
    multiplying requests for 1/3/5-year adaptive research. A bounded window can still be supplied
    explicitly if live evidence later proves such a source constraint.
    """

    if begin > end:
        raise ValueError("begin must not be after end")
    if max_window_days is None:
        return ((begin, end),)
    if max_window_days < 1:
        raise ValueError("max_window_days must be positive")

    windows: list[tuple[date, date]] = []
    cursor = begin
    while cursor <= end:
        window_end = min(end, cursor + timedelta(days=max_window_days - 1))
        windows.append((cursor, window_end))
        cursor = window_end + timedelta(days=1)
    return tuple(windows)


class G2BContractResearchClient:
    """Fetch goods contracts by bid notice or an independent PPS product-name search."""

    def __init__(
        self,
        service_key: str,
        *,
        base_url: str = G2B_CONTRACT_BASE_URL,
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

    def fetch_page(
        self,
        *,
        bid_notice_no: str,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> G2BShoppingPage:
        notice = bid_notice_no.strip()
        if not notice:
            raise ValueError("bid_notice_no is required")
        if page_no < 1 or num_of_rows < 1:
            raise ValueError("page bounds must be positive")
        payload = self.client.get_json(
            self.base_url,
            G2B_CONTRACT_PRODUCT_SEARCH_OPERATION,
            inqryDiv="4",
            ntceNo=notice,
            pageNo=page_no,
            numOfRows=num_of_rows,
        )
        return unwrap_g2b_page(payload)

    def fetch_product_search_page(
        self,
        *,
        product_name: str,
        begin_date: date,
        end_date: date,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> G2BShoppingPage:
        """Use the official PPS-search contract fields for an independent goods lookup."""

        keyword = " ".join(product_name.split()).strip()
        if not keyword:
            raise ValueError("product_name is required")
        if begin_date > end_date:
            raise ValueError("begin_date must not be after end_date")
        if page_no < 1 or num_of_rows < 1:
            raise ValueError("page bounds must be positive")

        payload = self.client.get_json(
            self.base_url,
            G2B_CONTRACT_PRODUCT_SEARCH_OPERATION,
            inqryDiv="1",
            inqryBgnDate=begin_date.strftime("%Y%m%d"),
            inqryEndDate=end_date.strftime("%Y%m%d"),
            prdctClsfcNoNm=keyword,
            pageNo=page_no,
            numOfRows=num_of_rows,
        )
        return unwrap_g2b_page(payload)

    def search_by_bid_notice(
        self,
        *,
        bid_notice_no: str,
        max_pages: int = 2,
        num_of_rows: int = 100,
    ) -> tuple[tuple[G2BResearchRecord, ...], int]:
        if max_pages < 1 or num_of_rows < 1:
            raise ValueError("page bounds must be positive")

        records: list[G2BResearchRecord] = []
        seen: set[str] = set()
        request_count = 0
        fetched = 0
        for page_no in range(1, max_pages + 1):
            request_count += 1
            page = self.fetch_page(
                bid_notice_no=bid_notice_no,
                page_no=page_no,
                num_of_rows=num_of_rows,
            )
            if not page.items:
                break
            fetched += len(page.items)
            for raw in page.items:
                record = parse_contract_research(raw)
                if record.source_record_id in seen:
                    continue
                seen.add(record.source_record_id)
                records.append(record)
            if page.total_count is not None and fetched >= page.total_count:
                break
            if len(page.items) < num_of_rows:
                break
        return tuple(records), request_count

    def search_by_product_name(
        self,
        *,
        product_name: str,
        begin_date: date,
        end_date: date,
        max_pages_per_window: int = 1,
        num_of_rows: int = 100,
        max_window_days: int | None = None,
    ) -> tuple[tuple[G2BResearchRecord, ...], int]:
        """Search contracts without requiring an upstream bid notice seed."""

        if max_pages_per_window < 1 or num_of_rows < 1:
            raise ValueError("page bounds must be positive")

        records: list[G2BResearchRecord] = []
        seen: set[str] = set()
        request_count = 0
        for window_begin, window_end in _date_windows(
            begin_date,
            end_date,
            max_window_days=max_window_days,
        ):
            fetched = 0
            for page_no in range(1, max_pages_per_window + 1):
                request_count += 1
                page = self.fetch_product_search_page(
                    product_name=product_name,
                    begin_date=window_begin,
                    end_date=window_end,
                    page_no=page_no,
                    num_of_rows=num_of_rows,
                )
                if not page.items:
                    break
                fetched += len(page.items)
                for raw in page.items:
                    record = parse_contract_research(raw, search_term=product_name)
                    if record.source_record_id in seen:
                        continue
                    seen.add(record.source_record_id)
                    records.append(record)
                if page.total_count is not None and fetched >= page.total_count:
                    break
                if len(page.items) < num_of_rows:
                    break
        return tuple(records), request_count
