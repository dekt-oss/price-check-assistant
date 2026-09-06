from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from purchase_price.config import Settings, get_settings

READY = "READY"
UNAVAILABLE = "UNAVAILABLE"
_OCR_EXECUTION_TOKEN = "OCRREADY123"


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
        return {"key": self.key, "label": self.label, "status": self.status, "ready": self.ready, "detail": self.detail}


def _credential_check(*, key: str, label: str, configured: bool) -> RuntimeReadinessCheck:
    if configured:
        return RuntimeReadinessCheck(key, label, READY, "설정됨 (secret 값은 표시하지 않음)")
    return RuntimeReadinessCheck(key, label, UNAVAILABLE, "미설정 — live API 호출 불가")


def public_data_credential_readiness(settings: Settings | None = None) -> tuple[RuntimeReadinessCheck, RuntimeReadinessCheck]:
    settings = settings or get_settings()
    return (
        _credential_check(key="g2b_credential", label="G2B 인증", configured=bool((settings.resolved_g2b_service_key or "").strip())),
        _credential_check(key="mfds_credential", label="MFDS 인증", configured=bool((settings.resolved_mfds_service_key or "").strip())),
    )


def _resolve_build_commit() -> tuple[str, str]:
    for key in ("STREAMLIT_GIT_COMMIT", "GIT_COMMIT", "COMMIT_SHA"):
        value = (os.getenv(key) or "").strip()
        if value:
            return value, key
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True, timeout=2
        )
        value = result.stdout.strip()
        if value:
            return value, "git"
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown", "none"


def build_identity_readiness() -> RuntimeReadinessCheck:
    commit, source = _resolve_build_commit()
    known = commit != "unknown"
    return RuntimeReadinessCheck(
        "build_identity", "실행 환경", READY if known else UNAVAILABLE,
        f"commit={commit[:12]}; source={source}; Python {platform.python_version()}" if known
        else f"commit=unknown; Python {platform.python_version()} — 배포 버전을 식별할 수 없음",
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


def _run_synthetic_ocr_execution() -> tuple[bool, str]:
    try:
        import pypdfium2 as pdfium
        import pytesseract
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        return False, f"import failed: {type(exc).__name__}"
    with tempfile.TemporaryDirectory(prefix="ocr-readiness-") as temp_dir:
        pdf_path = Path(temp_dir) / "synthetic.pdf"
        image = Image.new("RGB", (1600, 500), "white")
        font = ImageFont.load_default(size=64)
        ImageDraw.Draw(image).text((100, 180), _OCR_EXECUTION_TOKEN, fill="black", font=font)
        image.save(pdf_path, "PDF", resolution=150.0)
        document = page = bitmap = None
        try:
            document = pdfium.PdfDocument(str(pdf_path)); page = document[0]; bitmap = page.render(scale=2.0)
            text = pytesseract.image_to_string(bitmap.to_pil(), lang="eng", config="--psm 6", timeout=10)
        except Exception as exc:
            return False, f"execution failed: {type(exc).__name__}"
        finally:
            for value in (bitmap, page, document):
                closer = getattr(value, "close", None)
                if callable(closer): closer()
    normalized = "".join(c for c in text.upper() if c.isalnum())
    if _OCR_EXECUTION_TOKEN not in normalized:
        return False, "execution completed but synthetic token was not recognized"
    return True, "synthetic PDF rasterize -> Tesseract OCR succeeded"


def _ocr_execution_check(prerequisites_ready: bool) -> RuntimeReadinessCheck:
    if not prerequisites_ready:
        return RuntimeReadinessCheck("ocr_execution", "OCR 실행 검증", UNAVAILABLE, "선행 OCR 구성요소가 준비되지 않아 실행하지 않음")
    ready, detail = _run_synthetic_ocr_execution()
    return RuntimeReadinessCheck("ocr_execution", "OCR 실행 검증", READY if ready else UNAVAILABLE, detail)


def ocr_runtime_readiness_checks() -> tuple[RuntimeReadinessCheck, ...]:
    module_details, missing_modules = [], []
    for name in ("pypdfium2", "pytesseract"):
        version = _package_version(name)
        if importlib.util.find_spec(name) is None:
            missing_modules.append(name); module_details.append(f"{name}=missing")
        else: module_details.append(f"{name}={version or 'installed'}")
    module_check = RuntimeReadinessCheck("ocr_python_modules", "OCR Python 모듈", READY if not missing_modules else UNAVAILABLE, "; ".join(module_details))
    executable = shutil.which("tesseract")
    binary_check = RuntimeReadinessCheck("ocr_tesseract_binary", "Tesseract 실행파일", READY if executable else UNAVAILABLE, executable or "실행파일을 찾지 못함")
    version, languages, command_error = "unknown", set(), None
    if executable:
        try:
            vr = subprocess.run([executable, "--version"], check=True, capture_output=True, text=True, timeout=5)
            lr = subprocess.run([executable, "--list-langs"], check=True, capture_output=True, text=True, timeout=5)
            version = _tesseract_version_line(vr.stdout)
            languages = {line.strip() for line in lr.stdout.splitlines() if line.strip() and not line.lower().startswith("list of available languages")}
        except (OSError, subprocess.SubprocessError) as exc: command_error = type(exc).__name__
    if not executable: command_check = RuntimeReadinessCheck("ocr_tesseract_command", "Tesseract 상태", UNAVAILABLE, "실행파일 없음")
    elif command_error: command_check = RuntimeReadinessCheck("ocr_tesseract_command", "Tesseract 상태", UNAVAILABLE, f"상태 확인 실패: {command_error}")
    else: command_check = RuntimeReadinessCheck("ocr_tesseract_command", "Tesseract 상태", READY, f"version={version}")
    missing_languages = sorted({"kor", "eng"} - languages)
    language_ready = bool(executable and not command_error and not missing_languages)
    language_check = RuntimeReadinessCheck("ocr_languages", "OCR 언어팩", READY if language_ready else UNAVAILABLE, "kor+eng 사용 가능" if language_ready else f"누락: {', '.join(missing_languages) or '확인 불가'}")
    execution_check = _ocr_execution_check(module_check.ready and binary_check.ready and command_check.ready and language_check.ready)
    return module_check, binary_check, command_check, language_check, execution_check


def ocr_runtime_readiness() -> RuntimeReadinessCheck:
    checks = ocr_runtime_readiness_checks(); failed = [check for check in checks if not check.ready]
    if failed:
        return RuntimeReadinessCheck("local_ocr", "PDF 로컬 OCR", UNAVAILABLE, " / ".join(f"{c.label}: {c.detail}" for c in failed))
    version = next((c.detail for c in checks if c.key == "ocr_tesseract_command"), "")
    return RuntimeReadinessCheck("local_ocr", "PDF 로컬 OCR", READY, f"{version}; kor+eng; synthetic execution verified")


def runtime_readiness(settings: Settings | None = None) -> tuple[RuntimeReadinessCheck, ...]:
    return (build_identity_readiness(), *public_data_credential_readiness(settings), *ocr_runtime_readiness_checks())
