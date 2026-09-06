from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataPortalClient
from purchase_price.collectors.g2b_shopping import G2BShoppingPage, unwrap_g2b_page
from purchase_price.services.g2b_market_models import (
    G2BResearchRecord,
    G2BResearchSource,
    ResearchAmountType,
)
from purchase_price.services.g2b_market_sources import (
    G2B_BID_BASE_URL,
    G2B_BID_THING_ITEM_OPERATION,
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


def _record_id(record: Mapping[str, Any]) -> str:
    notice = _text(record.get("bidNtceNo")) or "unknown"
    order = _text(record.get("bidNtceOrd")) or ""
    sequence = _text(
        _first(
            record,
            "bidNtceDtlSeq",
            "purchsObjPrdctSeq",
            "prdctSeq",
            "seq",
            "prdctClsfcNo",
        )
    ) or ""
    product = _text(
        _first(record, "prdctClsfcNo", "prdctClsfcNoNm", "prdctNm", "purchsObjPrdctNm")
    ) or ""
    return f"bid-item:{notice}:{order}:{sequence}:{product}"


def parse_bid_purchase_item(record: Mapping[str, Any]) -> G2BResearchRecord:
    """Parse one official bid purchase-object item as research-only item detail.

    PPS purchase-object data describes what the bid plans to buy. Even when a response exposes a
    unit-price-looking field, it is an estimate/planning value rather than a transacted market unit
    price. The parser therefore uses ESTIMATED_UNIT_PRICE and never UNIT_PRICE.
    """

    amount = _decimal(
        _first(
            record,
            "presmptUnitPrce",
            "estmUnitPrc",
            "prdctUnitPrc",
            "unitPrce",
            "unitPrc",
        )
    )
    product_name = _text(
        _first(
            record,
            "prdctClsfcNoNm",
            "purchsObjPrdctNm",
            "prdctNm",
            "prdctDtlList",
        )
    )
    model_name = _text(_first(record, "modelNm", "mdlNm", "modelName"))
    manufacturer = _text(_first(record, "mnfcturNm", "makrNm", "manufacturer"))
    quantity = _decimal(_first(record, "prdctQty", "purchsObjPrdctQty", "qty"))
    unit = _text(_first(record, "prdctUnit", "unitNm", "unit"))

    return G2BResearchRecord(
        source_type=G2BResearchSource.BID_ITEM,
        source_record_id=_record_id(record),
        title=product_name,
        bid_notice_no=_text(record.get("bidNtceNo")),
        bid_notice_order=_text(record.get("bidNtceOrd")),
        product_name=product_name,
        manufacturer=manufacturer,
        model_name=model_name,
        quantity=quantity,
        unit=unit,
        amount=amount,
        amount_type=(
            ResearchAmountType.ESTIMATED_UNIT_PRICE
            if amount is not None
            else ResearchAmountType.UNKNOWN
        ),
    )


class G2BBidItemClient:
    """Fetch official purchase-object rows for an already identified goods bid notice."""

    def __init__(
        self,
        service_key: str,
        *,
        base_url: str = G2B_BID_BASE_URL,
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
        bid_notice_order: str | None = None,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> G2BShoppingPage:
        notice = bid_notice_no.strip()
        if not notice:
            raise ValueError("bid_notice_no is required")
        if page_no < 1 or num_of_rows < 1:
            raise ValueError("page bounds must be positive")

        params: dict[str, Any] = {
            "inqryDiv": "2",
            "bidNtceNo": notice,
            "pageNo": page_no,
            "numOfRows": num_of_rows,
        }
        order = (bid_notice_order or "").strip()
        if order:
            params["bidNtceOrd"] = order
        return unwrap_g2b_page(
            self.client.get_json(self.base_url, G2B_BID_THING_ITEM_OPERATION, **params)
        )

    def fetch_items(
        self,
        *,
        bid_notice_no: str,
        bid_notice_order: str | None = None,
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
                bid_notice_order=bid_notice_order,
                page_no=page_no,
                num_of_rows=num_of_rows,
            )
            if not page.items:
                break
            fetched += len(page.items)
            for raw in page.items:
                item = parse_bid_purchase_item(raw)
                if item.source_record_id in seen:
                    continue
                seen.add(item.source_record_id)
                records.append(item)
            if page.total_count is not None and fetched >= page.total_count:
                break
            if len(page.items) < num_of_rows:
                break
        return tuple(records), request_count
