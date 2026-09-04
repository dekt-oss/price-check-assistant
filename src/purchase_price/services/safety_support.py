from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

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
class SafetyCheckState:
    status: SafetyCheckStatus
    message: str
    model_name: str = ""
    permit_numbers: tuple[str, ...] = ()

    @property
    def search_keys(self) -> tuple[str, ...]:
        keys: list[str] = []
        if self.model_name:
            keys.append(f"모델명: {self.model_name}")
        keys.extend(f"허가번호: {number}" for number in self.permit_numbers)
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
                "회수·판매중지 자동 API는 아직 연결하지 않았습니다. 아래 exact 모델/허가번호를 "
                "기준으로 식약처 공식 회수·판매중지, 행정처분, 안전성서한을 직접 확인하세요. "
                "자동조회 미연결 상태를 안전하다는 뜻으로 해석하지 않습니다."
            ),
            model_name=model,
            permit_numbers=permits,
        )
    return SafetyCheckState(
        status=SafetyCheckStatus.NOT_CONNECTED,
        message=(
            "회수·판매중지 자동 API는 아직 연결하지 않았고 exact 모델/허가번호도 확보되지 "
            "않았습니다. 제품 identity를 먼저 확인한 뒤 공식 안전정보를 검토해야 합니다."
        ),
    )


def no_match_safety_state(
    *, model_name: str = "", permit_numbers: Iterable[str] = ()
) -> SafetyCheckState:
    """Future adapter result wording for a successful official query with zero exact matches."""

    return SafetyCheckState(
        status=SafetyCheckStatus.NO_MATCH,
        message="현재 연결된 공식 안전정보에서 일치 항목을 확인하지 못함",
        model_name=str(model_name or "").strip(),
        permit_numbers=_unique_text(permit_numbers),
    )
