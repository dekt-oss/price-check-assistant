from __future__ import annotations

from types import SimpleNamespace

from purchase_price.config import Settings
from purchase_price.services import runtime_readiness
from purchase_price.services.tesseract_runtime import TesseractRuntime


def test_shared_market_key_marks_all_public_data_sources_ready_without_exposing_value() -> None:
    secret = "SHARED-SUPER-SECRET"
    settings = Settings(
        data_go_kr_service_key=None,
        data_go_kr_market_service_key=secret,
        g2b_service_key=None,
        g2b_shopping_service_key=None,
        g2b_research_service_key=None,
        mfds_service_key=None,
    )
    checks = runtime_readiness.public_data_credential_readiness(settings)
    public_payload = repr([check.to_public_dict() for check in checks])
    assert all(check.ready for check in checks)
    assert {check.key for check in checks} == {
        "g2b_credential",
        "g2b_research_credential",
        "mfds_credential",
    }
    assert secret not in public_payload
    assert "DATA_GO_KR_MARKET_SERVICE_KEY" in public_payload


def test_historical_g2b_key_can_make_both_g2b_families_ready_without_mfds() -> None:
    settings = Settings(
        data_go_kr_service_key=None,
        data_go_kr_market_service_key=None,
        g2b_service_key="g2b-only-secret",
        g2b_shopping_service_key=None,
        g2b_research_service_key=None,
        mfds_service_key=None,
    )
    shopping, research, mfds = runtime_readiness.public_data_credential_readiness(settings)
    assert shopping.ready is True
    assert research.ready is True
    assert mfds.ready is False
    assert "g2b-only-secret" not in repr([shopping.to_public_dict(), research.to_public_dict()])
    assert "G2B_SERVICE_KEY" in shopping.detail
    assert "G2B_SERVICE_KEY" in research.detail


def test_dedicated_research_key_is_reported_independently() -> None:
    settings = Settings(
        data_go_kr_service_key=None,
        data_go_kr_market_service_key=None,
        g2b_service_key=None,
        g2b_shopping_service_key=None,
        g2b_research_service_key="research-secret",
        mfds_service_key=None,
    )
    shopping, research, _mfds = runtime_readiness.public_data_credential_readiness(settings)
    assert shopping.ready is False
    assert research.ready is True
    assert "G2B_RESEARCH_SERVICE_KEY" in research.detail
    assert "research-secret" not in research.detail


def _installed_packages(monkeypatch) -> None:
    monkeypatch.setattr(runtime_readiness.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setattr(runtime_readiness, "_package_version", lambda _: "1.0")


def _ready_runtime() -> TesseractRuntime:
    return TesseractRuntime(
        command="/opt/python/tesseract",
        tessdata_dir=None,
        source="python-bundled",
        version="5.5.0",
        languages=("eng", "kor"),
    )


def test_ocr_stages_report_missing_runtime_without_hiding_python_modules(monkeypatch) -> None:
    _installed_packages(monkeypatch)
    monkeypatch.setattr(
        runtime_readiness,
        "_resolve_ocr_runtime",
        lambda: (None, "runtime unavailable"),
    )
    by_key = {
        check.key: check for check in runtime_readiness.ocr_runtime_readiness_checks()
    }
    assert by_key["ocr_python_modules"].ready is True
    assert by_key["ocr_tesseract_binary"].ready is False
    assert by_key["ocr_languages"].ready is False
    assert by_key["ocr_execution"].ready is False


def _mock_ready_runtime(monkeypatch) -> None:
    _installed_packages(monkeypatch)
    monkeypatch.setattr(
        runtime_readiness,
        "_resolve_ocr_runtime",
        lambda: (_ready_runtime(), ""),
    )


def test_ocr_readiness_requires_real_execution_after_dependencies(monkeypatch) -> None:
    _mock_ready_runtime(monkeypatch)
    monkeypatch.setattr(
        runtime_readiness,
        "_run_synthetic_ocr_execution",
        lambda: (False, "execution failed: RuntimeError"),
    )
    assert runtime_readiness.ocr_runtime_readiness().ready is False


def test_ocr_readiness_reports_ready_only_after_synthetic_execution(monkeypatch) -> None:
    _mock_ready_runtime(monkeypatch)
    monkeypatch.setattr(
        runtime_readiness, "_run_synthetic_ocr_execution", lambda: (True, "ok")
    )
    readiness = runtime_readiness.ocr_runtime_readiness()
    assert readiness.ready is True
    assert "python-bundled" in readiness.detail


def test_build_identity_uses_environment_commit(monkeypatch) -> None:
    monkeypatch.setenv("COMMIT_SHA", "1234567890abcdef")
    check = runtime_readiness.build_identity_readiness()
    assert check.ready is True
    assert "source=COMMIT_SHA" in check.detail


def test_build_identity_falls_back_to_git(monkeypatch) -> None:
    for key in ("STREAMLIT_GIT_COMMIT", "GIT_COMMIT", "COMMIT_SHA"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        runtime_readiness.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="abcdef1234567890\n"),
    )
    check = runtime_readiness.build_identity_readiness()
    assert check.ready is True
    assert "source=git" in check.detail


def test_build_identity_unknown_is_unavailable(monkeypatch) -> None:
    for key in ("STREAMLIT_GIT_COMMIT", "GIT_COMMIT", "COMMIT_SHA"):
        monkeypatch.delenv(key, raising=False)

    def fail(*args, **kwargs):
        raise OSError("git unavailable")

    monkeypatch.setattr(runtime_readiness.subprocess, "run", fail)
    check = runtime_readiness.build_identity_readiness()
    assert check.ready is False
    assert check.status == runtime_readiness.UNAVAILABLE
    assert "commit=unknown" in check.detail
