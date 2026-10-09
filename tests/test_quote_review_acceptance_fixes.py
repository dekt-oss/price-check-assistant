"""견적서 검토 production acceptance fixes: plain read errors, one trade basis, split name columns."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import streamlit as st

from purchase_price.domain import MatchGrade
from purchase_price.services.quote_extraction import QuoteItem
from purchase_price.services.quote_upload_security import temporary_quote_upload
from purchase_price.ui import quote_review_layout as layout
from purchase_price.ui import quote_review_steps
from purchase_price.ui.quote_item_intelligence import (
    PERMIT_VS_TRADES_NOTE,
    build_quote_item_intelligence_summary,
    quote_item_intelligence_rows,
)
from purchase_price.ui.quote_review_layout import build_item_comparison, table_rows
from purchase_price.ui.quote_review_state import QuoteReviewState
from purchase_price.ui.result_summary import has_banned_term

TODAY = date(2026, 10, 9)


def _candidate(price: str, *, unit: str = "대", grade: str = "A", day: str = "2026-03-01"):
    return SimpleNamespace(
        price=Decimal(price),
        unit=unit,
        match_grade=MatchGrade(grade),
        transaction_date=day,
        supplier="납품사",
        demand_institution="기관",
    )


def _track_b(*candidates, status: str = "success"):
    return SimpleNamespace(status=status, candidates=tuple(candidates), reference_candidates=())


def _item(**overrides) -> QuoteItem:
    values = {
        "source_sheet": "Sheet1",
        "source_row": 2,
        "product_name": "환자감시장치",
        "manufacturer": "(주)메디아나",
        "model_name": "M40",
        "unit": "대",
        "quantity": Decimal("2"),
        "unit_price": Decimal("6500000"),
        "vat_status": "VAT 포함",
    }
    values.update(overrides)
    return QuoteItem(**values)


# ── 1. unreadable files ──


class _Upload:
    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


@pytest.mark.parametrize(
    "name", ["깨진.xlsx", "깨진.xls", "스캔.pdf", "사진.PNG", "사진.jpg", "메모.txt", "확장자없음"]
)
def test_friendly_read_error_is_plain_korean(name: str) -> None:
    message = quote_review_steps.friendly_read_error(name)

    assert re.search(r"[가-힣]", message)
    assert not re.search(r"zip|Error|Exception|traceback", message, re.IGNORECASE)


def test_broken_excel_shows_only_the_korean_sentence_and_logs_the_cause(monkeypatch, caplog) -> None:
    shown: list[str] = []
    fake_state: dict[str, object] = {}
    monkeypatch.setattr(st, "error", lambda text: shown.append(str(text)))
    monkeypatch.setattr(st, "session_state", fake_state)
    state = QuoteReviewState()

    with caplog.at_level("WARNING"):
        quote_review_steps._store_extraction(_Upload("깨진.xlsx", b"not a workbook" * 20), state)

    assert shown == [quote_review_steps.friendly_read_error("깨진.xlsx")]
    assert state.extraction is None and state.items == []
    assert fake_state[quote_review_steps.READ_ERROR_SESSION_KEY] == shown[0]
    assert any("not a zip file" in record.getMessage() for record in caplog.records)


def test_quote_page_can_keep_the_error_off_the_screen(monkeypatch) -> None:
    shown: list[str] = []
    fake_state: dict[str, object] = {}
    monkeypatch.setattr(st, "error", lambda text: shown.append(str(text)))
    monkeypatch.setattr(st, "session_state", fake_state)

    quote_review_steps._store_extraction(
        _Upload("깨진.xlsx", b"not a workbook" * 20), QuoteReviewState(), show_error=False
    )

    assert shown == []
    assert fake_state[quote_review_steps.READ_ERROR_SESSION_KEY]


@pytest.mark.parametrize("name", ["quote.png", "quote.JPG", "quote.jpeg"])
def test_temporary_upload_accepts_the_image_types_the_uploader_offers(name: str) -> None:
    with temporary_quote_upload(_Upload(name, b"x")) as path:
        assert path.exists()


# ── 3. one trade basis for the table, the card and the folded status list ──


def test_trade_stats_keep_other_unit_trades_out_of_the_range() -> None:
    # M40 on real data: 16 trades in 대 and 2 in set; the set trades never enter the range.
    trades = [_candidate(str(4_400_000 + step * 100_000)) for step in range(16)]
    trades += [_candidate("30000000", unit="SET"), _candidate("36513000", unit="SET")]
    stats = layout.comparable_trade_stats(_track_b(*trades), today=TODAY)

    assert stats.count == 16
    assert stats.main_unit == "대"
    assert stats.other_count == 2
    assert stats.other_units == ("SET",)
    assert stats.high == Decimal("5900000")


def test_item_comparison_and_trade_stats_agree() -> None:
    track_b = _track_b(_candidate("100"), _candidate("110"), _candidate("120"), _candidate("900", unit="SET"))
    comparison = build_item_comparison(0, _item(), track_b, today=TODAY)
    stats = layout.comparable_trade_stats(track_b, today=TODAY)

    assert (comparison.comparable_count, comparison.median_price) == (stats.count, stats.median)
    assert (comparison.low_price, comparison.high_price) == (stats.low, stats.high)
    assert comparison.other_unit_count == stats.other_count


def test_item_status_row_uses_the_same_trades_as_the_comparison_table() -> None:
    track_b = _track_b(
        _candidate("4400000"), _candidate("6585500"), _candidate("36513000", unit="SET"), status="success"
    )
    summary = build_quote_item_intelligence_summary(
        item=_item(), track_b=track_b, mfds_workspace=None, mfds_identity=None
    )
    row = quote_item_intelligence_rows([(0, "환자감시장치", summary)])[0]

    assert row["나라장터 같은 모델 거래"] == "2건 · 1대 기준 4,400,000 ~ 6,585,500원"
    assert row["단위가 다른 거래"] == "1건(SET) · 따로 셈"
    assert "36,513,000" not in str(list(row.values()))


def test_status_wording_has_no_developer_terms_and_explains_permit_vs_trades() -> None:
    summary = build_quote_item_intelligence_summary(
        item=_item(), track_b=_track_b(), mfds_workspace=None, mfds_identity=None
    )
    row = quote_item_intelligence_rows([(0, "환자감시장치", summary)])[0]

    assert has_banned_term(" ".join((*row, *map(str, row.values()), PERMIT_VS_TRADES_NOTE))) is None
    assert "허가 목록" in PERMIT_VS_TRADES_NOTE and "나라장터" in PERMIT_VS_TRADES_NOTE
    for developer_word in ("Median", "can_enter", "pair", "직접가격"):
        assert developer_word not in " ".join((*row, *map(str, row.values()), PERMIT_VS_TRADES_NOTE))


# ── stale modules after a deploy ──


def test_quote_page_reloads_modules_that_production_may_still_hold_old() -> None:
    import importlib
    import re as _re
    from pathlib import Path

    page = Path("pages/2_견적_검토.py").read_text(encoding="utf-8")
    pairs = _re.findall(r'\("(purchase_price\.[\w.]+)", "(\w+)"\)', page)

    assert len(pairs) >= 8
    for module_name, marker in pairs:
        assert hasattr(importlib.import_module(module_name), marker), (module_name, marker)
    # reloaded in dependency order: the table module before the page module that imports it
    names = [name for name, _ in pairs]
    assert names.index("purchase_price.ui.quote_review_layout") < names.index(
        "purchase_price.ui.quote_market_research"
    )


# ── 4. model and item name in separate columns ──


def test_table_rows_put_model_and_item_name_in_separate_columns() -> None:
    comparison = build_item_comparison(0, _item(), _track_b(_candidate("100")), today=TODAY)
    row = table_rows([comparison], [_item(model_name="HeartOn A16-DS", product_name="자동심장충격기")])[0]
    assert row["모델"] == "HeartOn A16-DS" and row["품명"] == "자동심장충격기"
    assert list(row) == list(layout.TABLE_COLUMNS)
    assert set(layout.COMPACT_TABLE_COLUMNS) <= set(layout.TABLE_COLUMNS)

    nameless = table_rows([comparison], [_item(model_name="", product_name="극초단파치료시스템")])[0]
    assert nameless["모델"] == "—" and nameless["품명"] == "극초단파치료시스템"
