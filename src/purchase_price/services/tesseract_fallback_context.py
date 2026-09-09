from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager

from purchase_price.services.tesseract_runtime import (
    TesseractRuntimeError,
    configured_pytesseract,
    resolve_tesseract_runtime,
)


class FallbackOcrRuntimeUnavailable(RuntimeError):
    pass


@contextmanager
def configured_fallback_ocr_runtime(
    languages: str = "kor+eng",
) -> Generator[None, None, None]:
    """Bind direct pytesseract fallback calls to the resolved system/bundled runtime.

    Older bounded fallback modules call `pytesseract.image_to_string` directly. Holding the same
    configured-pytesseract lock around the whole fallback call makes those paths use the exact
    executable and tessdata resolved for Production, including the apt-independent bundled runtime.
    """

    try:
        import pytesseract
    except ImportError as exc:
        raise FallbackOcrRuntimeUnavailable("pytesseract를 불러올 수 없습니다.") from exc

    required = tuple(part.strip() for part in languages.split("+") if part.strip())
    try:
        runtime = resolve_tesseract_runtime(required)
    except TesseractRuntimeError as exc:
        raise FallbackOcrRuntimeUnavailable(str(exc)) from exc

    previous_tessdata = os.environ.get("TESSDATA_PREFIX")
    try:
        with configured_pytesseract(pytesseract, runtime):
            if runtime.tessdata_dir is not None:
                os.environ["TESSDATA_PREFIX"] = str(runtime.tessdata_dir)
            yield
    finally:
        if previous_tessdata is None:
            os.environ.pop("TESSDATA_PREFIX", None)
        else:
            os.environ["TESSDATA_PREFIX"] = previous_tessdata
