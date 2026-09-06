from __future__ import annotations

from types import SimpleNamespace

from purchase_price.config import Settings
from purchase_price.services import runtime_readiness


def test_shared_market_key_marks_both_public_data_sources_ready_without_exposing_value() -> None:
    secret = "SHARED-SUPER-SECRET"
    settings = Settings(data_go_kr_service_key=None, data_go_kr_market_service_key=secret, g2b_service_key=None, mfds_service_key=None)
    checks = runtime_readiness.public_data_credential_readiness(settings)
    public_payload = repr([check.to_public_dict() for check in checks])
    assert all(check.ready for check in checks)
    assert {check.key for check in checks} == {"g2b_credential", "mfds_credential"}
    assert secret not in public_payload


def test_source_specific_key_can_make_only_one_source_ready() -> None:
    settings = Settings(data_go_kr_service_key=None, data_go_kr_market_service_key=None, g2b_service_key="g2b-only-secret", mfds_service_key=None)
    g2b, mfds = runtime_readiness.public_data_credential_readiness(settings)
    assert g2b.ready is True and mfds.ready is False
    assert "g2b-only-secret" not in repr(g2b.to_public_dict())


def _installed_packages(monkeypatch) -> None:
    monkeypatch.setattr(runtime_readiness.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setattr(runtime_readiness, "_package_version", lambda _: "1.0")


def test_ocr_stages_report_missing_binary_without_hiding_python_modules(monkeypatch) -> None:
    _installed_packages(monkeypatch); monkeypatch.setattr(runtime_readiness.shutil, "which", lambda _: None)
    by_key = {check.key: check for check in runtime_readiness.ocr_runtime_readiness_checks()}
    assert by_key["ocr_python_modules"].ready is True
    assert by_key["ocr_tesseract_binary"].ready is False
    assert by_key["ocr_languages"].ready is False
    assert by_key["ocr_execution"].ready is False


def _ready_tesseract(monkeypatch) -> None:
    _installed_packages(monkeypatch); monkeypatch.setattr(runtime_readiness.shutil, "which", lambda _: "/usr/bin/tesseract")
    def fake_run(command, **_: object):
        if command[-1] == "--version": return SimpleNamespace(stdout="tesseract 5.3.4\n")
        return SimpleNamespace(stdout="List of available languages (3):\neng\nkor\nosd\n")
    monkeypatch.setattr(runtime_readiness.subprocess, "run", fake_run)


def test_ocr_readiness_requires_real_execution_after_dependencies(monkeypatch) -> None:
    _ready_tesseract(monkeypatch)
    monkeypatch.setattr(runtime_readiness, "_run_synthetic_ocr_execution", lambda: (False, "execution failed: RuntimeError"))
    assert runtime_readiness.ocr_runtime_readiness().ready is False


def test_ocr_readiness_reports_ready_only_after_synthetic_execution(monkeypatch) -> None:
    _ready_tesseract(monkeypatch)
    monkeypatch.setattr(runtime_readiness, "_run_synthetic_ocr_execution", lambda: (True, "ok"))
    assert runtime_readiness.ocr_runtime_readiness().ready is True


def test_build_identity_uses_environment_commit(monkeypatch) -> None:
    monkeypatch.setenv("COMMIT_SHA", "1234567890abcdef")
    check = runtime_readiness.build_identity_readiness()
    assert check.ready is True
    assert "source=COMMIT_SHA" in check.detail


def test_build_identity_falls_back_to_git(monkeypatch) -> None:
    for key in ("STREAMLIT_GIT_COMMIT", "GIT_COMMIT", "COMMIT_SHA"): monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(runtime_readiness.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(stdout="abcdef1234567890\n"))
    check = runtime_readiness.build_identity_readiness()
    assert check.ready is True
    assert "source=git" in check.detail


def test_build_identity_unknown_is_unavailable(monkeypatch) -> None:
    for key in ("STREAMLIT_GIT_COMMIT", "GIT_COMMIT", "COMMIT_SHA"): monkeypatch.delenv(key, raising=False)
    def fail(*args, **kwargs): raise OSError("git unavailable")
    monkeypatch.setattr(runtime_readiness.subprocess, "run", fail)
    check = runtime_readiness.build_identity_readiness()
    assert check.ready is False
    assert check.status == runtime_readiness.UNAVAILABLE
    assert "commit=unknown" in check.detail
