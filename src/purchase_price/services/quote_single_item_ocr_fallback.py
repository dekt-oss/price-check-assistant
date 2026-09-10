from __future__ import annotations

import re
from dataclasses import dataclass
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
_QUOTE_MARKERS = ("견적서", "quotation", "estimate")
_INCLUDED_WITH_MARKERS = ("included with", "including", "포함품", "구성품")
_KNOWN_UNITS = ("unit", "set", "ea", "pcs", "piece", "kit", "대", "개", "식")
_SUMMARY_MARKERS = ("합계", "총계", "공급가액", "세액", "subtotal", "total")


@dataclass(frozen=True)
class _PricedRow:
    line_index: int
    source_row: int
    amount: Decimal
    prefix: str
    quantity: Decimal | None
    unit: str
    vat_status: str


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


def _vat_status_from_text(text: str) -> str:
    """Return explicit VAT status without turning any VAT mention into inclusion.

    Exclusion markers win only when inclusion is absent. Conflicting OCR evidence stays unknown so a
    fallback never reverses an explicit tax condition.
    """

    normalized = _normalize_line(text).casefold()
    excluded = bool(
        re.search(r"부가\s*세\s*(?:별도|미포함|제외)", normalized, re.IGNORECASE)
        or re.search(
            r"\bV\.?\s*A\.?\s*T\.?\s*(?:별도|미포함|제외|excluded?|not\s+included)",
            normalized,
            re.IGNORECASE,
        )
    )
    included = bool(
        re.search(r"부가\s*세\s*(?:포함)", normalized, re.IGNORECASE)
        or re.search(
            r"\bV\.?\s*A\.?\s*T\.?\s*(?:included?|포함)",
            normalized,
            re.IGNORECASE,
        )
        or re.search(r"\bwith\s+vat\b", normalized, re.IGNORECASE)
    )
    if excluded and included:
        return ""
    if excluded:
        return "별도"
    if included:
        return "포함"
    return ""


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


def _footer_price(text: str) -> tuple[Decimal, str] | None:
    normalized = "\n".join(_normalize_line(line) for line in text.splitlines() if line.strip())
    match = re.search(
        r"(?is)(?:\bTOTAL\s*PRICE\b|합\s*계|총\s*계)"
        r"(?P<context>.{0,120}?)(?P<amount>\d{1,3}(?:,\d{3})+(?:\.\d+)?)",
        normalized,
    )
    if match is None:
        return None
    amount = _parse_amount(match.group("amount"))
    if amount is None:
        return None
    context = f"{match.group(0)[:120]} {match.group('context')}"
    return amount, _vat_status_from_text(context)


def _looks_like_quote_document(text: str) -> bool:
    folded = text.casefold()
    return any(marker in folded for marker in _QUOTE_MARKERS)


def _parse_unit(prefix: str) -> str:
    folded = prefix.casefold()
    for unit in _KNOWN_UNITS:
        if re.search(rf"(?<![0-9a-z가-힣]){re.escape(unit)}(?![0-9a-z가-힣])", folded):
            return unit
    return ""


def _standalone_quantity(segment: str) -> Decimal | None:
    match = re.fullmatch(r"[^0-9]*(\d+(?:\.\d+)?)[^0-9]*", segment)
    if match is None:
        return None
    try:
        value = Decimal(match.group(1))
    except InvalidOperation:
        return None
    if value <= 0 or value > 100000:
        return None
    return value


def _parse_quantity(prefix: str) -> Decimal | None:
    """Parse quantity relative to the unit column, never from an arbitrary numeric spec token."""

    segments = [_normalize_line(part) for part in prefix.split("|") if _normalize_line(part)]
    if len(segments) < 2:
        return None

    unit_indexes = [index for index, segment in enumerate(segments) if _parse_unit(segment)]
    if len(unit_indexes) == 1:
        unit_index = unit_indexes[0]
        for segment in segments[unit_index + 1 :]:
            value = _standalone_quantity(segment)
            if value is not None:
                return value
        return None

    # Some OCR rows lose the unit token entirely. In that case recover only when there is exactly
    # one standalone numeric segment after the identity/specification segment. Multiple numbers are
    # ambiguous (for example model year + quantity) and must fail closed.
    candidates: list[Decimal] = []
    for segment in segments[1:]:
        value = _standalone_quantity(segment)
        if value is not None and value not in candidates:
            candidates.append(value)
    return candidates[0] if len(candidates) == 1 else None


def _repeated_price_row(text: str) -> _PricedRow | None:
    """Find one and only one plausible priced item row with repeated unit/total price.

    Every plausible row carrying two monetary values is counted before the repeated-price heuristic.
    This prevents a multi-item document from being silently collapsed to the one row whose unit and
    total happen to be equal.
    """

    lines = [_normalize_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    plausible_rows: list[_PricedRow] = []
    recoverable_row: _PricedRow | None = None

    for line_index, line in enumerate(lines):
        matches = list(_AMOUNT_RE.finditer(line))
        if len(matches) < 2:
            continue
        amounts = [_parse_amount(match.group(0)) for match in matches]
        valid_amounts = [amount for amount in amounts if amount is not None]
        if len(valid_amounts) < 2:
            continue

        prefix = _normalize_line(line[: matches[0].start()])
        folded_prefix = prefix.casefold()
        if not re.search(r"[A-Za-z가-힣]", prefix):
            continue
        if any(marker in folded_prefix for marker in _SUMMARY_MARKERS):
            continue

        quantity = _parse_quantity(prefix)
        if quantity is None:
            continue
        unit = _parse_unit(prefix)
        row = _PricedRow(
            line_index=line_index,
            source_row=line_index + 1,
            amount=valid_amounts[0],
            prefix=prefix,
            quantity=quantity,
            unit=unit,
            vat_status=_vat_status_from_text(line),
        )
        plausible_rows.append(row)
        if len(plausible_rows) > 1:
            return None

        if len(valid_amounts) == 2 and valid_amounts[0] == valid_amounts[1]:
            recoverable_row = row
        else:
            recoverable_row = None

    if len(plausible_rows) != 1:
        return None
    return recoverable_row


def _is_uppercase_identity_line(line: str) -> bool:
    folded = line.casefold()
    if any(marker in folded for marker in _STOP_MARKERS):
        return False
    if _AMOUNT_RE.search(line) or len(line) > 70:
        return False
    letters = [char for char in line if char.isalpha() and char.isascii()]
    if len(letters) < 4:
        return False
    uppercase = sum(char.isupper() for char in letters)
    return uppercase / len(letters) >= 0.8


def _product_block_before_priced_row(text: str, row: _PricedRow) -> str:
    lines = [_normalize_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    collected: list[str] = []
    skipped_connector = False

    for index in range(row.line_index - 1, max(-1, row.line_index - 7), -1):
        line = lines[index]
        folded = line.casefold()
        if any(folded == marker or folded.startswith(f"{marker} ") for marker in _INCLUDED_WITH_MARKERS):
            if collected or skipped_connector:
                break
            skipped_connector = True
            continue
        if _is_uppercase_identity_line(line):
            collected.append(line.strip("| "))
            continue
        if collected:
            break

    collected.reverse()
    return " ".join(collected)


def _specification_from_priced_row(text: str, row: _PricedRow) -> str:
    lines = [_normalize_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    segments = [_normalize_line(part).strip("—- ") for part in row.prefix.split("|")]
    segments = [segment for segment in segments if segment]
    specification = ""
    if segments:
        first = segments[0]
        if re.search(r"[A-Za-z가-힣]", first):
            specification = first

    if row.line_index + 1 < len(lines):
        following = lines[row.line_index + 1].strip("| ")
        if (
            following
            and len(following) <= 40
            and not _AMOUNT_RE.search(following)
            and not re.match(r"^\s*\d+[.)]", following)
            and re.search(r"[A-Za-z]", following)
            and (
                _is_uppercase_identity_line(following)
                or bool(re.search(r"[+\-/0-9]", following))
            )
        ):
            specification = _normalize_line(f"{specification} {following}")

    return specification


def _extract_context_fields(text: str) -> tuple[str, str, str]:
    warranty = ""
    warranty_match = re.search(
        r"(?is)(?:무상\s*)?(?:보증|warranty|하자)\s*(?:기간)?.{0,100}?(\d+)\s*년",
        text,
    )
    if warranty_match:
        warranty = f"{warranty_match.group(1)}년"

    installation = ""
    installation_match = re.search(
        r"(?im)장비\s*도입관련\s*공사여부\s*[:：]\s*([^\r\n]+)",
        text,
    )
    if installation_match:
        installation = _normalize_line(installation_match.group(1))

    other_parts: list[str] = []
    payment_match = re.search(
        r"(?im)(?:대금\s*)?(?:지불|결제)\s*조건\s*[:：]?\s*([^\r\n]+)",
        text,
    )
    if payment_match:
        value = _normalize_line(payment_match.group(1))
        if value:
            other_parts.append(f"결제조건: {value}")

    return warranty, installation, "; ".join(other_parts)


def _recover_from_repeated_price_row(
    full_text: str,
    *,
    page_number: int,
) -> QuoteItem | None:
    if not _looks_like_quote_document(full_text):
        return None
    row = _repeated_price_row(full_text)
    if row is None:
        return None
    product_name = _product_block_before_priced_row(full_text, row)
    if not product_name:
        return None
    specification = _specification_from_priced_row(full_text, row)
    if not specification:
        return None

    warranty, installation, other_conditions = _extract_context_fields(full_text)
    return QuoteItem(
        source_sheet=f"PDF {page_number}페이지 OCR 단일품목 fallback",
        source_row=row.source_row,
        product_name=product_name,
        specification=specification,
        quantity=row.quantity,
        unit=row.unit,
        unit_price=row.amount,
        total_amount=row.amount,
        vat_status=row.vat_status,
        installation_condition=installation,
        warranty_condition=warranty,
        other_conditions=other_conditions,
    )


def recover_single_item_from_text(
    full_text: str,
    footer_text: str,
    *,
    page_number: int = 1,
) -> QuoteItem | None:
    """Recover one product from a scanned single-item quote without using totals alone.

    Two bounded patterns are accepted:
    1. a recognizable product header plus one product name and an explicit TOTAL PRICE/합계;
    2. exactly one ruled-table item row where unit price and row total repeat the same amount,
       with an explicit quantity and a separate product identity block.

    Ambiguous or summary-only documents continue to fail closed.
    """

    product = _single_product_name(full_text)
    price = _footer_price(footer_text)
    if product is not None and price is not None:
        product_name, source_row = product
        amount, vat_status = price

        folded_footer = footer_text.casefold()
        has_individual_price_label = bool(
            re.search(r"개별\s*단가", footer_text, re.IGNORECASE)
            or re.search(r"\bunit\s*price\b", folded_footer, re.IGNORECASE)
        )
        warranty, installation, other_conditions = _extract_context_fields(full_text)

        return QuoteItem(
            source_sheet=f"PDF {page_number}페이지 OCR 단일품목 fallback",
            source_row=source_row,
            product_name=product_name,
            unit_price=amount if has_individual_price_label else None,
            total_amount=amount,
            vat_status=vat_status,
            installation_condition=installation,
            warranty_condition=warranty,
            other_conditions=other_conditions,
        )

    return _recover_from_repeated_price_row(full_text, page_number=page_number)


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
    """Run bounded adaptive OCR only after the main parser returned zero items."""

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

                # PSM 6 remains the first pass for compact quotation tables. PSM 4 is
                # attempted only after that fails; it is materially better for ruled tables
                # where Tesseract splits a single item across adjacent text lines.
                for psm in (6, 4):
                    full_text = _ocr_image(image, pytesseract, languages=languages, psm=psm)
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
