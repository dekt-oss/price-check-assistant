from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from purchase_price.schemas import ProductQuery


class QuoteExtractionError(RuntimeError):
    pass


@dataclass(frozen=True)
class QuoteItem:
    source_sheet: str
    source_row: int
    product_name: str = ""
    manufacturer: str = ""
    model_name: str = ""
    specification: str = ""
    quantity: Decimal | None = None
    unit: str = ""
    unit_price: Decimal | None = None
    total_amount: Decimal | None = None
    vat_status: str = ""
    delivery_condition: str = ""
    installation_condition: str = ""
    option_condition: str = ""
    warranty_condition: str = ""
    maintenance_condition: str = ""
    other_conditions: str = ""


@dataclass(frozen=True)
class QuoteExtractionResult:
    items: tuple[QuoteItem, ...]
    warnings: tuple[str, ...]


_FIELD_ALIASES = {
    "product_name": (
        "품명",
        "제품명",
        "상품명",
        "물품명",
        "품목명",
        "내역",
    ),
    "manufacturer": (
        "제조사",
        "제조업체",
        "메이커",
        "maker",
        "브랜드",
        "brand",
    ),
    "model_name": (
        "모델",
        "모델명",
        "model",
        "modelname",
        "modelno",
        "modelnumber",
    ),
    "specification": (
        "규격",
        "사양",
        "spec",
        "specification",
    ),
    "quantity": (
        "수량",
        "qty",
        "quantity",
    ),
    "unit": (
        "단위",
        "수량단위",
        "포장단위",
        "unit",
        "uom",
    ),
    "unit_price": (
        "단가",
        "견적단가",
        "공급단가",
        "판매단가",
        "unitprice",
        "price",
    ),
    "total_amount": (
        "금액",
        "합계금액",
        "공급가액",
        "총액",
        "amount",
        "total",
        "totalamount",
    ),
    "vat_status": (
        "vat",
        "vat여부",
        "vat포함",
        "vat포함여부",
        "부가세",
        "부가세여부",
        "부가세포함",
        "부가세포함여부",
        "세금",
    ),
    "delivery_condition": (
        "배송",
        "배송비",
        "배송조건",
        "운송",
        "운송비",
        "납품조건",
    ),
    "installation_condition": (
        "설치",
        "설치비",
        "설치조건",
        "설치비용",
    ),
    "option_condition": (
        "옵션",
        "옵션비",
        "옵션조건",
        "부속품",
        "부속",
        "구성",
        "구성품",
    ),
    "warranty_condition": (
        "보증",
        "보증기간",
        "무상보증",
        "무상보증기간",
        "warranty",
    ),
    "maintenance_condition": (
        "유지보수",
        "유지보수조건",
        "유지관리",
        "서비스계약",
        "maintenance",
    ),
    "other_conditions": (
        "기타조건",
        "기타",
        "조건",
        "비고",
        "특이사항",
        "remark",
        "remarks",
        "note",
    ),
}
_SUMMARY_LABELS = frozenset({"합계", "총계", "소계", "부가세", "vat", "공급가액합계"})
_MAX_HEADER_SCAN_ROWS = 30


def _normalize_header(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"[\s_./()\-]+", "", str(value).strip().casefold())


_ALIAS_LOOKUP = {
    _normalize_header(alias): field
    for field, aliases in _FIELD_ALIASES.items()
    for alias in aliases
}


def _text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        return text[:-2]
    return text


def parse_quote_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        text = str(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        text = re.sub(r"[,\s₩원]", "", text)
    try:
        result = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not result.is_finite():
        return None
    return result


def _header_mapping(values: tuple[object, ...]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, value in enumerate(values):
        field = _ALIAS_LOOKUP.get(_normalize_header(value))
        if field is not None and field not in mapping:
            mapping[field] = index
    return mapping


def _header_is_usable(mapping: dict[str, int]) -> bool:
    identifier_count = sum(
        field in mapping
        for field in ("product_name", "manufacturer", "model_name", "specification")
    )
    has_price = "unit_price" in mapping or "total_amount" in mapping
    return identifier_count >= 1 and has_price


def _cell(values: tuple[object, ...], mapping: dict[str, int], field: str) -> object:
    index = mapping.get(field)
    if index is None or index >= len(values):
        return None
    return values[index]


def _is_summary_row(item: QuoteItem) -> bool:
    label = _normalize_header(item.product_name or item.model_name)
    return label in _SUMMARY_LABELS


def _extract_sheet_rows(
    sheet_name: str,
    rows: Iterable[tuple[object, ...]],
) -> tuple[list[QuoteItem], str | None]:
    row_iterator = iter(enumerate(rows, start=1))
    header_row_number: int | None = None
    mapping: dict[str, int] = {}

    for row_number, values in row_iterator:
        if row_number > _MAX_HEADER_SCAN_ROWS:
            break
        candidate = _header_mapping(tuple(values))
        if _header_is_usable(candidate):
            header_row_number = row_number
            mapping = candidate
            break

    if header_row_number is None:
        return [], f"{sheet_name}: 품목/가격 헤더를 찾지 못해 건너뜀"

    items: list[QuoteItem] = []
    for row_number, values in row_iterator:
        row = tuple(values)
        item = QuoteItem(
            source_sheet=sheet_name,
            source_row=row_number,
            product_name=_text(_cell(row, mapping, "product_name")),
            manufacturer=_text(_cell(row, mapping, "manufacturer")),
            model_name=_text(_cell(row, mapping, "model_name")),
            specification=_text(_cell(row, mapping, "specification")),
            quantity=parse_quote_decimal(_cell(row, mapping, "quantity")),
            unit=_text(_cell(row, mapping, "unit")),
            unit_price=parse_quote_decimal(_cell(row, mapping, "unit_price")),
            total_amount=parse_quote_decimal(_cell(row, mapping, "total_amount")),
            vat_status=_text(_cell(row, mapping, "vat_status")),
            delivery_condition=_text(_cell(row, mapping, "delivery_condition")),
            installation_condition=_text(_cell(row, mapping, "installation_condition")),
            option_condition=_text(_cell(row, mapping, "option_condition")),
            warranty_condition=_text(_cell(row, mapping, "warranty_condition")),
            maintenance_condition=_text(_cell(row, mapping, "maintenance_condition")),
            other_conditions=_text(_cell(row, mapping, "other_conditions")),
        )
        if not any([item.product_name, item.manufacturer, item.model_name, item.specification]):
            continue
        if item.unit_price is None and item.total_amount is None:
            continue
        if _is_summary_row(item):
            continue
        items.append(item)

    return items, None


def extract_excel_quote(path: Path) -> QuoteExtractionResult:
    # Parser dependencies are imported only when the matching file type is actually used.
    # A missing optional runtime parser must never make every quote-related Streamlit page fail
    # during module import/startup.
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise QuoteExtractionError(
            "Excel(.xlsx) 지원 모듈 openpyxl을 불러올 수 없습니다. 배포 의존성을 확인하세요."
        ) from exc

    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception as exc:
        raise QuoteExtractionError(f"Excel 견적서를 읽을 수 없습니다: {exc}") from exc

    items: list[QuoteItem] = []
    warnings: list[str] = []
    try:
        for sheet in workbook.worksheets:
            sheet_items, warning = _extract_sheet_rows(
                sheet.title,
                (tuple(values) for values in sheet.iter_rows(values_only=True)),
            )
            items.extend(sheet_items)
            if warning:
                warnings.append(warning)
    finally:
        workbook.close()

    if not items:
        warnings.append("자동 추출된 견적 품목이 없습니다. 헤더명과 가격 열을 확인하세요.")
    return QuoteExtractionResult(items=tuple(items), warnings=tuple(warnings))


def extract_legacy_excel_quote(path: Path) -> QuoteExtractionResult:
    try:
        import xlrd
    except ImportError as exc:
        raise QuoteExtractionError(
            "구형 Excel(.xls) 지원 모듈 xlrd를 불러올 수 없습니다. "
            "배포 의존성을 확인하거나 .xlsx 파일로 저장해 다시 업로드하세요."
        ) from exc

    try:
        workbook = xlrd.open_workbook(str(path), on_demand=True)
    except Exception as exc:
        raise QuoteExtractionError(f"구형 Excel(.xls) 견적서를 읽을 수 없습니다: {exc}") from exc

    items: list[QuoteItem] = []
    warnings: list[str] = []
    try:
        for sheet in workbook.sheets():
            sheet_items, warning = _extract_sheet_rows(
                sheet.name,
                (tuple(sheet.row_values(index)) for index in range(sheet.nrows)),
            )
            items.extend(sheet_items)
            if warning:
                warnings.append(warning)
    finally:
        workbook.release_resources()

    if not items:
        warnings.append("자동 추출된 견적 품목이 없습니다. 헤더명과 가격 열을 확인하세요.")
    return QuoteExtractionResult(items=tuple(items), warnings=tuple(warnings))


def _pdf_text_rows(text: str) -> tuple[tuple[object, ...], ...]:
    """Convert layout-preserving PDF text into table-like rows.

    Text PDFs usually preserve column gaps as repeated spaces or tabs. We only split on those
    wider gaps, never on an ordinary single space inside a product/specification name.
    """

    rows: list[tuple[object, ...]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        cells = tuple(cell.strip() for cell in re.split(r"(?:\t+| {2,})", line) if cell.strip())
        if cells:
            rows.append(cells)
    return tuple(rows)


def extract_pdf_quote(path: Path) -> QuoteExtractionResult:
    """Extract table-like rows from a text PDF; scanned PDFs deliberately require OCR later."""

    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise QuoteExtractionError(
            "PDF 지원 모듈 pypdf를 불러올 수 없습니다. 배포 의존성을 확인하세요."
        ) from exc

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise QuoteExtractionError(f"PDF 견적서를 읽을 수 없습니다: {exc}") from exc

    items: list[QuoteItem] = []
    warnings: list[str] = []
    saw_text = False

    for page_number, page in enumerate(reader.pages, start=1):
        try:
            try:
                text = page.extract_text(extraction_mode="layout") or ""
            except TypeError:
                text = page.extract_text() or ""
        except Exception as exc:
            warnings.append(f"PDF {page_number}페이지: 텍스트 추출 실패 ({exc})")
            continue

        if not text.strip():
            continue
        saw_text = True
        page_items, warning = _extract_sheet_rows(
            f"PDF {page_number}페이지",
            _pdf_text_rows(text),
        )
        items.extend(page_items)
        if warning:
            warnings.append(warning)

    if not saw_text:
        raise QuoteExtractionError(
            "PDF에 추출 가능한 텍스트 레이어가 없습니다. 스캔 이미지형 PDF로 보이며 현재 단계에서는 "
            "OCR을 자동 실행하지 않습니다. 원본 Excel 또는 텍스트 PDF를 사용하거나 OCR 단계가 필요합니다."
        )

    if items:
        warnings.append(
            "PDF 표는 문서 내부 좌표에 따라 열이 어긋날 수 있습니다. 자동 추출된 제조사·모델·규격·"
            "단가·단위·VAT·배송·설치·옵션·보증·유지보수 조건을 반드시 화면에서 확인·수정하세요."
        )
    else:
        warnings.append(
            "PDF 텍스트는 읽었지만 품목/가격 표를 자동 식별하지 못했습니다. 표 헤더와 열 배치를 "
            "확인하세요."
        )
    return QuoteExtractionResult(items=tuple(items), warnings=tuple(warnings))


def extract_quote_file(path: Path) -> QuoteExtractionResult:
    suffix = path.suffix.casefold()
    if suffix == ".xlsx":
        return extract_excel_quote(path)
    if suffix == ".xls":
        return extract_legacy_excel_quote(path)
    if suffix == ".pdf":
        return extract_pdf_quote(path)
    raise QuoteExtractionError("지원하지 않는 파일 형식입니다. .xlsx/.xls/.pdf만 업로드하세요.")


def quote_item_query(item: QuoteItem) -> ProductQuery:
    return ProductQuery(
        product_name=item.product_name,
        manufacturer=item.manufacturer,
        model_name=item.model_name,
        specification=item.specification,
    )