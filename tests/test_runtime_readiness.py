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
    assert all("secret 값은 표시하지 않음" in check.detail for check in checks)


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


def test_ocr_readiness_reports_missing_binary_without_running_subprocess(monkeypatch) -> None:
    monkeypatch.setattr(runtime_readiness.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setattr(runtime_readiness.shutil, "which", lambda _: None)

    check = runtime_readiness.ocr_runtime_readiness()

    assert check.ready is False
    assert "Tesseract 실행파일" in check.detail


def test_ocr_readiness_requires_korean_and_english_language_packs(monkeypatch) -> None:
    monkeypatch.setattr(runtime_readiness.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setattr(runtime_readiness.shutil, "which", lambda _: "/usr/bin/tesseract")

    def fake_run(command, **_: object):
        if command[-1] == "--version":
            return SimpleNamespace(stdout="tesseract 5.3.4\n leptonica-1.82")
        return SimpleNamespace(stdout="List of available languages in /tmp (1):\neng\n")

    monkeypatch.setattr(runtime_readiness.subprocess, "run", fake_run)

    check = runtime_readiness.ocr_runtime_readiness()

    assert check.ready is False
    assert "5.3.4" in check.detail
    assert "kor" in check.detail


def test_ocr_readiness_reports_ready_for_real_required_language_set(monkeypatch) -> None:
    monkeypatch.setattr(runtime_readiness.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setattr(runtime_readiness.shutil, "which", lambda _: "/usr/bin/tesseract")

    def fake_run(command, **_: object):
        if command[-1] == "--version":
            return SimpleNamespace(stdout="tesseract 5.3.4\n leptonica-1.82")
        return SimpleNamespace(
            stdout="List of available languages in /usr/share/tesseract-ocr/5/tessdata/ (3):\neng\nkor\nosd\n"
        )

    monkeypatch.setattr(runtime_readiness.subprocess, "run", fake_run)

    check = runtime_readiness.ocr_runtime_readiness()

    assert check.ready is True
    assert check.status == runtime_readiness.READY
    assert "Tesseract 5.3.4" in check.detail
    assert "kor+eng" in check.detail


def test_runtime_readiness_makes_no_network_call_and_returns_three_public_checks(monkeypatch) -> None:
    settings = Settings(
        data_go_kr_service_key=None,
        data_go_kr_market_service_key="shared-secret",
    )
    monkeypatch.setattr(runtime_readiness.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setattr(runtime_readiness.shutil, "which", lambda _: None)

    checks = runtime_readiness.runtime_readiness(settings)

    assert [check.key for check in checks] == [
        "g2b_credential",
        "mfds_credential",
        "local_ocr",
    ]
    assert "shared-secret" not in repr([check.to_public_dict() for check in checks])
