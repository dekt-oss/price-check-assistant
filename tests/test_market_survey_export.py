from __future__ import annotations

from datetime import datetime
from io import BytesIO
from zoneinfo import ZoneInfo

from openpyxl import load_workbook

from purchase_price.services.market_survey_export import (
    MARKET_SURVEY_EXPORT_SCHEMA,
    build_market_survey_workbook,
)


def _sheet_rows(workbook, title: str) -> list[list[object]]:
    sheet = workbook[title]
    return [list(row) for row in sheet.iter_rows(values_only=True)]


def test_market_survey_export_preserves_direct_research_source_and_identity() -> None:
    payload = build_market_survey_workbook(
        search_identity={
            "검색어": "C101",
            "품목": "채혈기",
            "모델": "C101",
            "식약처 품목번호": "수신 22-2177호",
        },
        quote_context={
            "내 견적가": 500,
            "단위": "개",
            "VAT": "미확인",
            "설치·운송 등 조건": "미확인",
        },
        direct_rows=[
            {
                "가격": "450원",
                "단위": "개",
                "매칭등급": "A",
                "매칭근거": "model_exact_and_product_match",
                "판매처": "공급사A",
                "구매처": "기관A",
                "Source": "나라장터 납품요구",
                "원문근거키": "raw/example.json.gz",
            }
        ],
        research_rows=[
            {
                "가격": "470원",
                "자료성격": "검색 참고",
                "Source": "공개조달 Research",
                "원문": "https://example.invalid/source",
            }
        ],
        supplier_rows=[
            {
                "공급업체": "공급사A",
                "직접거래건수": 1,
                "Source": "나라장터 납품요구",
            }
        ],
        identity_rows=[
            {
                "유형": "신고",
                "식약처 품목번호": "수신 22-2177호",
                "모델": "C101",
                "품목 책임주체": "책임주체A",
                "UDI-DI": "UDI-1",
                "Source": "식약처 제품정보",
            }
        ],
        data_as_of=None,
        generated_at=datetime(2026, 9, 28, 15, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )

    workbook = load_workbook(BytesIO(payload), data_only=True)

    assert workbook.sheetnames == [
        "시장조사 요약",
        "A_B 직접근거",
        "C_Research",
        "조달업체",
        "식약처 Identity",
    ]
    summary = dict(_sheet_rows(workbook, "시장조사 요약"))
    assert summary["Export schema"] == MARKET_SURVEY_EXPORT_SCHEMA
    assert summary["data_as_of"] == "미확인"
    assert "구매검토 보조자료" in summary["주의"]
    assert summary["검색어"] == "C101"
    assert summary["견적.내 견적가"] == 500

    direct = _sheet_rows(workbook, "A_B 직접근거")
    direct_header = direct[0]
    direct_values = dict(zip(direct_header, direct[1], strict=True))
    assert direct_values["매칭등급"] == "A"
    assert direct_values["Source"] == "나라장터 납품요구"
    assert direct_values["원문근거키"] == "raw/example.json.gz"

    research = _sheet_rows(workbook, "C_Research")
    research_values = dict(zip(research[0], research[1], strict=True))
    assert research_values["자료성격"] == "검색 참고"
    assert research_values["원문"] == "https://example.invalid/source"

    identity = _sheet_rows(workbook, "식약처 Identity")
    identity_values = dict(zip(identity[0], identity[1], strict=True))
    assert identity_values["식약처 품목번호"] == "수신 22-2177호"
    assert identity_values["UDI-DI"] == "UDI-1"


def test_market_survey_export_marks_empty_sections_without_inventing_evidence() -> None:
    payload = build_market_survey_workbook(
        search_identity={"검색어": "UNKNOWN"},
        generated_at=datetime(2026, 9, 28, 15, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )
    workbook = load_workbook(BytesIO(payload), data_only=True)

    assert workbook["A_B 직접근거"]["A1"].value == "A/B 직접 비교 가능한 가격근거가 없습니다."
    assert workbook["C_Research"]["A1"].value == "C/Research 참고근거가 없습니다."
    assert workbook["조달업체"]["A1"].value == "A/B 직접근거 기준 조달 납품업체가 없습니다."
    assert workbook["식약처 Identity"]["A1"].value == "연결된 식약처 Identity 근거가 없습니다."
