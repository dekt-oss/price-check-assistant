from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from purchase_price.clients.data_go_kr import PublicDataClientError, PublicDataPortalClient
from purchase_price.domain import EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice, ProductQuery

G2B_SHOPPING_BASE_URL = "https://apis.data.go.kr/1230000/at/ShoppingMallPrdctInfoService"
SOURCE_NAME = "조달청_나라장터쇼핑몰 품목정보 서비스"


class G2BShoppingOperation(StrEnum):
    MAS_CONTRACT_PRODUCTS = "getMASCntrctPrdctInfoList"
    SHOPPING_MALL_PRODUCTS = "getShoppingMallPrdctInfoList"
    DELIVERY_REQUEST_DETAILS = "getDlvrReqDtlInfoList"
    SPECIFIC_ITEM_PROCUREMENTS = "getSpcifyPrdlstPrcureInfoList"


@dataclass(frozen=True)
class G2BShoppingPage:
    items: tuple[dict[str, Any], ...]
    total_count: int | None
    page_no: int | None
    num_of_rows: int | None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def unwrap_g2b_page(payload: Mapping[str, Any]) -> G2BShoppingPage:
    """Unwrap the common data.go.kr response envelope.

    This intentionally validates only the common envelope. Operation-specific field names
    are learned from captured live fixtures before being promoted into parser aliases.
    """

    response = payload.get("response", payload)
    if not isinstance(response, Mapping):
        raise PublicDataClientError("G2B response must be an object")

    header = response.get("header")
    if isinstance(header, Mapping):
        result_code = str(header.get("resultCode", "")).strip()
        result_msg = str(header.get("resultMsg", "")).strip()
        if result_code and result_code not in {"0", "00", "000"}:
            raise PublicDataClientError(
                f"G2B API error resultCode={result_code} resultMsg={result_msg or '-'}"
            )

    body = response.get("body", {})
    if not isinstance(body, Mapping):
        raise PublicDataClientError("G2B response body must be an object")

    raw_items = body.get("items", [])
    if isinstance(raw_items, Mapping) and "item" in raw_items:
        raw_items = raw_items["item"]
    if raw_items is None:
        raw_items = []
    if isinstance(raw_items, Mapping):
        raw_items = [raw_items]
    if not isinstance(raw_items, list):
        raise PublicDataClientError("G2B response items must be a list or item object")

    items: list[dict[str, Any]] = []
    for item in raw_items:
        if isinstance(item, Mapping):
            items.append(dict(item))

    return G2BShoppingPage(
        items=tuple(items),
        total_count=_int_or_none(body.get("totalCount")),
        page_no=_int_or_none(body.get("pageNo")),
        num_of_rows=_int_or_none(body.get("numOfRows")),
    )


# These aliases are based only on official G2B file-report field labels that are publicly
# documented. API-specific English/camelCase aliases are deliberately NOT guessed here.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "product_id": ("물품식별", "물품식별번호"),
    "product_name": ("물품식별명", "품명", "세부품명(명칭)", "세부품명"),
    "contract_number": ("계약번호", "단가계약번호"),
    "delivery_request_number": ("납품요구번호", "계약(납품요구)번호"),
    "contract_unit_price": ("계약단가",),
    "delivery_unit_price": ("납품단가",),
    "delivery_quantity": ("납품수량", "수량"),
    "delivery_amount": ("납품금액", "금액"),
    "unit": ("납품단위명", "단위"),
    "supplier": ("업체", "업체명"),
    "transaction_date": ("결재일자", "계약(납품요구)일자"),
    "contract_delivery_type": ("계약납품구분",),
}


def _first_value(record: Mapping[str, Any], logical_name: str) -> Any:
    for key in FIELD_ALIASES[logical_name]:
        value = record.get(key)
        if value not in (None, ""):
            return value
    return None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    cleaned = str(value).replace(",", "").replace("원", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _record_id(record: Mapping[str, Any]) -> str | None:
    for logical_name in ("delivery_request_number", "contract_number", "product_id"):
        value = _first_value(record, logical_name)
        if value not in (None, ""):
            return str(value)
    return None


def _evidence_amount(
    record: Mapping[str, Any], operation: G2BShoppingOperation
) -> tuple[Decimal, EvidenceType] | None:
    delivery_unit_price = _decimal_or_none(_first_value(record, "delivery_unit_price"))
    contract_unit_price = _decimal_or_none(_first_value(record, "contract_unit_price"))

    if operation == G2BShoppingOperation.DELIVERY_REQUEST_DETAILS and delivery_unit_price is not None:
        return delivery_unit_price, EvidenceType.DELIVERY_ORDER_UNIT_PRICE

    if operation in {
        G2BShoppingOperation.MAS_CONTRACT_PRODUCTS,
        G2BShoppingOperation.SHOPPING_MALL_PRODUCTS,
    } and contract_unit_price is not None:
        return contract_unit_price, EvidenceType.SHOPPING_CONTRACT_UNIT_PRICE

    if operation == G2BShoppingOperation.SPECIFIC_ITEM_PROCUREMENTS:
        delivery_or_contract = str(_first_value(record, "contract_delivery_type") or "")
        generic_unit_price = delivery_unit_price or contract_unit_price
        if generic_unit_price is not None:
            if "납품" in delivery_or_contract:
                return generic_unit_price, EvidenceType.DELIVERY_ORDER_UNIT_PRICE
            if "계약" in delivery_or_contract:
                return generic_unit_price, EvidenceType.CONTRACT_UNIT_PRICE

    return None


def parse_official_report_record(
    record: Mapping[str, Any],
    *,
    operation: G2BShoppingOperation,
) -> CollectedPrice | None:
    """Convert a record only when a documented unit-price field is present.

    Manufacturer/model identity is not inferred from supplier or product text. Until the
    matching engine runs, records stay MatchGrade.X and therefore cannot enter the direct
    reference-price range.
    """

    evidence = _evidence_amount(record, operation)
    if evidence is None:
        return None
    price, evidence_type = evidence

    product_name = _first_value(record, "product_name")
    if product_name in (None, ""):
        return None

    quantity = _decimal_or_none(_first_value(record, "delivery_quantity"))
    total_amount = _decimal_or_none(_first_value(record, "delivery_amount"))
    supplier = _first_value(record, "supplier")
    unit = _first_value(record, "unit")

    conditions_parts: list[str] = []
    if supplier not in (None, ""):
        conditions_parts.append(f"공급업체={supplier}")

    return CollectedPrice(
        manufacturer=None,
        product_name=str(product_name),
        model_name=None,
        specification=None,
        price=price,
        evidence_type=evidence_type,
        source_type=SourceType.PROCUREMENT,
        source_name=SOURCE_NAME,
        source_url=None,
        collected_at=date.today(),
        quantity=quantity,
        unit=str(unit) if unit not in (None, "") else None,
        total_amount=total_amount,
        source_record_id=_record_id(record),
        original_title=str(product_name),
        conditions="; ".join(conditions_parts) or None,
        match_grade=MatchGrade.X,
        match_note="F1 raw procurement evidence; product identity matching deferred to F3",
    )


class G2BShoppingCollector:
    name = SOURCE_NAME

    def __init__(
        self,
        service_key: str,
        *,
        base_url: str = G2B_SHOPPING_BASE_URL,
        client: PublicDataPortalClient | None = None,
    ) -> None:
        self.base_url = base_url
        self.client = client or PublicDataPortalClient(service_key)

    def fetch_page(
        self,
        operation: G2BShoppingOperation,
        **params: Any,
    ) -> tuple[G2BShoppingPage, dict[str, Any]]:
        payload = self.client.get_json(self.base_url, operation.value, **params)
        return unwrap_g2b_page(payload), payload

    def parse_payload(
        self,
        payload: Mapping[str, Any],
        *,
        operation: G2BShoppingOperation,
    ) -> list[CollectedPrice]:
        page = unwrap_g2b_page(payload)
        parsed: list[CollectedPrice] = []
        for item in page.items:
            price = parse_official_report_record(item, operation=operation)
            if price is not None:
                parsed.append(price)
        return parsed

    def search(self, query: ProductQuery) -> list[CollectedPrice]:
        raise RuntimeError(
            "Live G2B search parameter mapping is intentionally not guessed. "
            "Run purchase_price.scripts.g2b_shopping_probe after API approval, capture a live "
            "fixture, then wire verified query parameters into F1."
        )
