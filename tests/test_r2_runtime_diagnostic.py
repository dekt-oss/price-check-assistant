from pathlib import Path
from types import SimpleNamespace

from purchase_price.ui import r2_runtime_diagnostic as diagnostic


def test_diagnostic_reports_only_missing_component_names(monkeypatch) -> None:
    fake_settings = SimpleNamespace(
        resolved_r2_endpoint_url=None,
        resolved_r2_bucket_name="bucket",
        r2_access_key_id=None,
        r2_secret_access_key=None,
    )
    monkeypatch.setattr(diagnostic, "Settings", lambda: fake_settings)

    result = diagnostic.diagnose_track_b_r2_runtime()

    assert result.code == "config_missing"
    assert result.detail == "endpoint,access_key,secret_key"
    assert "bucket" not in result.detail


def test_home_exposes_diagnostic_only_behind_query_parameter() -> None:
    source = Path("Home.py").read_text(encoding="utf-8")

    assert 'st.query_params.get("_r2diag", "")' in source
    assert "R2_RUNTIME_DIAGNOSTIC code=" in source
    assert source.index("hydrate_streamlit_runtime_secrets()") < source.index(
        "_render_r2_runtime_diagnostic()"
    )
