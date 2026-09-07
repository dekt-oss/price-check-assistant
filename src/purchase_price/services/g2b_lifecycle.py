from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataClientError, PublicDataPortalClient

G2B_LIFECYCLE_BASE_URL = "https://apis.data.go.kr/1230000/ao/CntrctProcssIntgOpenService"
G2B_LIFECYCLE_GOODS_OPERATION = "getCntrctProcssIntgOpenThng"


class G2BLifecycleInquiry(StrEnum):
    """Official `inqryDiv` values from PPS lifecycle reference v1.0."""

    BID_NOTICE = "1"
    PRESPEC = "2"
    ORDER_PLAN = "3"
    PROCUREMENT_REQUEST = "4"

    @property
    def parameter_name(self) -> str:
        return {
            G2BLifecycleInquiry.BID_NOTICE: "bidNtceNo",
            G2BLifecycleInquiry.PRESPEC: "bfSpecRgstNo",
            G2BLifecycleInquiry.ORDER_PLAN: "orderPlanNo",
            G2BLifecycleInquiry.PROCUREMENT_REQUEST: "prcrmntReqNo",
        }[self]


@dataclass(frozen=True)
class G2BLifecycleRecord:
    source_record_id: str
    order_plan_no: str = ""
    order_plan_unified_no: str = ""
    order_business_name: str = ""
    order_institution: str = ""
    procurement_method: str = ""
    contract_method: str = ""
    prespec_no: str = ""
    prespec_business_name: str = ""
    bid_notice_no: str = ""
    bid_notice_order: str = ""
    bid_notice_name: str = ""
    bid_institution: str = ""
    bid_method: str = ""
    bid_notice_datetime: str = ""
    procurement_request_no: str = ""
    award_info_list: str = ""
    contract_info_list: str = ""


@dataclass(frozen=True)
class G2BLifecycleResult:
    inquiry: G2BLifecycleInquiry
    identifier: str
    records: tuple[G2BLifecycleRecord, ...]
    request_count: int = 1


def _items_from_payload(payload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    response = payload.get("response", payload)
    if not isinstance(response, Mapping):
        raise PublicDataClientError("G2B lifecycle response must be an object")
    header = response.get("header")
    if isinstance(header, Mapping):
        code = str(header.get("resultCode") or "").strip()
        if code and code not in {"0", "00", "000"}:
            message = str(header.get("resultMsg") or "").strip()
            raise PublicDataClientError(
                f"G2B lifecycle API error resultCode={code} resultMsg={message or '-'}"
            )
    body = response.get("body", {})
    if not isinstance(body, Mapping):
        raise PublicDataClientError("G2B lifecycle response body must be an object")
    raw = body.get("items", [])
    if isinstance(raw, Mapping) and "item" in raw:
        raw = raw["item"]
    if raw is None:
        return ()
    if isinstance(raw, Mapping):
        raw = [raw]
    if not isinstance(raw, list):
        raise PublicDataClientError("G2B lifecycle response items must be a list or item object")
    return tuple(dict(item) for item in raw if isinstance(item, Mapping))


def _text(item: Mapping[str, Any], key: str) -> str:
    return str(item.get(key) or "").strip()


def _record_id(item: Mapping[str, Any]) -> str:
    parts = [
        f"bid:{_text(item, 'bidNtceNo')}:{_text(item, 'bidNtceOrd')}",
        f"prespec:{_text(item, 'bfSpecRgstNo')}",
        f"order:{_text(item, 'orderPlanNo')}",
        f"request:{_text(item, 'prcrmntReqNo')}",
    ]
    meaningful = [part for part in parts if not part.endswith(":") and not part.endswith("::")]
    return "|".join(meaningful) or "lifecycle:unknown"


def _parse_record(item: Mapping[str, Any]) -> G2BLifecycleRecord:
    return G2BLifecycleRecord(
        source_record_id=_record_id(item),
        order_plan_no=_text(item, "orderPlanNo"),
        order_plan_unified_no=_text(item, "orderPlanUntyNo"),
        order_business_name=_text(item, "orderBizNm"),
        order_institution=_text(item, "orderInsttNm"),
        procurement_method=_text(item, "prcrmntMethdNm"),
        contract_method=_text(item, "cntrctCnclsMthdNm"),
        prespec_no=_text(item, "bfSpecRgstNo"),
        prespec_business_name=_text(item, "bfSpecBizNm"),
        bid_notice_no=_text(item, "bidNtceNo"),
        bid_notice_order=_text(item, "bidNtceOrd"),
        bid_notice_name=_text(item, "bidNtceNm"),
        bid_institution=_text(item, "bidDminsttNm"),
        bid_method=_text(item, "bidMthdNm"),
        bid_notice_datetime=_text(item, "bidNtceDt"),
        procurement_request_no=_text(item, "prcrmntReqNo"),
        award_info_list=_text(item, "bidwinrInfoList"),
        contract_info_list=_text(item, "cntrctInfoList"),
    )


class G2BLifecycleClient:
    """Resolve PPS procurement lifecycle by an exact official identifier.

    This service is deliberately not a keyword search. Amounts embedded in award/contract lists are
    left as raw research context; this client never turns them into product unit prices.
    """

    def __init__(
        self,
        service_key: str,
        *,
        base_url: str = G2B_LIFECYCLE_BASE_URL,
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

    def fetch(
        self,
        *,
        inquiry: G2BLifecycleInquiry,
        identifier: str,
        bid_notice_order: str | None = None,
        page_no: int = 1,
        num_of_rows: int = 20,
    ) -> G2BLifecycleResult:
        identifier = identifier.strip()
        if not identifier:
            raise ValueError("identifier is required")
        if page_no < 1 or num_of_rows < 1:
            raise ValueError("page_no and num_of_rows must be positive")

        params: dict[str, Any] = {
            "pageNo": page_no,
            "numOfRows": num_of_rows,
            "inqryDiv": inquiry.value,
            inquiry.parameter_name: identifier,
        }
        if inquiry == G2BLifecycleInquiry.BID_NOTICE and bid_notice_order:
            params["bidNtceOrd"] = bid_notice_order.strip()

        payload = self.client.get_json(
            self.base_url,
            G2B_LIFECYCLE_GOODS_OPERATION,
            **params,
        )
        records = tuple(_parse_record(item) for item in _items_from_payload(payload))
        return G2BLifecycleResult(inquiry=inquiry, identifier=identifier, records=records)
