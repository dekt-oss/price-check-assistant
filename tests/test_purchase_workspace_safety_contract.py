from __future__ import annotations

from pathlib import Path


def test_purchase_workspace_integrates_official_mfds_recall_lookup() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "lookup_mfds_recall" in source
    assert "def _build_safety_state_compat" in source
    assert 'evidence_status=_safety_evidence_token("NOT_AUTHORIZED")' in source
    assert 'safety_status_value == "RED"' in source
    assert '"NOT_AUTHORIZED",' in source
    assert '"safety_lookup": safety_lookup' in source
    assert "식약처 회수·판매중지 확인 시각" in source
    assert "회수 기록에는 허가번호가 없어 '관련 안전정보'로 표시합니다" in source


def test_recall_api_authorization_is_configured_separately() -> None:
    source = Path("src/purchase_price/config.py").read_text(encoding="utf-8")

    assert "mfds_recall_service_key" in source
    assert "resolved_mfds_recall_service_key" in source
    assert '"MFDS_RECALL_SERVICE_KEY"' in source


def test_unified_search_isolates_safety_source_runtime_failures() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "def _lookup_mfds_recall_isolated" in source
    assert "except Exception as exc:" in source
    assert "mfds_recall_exception_result(" in source
    assert "normalize_mfds_recall_lookup(result)" in source
    assert "safety_lookup = _lookup_mfds_recall_isolated(" in source
