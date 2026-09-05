from __future__ import annotations

from types import SimpleNamespace

from purchase_price.config import Settings
from purchase_price.services import runtime_readiness


def test_shared_market_key_marks_both_public_data_sources_ready_without_exposing_value() -> None:
    secret = "SHARED-SUPER-SECRET"
    settings = Settings(
        data_go_kr_service_key=None,
        data_go_kr_market_service_key=secret,
        g2b_service_key=None,
        mfds_service_key=None,
    )
    checks = runtime_readiness.public_data_credential_readiness(settings)
    public_payload = repr([check.to_public_dict() for check in checks])
    assert all(check.ready for check in checks)
    assert {check.key for check in checks} == {"g2b_credential", "mfds_credential"}
    assert secret not in public_payload


def test_source_specific_key_can_make_only_one_source_ready() -> None:
    settings = Settings(
        data_go_kr_service_key=None,
        data_go_kr_market_service_key=None,
        g2b_service_key="g2b-only-secret",
        mfds_service_key=None,
    )
    g2b, mfds = runtime_readiness.public_data_credential_readiness(settings)
    assert g2b.ready is True
    assert mfds.ready is False
    assert "g2b-only-secret" not in repr(g2b.to_public_dict())


def _installed_packages(monkeypatch) -> None:
    monkeypatch.setattr(runtime_readiness.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setattr(runtime_readiness, "_package_version", lambda _: "1.0")


def test_ocr_stages_report_missing_binary_without_hiding_python_modules(monkeypatch) -> None:
    _installed_packages(monkeypatch)
    monkeypatch.setattr(runtime_readiness.shutil, "which", lambda _: None)
    checks = runtime_readiness.ocr_runtime_readiness_checks()
    by_key = {check.key: check for check in checks}
    assert by_key["ocr_python_modules"].ready is True
    assert by_key["ocr_tesseract_binary"].ready is False
    assert by_key["ocr_languages"].ready is False


def test_ocr_readiness_requires_korean_and_english_language_packs(monkeypatch) -> None:
    _installed_packages(monkeypatch)
    monkeypatch.setattr(runtime_readiness.shutil, "which", lambda _: "/usr/bin/tesseract")

    def fake_run(command, **_: object):
        if command[-1] == "--version":
            return SimpleNamespace(stdout="tesseract 5.3.4\n leptonica-1.82")
        return SimpleNamespace(stdout="List of available languages in /tmp (1):\neng\n")

    monkeypatch.setattr(runtime_readiness.subprocess, "run", fake_run)
    check = runtime_readiness.ocr_runtime_readiness()
    assert check.ready is False
    assert "kor" in check.detail


def test_ocr_readiness_reports_ready_for_real_required_language_set(monkeypatch) -> None:
    _installed_packages(monkeypatch)
    monkeypatch.setattr(runtime_readiness.shutil, "which", lambda _: "/usr/bin/tesseract")

    def fake_run(command, **_: object):
        if command[-1] == "--version":
            return SimpleNamespace(stdout="tesseract 5.3.4\n leptonica-1.82")
        return SimpleNamespace(
            stdout="List of available languages in /usr/share/tessdata (3):\neng\nkor\nosd\n"
        )

    monkeypatch.setattr(runtime_readiness.subprocess, "run", fake_run)
    check = runtime_readiness.ocr_runtime_readiness()
    assert check.ready is True
    assert check.status == runtime_readiness.READY
    assert "kor+eng" in check.detail


def test_runtime_readiness_exposes_build_identity_and_all_ocr_stages(monkeypatch) -> None:
    settings = Settings(
        data_go_kr_service_key=None,
        data_go_kr_market_service_key="shared-secret",
    )
    _installed_packages(monkeypatch)
    monkeypatch.setattr(runtime_readiness.shutil, "which", lambda _: None)
    monkeypatch.setenv("COMMIT_SHA", "1234567890abcdef")
    checks = runtime_readiness.runtime_readiness(settings)
    keys = [check.key for check in checks]
    assert keys == [
        "build_identity",
        "g2b_credential",
        "mfds_credential",
        "ocr_python_modules",
        "ocr_tesseract_binary",
        "ocr_tesseract_command",
        "ocr_languages",
    ]
    assert "1234567890ab" in checks[0].detail
    assert "shared-secret" not in repr([check.to_public_dict() for check in checks])
