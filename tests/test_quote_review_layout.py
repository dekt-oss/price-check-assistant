from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from purchase_price.services.quote_extraction import QuoteItem
from purchase_price.ui import quote_review_layout as layout
from purchase_price.ui.quote_review_layout import (
    MIN_COMPARABLE_TRADES,
    QUOTE_CHECK_THRESHOLD_PERCENT,
    VERDICT_CHECK,
    VERDICT_IN_RANGE,
    VERDICT_INSUFFICIENT,
    build_item_comparison,
    condition_rows,
    detail_card_html,
    quote_verdict,
    rule_sentence,
    summary_cards_html,
    table_rows,
    verdict_counts,
)

TODAY = date(2026, 10, 9)


def _candidate(price: str, *, unit: str = "대", grade: str = "A", day: str = "2026-03-01"):
    return SimpleNamespace(
        price=Decimal(price),
        unit=unit,
        match_grade=SimpleNamespace(value=grade),
        transaction_date=day,
        supplier="납품사",
        demand_institution="기관",
    )


def _track_b(*candidates, references=(), status: str = "success"):
    return SimpleNamespace(status=status, candidates=tuple(candidates), reference_candidates=tuple(references))


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


def test_rule_constants_are_named_and_stated_in_plain_words() -> None:
    assert QUOTE_CHECK_THRESHOLD_PERCENT == Decimal("20")
    assert MIN_COMPARABLE_TRADES == 3
    sentence = rule_sentence()
    assert "3건 이상" in sentence
    assert "20% 넘게 높으면" in sentence
    assert "판단 부족" in sentence


def test_fewer_than_three_trades_is_not_judged() -> None:
    for count in (0, 1, 2):
        verdict = quote_verdict(
            quote_unit_price=Decimal("100"), median_price=Decimal("50"), comparable_count=count
        )
        assert verdict.kind == VERDICT_INSUFFICIENT
        assert verdict.label == "판단 부족"


def test_quote_far_above_median_needs_a_check_with_the_percent_in_the_label() -> None:
    verdict = quote_verdict(
        quote_unit_price=Decimal("6500000"), median_price=Decimal("4400000"), comparable_count=16
    )
    assert verdict.kind == VERDICT_CHECK
    assert verdict.label == "확인 필요 (가운데 값보다 47.7% 높음)"
    assert verdict.tone == "warn"


def test_verdict_uses_median_percent_not_min_max_range() -> None:
    # Claude's prototype called 6,500,000 "범위 밖" although the highest trade was 6,585,500.
    # Under the highest trade but far above the median is still a check.
    verdict = quote_verdict(
        quote_unit_price=Decimal("6500000"), median_price=Decimal("4400000"), comparable_count=16
    )
    assert verdict.kind == VERDICT_CHECK
    assert "범위 밖" not in verdict.label


def test_threshold_boundary_and_lower_quotes_stay_in_range() -> None:
    at_threshold = quote_verdict(
        quote_unit_price=Decimal("120"), median_price=Decimal("100"), comparable_count=3
    )
    just_above = quote_verdict(
        quote_unit_price=Decimal("120.1"), median_price=Decimal("100"), comparable_count=3
    )
    lower = quote_verdict(quote_unit_price=Decimal("50"), median_price=Decimal("100"), comparable_count=5)
    assert at_threshold.kind == VERDICT_IN_RANGE
    assert just_above.kind == VERDICT_CHECK
    assert lower.kind == VERDICT_IN_RANGE
    assert "50.0% 낮습니다" in lower.reason


def test_missing_quote_price_is_not_judged() -> None:
    verdict = quote_verdict(quote_unit_price=None, median_price=Decimal("100"), comparable_count=9)
    assert verdict.kind == VERDICT_INSUFFICIENT
    assert "단가를 읽지 못해" in verdict.reason


def test_item_comparison_uses_same_product_main_unit_trades_only() -> None:
    track_b = _track_b(
        _candidate("4000000"),
        _candidate("4400000"),
        _candidate("4800000"),
        _candidate("9000000", unit="set"),
        _candidate("1000000", grade="C"),
    )
    comparison = build_item_comparison(0, _item(), track_b, today=TODAY)

    assert comparison.comparable_count == 3
    assert comparison.median_price == Decimal("4400000")
    assert comparison.main_unit == "대"
    assert comparison.other_unit_count == 1
    assert comparison.reference_count == 1
    assert comparison.delta_percent == Decimal("47.7")
    assert comparison.verdict.kind == VERDICT_CHECK
    assert any("단위가 다른 거래 1건" in point for point in comparison.check_points)


def test_item_comparison_widens_the_period_like_the_price_screen() -> None:
    track_b = _track_b(*(_candidate("100", day="2019-05-01") for _ in range(3)))
    comparison = build_item_comparison(0, _item(unit_price=Decimal("100")), track_b, today=TODAY)

    assert comparison.period_label == "전체"
    assert comparison.comparable_count == 3
    assert any("넓혀" in point for point in comparison.check_points)


def test_failed_lookup_is_not_shown_as_zero_result() -> None:
    comparison = build_item_comparison(0, _item(), None, today=TODAY, failed=True)

    assert comparison.verdict.kind == VERDICT_INSUFFICIENT
    assert "불러오지 못했습니다" in comparison.verdict.reason
    row = table_rows([comparison], [_item()])[0]
    assert row["거래 가운데 값"] is None and row["차이 %"] is None
    assert row["판정"] == [VERDICT_INSUFFICIENT]
    assert row["품목 / 모델"] == "M40 · 환자감시장치"


def test_unit_mismatch_and_missing_vat_become_check_points() -> None:
    track_b = _track_b(_candidate("100"), _candidate("110"), _candidate("120"))
    comparison = build_item_comparison(
        0, _item(unit="SET", vat_status="", unit_price=Decimal("110")), track_b, today=TODAY
    )

    assert any("견적 단위(SET)와 거래 단위(대)가 다릅니다" in point for point in comparison.check_points)
    assert any("부가세" in point for point in comparison.check_points)


def test_summary_counts_cards_and_table_rows() -> None:
    check = build_item_comparison(
        0, _item(), _track_b(_candidate("4000000"), _candidate("4400000"), _candidate("4800000")), today=TODAY
    )
    thin = build_item_comparison(
        1, _item(model_name="DFM100", unit_price=Decimal("12000000")), _track_b(_candidate("13200000")), today=TODAY
    )
    ok = build_item_comparison(
        2,
        _item(model_name="A16-DS", unit_price=Decimal("2100000")),
        _track_b(_candidate("2000000"), _candidate("2100000"), _candidate("2200000")),
        today=TODAY,
    )
    counts = verdict_counts([check, thin, ok])
    assert (counts.total, counts.check, counts.insufficient, counts.in_range) == (
        3,
        ("M40",),
        ("DFM100",),
        ("A16-DS",),
    )

    cards = summary_cards_html(counts, file_name="견적서_<3품목>.xlsx")
    assert "견적서_&lt;3품목&gt;.xlsx" in cards
    assert cards.count("pc-metric") == 4

    rows = table_rows([check, thin, ok])
    assert list(rows[0]) == list(layout.TABLE_COLUMNS)
    assert rows[0]["판정"] == [VERDICT_CHECK]
    assert rows[1]["차이 %"] == -9.1
    assert rows[1]["판정"] == [VERDICT_INSUFFICIENT]


def test_detail_card_shows_both_prices_count_unit_and_check_points() -> None:
    comparison = build_item_comparison(
        0, _item(), _track_b(_candidate("4000000"), _candidate("4400000"), _candidate("4800000")), today=TODAY
    )
    card = detail_card_html(comparison, total=3)

    assert "선택한 품목 1 / 3" in card
    assert "6,500,000원" in card and "4,400,000원" in card
    assert "같은 제품 3건" in card and "1대당" in card
    assert "가운데 값보다 +47.7%" in card
    assert "확인할 점" in card


def test_condition_rows_say_what_to_ask_when_the_quote_is_silent() -> None:
    rows = condition_rows(_item(unit="SET", installation_condition="설치 포함"), main_unit="대")
    by_label = {row.label: row for row in rows}

    assert by_label["단위"].status == "거래와 다름"
    assert by_label["설치·운송"].value == "설치 포함"
    assert by_label["보증·유지보수"].status == "견적처에 확인"
