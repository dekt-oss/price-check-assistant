from __future__ import annotations

from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
UAT_PAGE = ROOT / "pages" / "13_견적추출_UAT.py"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _synthetic_quote_bytes() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Quote"
    sheet.append(
        [
            "품명",
            "제조사",
            "모델명",
            "규격",
            "수량",
            "단위",
            "단가",
            "금액",
            "부가세",
            "배송조건",
            "설치조건",
            "옵션조건",
            "보증기간",
            "유지보수조건",
            "기타조건",
        ]
    )
    sheet.append(
        [
            "SYNTH-UAT-DEVICE",
            "SYNTH-MAKER",
            "SYNTH-MODEL-1",
            "SYNTH-SPEC-1",
            1,
            "set",
            1000000,
            1000000,
            "포함",
            "SYNTH-DELIVERY-INCLUDED",
            "SYNTH-INSTALLATION-INCLUDED",
            "SYNTH-OPTION-NONE",
            "SYNTH-WARRANTY-3Y",
            "SYNTH-MAINTENANCE-1Y",
            "SYNTH-OTHER-CONDITION",
        ]
    )
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_quote_uat_page_survives_real_xlsx_upload() -> None:
    app = AppTest.from_file(str(UAT_PAGE), default_timeout=20)
    app.run()
    assert list(app.exception) == []
    assert len(app.file_uploader) == 1

    app.file_uploader[0].upload(
        "synthetic-quote-uat.xlsx",
        _synthetic_quote_bytes(),
        XLSX_MIME,
    )
    app.run(timeout=30)

    errors = [repr(item.value) for item in app.exception]
    assert errors == [], "Quote UAT upload runtime exception: " + " | ".join(errors)
    assert any(metric.label == "자동 추출 품목" and str(metric.value) == "1" for metric in app.metric)
