from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
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


def _record_id(record: Mapping[str, Any]) -> str:
    contract_no = _text(record.get("dcsnCntrctNo")) or "unknown"
    notice = _text(record.get("bidNtceNo")) or ""
    sequence = _text(_first(record, "cntrctDtlSeq", "prdctSeq", "seq")) or ""
    return f"contract:{contract_no}:{notice}:{sequence}"


def parse_contract_research(record: Mapping[str, Any]) -> G2BResearchRecord:
    """Parse one goods-contract record as linked procurement research.

    Contract monetary fields are kept as CONTRACT_TOTAL. They are never divided by bid quantity or
    promoted to UNIT_PRICE here because contract composition, changes, options and line-level scope
    can differ from the bid's purchase-object rows.
    """

    amount = _decimal(
        _first(
            record,
            "totCntrctAmt",
            "cntrctAmt",
            "dcsnCntrctAmt",
            "thtmCntrctAmt",
        )
    )
    return G2BResearchRecord(
        source_type=G2BResearchSource.CONTRACT,
        source_record_id=_record_id(record),
        title=_text(_first(record, "cntrctNm", "prdctClsfcNoNm", "prdctNm")),
        institution=_text(_first(record, "cntrctInsttNm", "dminsttNm")),
        published_date=_date(_first(record, "cntrctCnclsDate", "rgstDt")),
        bid_notice_no=_text(record.get("bidNtceNo")),
        bid_notice_order=_text(record.get("bidNtceOrd")),
        contract_no=_text(record.get("dcsnCntrctNo")),
        product_name=_text(_first(record, "prdctClsfcNoNm", "prdctNm")),
        quantity=_decimal(_first(record, "prdctQty", "cntrctQty", "qty")),
        unit=_text(_first(record, "prdctUnit", "unitNm", "unit")),
        amount=amount,
        amount_type=(
            ResearchAmountType.CONTRACT_TOTAL if amount is not None else ResearchAmountType.UNKNOWN
        ),
        supplier=_text(
            _first(
                record,
                "cntrctCorpNm",
                "cntrctEntrpsNm",
                "corpNm",
                "bidwinnrNm",
            )
        ),
        source_url=_text(record.get("cntrctDtlInfoUrl")),
    )


class G2BContractResearchClient:
    """Fetch goods contracts by an explicit G2B bid notice number."""

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
            bidNtceNo=notice,
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
