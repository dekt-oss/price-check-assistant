from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pdfplumber
import pypdf

from purchase_price.services.quote_extraction import extract_quote_file


def _word(text: str, x0: float, x1: float, top: float) -> dict[str, object]:
    return {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + 8}


def _header_words() -> list[dict[str, object]]:
    return [
        _word("품", 10, 18, 10),
        _word("명", 20, 28, 10),
        _word("규", 155, 163, 10),
        _word("격", 165, 173, 10),
        _word("수", 255, 263, 10),
        _word("량", 265, 273, 10),
        _word("단", 325, 333, 10),
        _word("가", 335, 343, 10),
        _word("금", 430, 438, 10),
        _word("액", 440, 448, 10),
    ]


class _FakePlumberPage:
    def __init__(
        self,
        *,
        text: str,
        words: list[dict[str, object]],
        tables: list[list[list[object | None]]] | None = None,
    ) -> None:
        self._text = text
        self._words = words
        self._tables = tables or []

    def extract_text(self, **_: object) -> str:
        return self._text

    def extract_tables(self, **_: object) -> list[list[list[object | None]]]:
        return self._tables

    def extract_words(self, **_: object) -> list[dict[str, object]]:
        return self._words


class _FakePlumberPdf:
    def __init__(self, pages: list[_FakePlumberPage]) -> None:
        self.pages = pages

    def __enter__(self) -> _FakePlumberPdf:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class _FakePyPdfPage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self, **_: object) -> str:
        return self._text


class _FakePyPdfReader:
    def __init__(self, texts: list[str]) -> None:
        self.pages = [_FakePyPdfPage(text) for text in texts]


def _patch_pdf_readers(monkeypatch, pages: list[_FakePlumberPage]) -> None:
    monkeypatch.setattr(pdfplumber, "open", lambda _: _FakePlumberPdf(pages))
    monkeypatch.setattr(
        pypdf,
        "PdfReader",
        lambda _: _FakePyPdfReader([page._text for page in pages]),
    )


def test_line_less_pdf_uses_split_header_word_geometry(monkeypatch, tmp_path: Path) -> None:
    words = _header_words() + [
        _word("Infusion", 10, 55, 30),
        _word("Pump", 58, 90, 30),
        _word("IP-200", 155, 205, 30),
        _word("2", 260, 268, 30),
        _word("1,250,000", 315, 390, 30),
        _word("2,500,000", 420, 500, 30),
        _word("합계", 10, 38, 50),
        _word("2,500,000", 420, 500, 50),
    ]
    page = _FakePlumberPage(
        text="품 명 규 격 수 량 단 가 금 액\nInfusion Pump IP-200 2 1,250,000 2,500,000",
        words=words,
    )
    _patch_pdf_readers(monkeypatch, [page])
    path = tmp_path / "line-less.pdf"
    path.write_bytes(b"fixture")

    result = extract_quote_file(path)

    assert len(result.items) == 1
    item = result.items[0]
    assert item.product_name == "Infusion Pump"
    assert item.specification == "IP-200"
    assert item.quantity == Decimal("2")
    assert item.unit_price == Decimal("1250000")
    assert item.total_amount == Decimal("2500000")
    assert any("단어 X/Y 좌표" in warning for warning in result.warnings)


def test_word_geometry_merges_wrapped_identity_into_following_price_row(
    monkeypatch, tmp_path: Path
) -> None:
    words = _header_words() + [
        _word("Multi", 10, 42, 30),
        _word("Purpose", 45, 88, 30),
        _word("Anesthesia", 10, 65, 40),
        _word("System", 68, 92, 40),
        _word("FLOW-C", 155, 205, 40),
        _word("1", 260, 268, 40),
        _word("66,000,000", 315, 395, 40),
        _word("66,000,000", 420, 505, 40),
    ]
    page = _FakePlumberPage(
        text="Multi Purpose\nAnesthesia System FLOW-C 1 66,000,000 66,000,000",
        words=words,
    )
    _patch_pdf_readers(monkeypatch, [page])
    path = tmp_path / "wrapped.pdf"
    path.write_bytes(b"fixture")

    result = extract_quote_file(path)

    assert len(result.items) == 1
    item = result.items[0]
    assert item.product_name == "Multi Purpose Anesthesia System"
    assert item.specification == "FLOW-C"
    assert item.unit_price == Decimal("66000000")
    assert item.total_amount == Decimal("66000000")


def test_ruled_table_wins_over_conflicting_word_fallback(monkeypatch, tmp_path: Path) -> None:
    table = [
        ["품명", "규격", "수량", "단가", "금액"],
        ["정상 장비", "GOOD-1", "1", "1,000,000", "1,000,000"],
    ]
    conflicting_words = _header_words() + [
        _word("오인", 10, 40, 30),
        _word("BAD-9", 155, 205, 30),
        _word("1", 260, 268, 30),
        _word("9,999,999", 315, 395, 30),
        _word("9,999,999", 420, 505, 30),
    ]
    page = _FakePlumberPage(
        text="품명 규격 수량 단가 금액\n정상 장비 GOOD-1 1 1,000,000 1,000,000",
        words=conflicting_words,
        tables=[table],
    )
    _patch_pdf_readers(monkeypatch, [page])
    path = tmp_path / "ruled.pdf"
    path.write_bytes(b"fixture")

    result = extract_quote_file(path)

    assert len(result.items) == 1
    assert result.items[0].product_name == "정상 장비"
    assert result.items[0].specification == "GOOD-1"
    assert result.items[0].unit_price == Decimal("1000000")
