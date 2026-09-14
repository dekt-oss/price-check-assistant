from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Protocol

from purchase_price.collectors.g2b_shopping import SOURCE_NAME, G2BShoppingOperation
from purchase_price.domain import ComparisonScope, EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice

TRACK_B_PAGE_SCHEMA = "g2b-track-b-page-v1"
TRACK_B_OPERATION = G2BShoppingOperation.SPECIFIC_ITEM_PROCUREMENTS.value
TRACK_B_NORMALIZER_VERSION = "g2b-track-b-normalizer-v1"


class TrackBNormalizationError(ValueError):
    """Raised when a Track B raw page violates the immutable page contract."""


class TrackBIdentityConflictError(TrackBNormalizationError):
    """Raised when one stable Track B identity maps to divergent raw payloads."""


class TrackBAmountCheck(StrEnum):
    NOT_CHECKED = "not_checked"
    CONSISTENT = "consistent"
    INCONSISTENT = "inconsistent"


@dataclass(frozen=True, order=True)
class TrackBStableIdentity:
    """Immutable Track B identity. Change order is deliberately part of the key."""

    delivery_request_number: str
    change_order: str
    product_sequence: str

    @property
    def source_record_id(self) -> str:
        return (
            f"delivery:{self.delivery_request_number}"
            f"|change:{self.change_order}"
            f"|line:{self.product_sequence}"
        )

    @property
    def logical_line_key(self) -> tuple[str, str]:
        """Logical line used only for latest/superseded projection, never for deduplication."""

        return self.delivery_request_number, self.product_sequence


@dataclass(frozen=True)
class TrackBProvenance:
    detail_code: str
    begin_date: str
    end_date: str
    page_no: int
    page_size: int
    api_params: tuple[tuple[str, str], ...]
    raw_object_key: str | None = None
    raw_payload_sha256: str | None = None
    fetched_at: datetime | None = None


@dataclass(frozen=True)
class NormalizedTrackBRecord:
    identity: TrackBStableIdentity
    provenance: TrackBProvenance
    item_sha256: str
    detail_code: str
    detail_name: str | None
    product_id: str | None
    product_name: str | None
    unit_price: Decimal | None
    quantity: Decimal | None
    unit: str | None
    total_amount: Decimal | None
    amount_check: TrackBAmountCheck
    supplier: str | None
    demand_institution: str | None
    transaction_date: date | None
    contract_delivery_type: str | None
    contract_type: str | None
    delivery_condition: str | None
    raw_item: dict[str, Any]


@dataclass(frozen=True)
class TrackBNormalizationIssue:
    item_index: int
    code: str
    message: str


@dataclass(frozen=True)
class TrackBNormalizationResult:
    records: tuple[NormalizedTrackBRecord, ...]
    issues: tuple[TrackBNormalizationIssue, ...]
    duplicate_count: int = 0


@dataclass(frozen=True)
class TrackBChangeOrderState:
    record: NormalizedTrackBRecord
    is_latest: bool
    superseded_by: TrackBStableIdentity | None


@dataclass(frozen=True)
class TrackBRawPage:
    """Raw R2 page plus metadata that is intentionally excluded from content hashing."""

    payload: Mapping[str, Any]
    raw_object_key: str | None = None
    raw_payload_sha256: str | None = None
    fetched_at: datetime | None = None


@dataclass(frozen=True)
class TrackBBatchNormalizationResult:
    records: tuple[NormalizedTrackBRecord, ...]
    issues: tuple[TrackBNormalizationIssue, ...]
    duplicate_pages: int
    duplicate_records: int


class TrackBNormalizedRepository(Protocol):
    """Future DB1 write boundary; implementations must keep raw evidence immutable."""

    def upsert_record(self, record: NormalizedTrackBRecord) -> None: ...

    def record_conflict(
        self,
        identity: TrackBStableIdentity,
        *,
        existing_item_sha256: str,
        incoming_item_sha256: str,
        incoming_raw_object_key: str,
    ) -> None: ...

    def save_price_candidate(self, record: NormalizedTrackBRecord, candidate: CollectedPrice) -> None: ...


def normalize_track_b_page(
    payload: Mapping[str, Any],
    *,
    raw_object_key: str | None = None,
    raw_payload_sha256: str | None = None,
    fetched_at: datetime | None = None,
) -> TrackBNormalizationResult:
    """Normalize one immutable `g2b-track-b-page-v1` page without inventing prices."""

    request, response = _validate_page_envelope(payload)
    detail_code = _required_text(request, "detail_code", context="request")
    begin_date = _required_text(request, "begin_date", context="request")
    end_date = _required_text(request, "end_date", context="request")
    page_no = _required_positive_int(request, "page_no", context="request")
    page_size = _required_positive_int(request, "page_size", context="request")
    items = response.get("items")
    if not isinstance(items, list):
        raise TrackBNormalizationError("response.items must be a list")

    provenance = TrackBProvenance(
        detail_code=detail_code,
        begin_date=begin_date,
        end_date=end_date,
        page_no=page_no,
        page_size=page_size,
        api_params=_api_params_from_request(request),
        raw_object_key=raw_object_key,
        raw_payload_sha256=raw_payload_sha256 or _payload_sha256(payload),
        fetched_at=_as_utc(fetched_at),
    )
    records: list[NormalizedTrackBRecord] = []
    issues: list[TrackBNormalizationIssue] = []
    seen: dict[TrackBStableIdentity, str] = {}
    duplicate_count = 0

    for index, raw in enumerate(items):
        if not isinstance(raw, Mapping):
            issues.append(
                TrackBNormalizationIssue(index, "INVALID_ITEM", "Track B item must be an object")
            )
            continue
        item = dict(raw)
        try:
            record = _normalize_item(item, provenance=provenance)
        except TrackBNormalizationError as exc:
            issues.append(TrackBNormalizationIssue(index, "INVALID_IDENTITY", str(exc)))
            continue

        previous_hash = seen.get(record.identity)
        if previous_hash is not None:
            if previous_hash == record.item_sha256:
                duplicate_count += 1
                continue
            issues.append(
                TrackBNormalizationIssue(
                    index,
                    "IDENTITY_CONFLICT",
                    f"stable identity {record.identity.source_record_id} has divergent payloads",
                )
            )
            continue

        seen[record.identity] = record.item_sha256
        records.append(record)
        if record.amount_check == TrackBAmountCheck.INCONSISTENT:
            issues.append(
                TrackBNormalizationIssue(
                    index,
                    "AMOUNT_MISMATCH",
                    "prdctAmt does not equal explicit prdctUprc × prdctQty; "
                    "the arithmetic result is validation-only and is never promoted to a price",
                )
            )

    return TrackBNormalizationResult(
        records=tuple(records),
        issues=tuple(issues),
        duplicate_count=duplicate_count,
    )


def normalize_track_b_pages(
    pages: Sequence[TrackBRawPage],
) -> TrackBBatchNormalizationResult:
    """Normalize multiple pages, making replayed pages and identity conflicts explicit."""

    page_hashes: set[str] = set()
    all_records: list[NormalizedTrackBRecord] = []
    all_issues: list[TrackBNormalizationIssue] = []
    duplicate_pages = 0
    duplicate_records = 0

    for page in pages:
        page_hash = page.raw_payload_sha256 or _payload_sha256(page.payload)
        if page_hash in page_hashes:
            duplicate_pages += 1
            continue
        page_hashes.add(page_hash)
        result = normalize_track_b_page(
            page.payload,
            raw_object_key=page.raw_object_key,
            raw_payload_sha256=page_hash,
            fetched_at=page.fetched_at,
        )
        all_issues.extend(result.issues)
        duplicate_records += result.duplicate_count
        all_records.extend(result.records)

    consolidated = consolidate_track_b_records(all_records)
    duplicate_records += len(all_records) - len(consolidated)
    return TrackBBatchNormalizationResult(
        records=consolidated,
        issues=tuple(all_issues),
        duplicate_pages=duplicate_pages,
        duplicate_records=duplicate_records,
    )


def consolidate_track_b_records(
    records: Sequence[NormalizedTrackBRecord],
) -> tuple[NormalizedTrackBRecord, ...]:
    """Deduplicate exact replays and fail closed on divergent payloads for one stable identity."""

    by_identity: dict[TrackBStableIdentity, NormalizedTrackBRecord] = {}
    for record in records:
        existing = by_identity.get(record.identity)
        if existing is None:
            by_identity[record.identity] = record
            continue
        if existing.item_sha256 != record.item_sha256:
            raise TrackBIdentityConflictError(
                f"stable identity {record.identity.source_record_id} has divergent payloads"
            )
    return tuple(by_identity.values())


def project_change_order_state(
    records: Sequence[NormalizedTrackBRecord],
) -> tuple[TrackBChangeOrderState, ...]:
    """Preserve every change order while marking the latest version of each logical line."""

    unique_records = consolidate_track_b_records(records)
    groups: dict[tuple[str, str], list[NormalizedTrackBRecord]] = defaultdict(list)
    for record in unique_records:
        groups[record.identity.logical_line_key].append(record)

    state_by_identity: dict[TrackBStableIdentity, TrackBChangeOrderState] = {}
    for group in groups.values():
        if any(not record.identity.change_order.isdigit() for record in group):
            raise TrackBNormalizationError("non-numeric change order cannot be projected as latest")
        ordered = sorted(group, key=lambda record: int(record.identity.change_order))
        if len(ordered) > 1 and int(ordered[-1].identity.change_order) == int(
            ordered[-2].identity.change_order
        ):
            raise TrackBNormalizationError("ambiguous latest change order for logical line")
        latest = ordered[-1]
        for record in ordered:
            state_by_identity[record.identity] = TrackBChangeOrderState(
                record=record,
                is_latest=record.identity == latest.identity,
                superseded_by=None if record.identity == latest.identity else latest.identity,
            )

    return tuple(state_by_identity[record.identity] for record in unique_records)


def project_latest_track_b_records(
    records: Sequence[NormalizedTrackBRecord],
) -> tuple[NormalizedTrackBRecord, ...]:
    """Derived current view; the input history and raw evidence remain untouched."""

    return tuple(state.record for state in project_change_order_state(records) if state.is_latest)


def build_track_b_price_candidate(
    record: NormalizedTrackBRecord,
    *,
    collected_at: date | None = None,
) -> CollectedPrice | None:
    """Build an observed-price candidate from explicit positive `prdctUprc` only.

    `prdctAmt`, `prdctQty`, and any arithmetic result are never used as a fallback price.
    Identity matching and quote-comparability remain separate downstream gates.
    """

    if record.unit_price is None or record.unit_price <= 0 or not record.product_name:
        return None
    conditions = _conditions(record)
    return CollectedPrice(
        manufacturer=None,
        product_name=record.product_name,
        model_name=None,
        specification=f"조달 세부품명번호={record.detail_code}",
        price=record.unit_price,
        evidence_type=EvidenceType.DELIVERY_ORDER_UNIT_PRICE,
        source_type=SourceType.PROCUREMENT,
        source_name=SOURCE_NAME,
        source_url=None,
        collected_at=collected_at or date.today(),
        transaction_date=record.transaction_date,
        quantity=record.quantity,
        unit=record.unit,
        total_amount=record.total_amount,
        source_record_id=record.identity.source_record_id,
        original_title=record.product_name,
        conditions=conditions,
        match_grade=MatchGrade.X,
        match_note="Track B normalized procurement evidence; product identity matching deferred",
        comparison_scope=ComparisonScope.OBSERVED_ONLY,
        comparison_note=(
            "명시적 prdctUprc 관측값. VAT·설치·옵션·보증 등 상업조건이 완전히 구조화되기 전에는 "
            "관측가격으로만 사용"
        ),
    )


def _validate_page_envelope(
    payload: Mapping[str, Any],
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    if payload.get("schema") != TRACK_B_PAGE_SCHEMA:
        raise TrackBNormalizationError("Track B raw page schema mismatch")
    if payload.get("operation") != TRACK_B_OPERATION:
        raise TrackBNormalizationError("Track B raw page operation mismatch")
    request = payload.get("request")
    response = payload.get("response")
    if not isinstance(request, Mapping) or not isinstance(response, Mapping):
        raise TrackBNormalizationError("Track B raw page must contain request/response objects")
    if request.get("final_change_order_filter") != "OMITTED":
        raise TrackBNormalizationError("Track B raw page must preserve all change orders")
    return request, response


def _normalize_item(
    item: dict[str, Any],
    *,
    provenance: TrackBProvenance,
) -> NormalizedTrackBRecord:
    identity = TrackBStableIdentity(
        delivery_request_number=_required_text(item, "cntrctDlvrReqNo", context="item"),
        change_order=_required_text(item, "cntrctDlvrReqChgOrd", context="item"),
        product_sequence=_required_text(item, "prdctSno", context="item"),
    )
    detail_code = _text_or_none(item.get("dtilPrdctClsfcNo")) or provenance.detail_code
    if detail_code != provenance.detail_code:
        raise TrackBNormalizationError(
            f"item detail code {detail_code} does not match request {provenance.detail_code}"
        )

    # Only this exact source field has direct-price semantics for Track B.
    unit_price = _decimal_or_none(item.get("prdctUprc"))
    quantity = _decimal_or_none(item.get("prdctQty"))
    total_amount = _decimal_or_none(item.get("prdctAmt"))
    return NormalizedTrackBRecord(
        identity=identity,
        provenance=provenance,
        item_sha256=_item_sha256(item),
        detail_code=detail_code,
        detail_name=_text_or_none(item.get("dtilPrdctClsfcNoNm")),
        product_id=_text_or_none(item.get("prdctIdntNo")),
        product_name=_text_or_none(item.get("prdctIdntNoNm")),
        unit_price=unit_price,
        quantity=quantity,
        unit=_text_or_none(item.get("prdctUnit")),
        total_amount=total_amount,
        amount_check=_amount_check(unit_price, quantity, total_amount),
        supplier=_text_or_none(item.get("corpNm")),
        demand_institution=_text_or_none(item.get("dminsttNm")),
        transaction_date=_date_or_none(item.get("cntrctDlvrReqDate")),
        contract_delivery_type=_text_or_none(item.get("cntrctDlvrDivNm")),
        contract_type=_text_or_none(item.get("cntrctDivNm")),
        delivery_condition=_text_or_none(item.get("dlvryCndtnNm")),
        raw_item=item,
    )


def _amount_check(
    unit_price: Decimal | None,
    quantity: Decimal | None,
    total_amount: Decimal | None,
) -> TrackBAmountCheck:
    if unit_price is None or quantity is None or total_amount is None or quantity <= 0:
        return TrackBAmountCheck.NOT_CHECKED
    expected = unit_price * quantity
    return (
        TrackBAmountCheck.CONSISTENT
        if expected == total_amount
        else TrackBAmountCheck.INCONSISTENT
    )


def _api_params_from_request(request: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    begin = _required_text(request, "begin_date", context="request").replace("-", "")
    end = _required_text(request, "end_date", context="request").replace("-", "")
    params = {
        "dtilPrdctClsfcNo": _required_text(request, "detail_code", context="request"),
        "inqryBgnDate": begin,
        "inqryDiv": str(request.get("inquiry_div") or "1"),
        "inqryEndDate": end,
        "inqryPrdctDiv": str(request.get("product_div") or "2"),
        "numOfRows": str(_required_positive_int(request, "page_size", context="request")),
        "pageNo": str(_required_positive_int(request, "page_no", context="request")),
    }
    return tuple(sorted(params.items()))


def _conditions(record: NormalizedTrackBRecord) -> str | None:
    values = (
        ("공급업체", record.supplier),
        ("수요기관", record.demand_institution),
        ("계약납품구분", record.contract_delivery_type),
        ("계약구분", record.contract_type),
        ("납품조건", record.delivery_condition),
        ("금액검산", record.amount_check.value),
    )
    parts = [f"{label}={value}" for label, value in values if value]
    return "; ".join(parts) or None


def _required_text(record: Mapping[str, Any], key: str, *, context: str) -> str:
    value = _text_or_none(record.get(key))
    if value is None:
        raise TrackBNormalizationError(f"{context}.{key} is required")
    return value


def _required_positive_int(record: Mapping[str, Any], key: str, *, context: str) -> int:
    try:
        value = int(record.get(key))
    except (TypeError, ValueError) as exc:
        raise TrackBNormalizationError(f"{context}.{key} must be an integer") from exc
    if value < 1:
        raise TrackBNormalizationError(f"{context}.{key} must be positive")
    return value


def _text_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _decimal_or_none(value: Any) -> Decimal | None:
    text = _text_or_none(value)
    if text is None:
        return None
    try:
        value = Decimal(text.replace(",", "").replace("원", "").strip())
        return value if value.is_finite() else None
    except InvalidOperation:
        return None


def _date_or_none(value: Any) -> date | None:
    text = _text_or_none(value)
    if text is None:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _payload_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _item_sha256(item: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        item,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
