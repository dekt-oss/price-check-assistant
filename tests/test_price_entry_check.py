"""입력 오류 의심: unit prices that cannot be real stay out of every price statistic (2026-10-10).

The real case: HeartOn A16-DS, 속초시, 2024-08-20, 단가 1원 x 수량 1,731,000대 = 총액 1,731,000원
(the purchase was 1대 x 1,731,000원), which made the price rail say "최저 1원".
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from purchase_price.services import category_market as cm
from purchase_price.services.price_entry_check import (
    KIND_SWAPPED,
    KIND_TINY_PRICE,
    KIND_ZERO_PRICE,
    candidate_entry_error,
    entry_error,
)
from purchase_price.ui import result_layout, result_summary, workspace_header
from purchase_price.ui.purchase_workspace import build_purchase_workspace_stats
from purchase_price.ui.quote_review_layout import build_item_comparison, comparable_trade_stats
from purchase_price.ui.track_b_transactions import (
    candidate_counts,
    direct_transaction_rows,
    entry_error_candidates,
    entry_error_rows,
    model_price_group_rows,
    strict_comparison_candidates,
)

SWAPPED_REASON = (
    "단가 1원 · 수량 1,731,000대로 적혀 있어 단가와 수량이 뒤바뀐 입력 오류로 보입니다 — 원문 확인"
)


# ── The rule ──


def test_swapped_one_won_line_is_flagged_with_the_plain_reason() -> None:
    error = entry_error(1, 1731000, 1731000, "대")

    assert error is not None
    assert error.kind == KIND_SWAPPED
    assert error.reason == SWAPPED_REASON


def test_zero_won_is_flagged() -> None:
    error = entry_error(0, 1, 0, "대")

    assert error is not None
    assert error.kind == KIND_ZERO_PRICE
    assert error.reason.startswith("단가 0원")


def test_tiny_price_without_a_swap_pattern_is_flagged_without_claiming_a_swap() -> None:
    error = entry_error(3, 20, 60, "대")

    assert error is not None
    assert error.kind == KIND_TINY_PRICE
    assert "뒤바뀐" not in error.reason
    assert error.reason == "단가 3원 · 수량 20대로 적혀 있어 입력 오류로 보입니다 — 원문 확인"


def test_ten_won_is_the_last_flagged_unit_price() -> None:
    assert entry_error(10, 5, 50, "개") is not None
    assert entry_error(11, 5, 55, "개") is None


def test_cheap_consumables_are_not_flagged() -> None:
    assert entry_error(3000, 100, 300000, "개") is None
    assert entry_error(3000, 1, 3000, "개") is None
    assert entry_error(1980000, 1, 1980000, "대") is None


def test_swap_wording_needs_a_matching_total_and_a_big_quantity() -> None:
    # 5원 x 5,000 = 25,000 matches the total: looks swapped.
    assert entry_error(5, 5000, 25000, "개").kind == KIND_SWAPPED
    # The total does not match quantity x price: still a tiny price, but no claim of a swap.
    assert entry_error(5, 5000, 9000000, "개").kind == KIND_TINY_PRICE
    # Small quantity: not the swap pattern.
    assert entry_error(5, 50, 250, "개").kind == KIND_TINY_PRICE


def test_cheap_bulk_goods_above_ten_won_are_real_prices() -> None:
    # 2026 index: 봉투 24.75원 x 80,000장 and 감응테이프 90원 x 14,000개 are ordinary bulk buying.
    assert entry_error("24.75", 80000, 1980000, "장") is None
    assert entry_error(90, 14000, 1260000, "개") is None
    assert entry_error(11, 650000, 7150000, "SET") is None


def test_missing_unit_price_is_not_judged_and_numbers_are_never_rewritten() -> None:
    assert entry_error(None, 5, 100, "대") is None
    error = entry_error("1", "1,731,000", "1,731,000원", "")
    assert error is not None
    assert error.unit_price == Decimal("1")
    assert error.quantity == Decimal("1731000")
    assert error.reason.startswith("단가 1원 · 수량 1,731,000으로 적혀 있어")


# ── HeartOn-like data ──


def _candidate(
    price: str,
    *,
    quantity: str = "1",
    total: str | None = None,
    unit: str = "대",
    day: str = "2025-03-01",
    supplier: str = "가 상사",
    grade: str = "A",
    institution: str = "기관",
):
    return SimpleNamespace(
        price=Decimal(price),
        quantity=Decimal(quantity),
        total_amount=Decimal(total if total is not None else Decimal(price) * Decimal(quantity)),
        unit=unit,
        match_grade=SimpleNamespace(value=grade),
        transaction_date=day,
        supplier=supplier,
        demand_institution=institution,
        product_title="자동심장충격기",
        manufacturer="메디아나",
        model_name="HeartOn A16-DS",
        specification=None,
        product_id=None,
        detail_code=None,
        transaction_type=None,
        amount_check=None,
        contract_delivery_type=None,
        contract_type=None,
        delivery_condition=None,
        business_name=None,
        source_record_id=None,
        raw_object_key=None,
        match_note=None,
    )


def _heart_on():
    swapped = _candidate(
        "1",
        quantity="1731000",
        total="1731000",
        day="2024-08-20",
        supplier="속초 상사",
        institution="강원특별자치도 속초시",
    )
    normal = [
        _candidate("1650000", day="2025-01-10", supplier="나 상사"),
        _candidate("1700000", day="2025-02-10", supplier="나 상사"),
        _candidate("1800000", day="2025-03-10", supplier="다 상사"),
        _candidate("1980000", day="2025-04-10", supplier="다 상사"),
    ]
    return SimpleNamespace(
        status="success",
        candidates=(swapped, *normal),
        reference_candidates=(),
    ), swapped


def test_flagged_trade_is_out_of_the_a_b_candidates_but_still_listed() -> None:
    track_b, swapped = _heart_on()

    assert swapped not in strict_comparison_candidates(track_b)
    assert len(strict_comparison_candidates(track_b)) == 4
    assert candidate_counts(track_b)[0] == 4
    flagged = entry_error_candidates(track_b)
    assert [candidate for candidate, _error in flagged] == [swapped]
    assert candidate_entry_error(swapped).reason == SWAPPED_REASON
    assert len(direct_transaction_rows(track_b)) == 4


def test_flagged_rows_carry_the_reason_for_the_box() -> None:
    track_b, _swapped = _heart_on()

    rows = entry_error_rows(track_b)

    assert len(rows) == 1
    assert rows[0]["입력 오류 사유"] == SWAPPED_REASON
    assert rows[0]["거래일"] == "2024-08-20"
    assert rows[0]["구매처"] == "강원특별자치도 속초시"
    assert rows[0]["비교수준"] == "입력 오류 의심"


def test_heart_on_stats_no_longer_report_one_won_as_the_lowest_price() -> None:
    track_b, _swapped = _heart_on()

    stats = build_purchase_workspace_stats(track_b=track_b, market_bundle=None, quote_unit_price=None)

    assert stats.min_price == Decimal("1650000")
    assert stats.max_price == Decimal("1980000")
    assert stats.median_price == Decimal("1750000")
    assert stats.direct_count == 4
    assert stats.entry_error_count == 1
    # The swapped line's supplier does not count as a supplier of the product either.
    assert stats.supplier_count == 2
    assert stats.latest_transaction_date == "2025-04-10"


def test_price_groups_and_year_table_ignore_the_flagged_trade() -> None:
    track_b, _swapped = _heart_on()

    groups = model_price_group_rows(track_b)
    years = result_summary.year_summary_rows(direct_transaction_rows(track_b), main_unit="대")

    assert groups[0]["거래건수"] == 4
    assert groups[0]["최저단가"] == "1,650,000원"
    assert [row["연도"] for row in years] == ["2025"]
    assert all("1원" not in str(value) for row in years for value in row.values())
    assert result_summary.unit_group_rows(direct_transaction_rows(track_b))[0]["건수"] == 4


def test_cards_and_headline_say_how_many_were_left_out() -> None:
    track_b, _swapped = _heart_on()
    stats = build_purchase_workspace_stats(track_b=track_b, market_bundle=None, quote_unit_price=None)

    card = workspace_header.price_card(stats)
    conclusion = result_summary.build_conclusion(stats, quote_unit_price=None, unit="대")
    lead = result_layout.lead_view(stats, conclusion, quote=None, unit="대")

    assert "같은 제품 거래 4건" in card.note
    assert "입력 오류 의심 1건 제외" in card.note
    assert "입력 오류 의심 1건 제외" in lead.basis
    assert "1원" not in conclusion.headline
    assert "1,650,000원" in (conclusion.detail or "")


def test_a_product_with_only_flagged_trades_says_so_instead_of_showing_one_won() -> None:
    only = SimpleNamespace(status="success", candidates=(_candidate("1", quantity="500", total="500"),), reference_candidates=())
    stats = build_purchase_workspace_stats(track_b=only, market_bundle=None, quote_unit_price=None)

    conclusion = result_summary.build_conclusion(stats, quote_unit_price=None, unit="대")

    assert stats.direct_count == 0
    assert stats.min_price is None
    assert stats.entry_error_count == 1
    assert "입력 오류 의심" in (conclusion.detail or "")
    assert "입력 오류 의심 1건 제외" in workspace_header.price_card(stats).note


def test_check_panel_and_chip_mention_the_exclusion() -> None:
    points = result_layout.check_points([], direct_count=4, entry_error_count=1)
    chip = result_layout.entry_error_chip(1)

    assert any("입력 오류 의심" in point.text and "1건" in point.text for point in points)
    assert chip is not None and "1건" in chip.text
    assert result_layout.entry_error_chip(0) is None
    assert not any("입력 오류" in point.text for point in result_layout.check_points([], direct_count=4))


def test_box_line_names_the_trade_without_rewriting_numbers() -> None:
    track_b, _swapped = _heart_on()
    row = entry_error_rows(track_b)[0]
    row["사업명"] = "청초호유원지 물놀이터 자동심장충격기 구입"

    line = result_summary.entry_error_line(row)

    assert "2024-08-20" in line
    assert "강원특별자치도 속초시" in line
    assert "사업명 「청초호유원지 물놀이터 자동심장충격기 구입」" in line
    assert "거래 총액 1,731,000원" in line
    assert result_summary.has_banned_term(line + SWAPPED_REASON) is None


# ── 견적서 검토 ──


def test_quote_review_median_and_verdict_ignore_the_flagged_trade() -> None:
    track_b, _swapped = _heart_on()
    today = date(2026, 10, 9)

    stats = comparable_trade_stats(track_b, today=today)

    assert stats.count == 4
    assert stats.low == Decimal("1650000")
    assert stats.median == Decimal("1750000")
    assert stats.entry_error_count == 1

    item = SimpleNamespace(
        product_name="자동심장충격기",
        model_name="HeartOn A16-DS",
        manufacturer="메디아나",
        specification="",
        unit="대",
        quantity=Decimal("1"),
        unit_price=Decimal("2300000"),
        vat_status="VAT 포함",
    )
    comparison = build_item_comparison(0, item, track_b, today=today)

    assert comparison.low_price == Decimal("1650000")
    assert comparison.median_price == Decimal("1750000")
    assert comparison.entry_error_count == 1
    assert comparison.verdict.kind == "확인 필요"
    assert any("입력 오류 의심" in point for point in comparison.check_points)


def test_quote_review_without_flagged_trades_has_no_extra_point() -> None:
    track_b = SimpleNamespace(
        status="success",
        candidates=(_candidate("1650000"), _candidate("1700000"), _candidate("1800000")),
        reference_candidates=(),
    )
    item = SimpleNamespace(
        product_name="x", model_name="y", manufacturer="", specification="", unit="대",
        quantity=Decimal("1"), unit_price=Decimal("1700000"), vat_status="VAT 포함",
    )

    comparison = build_item_comparison(0, item, track_b, today=date(2026, 10, 9))

    assert comparison.entry_error_count == 0
    assert not any("입력 오류" in point for point in comparison.check_points)


# ── 같은 품목 시세 ──


def _market_trade(price: str, *, quantity: str = "1", total: str | None = None, number: str = "R1"):
    return cm.CategoryTrade(
        source_record_id=f"delivery:{number}|change:00|line:1",
        raw_object_key="raw/key.json",
        transaction_date="2025-03-01",
        institution="가 병원",
        manufacturer="메디아나",
        model_name="HeartOn A16-DS",
        quantity=Decimal(quantity),
        unit="대",
        unit_price=Decimal(price),
        total_amount=Decimal(total if total is not None else Decimal(price) * Decimal(quantity)),
        supplier="가 상사",
        business_name="자동심장충격기 구입",
        product_title="저출력심장충격기",
        specification="",
        detail_code="4227250101",
    )


def test_category_market_leaves_flagged_trades_out_of_the_price_level_and_lists_them() -> None:
    trades = [
        _market_trade("1", quantity="1731000", total="1731000", number="BAD"),
        _market_trade("1650000", number="R1"),
        _market_trade("1700000", number="R2"),
        _market_trade("1800000", number="R3"),
    ]

    market = cm.build_category_market(trades, product_name="저출력심장충격기")

    assert market.level.count == 3
    assert market.level.low == Decimal("1650000")
    assert market.level.median == Decimal("1700000")
    assert [row.kind for row in market.trades if not row.is_equipment] == [cm.KIND_ENTRY_ERROR]
    assert market.years[0].low == Decimal("1650000")
    assert len(market.equipment) == 3
    exclusion = next(item for item in market.exclusions if item.kind == cm.KIND_ENTRY_ERROR)
    assert exclusion.label == "입력 오류 의심"
    assert exclusion.count == 1
    assert exclusion.examples == (SWAPPED_REASON,)


def test_category_market_period_keeps_the_exclusion() -> None:
    trades = [
        _market_trade("1", quantity="1731000", total="1731000", number="BAD"),
        _market_trade("1650000", number="R1"),
    ]
    market = cm.build_category_market(trades, product_name="저출력심장충격기")

    inside = cm.within_period(market, date(2025, 1, 1), label="최근 3년")

    assert inside.level.low == Decimal("1650000")
    assert any(item.kind == cm.KIND_ENTRY_ERROR for item in inside.exclusions)
