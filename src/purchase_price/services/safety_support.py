from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from purchase_price.evidence_domain import SafetyEvidenceStatus
from purchase_price.services.matching import normalize_text

MFDS_RECALL_PAGE_URL = "https://emedi.mfds.go.kr/recall/MNU20265"
MFDS_ADMIN_SANCTION_PAGE_URL = "https://emedi.mfds.go.kr/disps/MNU20266"
MFDS_SAFETY_LETTER_PAGE_URL = "https://emedi.mfds.go.kr/safeLet/safetyLttr/MNU20261"
MFDS_RECALL_DATASET_URL = "https://www.data.go.kr/data/15056785/openapi.do"
MFDS_STANDARD_CODE_DATASET_URL = "https://www.data.go.kr/data/15073875/openapi.do"
MFDS_UDI_PORTAL_URL = "https://emedi.mfds.go.kr/msismext/udi/ima/modelMngView.do"


class SafetyCheckStatus(StrEnum):
    NOT_CONNECTED = "자동조회 미연결"
    CHECK_REQUIRED = "공식 확인 필요"
    MATCH = "공식 안전조치 일치"
    NO_MATCH = "공식 안전정보 일치 미확인"
    ERROR = "공식 안전정보 조회 실패"


@dataclass(frozen=True)
class MedicalDeviceRecallRecord:
    """Normalized official recall/sale-stop record.

    Network adapters must map only fields explicitly supplied by the official source.
    Missing model/lot scope stays unknown and is never expanded by inference.
    """

    company_name: str | None = None
    product_name: str | None = None
    permit_number: str | None = None
    model_name: str | None = None
    manufacturing_number: str | None = None
    manufacturing_date: str | None = None
    reason: str | None = None
    action_date: str | None = None
    applies_to_all_models: bool | None = None


@dataclass(frozen=True)
class SafetyCheckState:
    status: SafetyCheckStatus
    message: str
    model_name: str = ""
    permit_numbers: tuple[str, ...] = ()
    semantic_status: SafetyEvidenceStatus | None = None
    checked_at: str | None = None
    source_url: str | None = None
    lot_scope: str | None = None

    @property
    def evidence_status(self) -> SafetyEvidenceStatus:
        if self.semantic_status is not None:
            return self.semantic_status
        return {
            SafetyCheckStatus.NOT_CONNECTED: SafetyEvidenceStatus.NOT_CONNECTED,
            SafetyCheckStatus.CHECK_REQUIRED: SafetyEvidenceStatus.NOT_CONNECTED,
            SafetyCheckStatus.MATCH: SafetyEvidenceStatus.RED,
            SafetyCheckStatus.NO_MATCH: SafetyEvidenceStatus.CHECKED_NONE,
            SafetyCheckStatus.ERROR: SafetyEvidenceStatus.CHECK_FAILED,
        }[self.status]

    @property
    def search_keys(self) -> tuple[str, ...]:
        keys: list[str] = []
        if self.model_name:
            keys.append(f"모델명: {self.model_name}")
        keys.extend(f"식약처 품목번호: {number}" for number in self.permit_numbers)
        return tuple(keys)


def _unique_text(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return tuple(result)


def build_manual_safety_check_state(
    *,
    model_name: str = "",
    permit_numbers: Iterable[str] = (),
) -> SafetyCheckState:
    """Represent the current safety state without implying that a missing API result means safe.

    The recall/sale-stop API is intentionally not called until its official operation/request
    contract is verified. Exact model and permit identifiers are preserved as manual verification
    keys so the UI can direct the reviewer to official MFDS safety pages in the meantime.
    """

    model = str(model_name or "").strip()
    permits = _unique_text(permit_numbers)
    if model or permits:
        return SafetyCheckState(
            status=SafetyCheckStatus.CHECK_REQUIRED,
            message=(
                "회수·판매중지 자동 API는 아직 연결하지 않았습니다. 아래 exact 모델/식약처 품목번호를 "
                "기준으로 식약처 공식 회수·판매중지, 행정처분, 안전성서한을 직접 확인하세요. "
                "자동조회 미연결 상태는 공식 안전정보 확인 결과가 아닙니다."
            ),
            model_name=model,
            permit_numbers=permits,
        )
    return SafetyCheckState(
        status=SafetyCheckStatus.NOT_CONNECTED,
        message=(
            "회수·판매중지 자동 API는 아직 연결하지 않았고 exact 모델/식약처 품목번호도 확보되지 "
            "않았습니다. 제품 identity를 먼저 확인한 뒤 공식 안전정보를 검토해야 합니다."
        ),
    )


def related_safety_state(
    *,
    message: str,
    model_name: str = "",
    permit_numbers: Iterable[str] = (),
    checked_at: str | None = None,
    source_url: str | None = None,
) -> SafetyCheckState:
    """Represent related safety information that is not an exact product action."""

    return SafetyCheckState(
        status=SafetyCheckStatus.CHECK_REQUIRED,
        message=message,
        semantic_status=SafetyEvidenceStatus.AMBER,
        model_name=str(model_name or "").strip(),
        permit_numbers=_unique_text(permit_numbers),
        checked_at=checked_at,
        source_url=source_url,
    )


def evaluate_official_recall_records(
    records: Iterable[MedicalDeviceRecallRecord],
    *,
    model_name: str = "",
    permit_numbers: Iterable[str] = (),
    checked_at: str | None = None,
    source_url: str | None = MFDS_RECALL_DATASET_URL,
) -> SafetyCheckState:
    """Evaluate already-fetched official recall rows with fail-closed identity rules.

    A RED state requires an exact permit match plus either an exact model match or an
    explicit source flag saying the action applies to all models. Permit-related rows
    with unknown/different model scope are AMBER rather than being promoted to RED.
    Model-name-only matching is intentionally insufficient because model strings can be
    shared across multiple permits or companies.
    """

    model = str(model_name or "").strip()
    model_key = normalize_text(model)
    permits = _unique_text(permit_numbers)
    permit_keys = {normalize_text(number) for number in permits if normalize_text(number)}
    if not permit_keys:
        return SafetyCheckState(
            status=SafetyCheckStatus.CHECK_REQUIRED,
            message=(
                "공식 회수·판매중지 조회 결과를 제품에 연결하려면 exact 식약처 품목번호가 필요합니다. "
                "모델명만으로는 회수대상을 확정하지 않습니다."
            ),
            semantic_status=SafetyEvidenceStatus.AMBER,
            model_name=model,
            permit_numbers=permits,
            checked_at=checked_at,
            source_url=source_url,
        )

    related: list[MedicalDeviceRecallRecord] = []
    exact: list[MedicalDeviceRecallRecord] = []
    for record in records:
        permit_key = normalize_text(record.permit_number)
        if not permit_key or permit_key not in permit_keys:
            continue
        related.append(record)
        record_model_key = normalize_text(record.model_name)
        if record.applies_to_all_models is True:
            exact.append(record)
        elif model_key and record_model_key and record_model_key == model_key:
            exact.append(record)

    if exact:
        lot_values = _unique_text(
            record.manufacturing_number or ""
            for record in exact
            if record.manufacturing_number
        )
        action_dates = _unique_text(
            record.action_date or ""
            for record in exact
            if record.action_date
        )
        date_text = f" · 조치일 {' / '.join(action_dates)}" if action_dates else ""
        lot_text = (
            f" · 제조번호/lot {' / '.join(lot_values)}"
            if lot_values
            else " · 제조번호/lot 범위는 Source 미제공"
        )
        return SafetyCheckState(
            status=SafetyCheckStatus.MATCH,
            message=(
                "공식 회수·판매중지 데이터에서 exact 제품 identity와 일치하는 안전조치가 확인됨"
                f"{date_text}{lot_text}"
            ),
            semantic_status=SafetyEvidenceStatus.RED,
            model_name=model,
            permit_numbers=permits,
            checked_at=checked_at,
            source_url=source_url,
            lot_scope=" / ".join(lot_values) if lot_values else None,
        )

    if related:
        return SafetyCheckState(
            status=SafetyCheckStatus.CHECK_REQUIRED,
            message=(
                "동일 식약처 품목번호의 회수·판매중지 기록이 있으나 모델 적용범위를 exact로 확인하지 "
                "못했습니다. 관련 안전정보로 표시하며 대상 모델·제조번호 범위를 원문에서 확인해야 합니다."
            ),
            semantic_status=SafetyEvidenceStatus.AMBER,
            model_name=model,
            permit_numbers=permits,
            checked_at=checked_at,
            source_url=source_url,
        )

    return no_match_safety_state(
        model_name=model,
        permit_numbers=permits,
        checked_at=checked_at,
        source_url=source_url,
    )


def no_match_safety_state(
    *,
    model_name: str = "",
    permit_numbers: Iterable[str] = (),
    checked_at: str | None = None,
    source_url: str | None = None,
) -> SafetyCheckState:
    """Future adapter result wording for a successful official query with zero exact matches."""

    return SafetyCheckState(
        status=SafetyCheckStatus.NO_MATCH,
        message="현재 연결된 공식 안전정보에서 일치 항목을 확인하지 못함",
        model_name=str(model_name or "").strip(),
        permit_numbers=_unique_text(permit_numbers),
        checked_at=checked_at,
        source_url=source_url,
    )
