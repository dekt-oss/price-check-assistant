from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from purchase_price.services.pdf_word_geometry import extract_word_geometry_rows_from_words

_DEFAULT_DPI = 220
_DEFAULT_LANGUAGES = "kor+eng"
_MAX_OCR_PAGES = 12
_OCR_TIMEOUT_SECONDS = 30


class PdfOcrUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class PdfOcrPage:
    page_number: int
    text: str
    table_rows: tuple[tuple[object, ...], ...]


@dataclass(frozen=True)
class PdfOcrResult:
    pages: tuple[PdfOcrPage, ...]
    warnings: tuple[str, ...]

    @property
    def saw_text(self) -> bool:
        return any(page.text.strip() for page in self.pages)


def _as_sequence(data: Mapping[str, object], key: str) -> Sequence[object]:
    value = data.get(key)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return value
    return ()


def _item(values: Sequence[object], index: int, default: object = "") -> object:
    return values[index] if index < len(values) else default


def _int_value(value: object, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _ocr_words_and_text(data: Mapping[str, object]) -> tuple[list[dict[str, object]], str]:
    texts = _as_sequence(data, "text")
    lefts = _as_sequence(data, "left")
    tops = _as_sequence(data, "top")
    widths = _as_sequence(data, "width")
    block_numbers = _as_sequence(data, "block_num")
    paragraph_numbers = _as_sequence(data, "par_num")
    line_numbers = _as_sequence(data, "line_num")

    words: list[dict[str, object]] = []
    lines: dict[tuple[int, int, int], list[tuple[float, str]]] = defaultdict(list)
    for index, raw_text in enumerate(texts):
        text = str(raw_text or "").strip()
        if not text:
            continue
        left = float(_int_value(_item(lefts, index)))
        top = float(_int_value(_item(tops, index)))
        width = max(1.0, float(_int_value(_item(widths, index), 1)))
        words.append({"text": text, "x0": left, "x1": left + width, "top": top})

        line_key = (
            _int_value(_item(block_numbers, index)),
            _int_value(_item(paragraph_numbers, index)),
            _int_value(_item(line_numbers, index)),
        )
        lines[line_key].append((left, text))

    ordered_lines = [
        " ".join(text for _, text in sorted(line_words, key=lambda item: item[0])).strip()
        for _, line_words in sorted(lines.items(), key=lambda item: item[0])
    ]
    return words, "\n".join(line for line in ordered_lines if line)


def _close_if_possible(value: object) -> None:
    closer = getattr(value, "close", None)
    if callable(closer):
        closer()


def run_local_pdf_ocr(
    path: Path,
    resolve_header: Callable[[str], str | None],
    *,
    dpi: int = _DEFAULT_DPI,
    languages: str = _DEFAULT_LANGUAGES,
    max_pages: int = _MAX_OCR_PAGES,
) -> PdfOcrResult:
    """OCR a scanned PDF locally and reconstruct conservative table rows from word boxes.

    No document bytes or recognized text are sent to an external service. The caller remains
    responsible for validating extracted fields against the original quote.
    """

    try:
        import pypdfium2 as pdfium
        import pytesseract
        from pytesseract import Output
    except ImportError as exc:
        raise PdfOcrUnavailableError(
            "로컬 OCR Python 모듈(pypdfium2/pytesseract)을 불러올 수 없습니다."
        ) from exc

    try:
        document = pdfium.PdfDocument(str(path))
    except Exception as exc:
        raise PdfOcrUnavailableError(f"OCR용 PDF 렌더러를 시작할 수 없습니다: {exc}") from exc

    pages: list[PdfOcrPage] = []
    warnings: list[str] = []
    page_count = len(document)
    ocr_page_count = min(page_count, max_pages)
    if page_count > max_pages:
        warnings.append(
            f"OCR 자원 보호를 위해 앞 {max_pages}페이지만 처리했습니다. 전체 {page_count}페이지입니다."
        )

    try:
        for page_index in range(ocr_page_count):
            page = document[page_index]
            bitmap = None
            try:
                bitmap = page.render(scale=dpi / 72)
                image = bitmap.to_pil()
                try:
                    data = pytesseract.image_to_data(
                        image,
                        lang=languages,
                        config="--psm 6",
                        output_type=Output.DICT,
                        timeout=_OCR_TIMEOUT_SECONDS,
                    )
                except Exception as exc:
                    raise PdfOcrUnavailableError(
                        "로컬 Tesseract OCR 실행에 실패했습니다. "
                        "tesseract-ocr 및 kor/eng 언어팩 배포 상태를 확인하세요."
                    ) from exc

                words, text = _ocr_words_and_text(data)
                table_rows = extract_word_geometry_rows_from_words(
                    words,
                    resolve_header,
                    y_tolerance=10.0,
                )
                pages.append(
                    PdfOcrPage(
                        page_number=page_index + 1,
                        text=text,
                        table_rows=table_rows,
                    )
                )
            finally:
                if bitmap is not None:
                    _close_if_possible(bitmap)
                _close_if_possible(page)
    finally:
        _close_if_possible(document)

    if not any(page.text.strip() for page in pages):
        warnings.append("로컬 OCR을 실행했지만 인식 가능한 텍스트를 찾지 못했습니다.")
    return PdfOcrResult(pages=tuple(pages), warnings=tuple(warnings))
