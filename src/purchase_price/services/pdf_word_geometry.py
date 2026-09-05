from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

_CANONICAL_HEADERS = {
    "product_name": "품명",
    "manufacturer": "제조사",
    "model_name": "모델명",
    "specification": "규격",
    "quantity": "수량",
    "unit": "단위",
    "unit_price": "단가",
    "total_amount": "금액",
    "vat_status": "VAT",
    "delivery_condition": "배송",
    "installation_condition": "설치",
    "option_condition": "옵션",
    "warranty_condition": "보증기간",
    "maintenance_condition": "유지보수",
    "other_conditions": "비고",
}
_IDENTITY_FIELDS = frozenset({"product_name", "manufacturer", "model_name", "specification"})
_PRICE_FIELDS = frozenset({"unit_price", "total_amount"})


@dataclass(frozen=True)
class _Word:
    text: str
    x0: float
    x1: float
    top: float

    @property
    def center(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass(frozen=True)
class _HeaderAnchor:
    field: str
    x0: float
    x1: float

    @property
    def center(self) -> float:
        return (self.x0 + self.x1) / 2


def _word_from_mapping(value: Mapping[str, object]) -> _Word | None:
    text = str(value.get("text") or "").strip()
    if not text:
        return None
    try:
        x0 = float(value["x0"])
        x1 = float(value["x1"])
        top = float(value["top"])
    except (KeyError, TypeError, ValueError):
        return None
    return _Word(text=text, x0=x0, x1=x1, top=top)


def _group_lines(words: list[_Word], *, y_tolerance: float) -> list[list[_Word]]:
    lines: list[list[_Word]] = []
    for word in sorted(words, key=lambda item: (item.top, item.x0)):
        if not lines:
            lines.append([word])
            continue
        line_top = sum(item.top for item in lines[-1]) / len(lines[-1])
        if abs(word.top - line_top) <= y_tolerance:
            lines[-1].append(word)
        else:
            lines.append([word])
    for line in lines:
        line.sort(key=lambda item: item.x0)
    return lines


def _has_same_field_prefix(
    line: list[_Word],
    index: int,
    width: int,
    field: str,
    resolve_header: Callable[[str], str | None],
) -> bool:
    for prefix_width in range(1, width):
        prefix = " ".join(word.text for word in line[index : index + prefix_width])
        if resolve_header(prefix) == field:
            return True
    return False


def _find_header_anchors(
    line: list[_Word],
    resolve_header: Callable[[str], str | None],
) -> list[_HeaderAnchor]:
    anchors: list[_HeaderAnchor] = []
    used_fields: set[str] = set()
    index = 0
    while index < len(line):
        best: tuple[int, str] | None = None
        max_window = min(4, len(line) - index)
        for width in range(max_window, 0, -1):
            phrase = " ".join(word.text for word in line[index : index + width])
            field = resolve_header(phrase)
            if field is None or field in used_fields:
                continue
            if _has_same_field_prefix(line, index, width, field, resolve_header):
                continue
            best = (width, field)
            break
        if best is None:
            index += 1
            continue
        width, field = best
        span = line[index : index + width]
        anchors.append(_HeaderAnchor(field=field, x0=span[0].x0, x1=span[-1].x1))
        used_fields.add(field)
        index += width

    fields = {anchor.field for anchor in anchors}
    if not fields.intersection(_IDENTITY_FIELDS) or not fields.intersection(_PRICE_FIELDS):
        return []
    return sorted(anchors, key=lambda anchor: anchor.center)


def _header_line(
    lines: list[list[_Word]],
    resolve_header: Callable[[str], str | None],
) -> tuple[int, list[_HeaderAnchor]] | None:
    for index, line in enumerate(lines[:40]):
        anchors = _find_header_anchors(line, resolve_header)
        if anchors:
            return index, anchors
    return None


def _boundaries(anchors: list[_HeaderAnchor]) -> list[float]:
    return [
        (left.center + right.center) / 2
        for left, right in zip(anchors, anchors[1:], strict=False)
    ]


def _column_index(center: float, boundaries: list[float]) -> int:
    for index, boundary in enumerate(boundaries):
        if center < boundary:
            return index
    return len(boundaries)


def _cells_for_line(line: list[_Word], anchors: list[_HeaderAnchor]) -> list[str]:
    boundaries = _boundaries(anchors)
    cells: list[list[_Word]] = [[] for _ in anchors]
    for word in line:
        cells[_column_index(word.center, boundaries)].append(word)
    return [" ".join(word.text for word in cell).strip() for cell in cells]


def _looks_like_price(value: str) -> bool:
    text = value.replace(",", "").replace("₩", "").replace("원", "").replace("\\", "")
    text = text.strip().strip("()")
    if not text:
        return False
    try:
        number = float(text)
    except ValueError:
        return False
    return number > 0


def _looks_like_quantity(value: str) -> bool:
    text = value.replace(",", "").strip().strip("()")
    if not text:
        return False
    try:
        number = float(text)
    except ValueError:
        return False
    return number >= 0


def _row_has_price(cells: list[str], anchors: list[_HeaderAnchor]) -> bool:
    for index, anchor in enumerate(anchors):
        if anchor.field in _PRICE_FIELDS and _looks_like_price(cells[index]):
            return True
    return False


def _row_has_invalid_quantity(cells: list[str], anchors: list[_HeaderAnchor]) -> bool:
    """Reject geometry rows whose populated quantity cell is visibly shifted/non-numeric.

    Quantity remains optional. This only treats a non-empty, non-numeric reconstructed quantity
    as evidence that column geometry is unreliable, so the caller can use a safer fallback.
    """

    for index, anchor in enumerate(anchors):
        if anchor.field != "quantity":
            continue
        value = cells[index].strip()
        return bool(value) and not _looks_like_quantity(value)
    return False


def _row_has_identity(cells: list[str], anchors: list[_HeaderAnchor]) -> bool:
    for index, anchor in enumerate(anchors):
        if anchor.field in _IDENTITY_FIELDS and cells[index].strip():
            return True
    return False


def _merge_cells(left: list[str], right: list[str]) -> list[str]:
    merged: list[str] = []
    for first, second in zip(left, right, strict=True):
        if first and second:
            merged.append(f"{first} {second}".strip())
        else:
            merged.append(first or second)
    return merged


def extract_word_geometry_rows_from_words(
    raw_words: Sequence[Mapping[str, object]],
    resolve_header: Callable[[str], str | None],
    *,
    y_tolerance: float = 3.0,
) -> tuple[tuple[object, ...], ...]:
    """Reconstruct conservative table rows from generic word bounding boxes."""

    words = [word for raw in raw_words if (word := _word_from_mapping(raw)) is not None]
    if not words:
        return ()
    lines = _group_lines(words, y_tolerance=y_tolerance)
    header = _header_line(lines, resolve_header)
    if header is None:
        return ()
    header_index, anchors = header

    rows: list[tuple[object, ...]] = [
        tuple(_CANONICAL_HEADERS[anchor.field] for anchor in anchors)
    ]
    pending: list[str] | None = None
    for line in lines[header_index + 1 :]:
        cells = _cells_for_line(line, anchors)
        has_price = _row_has_price(cells, anchors)
        has_identity = _row_has_identity(cells, anchors)

        if has_price:
            if pending is not None:
                cells = _merge_cells(pending, cells)
                pending = None
            if _row_has_invalid_quantity(cells, anchors):
                continue
            rows.append(tuple(cells))
            continue

        if has_identity:
            pending = cells if pending is None else _merge_cells(pending, cells)
            continue

        pending = None

    return tuple(rows) if len(rows) > 1 else ()


def extract_word_geometry_rows(
    page: object,
    resolve_header: Callable[[str], str | None],
    *,
    y_tolerance: float = 3.0,
) -> tuple[tuple[object, ...], ...]:
    """Reconstruct a text table from word coordinates when ruled-line detection fails.

    This fallback is deliberately conservative: it requires a recognizable identity column and
    a price column, and only emits rows that contain an explicit price. Text-only continuations
    may be merged into the immediately following priced row, but free-form prose is never emitted
    as an item on its own.
    """

    extractor = getattr(page, "extract_words", None)
    if extractor is None:
        return ()
    try:
        raw_words = extractor(
            x_tolerance=1,
            y_tolerance=y_tolerance,
            keep_blank_chars=False,
            use_text_flow=True,
        ) or []
    except TypeError:
        raw_words = extractor() or []
    except Exception:
        return ()

    return extract_word_geometry_rows_from_words(
        raw_words,
        resolve_header,
        y_tolerance=y_tolerance,
    )
