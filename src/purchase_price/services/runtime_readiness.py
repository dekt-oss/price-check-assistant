from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import platform
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
        return RuntimeReadinessCheck(key, label, READY, "설정됨 (secret 값은 표시하지 않음)")
    return RuntimeReadinessCheck(key, label, UNAVAILABLE, "미설정 — live API 호출 불가")


def public_data_credential_readiness(
    settings: Settings | None = None,
) -> tuple[RuntimeReadinessCheck, RuntimeReadinessCheck]:
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


def build_identity_readiness() -> RuntimeReadinessCheck:
    commit = (
        os.getenv("STREAMLIT_GIT_COMMIT")
        or os.getenv("GIT_COMMIT")
        or os.getenv("COMMIT_SHA")
        or "unknown"
    )
    return RuntimeReadinessCheck(
        "build_identity",
        "실행 환경",
        READY,
        f"commit={commit[:12]}; Python {platform.python_version()}",
    )


def _package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _tesseract_version_line(stdout: str) -> str:
    first_line = stdout.strip().splitlines()[0] if stdout.strip() else ""
    match = re.search(r"tesseract\s+([^\s]+)", first_line, flags=re.IGNORECASE)
    return match.group(1) if match else "unknown"


def ocr_runtime_readiness_checks() -> tuple[RuntimeReadinessCheck, ...]:
    """Return all OCR dependency stages without reading user documents or using network."""
    module_details = []
    missing_modules = []
    for name in ("pypdfium2", "pytesseract"):
        version = _package_version(name)
        if importlib.util.find_spec(name) is None:
            missing_modules.append(name)
            module_details.append(f"{name}=missing")
        else:
            module_details.append(f"{name}={version or 'installed'}")
    module_check = RuntimeReadinessCheck(
        "ocr_python_modules",
        "OCR Python 모듈",
        READY if not missing_modules else UNAVAILABLE,
        "; ".join(module_details),
    )

    executable = shutil.which("tesseract")
    binary_check = RuntimeReadinessCheck(
        "ocr_tesseract_binary",
        "Tesseract 실행파일",
        READY if executable else UNAVAILABLE,
        executable or "실행파일을 찾지 못함",
    )
    version = "unknown"
    languages: set[str] = set()
    command_error: str | None = None
    if executable:
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
            version = _tesseract_version_line(version_result.stdout)
            languages = {
                line.strip()
                for line in language_result.stdout.splitlines()
                if line.strip()
                and not line.lower().startswith("list of available languages")
            }
        except (OSError, subprocess.SubprocessError) as exc:
            command_error = type(exc).__name__

    if not executable:
        command_check = RuntimeReadinessCheck(
            "ocr_tesseract_command", "Tesseract 상태", UNAVAILABLE, "실행파일 없음"
        )
    elif command_error:
        command_check = RuntimeReadinessCheck(
            "ocr_tesseract_command",
            "Tesseract 상태",
            UNAVAILABLE,
            f"상태 확인 실패: {command_error}",
        )
    else:
        command_check = RuntimeReadinessCheck(
            "ocr_tesseract_command", "Tesseract 상태", READY, f"version={version}"
        )

    required_languages = {"kor", "eng"}
    missing_languages = sorted(required_languages - languages)
    language_ready = bool(executable and not command_error and not missing_languages)
    language_check = RuntimeReadinessCheck(
        "ocr_languages",
        "OCR 언어팩",
        READY if language_ready else UNAVAILABLE,
        "kor+eng 사용 가능"
        if language_ready
        else f"누락: {', '.join(missing_languages) or '확인 불가'}",
    )
    return module_check, binary_check, command_check, language_check


def ocr_runtime_readiness() -> RuntimeReadinessCheck:
    """Compatibility aggregate for callers that expect one local OCR status."""
    checks = ocr_runtime_readiness_checks()
    failed = [check for check in checks if not check.ready]
    if failed:
        return RuntimeReadinessCheck(
            "local_ocr",
            "PDF 로컬 OCR",
            UNAVAILABLE,
            " / ".join(f"{check.label}: {check.detail}" for check in failed),
        )
    version = next(
        (check.detail for check in checks if check.key == "ocr_tesseract_command"),
        "",
    )
    return RuntimeReadinessCheck(
        "local_ocr", "PDF 로컬 OCR", READY, f"{version}; kor+eng 사용 가능"
    )


def runtime_readiness(settings: Settings | None = None) -> tuple[RuntimeReadinessCheck, ...]:
    """Return secret-free local capability checks. No external API request is performed."""
    return (
        build_identity_readiness(),
        *public_data_credential_readiness(settings),
        *ocr_runtime_readiness_checks(),
    )
