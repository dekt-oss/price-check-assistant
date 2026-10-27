"""The weekly OCR smoke reaches the UAT upload page by URL, not through the hidden admin menu."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "production_scan_ocr_smoke.py"


def _smoke():
    spec = importlib.util.spec_from_file_location("production_scan_ocr_smoke", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_smoke_opens_the_registered_uat_url_directly() -> None:
    smoke = _smoke()

    assert smoke.uat_url("https://example.test/") == "https://example.test/quote-extraction-uat"
    assert smoke.uat_url("https://example.test") == "https://example.test/quote-extraction-uat"
    home = (ROOT / "Home.py").read_text(encoding="utf-8")
    assert f'url_path="{smoke.UAT_URL_PATH}"' in home


def test_smoke_does_not_wait_for_the_admin_only_menu_link() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'get_by_role("link"' not in source
    assert "failure_stage" in source


def test_entry_failure_is_reported_apart_from_ocr_failure() -> None:
    smoke = _smoke()

    error = smoke.SmokeStageError("entry", "timed out")
    assert error.stage == "entry"
    assert str(error) == "entry: timed out"
