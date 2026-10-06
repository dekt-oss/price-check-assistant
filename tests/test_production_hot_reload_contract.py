from pathlib import Path


def test_dashboard_does_not_direct_import_hot_added_business_lookup_symbol() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "lookup_mfds_business_license," not in source
    assert "from purchase_price.services import mfds_workspace as mfds_workspace_service" in source
    assert 'getattr(mfds_workspace_service, "lookup_mfds_business_license", None)' in source
    assert "업허가 조회 기능을 지금 쓸 수 없습니다" in source
