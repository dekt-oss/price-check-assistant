from decimal import Decimal
from pathlib import Path

import pdfplumber

from purchase_price.services.quote_extraction import extract_quote_file


class _FakePlumberPage:
    def __init__(self, text: str, tables: list[list[list[object | None]]]) -> None:
        self._text = text
        self._tables = tables

    def extract_text(self, **_: object) -> str:
        return self._text

    def extract_tables(self, **_: object) -> list[list[list[object | None]]]:
        return self._tables


class _FakePlumberPdf:
    def __init__(self, pages: list[_FakePlumberPage]) -> None:
        self.pages = pages

    def __enter__(self) -> "_FakePlumberPdf":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def test_multpage_hospital_quote_uses_table_geometry_and_document_context(
    monkeypatch,
    tmp_path: Path,
) -> None:
    page1_table = [
        ["품 명", "규 격", "수 량", "단 가", "공급가액", "세 액", "비고"],
        [
            "가스 마취기(Anesthesia Machine)",
            "Flow-C",
            "1",
            "66,000,000",
            "66,000,000",
            "(포함)",
            "",
        ],
        ["공 급 가 총 액", "", "", "", "60,000,000", "6,000,000", ""],
        ["합 계 금 액", "", "", "", "66,000,000", "", ""],
    ]
    page1 = _FakePlumberPage(
        "가스 마취기(Anesthesia Machine) Flow-C 1 66,000,000 66,000,000 (포함)",
        [page1_table],
    )
    page2 = _FakePlumberPage(
        "\n".join(
            [
                "Manufacturer : Maquet",
                "Multi Purpose Anesthesia System",
                "Model-FLOW-C           1 set",
                "*warranty 3 years",
            ]
        ),
        [],
    )
    page3 = _FakePlumberPage(
        "\n".join(
            [
                "Total (V.A.T) Included ₩66,000,000",
                "1. The installation and operation should be provided by Contractor.",
                (
                    "2. Warranty: Contract of should guarantee three years "
                    "after successful performance."
                ),
                "3. 결제조건: 리스(익월결제)",
                (
                    "4. 기타제안: Water trap(20 ea) & CO2 absorber disposable(24 ea) "
                    "각 2 박스씩 제공"
                ),
            ]
        ),
        [],
    )
    monkeypatch.setattr(pdfplumber, "open", lambda _: _FakePlumberPdf([page1, page2, page3]))

    path = tmp_path / "hospital-quote.pdf"
    path.write_bytes(b"not-used-because-pdfplumber-is-faked")
    result = extract_quote_file(path)

    assert len(result.items) == 1
    item = result.items[0]
    assert item.product_name == "가스 마취기(Anesthesia Machine)"
    assert item.manufacturer == "Maquet"
    assert item.model_name == "FLOW-C"
    assert item.specification == "Flow-C"
    assert item.quantity == Decimal("1")
    assert item.unit == "set"
    assert item.unit_price == Decimal("66000000")
    assert item.total_amount == Decimal("66000000")
    assert item.vat_status == "포함"
    assert item.installation_condition == "Contractor 설치·운영 제공"
    assert item.warranty_condition == "3년"
    assert "Water trap" in item.option_condition
    assert item.other_conditions == "결제조건: 리스(익월결제)"
    assert all(item.specification != "가" for item in result.items)
    assert any("표 경계/좌표 기반" in warning for warning in result.warnings)
