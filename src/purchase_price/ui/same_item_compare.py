"""Same-item comparison grouped by 품목 책임주체 → 모델 (W3 phase 2, #221 §11).

Rows come from the MFDS identity crosslinks (company, model, permit and the model's direct
나라장터 evidence). Domestic status comes from the MFDS model-info records when they were
loaded; until then a row is "상태 미확인" and is never presented as active. Known cancelled or
export-only models are hidden by default, unpriced models are hidden by default, and the
searched model is always kept so the buyer can see where it sits.

New module so a Streamlit hot reload that keeps older modules never sees a half-updated import.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from purchase_price.services.matching import normalize_text

STATUS_ACTIVE = "국내 정상"
STATUS_CANCELLED = "취소·취하"
STATUS_EXPORT = "수출용"
STATUS_UNKNOWN = "상태 미확인"
_INACTIVE = {STATUS_CANCELLED, STATUS_EXPORT}


def _key(permit: object, model: object) -> tuple[str, str]:
    return normalize_text(str(permit or "")), normalize_text(str(model or ""))


def live_status_index(records: Iterable[Any] | None) -> dict[tuple[str, str], str] | None:
    """(permit, model) -> status from MFDS model-info rows; None when not loaded yet."""

    if records is None:
        return None
    index: dict[tuple[str, str], str] = {}
    for record in records:
        permit = getattr(record, "permit_number", None)
        model = getattr(record, "model_name", None)
        if not permit or not model:
            continue
        key = _key(permit, model)
        if getattr(record, "active_for_domestic_candidate", False):
            status = STATUS_ACTIVE
        elif getattr(record, "cancellation_status", None):
            status = STATUS_CANCELLED
        else:
            status = STATUS_EXPORT
        # One active row is enough for the model to be domestically available.
        if index.get(key) != STATUS_ACTIVE:
            index[key] = status
    return index


@dataclass(frozen=True)
class SameItemView:
    rows: tuple[dict[str, object], ...]
    total: int
    hidden_unpriced: int
    hidden_inactive: int
    status_loaded: bool
    unknown_status_count: int = 0
    current_present: bool = True


def _direct_count(row: Mapping[str, object]) -> int:
    try:
        return int(row.get("나라장터 직접거래") or 0)
    except (TypeError, ValueError):
        return 0


def build_same_item_rows(
    crosslinks: Sequence[Mapping[str, object]],
    status_index: Mapping[tuple[str, str], str] | None,
    *,
    include_unpriced: bool = False,
    include_inactive: bool = False,
    current_keys: Iterable[tuple[object, object]] = (),
) -> SameItemView:
    """current_keys: (permit, model) of the exact MFDS record the search resolved to."""

    resolved = {_key(permit, model) for permit, model in current_keys}
    hidden_unpriced = 0
    hidden_inactive = 0
    kept: list[tuple[Mapping[str, object], str, bool]] = []
    for row in crosslinks:
        current = bool(row.get("현재 모델")) or _key(row.get("식약처 품목번호"), row.get("모델")) in resolved
        status = STATUS_UNKNOWN
        if status_index is not None:
            status = status_index.get(_key(row.get("식약처 품목번호"), row.get("모델")), STATUS_UNKNOWN)
        if not current:
            if status in _INACTIVE and not include_inactive:
                hidden_inactive += 1
                continue
            if _direct_count(row) == 0 and not include_unpriced:
                hidden_unpriced += 1
                continue
        kept.append((row, status, current))

    company_weight: dict[str, tuple[int, int]] = {}
    for row, _status, current in kept:
        company = str(row.get("품목 책임주체") or "").strip() or "업체 미확인"
        has_current, priced = company_weight.get(company, (0, 0))
        company_weight[company] = (has_current or int(current), priced + int(_direct_count(row) > 0))

    def sort_key(item: tuple[Mapping[str, object], str, bool]) -> tuple[object, ...]:
        row, _status, current = item
        company = str(row.get("품목 책임주체") or "").strip() or "업체 미확인"
        has_current, priced = company_weight[company]
        return (-has_current, -priced, company, not current, -_direct_count(row), str(row.get("모델") or ""))

    output: list[dict[str, object]] = []
    previous_company: str | None = None
    for row, status, current in sorted(kept, key=sort_key):
        company = str(row.get("품목 책임주체") or "").strip() or "업체 미확인"
        permit = str(row.get("식약처 품목번호") or "").strip()
        kind = str(row.get("유형") or "").strip()
        count = row.get("나라장터 직접거래")
        output.append(
            {
                # Company only on the first row of its group, so the table reads as a tree.
                "품목 책임주체": company if company != previous_company else "",
                "모델": f"▶ {row.get('모델')}" if current else str(row.get("모델") or ""),
                "식약처 품목번호": f"[{kind}] {permit}" if kind and permit else permit or "미확인",
                "식약처 상태": status,
                "나라장터 거래": "조회 불가" if count is None else f"{_direct_count(row)}건",
                "가격범위": row.get("나라장터 가격범위") or "",
                "최근거래": row.get("최근거래") or "",
                "실제 납품업체": row.get("실제 조달 공급업체") or "",
            }
        )
        previous_company = company
    return SameItemView(
        rows=tuple(output),
        total=len(crosslinks),
        hidden_unpriced=hidden_unpriced,
        hidden_inactive=hidden_inactive,
        status_loaded=status_index is not None,
        unknown_status_count=sum(1 for _row, status, _current in kept if status == STATUS_UNKNOWN),
        current_present=any(current for _row, _status, current in kept) or not resolved,
    )


def status_notes(view: SameItemView) -> list[str]:
    notes: list[str] = []
    if not view.status_loaded:
        notes.append(
            "식약처 상태는 상단 버튼으로 형명정보를 불러온 뒤 표시되며, 그 전에는 국내 정상으로 단정하지 않습니다"
        )
    elif view.unknown_status_count:
        notes.append(
            f"상태 미확인 {view.unknown_status_count}개는 형명 조회 결과에 없던 모델입니다. "
            "품목번호별 상태표(수집 중)를 연결하면 채워집니다"
        )
    if not view.current_present:
        notes.append("검색한 모델은 아직 수집된 같은 품목 목록에 없어 이 표에 없습니다 (가격은 위 카드 기준)")
    return notes


def hidden_note(view: SameItemView) -> str:
    parts = []
    if view.hidden_unpriced:
        parts.append(f"조달가격 없는 모델 {view.hidden_unpriced}개")
    if view.hidden_inactive:
        parts.append(f"취소·취하·수출용 {view.hidden_inactive}개")
    return "숨김 · " + " · ".join(parts) if parts else ""
