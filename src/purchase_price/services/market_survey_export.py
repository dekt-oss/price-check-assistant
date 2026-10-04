from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

MARKET_SURVEY_EXPORT_SCHEMA = "workspace-v3-market-survey-xlsx-v1"
DEFAULT_CAUTION = (
    "본 자료는 구매검토 보조자료입니다. 가격·단위·VAT·설치·운송·옵션·보증 등 "
    "조건 동일성을 원문에서 확인한 뒤 사용하세요. 시스템이 구매 여부나 업체를 결정하지 않습니다."
)


def _excel_value(value: Any) -> Any:
    if value is None:
        return "미확인"
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _ordered_columns(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            key_text = str(key)
            if key_text not in seen:
                seen.add(key_text)
                columns.append(key_text)
    return columns


def _append_table_sheet(
    workbook: Workbook,
    *,
    title: str,
    rows: Sequence[Mapping[str, Any]],
    empty_message: str,
) -> None:
    sheet = workbook.create_sheet(title=title)
    if not rows:
        sheet["A1"] = empty_message
        sheet["A1"].alignment = Alignment(wrap_text=True, vertical="top")
        sheet.column_dimensions["A"].width = 80
        return

    columns = _ordered_columns(rows)
    for column_index, name in enumerate(columns, start=1):
        cell = sheet.cell(row=1, column=column_index, value=name)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="top")

    for row_index, row in enumerate(rows, start=2):
        for column_index, name in enumerate(columns, start=1):
            sheet.cell(
                row=row_index,
                column=column_index,
                value=_excel_value(row.get(name)),
            ).alignment = Alignment(wrap_text=True, vertical="top")

    for column_index, name in enumerate(columns, start=1):
        longest = max(
            [len(str(name))]
            + [len(str(_excel_value(row.get(name)))) for row in rows]
        )
        sheet.column_dimensions[get_column_letter(column_index)].width = min(
            max(longest + 2, 12), 48
        )
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions


def build_market_survey_workbook(
    *,
    search_identity: Mapping[str, Any],
    quote_context: Mapping[str, Any] | None = None,
    direct_rows: Sequence[Mapping[str, Any]] = (),
    research_rows: Sequence[Mapping[str, Any]] = (),
    supplier_rows: Sequence[Mapping[str, Any]] = (),
    identity_rows: Sequence[Mapping[str, Any]] = (),
    data_as_of: str | None = None,
    caution: str = DEFAULT_CAUTION,
    generated_at: datetime | None = None,
) -> bytes:
    """Build the Workspace V3 market-survey Excel attachment.

    data_as_of is deliberately caller-supplied. When the connected source does not expose
    a trustworthy as-of timestamp, callers should pass None rather than infer one from
    transaction dates or export time.
    """

    generated_at = generated_at or datetime.now(ZoneInfo("Asia/Seoul"))
    workbook = Workbook()
    summary = workbook.active
    summary.title = "시장조사 요약"

    summary_rows = [
        ("Export schema", MARKET_SURVEY_EXPORT_SCHEMA),
        ("보고서 생성일시", generated_at.isoformat()),
        ("data_as_of", data_as_of or "미확인"),
        ("주의", caution),
    ]
    summary_rows.extend(
        (str(key), _excel_value(value)) for key, value in search_identity.items()
    )
    if quote_context:
        summary_rows.extend(
            (f"견적.{key}", _excel_value(value))
            for key, value in quote_context.items()
        )

    for row_index, (label, value) in enumerate(summary_rows, start=1):
        summary.cell(row=row_index, column=1, value=label).font = Font(bold=True)
        summary.cell(row=row_index, column=2, value=value).alignment = Alignment(
            wrap_text=True,
            vertical="top",
        )
    summary.column_dimensions["A"].width = 24
    summary.column_dimensions["B"].width = 92

    _append_table_sheet(
        workbook,
        title="A_B 직접근거",
        rows=direct_rows,
        empty_message="A/B 직접 비교 가능한 가격근거가 없습니다.",
    )
    _append_table_sheet(
        workbook,
        title="C_Research",
        rows=research_rows,
        empty_message="C/Research 참고근거가 없습니다.",
    )
    _append_table_sheet(
        workbook,
        title="조달업체",
        rows=supplier_rows,
        empty_message="A/B 직접근거 기준 조달 납품업체가 없습니다.",
    )
    _append_table_sheet(
        workbook,
        title="식약처 Identity",
        rows=identity_rows,
        empty_message="연결된 식약처 Identity 근거가 없습니다.",
    )

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
