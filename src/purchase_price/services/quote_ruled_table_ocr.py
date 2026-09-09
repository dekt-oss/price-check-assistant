from __future__ import annotations

import re
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from pathlib import Path

from purchase_price.services.quote_extraction_core import QuoteItem

_OCR_DPI = 220
_OCR_TIMEOUT_SECONDS = 30
_AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_KNOWN_UNITS = ("unit", "set", "ea", "pcs", "piece", "kit", "대", "개", "식")
_PRODUCT_STOP = (
    "included with",
    "including",
    "operating manual",
    "manual",
    "quotation",
    "estimate",
    "견적",
    "품목",
    "품명",
    "규격",
    "단위",
    "수량",
    "단가",
    "금액",
    "비고",
    "합계",
    "총계",
    "공급가액",
    "부가세",
    "vat",
    "warranty",
    "보증",
    "하자",
    "결제",
    "리스",
    "제조",
    "수입",
    "업체",
)


def _normalize_line(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" |\t\r\n")


def _lines(text: str) -> list[str]:
    return [line for raw in text.splitlines() if (line := _normalize_line(raw))]


def _parse_amount(value: str) -> Decimal | None:
    cleaned = re.sub(r"[,₩원\\\s]", "", value or "")
    try:
        amount = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount <= 0:
        return None
    return amount


def _repeated_price_line(lines: list[str]) -> tuple[int, Decimal] | None:
    candidates: list[tuple[int, Decimal]] = []
    for index, line in enumerate(lines):
        folded = line.casefold()
        if any(marker in folded for marker in ("합계", "총계", "공급가액", "세액")):
            continue
        matches = list(_AMOUNT_RE.finditer(line))
        if len(matches) < 2:
            continue
        amounts = [_parse_amount(match.group(0)) for match in matches]
        valid = [amount for amount in amounts if amount is not None]
        if len(valid) < 2 or valid[0] != valid[1]:
            continue
        candidates.append((index, valid[0]))
        if len(candidates) > 1:
            return None
    return candidates[0] if len(candidates) == 1 else None


def _nearby_quantity(lines: list[str], price_index: int) -> Decimal | None:
    values: list[Decimal] = []
    start = max(0, price_index - 4)
    end = min(len(lines), price_index + 3)
    for index in range(start, end):
        if index == price_index:
            continue
        line = lines[index]
        match = re.fullmatch(r"[^0-9]*(\d+(?:\.\d+)?)[^0-9]*", line)
        if match is None:
            continue
        if re.search(r"\d\s*(?:부|page|쪽)\b", line, re.IGNORECASE):
            continue
        try:
            value = Decimal(match.group(1))
        except InvalidOperation:
            continue
        if 0 < value <= 100000 and value not in values:
            values.append(value)
    return values[0] if len(values) == 1 else None


def _known_unit(text: str) -> str:
    found: list[str] = []
    folded = text.casefold()
    for unit in _KNOWN_UNITS:
        if re.search(rf"(?<![0-9a-z가-힣]){re.escape(unit)}(?![0-9a-z가-힣])", folded):
            found.append(unit)
    return found[0] if len(found) == 1 else ""


def _identity_candidates(lines: list[str], price_index: int) -> tuple[str, str]:
    start = max(0, price_index - 5)
    end = min(len(lines), price_index + 6)
    product_parts: list[tuple[int, str]] = []
    spec_parts: list[tuple[int, str]] = []

    for index in range(start, end):
        if index == price_index:
            continue
        line = lines[index]
        folded = line.casefold()
        if any(marker in folded for marker in _PRODUCT_STOP):
            continue
        if _AMOUNT_RE.search(line):
            continue
        if re.fullmatch(r"[^0-9]*(\d+(?:\.\d+)?)[^0-9]*", line):
            continue
        if _known_unit(line):
            continue

        ascii_letters = [char for char in line if char.isascii() and char.isalpha()]
        hangul_letters = re.findall(r"[가-힣]", line)
        if len(ascii_letters) < 3:
            continue
        uppercase_ratio = sum(char.isupper() for char in ascii_letters) / len(ascii_letters)
        ascii_share = len(ascii_letters) / max(1, len(ascii_letters) + len(hangul_letters))
        words = re.findall(r"[A-Za-z]+", line)
        has_model_marker = bool(re.search(r"[+\-/0-9]", line))

        if uppercase_ratio >= 0.8 and len(words) >= 2 and not has_model_marker:
            product_parts.append((index, line))
            continue
        if (
            len(line) <= 60
            and ascii_share >= 0.8
            and (uppercase_ratio < 0.8 or has_model_marker)
        ):
            spec_parts.append((index, line))

    def _join(parts: list[tuple[int, str]]) -> str:
        result: list[str] = []
        seen: set[str] = set()
        for _, value in sorted(parts):
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(value)
        return _normalize_line(" ".join(result))

    return _join(product_parts), _join(spec_parts)


def _repair_short_ascii_suffix(value: str) -> str:
    match = re.fullmatch(r"([A-Za-z]{4,})\s+([A-Za-z]{1,3})", value)
    if match:
        return f"{match.group(1)}{match.group(2)}"
    return value


def _manufacturer_from_context(text: str) -> str:
    lines = _lines(text)
    for index, line in enumerate(lines):
        folded = line.casefold()
        if not (("제조" in folded or "수입" in folded) and "업체" in folded):
            continue
        for candidate in lines[index + 1 : index + 4]:
            if len(candidate) > 60:
                continue
            if re.search(r"warranty|보증|하자|결제|리스", candidate, re.IGNORECASE):
                break
            if re.fullmatch(r"[A-Za-z][A-Za-z .&'\-/]{2,}", candidate):
                return _repair_short_ascii_suffix(_normalize_line(candidate))
    return ""


def _warranty_from_context(text: str) -> str:
    lines = _lines(text)
    for index, line in enumerate(lines):
        if not re.search(r"warranty|보증|하자", line, re.IGNORECASE):
            continue
        window = " ".join(lines[index : index + 3])
        match = re.search(r"(\d+)\s*년", window)
        if match:
            return f"{match.group(1)}년"
    return ""


def _payment_from_context(text: str) -> str:
    for line in _lines(text):
        folded = line.casefold()
        if "리스" in folded and "결제" in folded:
            return f"결제조건: {line}"
    return ""


def recover_sparse_single_item_from_text(
    sparse_text: str,
    *,
    context_text: str = "",
    page_number: int = 1,
) -> QuoteItem | None:
    """Recover one ruled-table quote row from sparse OCR reading order.

    This path is deliberately strict: exactly one repeated unit-price/amount line,
    exactly one nearby quantity, and both product and specification fragments are required.
    It never creates a quote item from a document-level total alone.
    """

    lines = _lines(sparse_text)
    priced = _repeated_price_line(lines)
    if priced is None:
        return None
    price_index, amount = priced
    quantity = _nearby_quantity(lines, price_index)
    if quantity is None:
        return None
    product_name, specification = _identity_candidates(lines, price_index)
    if not product_name or not specification:
        return None

    all_context = "\n".join(text for text in (context_text, sparse_text) if text)
    vat_included = bool(
        re.search(r"부가\s*세\s*포함", all_context, re.IGNORECASE)
        or re.search(r"\bV\.?\s*A\.?\s*T\.?\s*(?:included?|포함)", all_context, re.IGNORECASE)
    )
    unit = _known_unit(all_context)

    return QuoteItem(
        source_sheet=f"PDF {page_number}페이지 OCR ruled-table fallback",
        source_row=price_index + 1,
        product_name=product_name,
        manufacturer=_manufacturer_from_context(all_context),
        specification=specification,
        quantity=quantity,
        unit=unit,
        unit_price=amount,
        total_amount=amount,
        vat_status="포함" if vat_included else "",
        warranty_condition=_warranty_from_context(all_context),
        other_conditions=_payment_from_context(all_context),
    )


def _remove_long_grid_lines(image):
    """Whiten long table ruling using Pillow+NumPy only; keep text strokes intact."""

    import numpy as np
    from PIL import Image, ImageOps

    gray = np.array(ImageOps.grayscale(image))
    dark = gray < 190
    height, width = dark.shape
    mask = np.zeros_like(dark)
    min_horizontal = max(60, width // 18)
    min_vertical = max(45, min(250, height // 10))

    for y, row in enumerate(dark):
        padded = np.concatenate(([False], row, [False]))
        transitions = np.diff(padded.astype(np.int8))
        starts = np.where(transitions == 1)[0]
        ends = np.where(transitions == -1)[0]
        for start, end in zip(starts, ends, strict=False):
            if end - start >= min_horizontal:
                mask[y, max(0, start - 1) : min(width, end + 1)] = True

    for x, column in enumerate(dark.T):
        padded = np.concatenate(([False], column, [False]))
        transitions = np.diff(padded.astype(np.int8))
        starts = np.where(transitions == 1)[0]
        ends = np.where(transitions == -1)[0]
        for start, end in zip(starts, ends, strict=False):
            if end - start >= min_vertical:
                mask[max(0, start - 1) : min(height, end + 1), x] = True

    expanded = mask.copy()
    expanded[1:] |= mask[:-1]
    expanded[:-1] |= mask[1:]
    expanded[:, 1:] |= mask[:, :-1]
    expanded[:, :-1] |= mask[:, 1:]
    cleaned = gray.copy()
    cleaned[expanded] = 255
    return Image.fromarray(cleaned)


def _ocr_image(image, pytesseract, *, languages: str, psm: int) -> str:
    return pytesseract.image_to_string(
        image,
        lang=languages,
        config=f"--psm {psm}",
        timeout=_OCR_TIMEOUT_SECONDS,
    )


def recover_sparse_ruled_table_scanned_quote(
    path: Path,
    *,
    languages: str = "kor+eng",
    max_pages: int = 2,
) -> QuoteItem | None:
    """Target the ruled-table scan failure mode before the older footer fallback."""

    try:
        import pypdfium2 as pdfium
        import pytesseract
    except ImportError:
        return None

    try:
        document = pdfium.PdfDocument(str(path))
    except Exception:
        return None

    try:
        for page_index in range(min(len(document), max_pages)):
            page = document[page_index]
            bitmap = None
            try:
                bitmap = page.render(scale=_OCR_DPI / 72)
                image = bitmap.to_pil()
                original_text = _ocr_image(
                    image,
                    pytesseract,
                    languages=languages,
                    psm=11,
                )
                cleaned_image = _remove_long_grid_lines(image)
                sparse_text = _ocr_image(
                    cleaned_image,
                    pytesseract,
                    languages=languages,
                    psm=11,
                )
                recovered = recover_sparse_single_item_from_text(
                    sparse_text,
                    context_text=original_text,
                    page_number=page_index + 1,
                )
                if recovered is not None:
                    unit = recovered.unit or _known_unit(original_text)
                    if unit != recovered.unit:
                        recovered = replace(recovered, unit=unit)
                    return recovered
            except Exception:
                continue
            finally:
                if bitmap is not None:
                    closer = getattr(bitmap, "close", None)
                    if callable(closer):
                        closer()
                closer = getattr(page, "close", None)
                if callable(closer):
                    closer()
    finally:
        closer = getattr(document, "close", None)
        if callable(closer):
            closer()

    return None
