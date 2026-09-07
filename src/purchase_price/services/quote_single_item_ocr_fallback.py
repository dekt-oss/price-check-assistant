from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from purchase_price.services.quote_extraction_core import QuoteItem

_FOOTER_CROP_RATIO = 0.18
_TIGHT_FOOTER_CROP_RATIO = 0.10
_OCR_DPI = 220
_OCR_TIMEOUT_SECONDS = 30
_AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_HEADER_MARKERS = ("품명", "물품명", "제품명", "상품명")
_STOP_MARKERS = (
    "remark",
    "비고",
    "구성",
    "구성품",
    "total price",
    "합계",
    "총계",
    "공급가액",
    "부가세",
    "vat",
)


def _normalize_line(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _parse_amount(value: str) -> Decimal | None:
    text = re.sub(r"[,₩원\\\s]", "", value or "")
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite() or number <= 0:
        return None
    return number


def _looks_like_header(line: str) -> bool:
    compact = re.sub(r"\s+", "", line).casefold()
    has_identity = any(marker in compact for marker in _HEADER_MARKERS)
    has_price = "금액" in compact or "단가" in compact or "price" in compact
    return has_identity and has_price


def _looks_like_product_candidate(line: str) -> bool:
    compact = re.sub(r"[^0-9A-Za-z가-힣]", "", line)
    if len(compact) < 2 or len(line) > 80:
        return False
    folded = line.casefold()
    if any(marker in folded for marker in _STOP_MARKERS):
        return False
    if re.match(r"^\s*\d+(?:[.)]|\s)", line):
        return False
    if _AMOUNT_RE.fullmatch(line.replace(" ", "")):
        return False
    return bool(re.search(r"[A-Za-z가-힣]", line))


def _single_product_name(text: str) -> tuple[str, int] | None:
    lines = [_normalize_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    header_index = next((index for index, line in enumerate(lines) if _looks_like_header(line)), None)
    if header_index is None:
        return None

    candidates: list[tuple[str, int]] = []
    for offset, line in enumerate(lines[header_index + 1 : header_index + 8], start=1):
        folded = line.casefold()
        if re.match(r"^\s*\d+(?:[.)]|\s)", line) and any(
            marker in folded for marker in ("구성", "remark", "비고")
        ):
            break
        if "total price" in folded:
            break
        if _looks_like_product_candidate(line):
            candidates.append((line, header_index + offset + 1))
            if len(candidates) > 1:
                return None

    return candidates[0] if len(candidates) == 1 else None


def _footer_price(text: str) -> tuple[Decimal, bool] | None:
    normalized = "\n".join(_normalize_line(line) for line in text.splitlines() if line.strip())
    match = re.search(
        r"(?is)\bTOTAL\s*PRICE\b(?P<context>.{0,120}?)(?P<amount>\d{1,3}(?:,\d{3})+(?:\.\d+)?)",
        normalized,
    )
    if match is None:
        return None
    amount = _parse_amount(match.group("amount"))
    if amount is None:
        return None
    context = f"TOTAL PRICE {match.group('context')}".casefold()
    with_vat = "vat" in context
    return amount, with_vat


def recover_single_item_from_text(
    full_text: str,
    footer_text: str,
    *,
    page_number: int = 1,
) -> QuoteItem | None:
    """Recover one product whose identity row and footer price are separated.

    This is intentionally narrow. It only fires when a recognizable product/price header exists,
    exactly one plausible product name follows it, and the footer contains an explicit TOTAL PRICE.
    Generic sums are not enough to create an item.
    """

    product = _single_product_name(full_text)
    price = _footer_price(footer_text)
    if product is None or price is None:
        return None
    product_name, source_row = product
    amount, with_vat = price

    folded_footer = footer_text.casefold()
    has_individual_price_label = bool(
        re.search(r"개별\s*단가", footer_text, re.IGNORECASE)
        or re.search(r"\bunit\s*price\b", folded_footer, re.IGNORECASE)
    )

    warranty = ""
    warranty_match = re.search(
        r"(?is)(?:무상\s*)?보증\s*기간.{0,80}?납품\s*후\s*(\d+)\s*년",
        full_text,
    )
    if warranty_match:
        warranty = f"{warranty_match.group(1)}년"

    installation = ""
    installation_match = re.search(
        r"(?im)장비\s*도입관련\s*공사여부\s*[:：]\s*([^\r\n]+)",
        full_text,
    )
    if installation_match:
        installation = _normalize_line(installation_match.group(1))

    other_parts: list[str] = []
    payment_match = re.search(
        r"(?im)대금\s*지불조건\s*[:：]\s*([^\r\n]+)",
        full_text,
    )
    if payment_match:
        other_parts.append(f"대금지불조건: {_normalize_line(payment_match.group(1))}")

    return QuoteItem(
        source_sheet=f"PDF {page_number}페이지 OCR 단일품목 fallback",
        source_row=source_row,
        product_name=product_name,
        unit_price=amount if has_individual_price_label else None,
        total_amount=amount,
        vat_status="포함" if with_vat else "",
        installation_condition=installation,
        warranty_condition=warranty,
        other_conditions="; ".join(other_parts),
    )


def _ocr_image(image, pytesseract, *, languages: str, psm: int) -> str:
    return pytesseract.image_to_string(
        image,
        lang=languages,
        config=f"--psm {psm}",
        timeout=_OCR_TIMEOUT_SECONDS,
    )


def recover_single_item_scanned_quote(
    path: Path,
    *,
    languages: str = "kor+eng",
    max_pages: int = 3,
) -> QuoteItem | None:
    """Run an extra bounded OCR pass only after the main parser returned zero items."""

    try:
        import pypdfium2 as pdfium
        import pytesseract
        from PIL import ImageOps
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
                full_text = _ocr_image(image, pytesseract, languages=languages, psm=6)

                width, height = image.size
                footer_top = int(height * (1 - _FOOTER_CROP_RATIO))
                tight_footer_top = int(height * (1 - _TIGHT_FOOTER_CROP_RATIO))

                footer = image.crop((0, footer_top, width, height))
                tight_footer = image.crop((0, tight_footer_top, width, height))

                footer = ImageOps.autocontrast(ImageOps.grayscale(footer))
                tight_footer = ImageOps.autocontrast(ImageOps.grayscale(tight_footer))
                footer = footer.resize((footer.width * 2, footer.height * 2))
                tight_footer = tight_footer.resize(
                    (tight_footer.width * 2, tight_footer.height * 2)
                )

                footer_text = _ocr_image(footer, pytesseract, languages=languages, psm=6)
                tight_footer_text = _ocr_image(
                    tight_footer,
                    pytesseract,
                    languages=languages,
                    psm=12,
                )
                combined_footer = "\n".join(
                    text for text in (footer_text, tight_footer_text) if text.strip()
                )

                recovered = recover_single_item_from_text(
                    full_text,
                    combined_footer,
                    page_number=page_index + 1,
                )
                if recovered is not None:
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
