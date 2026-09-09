from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from purchase_price.services import tesseract_runtime
from purchase_price.services.tesseract_runtime import (
    TesseractRuntime,
    TesseractRuntimeError,
    pytesseract_config,
    resolve_tesseract_runtime,
)


def _runtime(source: str) -> TesseractRuntime:
    return TesseractRuntime(
        command=f"/{source}/tesseract",
        tessdata_dir=None,
        source=source,
        version="5.5.0",
        languages=("eng", "kor"),
    )


def test_auto_prefers_complete_system_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRICE_CHECK_TESSERACT_MODE", "auto")
    monkeypatch.setattr(tesseract_runtime, "_system_runtime", lambda required: _runtime("system"))

    def bundled_should_not_run(required):
        raise AssertionError("complete system runtime must be preferred")

    monkeypatch.setattr(tesseract_runtime, "_bundled_runtime", bundled_should_not_run)
    assert resolve_tesseract_runtime().source == "system"


def test_auto_falls_back_to_bundled_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRICE_CHECK_TESSERACT_MODE", "auto")
    monkeypatch.setattr(tesseract_runtime, "_system_runtime", lambda required: None)
    monkeypatch.setattr(
        tesseract_runtime,
        "_bundled_runtime",
        lambda required: _runtime("python-bundled"),
    )
    assert resolve_tesseract_runtime().source == "python-bundled"


def test_system_mode_fails_closed_when_kor_eng_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PRICE_CHECK_TESSERACT_MODE", "system")
    monkeypatch.setattr(tesseract_runtime, "_system_runtime", lambda required: None)
    with pytest.raises(TesseractRuntimeError, match="kor/eng"):
        resolve_tesseract_runtime()


class _FakeStreamResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self):
        yield self.payload


def test_korean_model_download_is_hash_verified_and_cached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"verified-korean-traineddata"
    expected = hashlib.sha512(payload).hexdigest()
    monkeypatch.setattr(tesseract_runtime, "_KOR_SHA512", expected)
    calls = 0

    def fake_stream(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _FakeStreamResponse(payload)

    monkeypatch.setattr(tesseract_runtime.httpx, "stream", fake_stream)
    destination = tmp_path / "kor.traineddata"

    tesseract_runtime._download_korean_model(destination)
    tesseract_runtime._download_korean_model(destination)

    assert destination.read_bytes() == payload
    assert calls == 1


def test_korean_model_rejects_unexpected_content(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tesseract_runtime, "_KOR_SHA512", "0" * 128)
    monkeypatch.setattr(
        tesseract_runtime.httpx,
        "stream",
        lambda *_args, **_kwargs: _FakeStreamResponse(b"tampered"),
    )
    destination = tmp_path / "kor.traineddata"

    with pytest.raises(TesseractRuntimeError, match="무결성"):
        tesseract_runtime._download_korean_model(destination)

    assert not destination.exists()


def test_pytesseract_config_pins_resolved_tessdata_directory(tmp_path: Path) -> None:
    runtime = TesseractRuntime(
        command="/bundle/tesseract",
        tessdata_dir=tmp_path,
        source="python-bundled",
        version="5.5.0",
        languages=("eng", "kor"),
    )
    config = pytesseract_config(runtime, "--psm 6")
    assert "--tessdata-dir" in config
    assert str(tmp_path) in config
    assert config.endswith("--psm 6")
