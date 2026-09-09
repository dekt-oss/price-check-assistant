from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from purchase_price.services.pdf_ocr import _ocr_words_and_text
from purchase_price.services.pdf_word_geometry import extract_word_geometry_rows_from_words
from purchase_price.services.tesseract_runtime import (
    TesseractRuntimeError,
    configured_pytesseract,
    resolve_tesseract_runtime,
)

_DEFAULT_LANGUAGES = "kor+eng"
_OCR_TIMEOUT_SECONDS = 30


class ImageOcrUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class ImageOcrResult:
    text: str
    table_rows: tuple[tuple[object, ...], ...]
    warnings: tuple[str, ...]


def _required_languages(languages: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in languages.split("+") if part.strip())


def ocr_pil_image_text(
    image,
    *,
    languages: str = _DEFAULT_LANGUAGES,
    psm: int = 11,
) -> str:
    """OCR a Pillow image through the same resolved/bundled Tesseract runtime as PDF OCR."""

    try:
        import pytesseract
    except ImportError as exc:
        raise ImageOcrUnavailableError("pytesseract를 불러올 수 없습니다.") from exc
    try:
        runtime = resolve_tesseract_runtime(_required_languages(languages))
    except TesseractRuntimeError as exc:
        raise ImageOcrUnavailableError(
            f"로컬 Tesseract OCR 런타임을 준비할 수 없습니다: {exc}"
        ) from exc
    try:
        with configured_pytesseract(
            pytesseract,
            runtime,
            base_config=f"--psm {psm}",
        ) as config:
            return pytesseract.image_to_string(
                image,
                lang=languages,
                config=config,
                timeout=_OCR_TIMEOUT_SECONDS,
            )
    except Exception as exc:
        raise ImageOcrUnavailableError("로컬 이미지 OCR 실행에 실패했습니다.") from exc


def run_local_image_ocr(
    path: Path,
    resolve_header: Callable[[str], str | None],
    *,
    languages: str = _DEFAULT_LANGUAGES,
) -> ImageOcrResult:
    """OCR one PNG/JPEG quotation locally and reconstruct conservative table rows.

    The image and recognized text remain local to the app runtime. EXIF orientation is normalized
    before OCR so phone photos exported with rotation metadata are handled consistently.
    """

    try:
        import pytesseract
        from PIL import Image, ImageOps
        from pytesseract import Output
    except ImportError as exc:
        raise ImageOcrUnavailableError(
            "이미지 OCR Python 모듈(Pillow/pytesseract)을 불러올 수 없습니다."
        ) from exc

    try:
        runtime = resolve_tesseract_runtime(_required_languages(languages))
    except TesseractRuntimeError as exc:
        raise ImageOcrUnavailableError(
            f"로컬 Tesseract OCR 런타임을 준비할 수 없습니다: {exc}"
        ) from exc

    try:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            with configured_pytesseract(
                pytesseract,
                runtime,
                base_config="--psm 6",
            ) as config:
                data = pytesseract.image_to_data(
                    image,
                    lang=languages,
                    config=config,
                    output_type=Output.DICT,
                    timeout=_OCR_TIMEOUT_SECONDS,
                )
    except Exception as exc:
        raise ImageOcrUnavailableError(
            "이미지 견적 로컬 OCR 실행에 실패했습니다. 이미지 파일과 OCR 런타임을 확인하세요."
        ) from exc

    words, text = _ocr_words_and_text(data)
    table_rows = extract_word_geometry_rows_from_words(
        words,
        resolve_header,
        y_tolerance=10.0,
    )
    warnings: list[str] = []
    if not text.strip():
        warnings.append("이미지 OCR을 실행했지만 인식 가능한 텍스트를 찾지 못했습니다.")
    return ImageOcrResult(
        text=text,
        table_rows=table_rows,
        warnings=tuple(warnings),
    )
