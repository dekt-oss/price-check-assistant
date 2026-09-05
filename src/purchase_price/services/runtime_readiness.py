from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
from dataclasses import dataclass

from purchase_price.config import Settings, get_settings

READY = "READY"
UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class RuntimeReadinessCheck:
    key: str
    label: str
    status: str
    detail: str

    @property
    def ready(self) -> bool:
        return self.status == READY

    def to_public_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "ready": self.ready,
            "detail": self.detail,
        }


def _credential_check(*, key: str, label: str, configured: bool) -> RuntimeReadinessCheck:
    if configured:
        return RuntimeReadinessCheck(
            key=key,
            label=label,
            status=READY,
            detail="설정됨 (secret 값은 표시하지 않음)",
        )
    return RuntimeReadinessCheck(
        key=key,
        label=label,
        status=UNAVAILABLE,
        detail="미설정 — live API 호출 불가",
    )


def public_data_credential_readiness(
    settings: Settings | None = None,
) -> tuple[RuntimeReadinessCheck, RuntimeReadinessCheck]:
    """Report only whether resolved G2B/MFDS credentials exist, never their values."""

    settings = settings or get_settings()
    return (
        _credential_check(
            key="g2b_credential",
            label="G2B 인증",
            configured=bool((settings.resolved_g2b_service_key or "").strip()),
        ),
        _credential_check(
            key="mfds_credential",
            label="MFDS 인증",
            configured=bool((settings.resolved_mfds_service_key or "").strip()),
        ),
    )


def _tesseract_version_line(stdout: str) -> str:
    first_line = stdout.strip().splitlines()[0] if stdout.strip() else ""
    match = re.search(r"tesseract\s+([^\s]+)", first_line, flags=re.IGNORECASE)
    return match.group(1) if match else "unknown"


def ocr_runtime_readiness() -> RuntimeReadinessCheck:
    """Check local OCR dependencies without reading a document or making a network call."""

    missing_modules = [
        name
        for name in ("pypdfium2", "pytesseract")
        if importlib.util.find_spec(name) is None
    ]
    if missing_modules:
        return RuntimeReadinessCheck(
            key="local_ocr",
            label="PDF 로컬 OCR",
            status=UNAVAILABLE,
            detail=f"Python 모듈 미설치: {', '.join(missing_modules)}",
        )

    executable = shutil.which("tesseract")
    if not executable:
        return RuntimeReadinessCheck(
            key="local_ocr",
            label="PDF 로컬 OCR",
            status=UNAVAILABLE,
            detail="Tesseract 실행파일을 찾지 못함",
        )

    try:
        version_result = subprocess.run(
            [executable, "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        language_result = subprocess.run(
            [executable, "--list-langs"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return RuntimeReadinessCheck(
            key="local_ocr",
            label="PDF 로컬 OCR",
            status=UNAVAILABLE,
            detail=f"Tesseract 상태 확인 실패: {type(exc).__name__}",
        )

    languages = {
        line.strip()
        for line in language_result.stdout.splitlines()
        if line.strip() and not line.lower().startswith("list of available languages")
    }
    required_languages = {"kor", "eng"}
    missing_languages = sorted(required_languages - languages)
    version = _tesseract_version_line(version_result.stdout)
    if missing_languages:
        return RuntimeReadinessCheck(
            key="local_ocr",
            label="PDF 로컬 OCR",
            status=UNAVAILABLE,
            detail=(
                f"Tesseract {version}; language pack 누락: {', '.join(missing_languages)}"
            ),
        )

    return RuntimeReadinessCheck(
        key="local_ocr",
        label="PDF 로컬 OCR",
        status=READY,
        detail=f"Tesseract {version}; kor+eng 사용 가능",
    )


def runtime_readiness(settings: Settings | None = None) -> tuple[RuntimeReadinessCheck, ...]:
    """Return secret-free local capability checks. No external API request is performed."""

    return (*public_data_credential_readiness(settings), ocr_runtime_readiness())
