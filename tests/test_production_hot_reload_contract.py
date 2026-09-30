from pathlib import Path


def test_dashboard_does_not_direct_import_hot_added_business_lookup_symbol() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "lookup_mfds_business_license," not in source
    assert "from purchase_price.services import mfds_workspace as mfds_workspace_service" in source
    assert 'getattr(\n                    mfds_workspace_service,\n                    "lookup_mfds_business_license",' in source
    assert "배포 프로세스가 이전 식약처 모듈을 유지" in source
