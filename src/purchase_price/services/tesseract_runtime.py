from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx

_TESSDATA_FAST_VERSION = "4.1.0"
_KOR_FILENAME = "kor.traineddata"
_KOR_URL = (
    "https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/"
    f"{_TESSDATA_FAST_VERSION}/{_KOR_FILENAME}"
)
_KOR_SHA512 = (
    "ca22e6229b66c3b614876275823a6582483d4701992975197ea5a29144b0b660"
    "dbf662a63552dd41bbd56a1c0e1ce5d50a68d69fdf0cda4948e87c92a0813b51"
)
_MAX_LANGUAGE_MODEL_BYTES = 4 * 1024 * 1024
_DOWNLOAD_TIMEOUT_SECONDS = 20.0
_PYTESSERACT_LOCK = threading.RLock()


class TesseractRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class TesseractRuntime:
    command: str
    tessdata_dir: Path | None
    source: str
    version: str
    languages: tuple[str, ...]


def _command_output(command: list[str], *, timeout: float = 8.0) -> str:
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TesseractRuntimeError(
            f"Tesseract 명령 실행 실패: {type(exc).__name__}"
        ) from exc
    return result.stdout


def _version(command: str) -> str:
    first_line = _command_output([command, "--version"]).strip().splitlines()
    if not first_line:
        return "unknown"
    fields = first_line[0].split()
    return fields[1] if len(fields) >= 2 else "unknown"


def _languages(command: str, tessdata_dir: Path | None = None) -> tuple[str, ...]:
    args = [command]
    if tessdata_dir is not None:
        args.extend(["--tessdata-dir", str(tessdata_dir)])
    args.append("--list-langs")
    lines = _command_output(args).splitlines()
    languages = sorted(
        line.strip()
        for line in lines
        if line.strip() and not line.lower().startswith("list of available languages")
    )
    return tuple(languages)


def _contains_required(languages: Iterable[str], required: tuple[str, ...]) -> bool:
    return set(required).issubset(set(languages))


def _writable_cache_dir() -> Path:
    explicit = (os.getenv("PRICE_CHECK_OCR_TESSDATA_DIR") or "").strip()
    candidates = (
        [Path(explicit)]
        if explicit
        else [
            Path.home() / ".cache" / "price-check-assistant" / "tessdata",
            Path(tempfile.gettempdir()) / "price-check-assistant" / "tessdata",
        ]
    )
    errors: list[str] = []
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except OSError as exc:
            errors.append(f"{candidate}: {type(exc).__name__}")
    raise TesseractRuntimeError(
        "OCR 언어모델 캐시 디렉터리를 준비할 수 없습니다: " + "; ".join(errors)
    )


def _sha512(path: Path) -> str:
    digest = hashlib.sha512()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_atomic(source: Path, destination: Path) -> None:
    if destination.exists() and destination.stat().st_size == source.stat().st_size:
        return
    with tempfile.NamedTemporaryFile(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, delete=False
    ) as handle:
        temp_path = Path(handle.name)
    try:
        shutil.copyfile(source, temp_path)
        os.replace(temp_path, destination)
    finally:
        temp_path.unlink(missing_ok=True)


def _download_korean_model(destination: Path) -> None:
    if destination.exists() and _sha512(destination) == _KOR_SHA512:
        return
    destination.unlink(missing_ok=True)

    with tempfile.NamedTemporaryFile(
        prefix=f".{destination.name}.", suffix=".download", dir=destination.parent, delete=False
    ) as handle:
        temp_path = Path(handle.name)

    try:
        digest = hashlib.sha512()
        total = 0
        try:
            with httpx.stream(
                "GET",
                _KOR_URL,
                follow_redirects=True,
                timeout=_DOWNLOAD_TIMEOUT_SECONDS,
            ) as response:
                response.raise_for_status()
                with temp_path.open("wb") as output:
                    for chunk in response.iter_bytes():
                        if not chunk:
                            continue
                        total += len(chunk)
                        if total > _MAX_LANGUAGE_MODEL_BYTES:
                            raise TesseractRuntimeError(
                                "Korean OCR 언어모델 응답이 예상 크기를 초과했습니다."
                            )
                        digest.update(chunk)
                        output.write(chunk)
        except (httpx.HTTPError, OSError) as exc:
            raise TesseractRuntimeError(
                "Korean OCR 언어모델을 내려받지 못했습니다. 네트워크 상태를 확인하세요."
            ) from exc

        if digest.hexdigest() != _KOR_SHA512:
            raise TesseractRuntimeError(
                "Korean OCR 언어모델 무결성 검증에 실패했습니다. 파일을 사용하지 않습니다."
            )
        os.replace(temp_path, destination)
    finally:
        temp_path.unlink(missing_ok=True)


def _system_runtime(required: tuple[str, ...]) -> TesseractRuntime | None:
    command = shutil.which("tesseract")
    if not command:
        return None
    try:
        languages = _languages(command)
        version = _version(command)
    except TesseractRuntimeError:
        return None
    if not _contains_required(languages, required):
        return None
    return TesseractRuntime(
        command=command,
        tessdata_dir=None,
        source="system",
        version=version,
        languages=languages,
    )


def _bundled_runtime(required: tuple[str, ...]) -> TesseractRuntime:
    try:
        from tesseract_bin import TESSDATA_PREFIX, TESSERACT_PATH
    except ImportError as exc:
        raise TesseractRuntimeError(
            "apt-independent Tesseract binary package(tesseract-bin)를 불러올 수 없습니다."
        ) from exc

    command_path = Path(TESSERACT_PATH)
    source_tessdata = Path(TESSDATA_PREFIX)
    if not command_path.is_file():
        raise TesseractRuntimeError("번들 Tesseract 실행파일을 찾지 못했습니다.")

    cache_dir = _writable_cache_dir()
    for language in required:
        destination = cache_dir / f"{language}.traineddata"
        bundled_model = source_tessdata / f"{language}.traineddata"
        if bundled_model.is_file():
            _copy_atomic(bundled_model, destination)
            continue
        if language == "kor":
            _download_korean_model(destination)
            continue
        raise TesseractRuntimeError(
            f"필수 OCR 언어모델을 준비할 수 없습니다: {language}"
        )

    command = str(command_path)
    languages = _languages(command, cache_dir)
    if not _contains_required(languages, required):
        missing = sorted(set(required) - set(languages))
        raise TesseractRuntimeError(
            "번들 Tesseract에서 필수 OCR 언어를 확인하지 못했습니다: " + ", ".join(missing)
        )
    return TesseractRuntime(
        command=command,
        tessdata_dir=cache_dir,
        source="python-bundled",
        version=_version(command),
        languages=languages,
    )


def resolve_tesseract_runtime(
    required_languages: tuple[str, ...] = ("eng", "kor"),
) -> TesseractRuntime:
    """Resolve a usable local OCR runtime without making Streamlit apt a hard dependency.

    `auto` prefers a fully configured system Tesseract and falls back to the pinned
    Python-bundled executable. `bundled` is used by CI to prove the same path used when
    Streamlit Community Cloud cannot install OS packages.
    """

    mode = (os.getenv("PRICE_CHECK_TESSERACT_MODE") or "auto").strip().casefold()
    if mode not in {"auto", "system", "bundled"}:
        raise TesseractRuntimeError(
            "PRICE_CHECK_TESSERACT_MODE는 auto/system/bundled 중 하나여야 합니다."
        )
    required = tuple(dict.fromkeys(language.strip() for language in required_languages if language))
    if not required:
        raise TesseractRuntimeError("필수 OCR 언어가 지정되지 않았습니다.")

    if mode in {"auto", "system"}:
        runtime = _system_runtime(required)
        if runtime is not None:
            return runtime
        if mode == "system":
            raise TesseractRuntimeError(
                "system Tesseract 또는 필수 kor/eng 언어팩을 사용할 수 없습니다."
            )
    return _bundled_runtime(required)


def pytesseract_config(runtime: TesseractRuntime, base_config: str = "") -> str:
    parts: list[str] = []
    if runtime.tessdata_dir is not None:
        path = str(runtime.tessdata_dir)
        if '"' in path:
            raise TesseractRuntimeError("OCR tessdata 경로에 지원하지 않는 따옴표가 포함되어 있습니다.")
        parts.append(f'--tessdata-dir "{path}"')
    if base_config.strip():
        parts.append(base_config.strip())
    return " ".join(parts)


@contextmanager
def configured_pytesseract(
    pytesseract_module: object,
    runtime: TesseractRuntime,
    *,
    base_config: str = "",
) -> Generator[str, None, None]:
    """Temporarily bind pytesseract to the resolved executable under a process lock."""

    engine = getattr(pytesseract_module, "pytesseract", pytesseract_module)
    if not hasattr(engine, "tesseract_cmd"):
        raise TesseractRuntimeError("pytesseract 실행 설정을 찾을 수 없습니다.")
    with _PYTESSERACT_LOCK:
        previous = engine.tesseract_cmd
        engine.tesseract_cmd = runtime.command
        try:
            yield pytesseract_config(runtime, base_config)
        finally:
            engine.tesseract_cmd = previous
