from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
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
    """Raised when one stable Track B identity maps to different raw item payloads."""


@dataclass(frozen=True, order=True)
class TrackBStableIdentity:
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
        return self.delivery_request_number, self.product_sequence


@dataclass(frozen=True)
class TrackBProvenance:
    detail_code: str
    begin_date: str
    end_date: str
    page_no: int
    raw_object_key: str | None = None
    raw_payload_sha256: str | None = None


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


class TrackBNormalizedRepository(Protocol):
    """Persistence seam for DB1; the raw-to-normalized contract does not require a DB migration."""

    def persist(self, records: Sequence[NormalizedTrackBRecord]) -> None: ...


def normalize_track_b_page(
    payload: Mapping[str, Any],
    *,
    raw_object_key: str | None = None,
    raw_payload_sha256: str | None = None,
) -> TrackBNormalizationResult:
    request, response = _validate_page_envelope(payload)
    detail_code = _required_text(request, "detail_code", context="request")
    begin_date = _required_text(request, "begin_date", context="request")
    end_date = _required_text(request, "end_date", context="request")
    page_no = _required_positive_int(request, "page_no", context="request")
    items = response.get("items")
    if not isinstance(items, list):
        raise TrackBNormalizationError("response.items must be a list")

    provenance = TrackBProvenance(
        detail_code=detail_code,
        begin_date=begin_date,
        end_date=end_date,
        page_no=page_no,
        raw_object_key=raw_object_key,
        raw_payload_sha256=raw_payload_sha256,
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

    return TrackBNormalizationResult(
        records=tuple(records),
        issues=tuple(issues),
        duplicate_count=duplicate_count,
    )


def consolidate_track_b_records(
    records: Sequence[NormalizedTrackBRecord],
) -> tuple[NormalizedTrackBRecord, ...]:
    """Deduplicate replayed records and fail closed on divergent payloads for one identity."""

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
    """Preserve every change order while marking the latest record per delivery-request line."""

    groups: dict[tuple[str, str], list[NormalizedTrackBRecord]] = defaultdict(list)
    for record in records:
        groups[record.identity.logical_line_key].append(record)

    state_by_identity: dict[TrackBStableIdentity, TrackBChangeOrderState] = {}
    for group in groups.values():
        ordered = sorted(group, key=lambda record: _change_order_key(record.identity.change_order))
        latest = ordered[-1]
        for record in ordered:
            state_by_identity[record.identity] = TrackBChangeOrderState(
                record=record,
                is_latest=record.identity == latest.identity,
                superseded_by=None if record.identity == latest.identity else latest.identity,
            )

    return tuple(state_by_identity[record.identity] for record in records)


def build_track_b_price_candidate(
    record: NormalizedTrackBRecord,
    *,
    collected_at: date | None = None,
) -> CollectedPrice | None:
    """Promote only the explicit Track B `prdctUprc` field into a price candidate."""

    if record.unit_price is None or not record.product_name:
        return None
    evidence_type = _evidence_type(record.contract_delivery_type)
    conditions = _conditions(record)
    return CollectedPrice(
        manufacturer=None,
        product_name=record.product_name,
        model_name=None,
        specification=f"조달 세부품명번호={record.detail_code}",
        price=record.unit_price,
        evidence_type=evidence_type,
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
            "VAT·설치·옵션·보증 등 상업조건이 완전히 구조화되기 전에는 관측가격으로만 사용"
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
    return NormalizedTrackBRecord(
        identity=identity,
        provenance=provenance,
        item_sha256=_item_sha256(item),
        detail_code=detail_code,
        detail_name=_text_or_none(item.get("dtilPrdctClsfcNoNm")),
        product_id=_text_or_none(item.get("prdctIdntNo")),
        product_name=_text_or_none(item.get("prdctIdntNoNm")),
        unit_price=_decimal_or_none(item.get("prdctUprc")),
        quantity=_decimal_or_none(item.get("prdctQty")),
        unit=_text_or_none(item.get("prdctUnit")),
        total_amount=_decimal_or_none(item.get("prdctAmt")),
        supplier=_text_or_none(item.get("corpNm")),
        demand_institution=_text_or_none(item.get("dminsttNm")),
        transaction_date=_date_or_none(item.get("cntrctDlvrReqDate")),
        contract_delivery_type=_text_or_none(item.get("cntrctDlvrDivNm")),
        contract_type=_text_or_none(item.get("cntrctDivNm")),
        delivery_condition=_text_or_none(item.get("dlvryCndtnNm")),
        raw_item=item,
    )


def _evidence_type(contract_delivery_type: str | None) -> EvidenceType:
    text = contract_delivery_type or ""
    if "납품" in text:
        return EvidenceType.DELIVERY_ORDER_UNIT_PRICE
    if "계약" in text:
        return EvidenceType.CONTRACT_UNIT_PRICE
    return EvidenceType.UNKNOWN


def _conditions(record: NormalizedTrackBRecord) -> str | None:
    values = (
        ("공급업체", record.supplier),
        ("수요기관", record.demand_institution),
        ("계약구분", record.contract_type),
        ("납품조건", record.delivery_condition),
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
        return Decimal(text.replace(",", "").replace("원", "").strip())
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


def _item_sha256(item: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        item,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _change_order_key(value: str) -> tuple[int, int | str]:
    stripped = value.strip()
    if stripped.isdigit():
        return 0, int(stripped)
    return 1, stripped
