"""9100c NXT (production check 2026-10-10): 2 trades in 대 (2021, 2023) and 1 in 식 (2026)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from purchase_price.ui import result_layout as rl
from purchase_price.ui import result_summary as rs


def _cand(unit: str, price: str, when: str):
    return SimpleNamespace(unit=unit, price=Decimal(price), transaction_date=when)


ALL = [
    _cand("대", "27500000", "2021-12-01"),
    _cand("대", "32000000", "2023-11-24"),
    _cand("식", "108300000", "2026-07-31"),
]
RECENT_3Y = ALL[1:]


def test_main_unit_over_all_periods_is_the_most_common_one() -> None:
    assert rs.main_unit_of(ALL) == "대"
    # On a tie the most recent trade's unit decides, never the unit's spelling.
    assert rs.main_unit_of(RECENT_3Y) == "식"
    assert rs.main_unit_of([]) is None


def test_preferred_unit_keeps_every_period_on_the_same_unit() -> None:
    preferred = rs.main_unit_of(ALL)
    recent = rs.split_by_main_unit(RECENT_3Y, preferred=preferred)
    assert recent.main_unit == "대"
    assert [c.price for c in recent.kept] == [Decimal("32000000")]
    assert recent.other_units == ("식",)
    assert recent.unit_changed is False
    whole = rs.split_by_main_unit(ALL, preferred=preferred)
    assert whole.main_unit == "대" and len(whole.other) == 1


def test_period_without_the_preferred_unit_says_the_basis_moved() -> None:
    only_set = [_cand("식", "108300000", "2026-07-31")]
    split = rs.split_by_main_unit(only_set, preferred="대")
    assert split.main_unit == "식"
    assert split.unit_changed is True
    note = rl.unit_change_note(split, "대", "최근 1년")
    assert note.startswith("기간에 따라 기준 단위가 바뀝니다.")
    assert "최근 1년에는 대 단위 거래가 없어 식 단위로 셉니다" in note
    assert rl.unit_change_note(rs.split_by_main_unit(ALL, preferred="대"), "대", "전체") == ""


def test_outliers_need_three_comparable_trades() -> None:
    two = [{"가격": "27,500,000원"}, {"가격": "108,300,000원"}]
    assert rs.comparable_outlier_rows(two, Decimal("27500000")) == []
    three = [{"가격": "1,000,000원"}, {"가격": "1,100,000원"}, {"가격": "4,000,000원"}]
    assert [row["가격"] for row in rs.comparable_outlier_rows(three, Decimal("1100000"))] == ["4,000,000원"]


def test_counts_add_up_between_header_period_and_other_units() -> None:
    assert rl.trade_count_note(
        all_period_count=3, period_count=2, period_label="최근 3년", other_unit_count=1, other_units=("식",)
    ) == "같은 제품 거래 3건 (전체 기간) · 최근 3년 2건, 그중 단위 다른 1건(식)"
    assert rl.trade_count_note(
        all_period_count=3, period_count=3, period_label="전체", other_unit_count=1, other_units=("식",)
    ) == "같은 제품 거래 3건 (전체 기간) · 그중 단위 다른 1건(식)"
    assert rl.trade_count_note(all_period_count=267, period_count=267, period_label="최근 3년") == (
        "같은 제품 거래 267건 (전체 기간)"
    )
    assert rl.other_unit_suffix(1, ("식",)) == " · 단위 다른 1건(식) 포함"
    assert rl.other_unit_suffix(0) == ""


def test_dashboard_wires_the_stable_unit_and_the_count_note() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")
    assert "all_period_unit = result_summary_ui.main_unit_of(strict_comparison_candidates(track_b))" in source
    assert "_main_unit_view(track_b, preferred_unit=all_period_unit)" in source
    # The all-period unit is chosen before the period filter replaces track_b.
    assert source.index("all_period_unit = result_summary_ui.main_unit_of(") < source.index(
        "track_b, direct_rows, reference_rows, period_choice = _apply_search_period("
    )
    assert "result_layout_ui.unit_change_note(unit_split, all_period_unit, period_choice.label)" in source
    assert "result_layout_ui.trade_count_note(" in source
    assert '("purchase_price.ui.result_summary", "SEARCH_FIXES_V1")' in source
    assert '("purchase_price.ui.result_layout", "RESULT_LAYOUT_SEARCH_FIXES_V1")' in source
    assert rs.SEARCH_FIXES_V1 is True and rl.RESULT_LAYOUT_SEARCH_FIXES_V1 is True


def test_empty_state_hint_does_not_mislead_for_permits() -> None:
    html = rl.not_found_html("제허19-999")
    assert "모델명은 띄어쓰기와 하이픈(-)을 빼도 됩니다" in html
    assert "‘제허 19-527 호’처럼" in html
