from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from purchase_price.services.quote_comparability import evaluate_quote_comparability_candidate

if TYPE_CHECKING:
    from purchase_price.services.g2b_unmapped_discovery import G2BUnmappedDiscoveryResult
    from purchase_price.services.quote_comparability import QuoteComparabilityContext
    from purchase_price.services.quote_comparable_approval import QuoteComparableApproval
    from purchase_price.services.quote_extraction import QuoteExtractionResult, QuoteItem
    from purchase_price.services.quote_extraction_diagnostics import QuoteExtractionDiagnostics
    from purchase_price.services.search import SearchRun

QUOTE_REVIEW_STATE_SESSION_KEY = "quote_review_state"
QUOTE_REVIEW_STEPS = (
    "업로드·추출",
    "품목 확인",
    "제품 식별",
    "근거 수집",
    "조건 대조",
    "승인·판정",
)


@dataclass(frozen=True)
class IdentityResult:
    """UI-only identity checkpoint; it does not replace matching service contracts."""

    ready: bool
    status: str
    detail: str = ""
    source: str = ""
    mapping_verified: bool = False
    mfds_confirmed: bool = False
    research_required: bool = False


@dataclass
class QuoteReviewState:
    file_name: str | None = None
    file_kind: str | None = None
    extraction: QuoteExtractionResult | None = None
    diagnostics: QuoteExtractionDiagnostics | None = None
    items: list[QuoteItem] = field(default_factory=list)
    item_confirmed: dict[int, bool] = field(default_factory=dict)
    item_notes: dict[int, str] = field(default_factory=dict)
    condition_notes: dict[int, dict[str, str]] = field(default_factory=dict)
    vat_conflict: bool = False
    identity: dict[int, IdentityResult] = field(default_factory=dict)
    search_runs: dict[int, SearchRun] = field(default_factory=dict)
    discoveries: dict[int, G2BUnmappedDiscoveryResult | None] = field(default_factory=dict)
    lookback_days: int = 365
    comparability_context: dict[int, QuoteComparabilityContext] = field(default_factory=dict)
    approvals: dict[str, QuoteComparableApproval] = field(default_factory=dict)
    reviewer: str = ""
    step: int = 1
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def reset_downstream(self, after_step: int) -> None:
        """Drop only derived UI state after an upstream edit."""
        if after_step < 3:
            self.identity.clear()
        if after_step < 4:
            self.search_runs.clear()
            self.discoveries.clear()
        if after_step < 5:
            self.comparability_context.clear()
        if after_step < 6:
            self.approvals.clear()
        self.step = min(self.step, max(1, after_step))


def _item_numbers(indices: list[int]) -> str:
    return ", ".join(str(index + 1) for index in indices)


def _has_eligible_candidate(state: QuoteReviewState) -> bool:
    for index, run in state.search_runs.items():
        context = state.comparability_context.get(index)
        if context is None:
            continue
        for evidence in run.results:
            if evaluate_quote_comparability_candidate(context, evidence).eligible_candidate:
                return True
    return False


def can_enter(step: int, state: QuoteReviewState) -> tuple[bool, tuple[str, ...]]:
    """Pure UI navigation gate. Reasons are safe to render verbatim in the status card."""
    if step < 1 or step > len(QUOTE_REVIEW_STEPS):
        raise ValueError(f"step must be between 1 and {len(QUOTE_REVIEW_STEPS)}")
    if step == 1:
        return True, ()

    reasons: list[str] = []
    if state.extraction is None:
        reasons.append("견적서를 업로드하고 추출을 실행하세요.")
        return False, tuple(reasons)
    if step == 2:
        return True, ()

    if not state.items:
        reasons.append("자동 추출 품목이 없어 수동 품목을 1건 이상 입력하세요.")
        return False, tuple(reasons)

    unconfirmed = [
        index
        for index in range(len(state.items))
        if not state.item_confirmed.get(index, False)
    ]
    if unconfirmed:
        reasons.append(f"품목 {_item_numbers(unconfirmed)}의 추출값을 원문과 대조해 확인하세요.")
        return False, tuple(reasons)
    if step == 3:
        return True, ()

    identity_missing = [
        index
        for index in range(len(state.items))
        if not state.identity.get(index) or not state.identity[index].ready
    ]
    if identity_missing:
        reasons.append(f"품목 {_item_numbers(identity_missing)}의 제품 식별을 완료하세요.")
        return False, tuple(reasons)
    if step == 4:
        return True, ()

    if not state.search_runs:
        reasons.append("제품 식별이 끝난 품목의 공개 가격근거 검색을 실행하세요.")
        return False, tuple(reasons)
    if step == 5:
        return True, ()

    missing_context = [
        index for index in state.search_runs if index not in state.comparability_context
    ]
    if missing_context:
        reasons.append(f"품목 {_item_numbers(missing_context)}의 견적 비교조건을 확인하세요.")
        return False, tuple(reasons)
    if not _has_eligible_candidate(state):
        reasons.append("현재 조건에서 승인 가능한 직접 비교 후보가 없습니다.")
        return False, tuple(reasons)
    return True, ()
