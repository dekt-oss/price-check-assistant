from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from purchase_price.ui import quote_input as qi
from purchase_price.ui import result_layout as rl
from purchase_price.ui import result_summary as rs


@pytest.mark.parametrize(
    ("typed", "value"),
    [
        ("1800000", "1800000"),
        ("1,800,000", "1800000"),
        ("1,800,000원", "1800000"),
        ("₩ 1,800,000", "1800000"),
        ("250만", "2500000"),
        ("250만원", "2500000"),
        ("2억 5천만", "250000000"),
        ("2억5천만원", "250000000"),
        ("1억 5천", "150000000"),
        ("1.5억", "150000000"),
        ("3만5천", "35000"),
        ("천만", "10000000"),
        ("2억 5000만", "250000000"),
        ("99999999999", "99999999999"),
    ],
)
def test_quote_box_accepts_korean_amounts(typed: str, value: str) -> None:
    parsed = qi.parse_quote_input(typed)
    assert parsed.error is None
    assert parsed.value == Decimal(value)


def test_empty_quote_is_no_quote() -> None:
    assert qi.parse_quote_input("  ").empty


@pytest.mark.parametrize("typed", ["0", "0원", "-5", "-1,000"])
def test_zero_and_negative_quotes_are_refused(typed: str) -> None:
    parsed = qi.parse_quote_input(typed)
    assert parsed.value is None
    assert parsed.error == qi.MSG_NOT_POSITIVE


def test_absurd_quotes_are_capped() -> None:
    parsed = qi.parse_quote_input("100000000001")
    assert parsed.value is None and parsed.error == qi.MSG_TOO_LARGE
    assert qi.parse_quote_input("1,000억").error is None
    assert qi.parse_quote_input("1001억").error == qi.MSG_TOO_LARGE


@pytest.mark.parametrize("typed", ["abc", "1.2.3", "만원짜리", "1e9"])
def test_text_is_refused_with_an_example(typed: str) -> None:
    assert qi.parse_quote_input(typed).error == qi.MSG_NOT_NUMBER


def test_error_message_names_the_previous_value_only_when_there_is_one() -> None:
    assert "직전" not in qi.quote_error_message(qi.MSG_NOT_POSITIVE, None)
    assert "견적 위치는 표시하지 않습니다" in qi.quote_error_message(qi.MSG_NOT_POSITIVE, None)
    assert qi.quote_error_message(qi.MSG_NOT_NUMBER, Decimal("1800000")) == (
        "입력한 견적 단가를 쓸 수 없어 직전에 넣은 1,800,000원으로 비교합니다."
    )
    # The reason sits next to the box; the warning only says what is compared now.
    assert qi.MSG_NOT_NUMBER not in qi.quote_error_message(qi.MSG_NOT_NUMBER, None)


def test_difference_phrase_has_separators_and_switches_to_times() -> None:
    base = Decimal("1980000")
    assert qi.difference_phrase(Decimal("1800000"), base) == "9.1% 낮습니다"
    assert qi.difference_phrase(Decimal("21780000"), base) == "11배 넘게 높습니다"
    assert qi.difference_phrase(Decimal("19800000"), base) == "900.0% 높습니다"
    assert qi.difference_phrase(Decimal("99999999999"), base) == "50,505배 넘게 높습니다"
    assert qi.difference_phrase(base, base) == "같습니다"


def _stats(direct: int, low: str, high: str, mid: str):
    from types import SimpleNamespace

    return SimpleNamespace(
        direct_count=direct,
        min_price=Decimal(low),
        max_price=Decimal(high),
        median_price=Decimal(mid),
        latest_transaction_date="2026-10-07",
        reference_count=0,
        entry_error_count=0,
    )


def test_lead_and_conclusion_never_show_a_five_digit_percentage() -> None:
    stats = _stats(267, "297000", "1980000", "1980000")
    quote = Decimal("99999999999")
    conclusion = rs.build_conclusion(stats, quote_unit_price=quote, unit="대")
    lead = rl.lead_view(stats, conclusion, quote=quote, unit="대")
    assert "50,505배 넘게 높습니다" in lead.headline_html
    assert "5050405" not in lead.headline_html
    assert "50,505배 넘게 높습니다" in (conclusion.quote_line or "")


def test_dashboard_uses_the_quote_parser_and_keeps_the_hidden_label() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")
    assert '"내 견적가 (원)"' in source
    assert "quote_input_ui.parse_quote_input(quote_text)" in source
    assert "quote_input_ui.quote_error_message(" in source
    assert "직전 값으로 비교합니다" not in source
