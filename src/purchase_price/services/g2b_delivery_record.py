"""Show one 나라장터 delivery line exactly as the public API published it.

Buyers want to check an odd price (for example one M40 line at 36,513,000원 among 4,400,000원
lines) against the source. 나라장터 screens have no per-record URL to link to, and many lines are
an institution's own 총액계약 that the shopping mall does not list. The collector, however, kept
every raw API page in R2 under its SHA-256, so the exact public record can be shown on request.

New module so a Streamlit hot reload that keeps older modules never sees a half-updated import.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

G2B_SHOPPING_DATASET_URL = "https://www.data.go.kr/data/15129471/openapi.do"
G2B_SHOPPING_DATASET_NAME = "조달청_나라장터쇼핑몰 품목정보 서비스"
# Runtime marker: bump when the field list changes so a retained copy reloads.
FIELD_ORDER_V1 = True

_SOURCE_ID = re.compile(r"^delivery:(?P<number>[^|]+)\|change:(?P<change>[^|]*)\|line:(?P<line>.+)$")
_RAW_HASH = re.compile(r"(?P<hash>[0-9a-f]{64})\.json\.gz$")

# (API field, plain label, kind). Order is the order a buyer reads the record in.
_FIELDS: tuple[tuple[str, str, str], ...] = (
    # What explains an odd price comes first: the project, then price, quantity and unit,
    # then how it was bought.
    ("cntrctDlvrReqNm", "사업명", "text"),
    ("prdctUprc", "단가", "money"),
    ("prdctQty", "수량", "number"),
    ("prdctUnit", "단위", "text"),
    ("prdctAmt", "금액", "money"),
    ("cntrctDivNm", "계약 구분", "text"),
    ("cntrctMthdNm", "계약 방법", "text"),
    ("prcrmntDivNm", "조달 구분", "text"),
    ("dlvryCndtnNm", "납품 조건", "text"),
    ("dlvrPlceNm", "납품 장소", "text"),
    ("dlvrTmlmtDate", "납품 기한", "date"),
    ("dminsttNm", "구매 기관", "text"),
    ("dminsttRgnNm", "기관 소재지", "text"),
    ("dmndInsttDivNm", "기관 구분", "text"),
    ("corpNm", "납품업체", "text"),
    ("prdctIdntNoNm", "물품", "text"),
    ("prdctIdntNo", "물품식별번호", "text"),
    ("dtilPrdctClsfcNoNm", "세부품명", "text"),
    ("dtilPrdctClsfcNo", "세부품명번호", "text"),
    ("cntrctDlvrReqNo", "납품요구번호", "text"),
    ("cntrctDlvrReqChgOrd", "변경 차수", "text"),
    ("cntrctDlvrReqDate", "납품요구일", "date"),
    ("exclcProdctYn", "우수제품", "yn"),
    ("masYn", "다수공급자계약(MAS)", "yn"),
)


@dataclass(frozen=True)
class DeliveryRecordRef:
    delivery_number: str
    change_order: str
    line: str
    raw_object_key: str

    @property
    def payload_hash(self) -> str | None:
        match = _RAW_HASH.search(self.raw_object_key or "")
        return match.group("hash") if match else None

    @property
    def label(self) -> str:
        text = f"{self.delivery_number} · {self.line}번 물품"
        if self.change_order and self.change_order.strip("0"):
            text += f" · 변경 {self.change_order}"
        return text


@dataclass(frozen=True)
class DeliveryRecordLookup:
    status: str  # found | not_archived | not_found | failure
    fields: tuple[tuple[str, str], ...] = ()
    error_type: str = ""


def parse_record_ref(source_record_id: object, raw_object_key: object) -> DeliveryRecordRef | None:
    match = _SOURCE_ID.match(str(source_record_id or "").strip())
    if match is None:
        return None
    return DeliveryRecordRef(
        delivery_number=match.group("number").strip(),
        change_order=match.group("change").strip(),
        line=match.group("line").strip(),
        raw_object_key=str(raw_object_key or "").strip(),
    )


def _iter_dicts(payload: object) -> Iterable[Mapping[str, Any]]:
    if isinstance(payload, Mapping):
        yield payload
        for value in payload.values():
            yield from _iter_dicts(value)
    elif isinstance(payload, list):
        for value in payload:
            yield from _iter_dicts(value)


def find_line(payload: object, ref: DeliveryRecordRef) -> Mapping[str, Any] | None:
    for item in _iter_dicts(payload):
        if str(item.get("cntrctDlvrReqNo") or "").strip() != ref.delivery_number:
            continue
        if str(item.get("prdctSno") or "").strip() != ref.line:
            continue
        change = str(item.get("cntrctDlvrReqChgOrd") or "").strip()
        if ref.change_order and change and change != ref.change_order:
            continue
        return item
    return None


def _format(value: object, kind: str) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        return ""
    if kind in {"money", "number"}:
        try:
            number = Decimal(text.replace(",", ""))
        except InvalidOperation:
            return text
        formatted = f"{number:,.0f}" if number == number.to_integral_value() else f"{number:,}"
        return f"{formatted}원" if kind == "money" else formatted
    if kind == "date" and len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    if kind == "yn":
        return {"Y": "예", "N": "아니요"}.get(text.upper(), text)
    return text


def record_fields(item: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    rows = [(label, _format(item.get(key), kind)) for key, label, kind in _FIELDS]
    return tuple((label, value) for label, value in rows if value)


def load_delivery_record(
    ref: DeliveryRecordRef,
    *,
    read_payload: Callable[[str, str], object] | None = None,
) -> DeliveryRecordLookup:
    """Read the archived API page from R2 and return the matching line; never raises.

    ``read_payload(key, payload_hash)`` is injectable for tests; by default it reads R2 with the
    hash check of R2RawEvidenceStore.get_public_json.
    """

    payload_hash = ref.payload_hash
    if not payload_hash:
        # Lines from the live gap-fill are shown before the collector archives them.
        return DeliveryRecordLookup("not_archived")
    try:
        reader = read_payload or _read_from_r2
        item = find_line(reader(ref.raw_object_key, payload_hash), ref)
    except Exception as exc:  # noqa: BLE001 - shown as a failure state, never breaks the page
        return DeliveryRecordLookup("failure", error_type=type(exc).__name__)
    if item is None:
        return DeliveryRecordLookup("not_found")
    return DeliveryRecordLookup("found", record_fields(item))


def _read_from_r2(key: str, payload_hash: str) -> object:
    from purchase_price.config import get_settings
    from purchase_price.storage.r2 import R2RawEvidenceStore, RawObjectRef

    store = R2RawEvidenceStore.from_settings(get_settings())
    return store.get_public_json(
        RawObjectRef(
            bucket=store.bucket,
            key=key,
            payload_hash=payload_hash,
            uncompressed_bytes=0,
            stored_bytes=0,
            created=False,
        )
    )
