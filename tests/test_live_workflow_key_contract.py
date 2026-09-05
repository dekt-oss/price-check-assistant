from __future__ import annotations

import re
from pathlib import Path

_G2B_WORKFLOWS = (
    Path(".github/workflows/g2b-live-smoke.yml"),
    Path(".github/workflows/g2b-ground-truth-capture.yml"),
    Path(".github/workflows/phase0-live-validation.yml"),
)
_MFDS_WORKFLOW = Path(".github/workflows/mfds-live-validation.yml")
_G2B_RESOLUTION = (
    "secrets.G2B_SERVICE_KEY || secrets.DATA_GO_KR_MARKET_SERVICE_KEY || "
    "secrets.DATA_GO_KR_SERVICE_KEY"
)
_MFDS_RESOLUTION = (
    "secrets.MFDS_SERVICE_KEY || secrets.DATA_GO_KR_MARKET_SERVICE_KEY || "
    "secrets.DATA_GO_KR_SERVICE_KEY"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _assert_manual_only(text: str) -> None:
    assert "workflow_dispatch:" in text
    assert re.search(r"^  (?:push|pull_request):", text, flags=re.MULTILINE) is None


def test_g2b_live_workflows_keep_shared_market_key_fallback_and_manual_trigger() -> None:
    for path in _G2B_WORKFLOWS:
        text = _read(path)
        _assert_manual_only(text)
        assert _G2B_RESOLUTION in text
        assert "DATA_GO_KR_MARKET_SERVICE_KEY" in text
        assert "Verify G2B secret" in text


def test_mfds_live_workflow_keeps_shared_market_key_fallback_and_manual_trigger() -> None:
    text = _read(_MFDS_WORKFLOW)

    _assert_manual_only(text)
    assert _MFDS_RESOLUTION in text
    assert "DATA_GO_KR_MARKET_SERVICE_KEY" in text
    assert "Verify MFDS secret" in text
    assert "run_mfds_live_validation" in text


def test_live_workflow_shell_arguments_use_quoted_environment_inputs() -> None:
    g2b_smoke = _read(Path(".github/workflows/g2b-live-smoke.yml"))
    capture = _read(Path(".github/workflows/g2b-ground-truth-capture.yml"))
    mfds = _read(_MFDS_WORKFLOW)

    assert '--param "inqryBgnDate=$INPUT_BEGIN_DATE"' in g2b_smoke
    assert '--param "inqryEndDate=$INPUT_END_DATE"' in g2b_smoke
    assert '--param "dtilPrdctClsfcNoNm=$INPUT_DETAIL_PRODUCT_NAME"' in g2b_smoke
    assert '--begin-date "$INPUT_BEGIN_DATE"' in capture
    assert '--end-date "$INPUT_END_DATE"' in capture
    assert '--product-name "$INPUT_PRODUCT_NAME"' in mfds
    assert '--model-name "$INPUT_MODEL_NAME"' in mfds
    assert '--company-name "$INPUT_COMPANY_NAME"' in mfds


def test_env_example_documents_shared_market_key() -> None:
    env_example = _read(Path(".env.example"))

    assert "DATA_GO_KR_MARKET_SERVICE_KEY=" in env_example
    assert "source-specific > DATA_GO_KR_MARKET_SERVICE_KEY > legacy common key" in env_example
