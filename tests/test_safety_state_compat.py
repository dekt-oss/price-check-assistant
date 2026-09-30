from __future__ import annotations

from types import SimpleNamespace

from purchase_price.evidence_domain import SafetyEvidenceStatus
from purchase_price.ui.safety_state_compat import (
    SafetyDisplayStatus,
    build_safety_state_compat,
)


class StaleSafetyModule:
    """Simulate a Streamlit process retaining the pre-live-Safety module."""


def _lookup(status: str, *, records=()):
    return SimpleNamespace(
        status=status,
        records=records,
        checked_at="2026-09-30T17:00:00+09:00",
        source_url="https://www.data.go.kr/data/15056785/openapi.do",
    )


def test_stale_module_preserves_not_authorized_status() -> None:
    state = build_safety_state_compat(
        safety_support_module=StaleSafetyModule(),
        lookup=_lookup("not_authorized"),
        model_name="Efficia DFM100",
        permit_numbers=["수허 12-3456"],
    )

    assert state.status == SafetyDisplayStatus.NOT_AUTHORIZED
    assert state.evidence_status == SafetyEvidenceStatus.NOT_CONNECTED
    assert "활용승인" in state.message
    assert state.checked_at == "2026-09-30T17:00:00+09:00"
    assert state.search_keys == (
        "모델명: Efficia DFM100",
        "식약처 품목번호: 수허 12-3456",
    )


def test_stale_module_preserves_failure_distinct_from_zero() -> None:
    state = build_safety_state_compat(
        safety_support_module=StaleSafetyModule(),
        lookup=_lookup("failure"),
        model_name="DFM100",
    )

    assert state.status == SafetyDisplayStatus.ERROR
    assert state.evidence_status == SafetyEvidenceStatus.CHECK_FAILED
    assert "0건으로 해석하지" in state.message


def test_stale_module_preserves_success_zero_without_safe_claim() -> None:
    state = build_safety_state_compat(
        safety_support_module=StaleSafetyModule(),
        lookup=_lookup("success_0"),
        model_name="DFM100",
    )

    assert state.status == SafetyDisplayStatus.NO_MATCH
    assert state.evidence_status == SafetyEvidenceStatus.CHECKED_NONE
    assert "안전하다는 판정이 아니며" in state.message
    assert "안전함" not in state.message


def test_stale_module_positive_rows_remain_amber() -> None:
    state = build_safety_state_compat(
        safety_support_module=StaleSafetyModule(),
        lookup=_lookup("success", records=(SimpleNamespace(),)),
        model_name="DFM100",
        permit_numbers=["수허 12-3456"],
    )

    assert state.status == SafetyDisplayStatus.CHECK_REQUIRED
    assert state.evidence_status == SafetyEvidenceStatus.AMBER
    assert "exact 식약처 품목번호가 없어" in state.message


def test_current_builder_is_preferred_when_available() -> None:
    sentinel = object()

    class CurrentModule:
        @staticmethod
        def build_safety_state_from_recall_lookup(
            lookup,
            *,
            model_name: str,
            product_name: str,
            permit_numbers,
        ):
            assert lookup.status == "success_0"
            assert model_name == "DFM100"
            return sentinel

    state = build_safety_state_compat(
        safety_support_module=CurrentModule(),
        lookup=_lookup("success_0"),
        model_name="DFM100",
    )

    assert state is sentinel
