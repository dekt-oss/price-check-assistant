from __future__ import annotations

from pathlib import Path


def test_purchase_workspace_integrates_official_mfds_recall_lookup() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "lookup_mfds_recall" in source
    assert "build_safety_state_from_recall_lookup" in source
    assert '"safety_lookup": safety_lookup' in source
    assert "식약처 회수·판매중지 API 확인시각" in source
    assert "Service04 형명/품목 응답에는 exact 식약처 품목번호가 없어" in source


def test_recall_api_authorization_is_configured_separately() -> None:
    source = Path("src/purchase_price/config.py").read_text(encoding="utf-8")

    assert "mfds_recall_service_key" in source
    assert "resolved_mfds_recall_service_key" in source
    assert '"MFDS_RECALL_SERVICE_KEY"' in source
