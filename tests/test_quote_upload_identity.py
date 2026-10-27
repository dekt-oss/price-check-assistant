"""A revised quote sent under the same file name is read again, not served from the previous one."""

from __future__ import annotations

from decimal import Decimal
from io import BytesIO
from pathlib import Path

import streamlit as st
from openpyxl import Workbook

from purchase_price.services.quote_upload_security import upload_fingerprint
from purchase_price.ui import quote_review_steps
from purchase_price.ui.quote_review_state import QuoteReviewState

ROOT = Path(__file__).resolve().parents[1]


class _Upload:
    def __init__(self, name: str, data: bytes) -> None:
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


def _quote_bytes(model: str, unit_price: int) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["품명", "제조사", "모델명", "규격", "수량", "단위", "단가", "금액", "부가세"])
    sheet.append(["SYNTH-DEVICE", "SYNTH-MAKER", model, "SYNTH-SPEC", 1, "set", unit_price, unit_price, "포함"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_same_name_with_new_content_is_extracted_again(monkeypatch) -> None:
    monkeypatch.setattr(st, "session_state", {})
    state = QuoteReviewState()
    first = _Upload("same-quote.xlsx", _quote_bytes("SYNTH-REVIEW-001", 123456))
    revised = _Upload("same-quote.xlsx", _quote_bytes("SYNTH-REVIEW-002", 654321))

    assert quote_review_steps.needs_extraction(first, state)
    quote_review_steps._store_extraction(first, state)
    assert [item.model_name for item in state.items] == ["SYNTH-REVIEW-001"]
    state.item_confirmed[0] = True

    assert not quote_review_steps.needs_extraction(first, state)
    assert not quote_review_steps.needs_extraction(_Upload("renamed.xlsx", first.getvalue()), state)
    assert quote_review_steps.needs_extraction(revised, state)

    quote_review_steps._store_extraction(revised, state)
    assert [item.model_name for item in state.items] == ["SYNTH-REVIEW-002"]
    assert state.items[0].unit_price == Decimal("654321")
    assert state.item_confirmed == {0: False}
    assert state.file_fingerprint == upload_fingerprint(revised)


def test_failed_read_forgets_the_previous_fingerprint(monkeypatch) -> None:
    monkeypatch.setattr(st, "session_state", {})
    monkeypatch.setattr(st, "error", lambda text: None)
    state = QuoteReviewState()
    good = _Upload("quote.xlsx", _quote_bytes("SYNTH-REVIEW-001", 123456))
    quote_review_steps._store_extraction(good, state)

    quote_review_steps._store_extraction(_Upload("quote.xlsx", b"not a workbook" * 20), state)

    assert state.file_fingerprint is None
    assert quote_review_steps.needs_extraction(good, state)


def test_no_screen_decides_a_new_upload_by_its_name_alone() -> None:
    sources = [
        ROOT / "pages" / "1_대시보드.py",
        ROOT / "src" / "purchase_price" / "ui" / "quote_market_research.py",
        ROOT / "src" / "purchase_price" / "ui" / "quote_review_steps.py",
    ]
    for path in sources:
        source = path.read_text(encoding="utf-8")
        assert "file_name != uploaded.name" not in source, path.name
        assert "== uploaded.name" not in source, path.name
