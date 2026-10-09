from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from purchase_price.ui import result_summary as rs

TODAY = date(2026, 10, 9)


def test_three_years_is_the_default_and_counts_back_from_today() -> None:
    choice = rs.choose_period(["2026-09-21", "2022-05-01"], requested=None, user_chose=False, today=TODAY)

    assert choice.label == "최근 3년"
    assert choice.cutoff == date(2023, 10, 10)
    assert choice.note is None
    assert rs.period_caption(choice) == "거래 기간 · 최근 3년 (2023-10-10 이후 거래)"


def test_no_trade_in_three_years_widens_to_five_then_everything() -> None:
    five = rs.choose_period(["2022-05-01"], requested=None, user_chose=False, today=TODAY)
    everything = rs.choose_period(["2021-02-01"], requested=None, user_chose=False, today=TODAY)

    assert five.label == "최근 5년" and five.cutoff == date(2021, 10, 10)
    assert five.note == "최근 3년 안에는 같은 제품 거래가 없어 최근 5년으로 넓혀 보여줍니다."
    assert everything.label == "전체" and everything.cutoff is None


def test_a_period_the_reader_picked_is_kept_even_when_empty() -> None:
    choice = rs.choose_period(["2022-05-01"], requested="최근 3년", user_chose=True, today=TODAY)

    assert choice.label == "최근 3년" and choice.note is None


def test_filters_keep_trades_inside_the_period_and_undated_ones() -> None:
    cutoff = date(2023, 10, 10)
    old = SimpleNamespace(transaction_date="2022-01-05")
    new = SimpleNamespace(transaction_date="2025-01-05")
    undated = SimpleNamespace(transaction_date=None)

    assert rs.filter_candidates([old, new, undated], cutoff) == (new, undated)
    assert rs.filter_rows([{"거래일": "2023-10-09"}, {"거래일": "2023-10-10"}], cutoff) == [
        {"거래일": "2023-10-10"}
    ]
    assert rs.filter_candidates([old], None) == (old,)


def test_leap_day_cutoff_does_not_crash() -> None:
    assert rs.period_cutoff(3, date(2028, 2, 29)) == date(2025, 3, 1)


def test_year_rows_are_newest_first_and_never_mix_units() -> None:
    rows = [
        {"거래일": "2026-09-21", "가격": "4,400,000원", "단위": "대", "수량": "2"},
        {"거래일": "2026-04-28", "가격": "6,585,500원", "단위": "대", "수량": "1"},
        {"거래일": "2026-09-28", "가격": "36,513,000원", "단위": "set", "수량": "2"},
        {"거래일": "2024-03-02", "가격": "4,100,000원", "단위": "대", "수량": "3"},
    ]

    table = rs.year_summary_rows(rows, main_unit="대")

    assert [row["연도"] for row in table] == ["2026", "2024"]
    assert table[0]["거래 건수"] == 3
    assert table[0]["1대당 중앙값"] == "5,492,750원"
    assert table[0]["1대당 최저~최고"] == "4,400,000원 ~ 6,585,500원"
    assert table[0]["다른 단위 거래"] == "1건"
    assert table[0]["총수량"] == "3 대"
    assert table[1]["1대당 중앙값"] == "4,100,000원"
