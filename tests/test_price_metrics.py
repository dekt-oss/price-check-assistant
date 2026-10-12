"""Price metric contract (UX v1.1 P0): golden fixtures, equivalence with the screens, documented gaps.

Fixtures live in tests/fixtures/price/. The contract is services/price_metrics.py; the plain-language
copy is docs/metrics/price.md. When an older path disagrees on purpose, the gap has its own test
named ``test_known_gap_*`` so fixing it later is a visible change.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from purchase_price.domain import MatchGrade
from purchase_price.services import price_metrics as pm
from purchase_price.ui import quote_review_layout as qr
from purchase_price.ui import result_summary as rs
from purchase_price.ui.purchase_workspace import build_purchase_workspace_stats
from purchase_price.ui.track_b_transactions import strict_comparison_candidates

FIXTURES = Path(__file__).parent / "fixtures" / "price"
DOC = Path(__file__).resolve().parents[1] / "docs" / "metrics" / "price.md"
NAMES = (
    "many_single_unit",
    "many_mixed_units",
    "few_trades",
    "zero_trades",
    "entry_errors_and_outlier",
    "unit_changes_by_period",
)
# Judgment words the contract's labels and reasons must never produce (작업지시서 3.5).
JUDGMENT_TERMS = ("적정", "싸다", "싸게", "비싸", "권장", "절감", "대체 가능", "안전한 제품", "추천", "인기")


@dataclass(frozen=True)
class Case:
    name: str
    today: date
    quote: Decimal
    rows: list[dict]

    @property
    def trades(self) -> list[pm.PriceTrade]:
        return [pm.PriceTrade.from_mapping(row) for row in self.rows]

    @property
    def track_b(self) -> SimpleNamespace:
        return SimpleNamespace(
            candidates=tuple(
                SimpleNamespace(
                    source_record_id=row["record_id"],
                    price=Decimal(row["unit_price"]),
                    unit=row["unit"],
                    quantity=Decimal(row["quantity"]),
                    total_amount=Decimal(row["total_amount"]),
                    transaction_date=row["trade_date"],
                    demand_institution=row["institution"],
                    supplier=row["supplier"],
                    match_grade=MatchGrade(row["grade"]),
                )
                for row in self.rows
            ),
            reference_candidates=(),
        )


def load(name: str) -> Case:
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return Case(name, date.fromisoformat(data["today"]), Decimal(data["quote_unit_price"]), data["trades"])


def dashboard_period(case: Case):
    """The result screen's default period: 최근 3년, widened when empty (user did not pick one)."""

    strict = strict_comparison_candidates(case.track_b)
    return rs.choose_period(
        [c.transaction_date for c in strict], requested=None, user_chose=False, today=case.today
    )


def contract(case: Case) -> pm.PriceResult:
    valid = [trade for trade in case.trades if trade.entry_error_reason is None]
    choice = dashboard_period(case)
    return pm.build_price_result(
        case.trades,
        quote_unit_price=case.quote,
        identity_confirmed=True,
        identity_exact=True,
        period_label=choice.label,
        cutoff=choice.cutoff,
        preferred_unit=pm.main_unit(valid),
        data_as_of="2026-10-10",
        today=case.today,
    )


def dashboard(case: Case):
    """What pages/1_대시보드.py does today: period filter, all-period unit preferred, then stats."""

    strict = strict_comparison_candidates(case.track_b)
    choice = dashboard_period(case)
    preferred = rs.main_unit_of(strict)
    in_period = rs.filter_candidates(strict, choice.cutoff)
    split = rs.split_by_main_unit(in_period, preferred=preferred) if preferred else rs.split_by_main_unit(in_period)
    price_stats = build_purchase_workspace_stats(
        track_b=SimpleNamespace(candidates=split.kept, reference_candidates=()),
        market_bundle=None,
        quote_unit_price=case.quote,
    )
    # The header cards (납품업체·구매 기관) use every unit of the period.
    card_stats = build_purchase_workspace_stats(
        track_b=SimpleNamespace(candidates=in_period, reference_candidates=()),
        market_bundle=None,
        quote_unit_price=None,
    )
    return price_stats, card_stats, split


# ── Golden values (hand-checked; see docs/metrics/price.md §3–4) ──

EXPECTED = {
    "many_single_unit": dict(
        confirmed=11, priced=11, errors=0, other=0, unit="대", median="11880000", low="10500000",
        high="11880000", quantity="11", institutions=5, suppliers=3, outliers=0, latest="2026-08-20",
        status=pm.STATUS_IN_RANGE, diff="120000", pct="1.0", level=pm.LEVEL_HIGH, category=False,
    ),
    "many_mixed_units": dict(
        confirmed=18, priced=16, errors=0, other=2, unit="대", median="4400000", low="4389000",
        high="6585500", quantity="16", institutions=14, suppliers=7, outliers=0, latest="2026-09-01",
        status=pm.STATUS_CHECK, diff="2100000", pct="47.7", level=pm.LEVEL_NORMAL, category=False,
    ),
    "few_trades": dict(
        confirmed=2, priced=2, errors=0, other=0, unit="식", median="13050000", low="12900000",
        high="13200000", quantity="2", institutions=2, suppliers=2, outliers=0, latest="2025-04-01",
        status=pm.STATUS_INSUFFICIENT, diff="-1050000", pct="-8.0", level=pm.LEVEL_LIMITED, category=True,
    ),
    "zero_trades": dict(
        confirmed=0, priced=0, errors=0, other=0, unit=None, median=None, low=None, high=None,
        quantity=None, institutions=0, suppliers=0, outliers=0, latest="",
        status=pm.STATUS_INSUFFICIENT, diff=None, pct=None, level=pm.LEVEL_LIMITED, category=True,
    ),
    "entry_errors_and_outlier": dict(
        confirmed=10, priced=8, errors=2, other=0, unit="대", median="1980000", low="1731000",
        high="7920000", quantity="8", institutions=7, suppliers=1, outliers=1, latest="2026-09-10",
        status=pm.STATUS_IN_RANGE, diff="120000", pct="6.1", level=pm.LEVEL_NORMAL, category=False,
    ),
    "unit_changes_by_period": dict(
        confirmed=4, priced=1, errors=0, other=3, unit="set", median="9500000", low="9500000",
        high="9500000", quantity="1", institutions=4, suppliers=2, outliers=0, latest="2026-02-01",
        status=pm.STATUS_INSUFFICIENT, diff="-6200000", pct="-65.3", level=pm.LEVEL_LIMITED, category=True,
    ),
}


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


@pytest.mark.parametrize("name", NAMES)
def test_contract_matches_golden_values(name: str) -> None:
    expected = EXPECTED[name]
    result = contract(load(name))
    summary = result.summary
    assert summary.confirmed_count == expected["confirmed"]
    assert summary.priced_count == expected["priced"]
    assert summary.entry_error_count == expected["errors"]
    assert summary.other_unit_count == expected["other"]
    assert summary.main_unit == expected["unit"]
    assert summary.median == _dec(expected["median"])
    assert summary.low == _dec(expected["low"])
    assert summary.high == _dec(expected["high"])
    assert summary.total_quantity == _dec(expected["quantity"])
    assert summary.institution_count == expected["institutions"]
    assert summary.supplier_count == expected["suppliers"]
    assert summary.outlier_count == expected["outliers"]
    assert summary.latest_date == expected["latest"]
    assert result.comparison.status == expected["status"]
    assert result.comparison.difference_amount == _dec(expected["diff"])
    assert result.comparison.difference_percent == _dec(expected["pct"])
    assert result.evidence.level == expected["level"]
    assert result.show_category_in_conclusion is expected["category"]


@pytest.mark.parametrize("name", NAMES)
def test_contract_matches_result_screen(name: str) -> None:
    """Median, range and counts equal what the 가격 조사 result screen computes today."""

    case = load(name)
    summary = contract(case).summary
    price_stats, card_stats, split = dashboard(case)
    assert summary.median == price_stats.median_price
    assert summary.low == price_stats.min_price
    assert summary.high == price_stats.max_price
    assert summary.priced_count == price_stats.direct_count
    assert summary.main_unit == split.main_unit
    assert summary.other_unit_count == len(split.other)
    assert summary.institution_count == card_stats.demand_institution_count
    assert summary.supplier_count == card_stats.supplier_count
    if price_stats.quote_vs_median_percent is not None:
        assert contract(case).comparison.difference_percent == price_stats.quote_vs_median_percent


@pytest.mark.parametrize("name", [name for name in NAMES if name != "unit_changes_by_period"])
def test_contract_matches_quote_review(name: str) -> None:
    case = load(name)
    result = contract(case)
    stats = qr.comparable_trade_stats(case.track_b, today=case.today)
    assert stats.count == result.summary.priced_count
    assert stats.median == result.summary.median
    verdict = qr.quote_verdict(quote_unit_price=case.quote, median_price=stats.median, comparable_count=stats.count)
    assert {
        qr.VERDICT_IN_RANGE: pm.STATUS_IN_RANGE,
        qr.VERDICT_CHECK: pm.STATUS_CHECK,
        qr.VERDICT_INSUFFICIENT: pm.STATUS_INSUFFICIENT,
    }[verdict.kind] == result.comparison.status


def test_known_gap_quote_review_picks_the_period_unit() -> None:
    """docs/metrics/price.md §6 차이 1: the quote review uses the period's own main unit, the result
    screen (and the contract) keeps the all-period unit. Remove this test when P1 aligns them."""

    case = load("unit_changes_by_period")
    result = contract(case)
    stats = qr.comparable_trade_stats(case.track_b, today=case.today)
    assert (result.summary.main_unit, result.summary.priced_count, result.summary.median) == (
        "set",
        1,
        Decimal("9500000"),
    )
    assert (stats.split.main_unit, stats.count, stats.median) == ("대", 3, Decimal("3100000"))


def test_known_gap_category_groups_machine_units() -> None:
    """§6 차이 3: the same-품목 market treats 대·세트·식·조 as one unit; the same-model price does not."""

    from purchase_price.services.category_market import unit_group

    assert unit_group("set") == unit_group("대") == unit_group("식")
    assert pm.unit_key("set") != pm.unit_key("대")


# ── Rules ──


def test_median_even_count_is_the_mean_of_the_two_middle_values() -> None:
    assert pm.median([Decimal("1"), Decimal("4"), Decimal("2"), Decimal("3")]) == Decimal("2.5")
    assert pm.median([]) is None


def test_undated_trades_stay_in_every_period() -> None:
    trade = pm.PriceTrade.from_mapping({"record_id": "x", "unit_price": "100", "trade_date": ""})
    assert pm.in_period(trade, date(2026, 1, 1))


def test_calculated_unit_price_is_counted_not_priced() -> None:
    trades = [
        pm.PriceTrade.from_mapping({"record_id": "a", "unit_price": "1000", "unit": "대", "trade_date": "2026-01-01"}),
        pm.PriceTrade.from_mapping(
            {"record_id": "b", "unit_price": "9000", "unit": "대", "trade_date": "2026-01-02",
             "unit_price_basis": "calculated_unit_price"}
        ),
    ]
    summary = pm.summarize_same_model(trades)
    assert summary.priced_count == 1
    assert summary.calculated_price_count == 1
    assert summary.median == Decimal("1000")


def test_same_unit_spelled_two_ways_is_listed_once() -> None:
    summary = contract(load("many_mixed_units")).summary
    assert summary.other_units == ("set",)


def test_identity_not_confirmed_never_compares() -> None:
    case = load("many_single_unit")
    summary = pm.summarize_same_model(case.trades)
    comparison = pm.compare_quote(case.quote, summary, identity_confirmed=False)
    assert comparison.status == pm.STATUS_IDENTITY_NEEDED


def test_check_status_starts_above_twenty_percent() -> None:
    summary = pm.summarize_same_model(
        [pm.PriceTrade.from_mapping({"record_id": str(i), "unit_price": "100000", "unit": "대"}) for i in range(3)]
    )
    assert pm.compare_quote(Decimal("120000"), summary).status == pm.STATUS_IN_RANGE
    assert pm.compare_quote(Decimal("120100"), summary).status == pm.STATUS_CHECK


def test_quantity_weighted_mean_needs_every_quantity() -> None:
    rows = [
        {"record_id": "a", "unit_price": "100", "unit": "대", "quantity": "1"},
        {"record_id": "b", "unit_price": "200", "unit": "대", "quantity": "3"},
    ]
    trades = [pm.PriceTrade.from_mapping(row) for row in rows]
    assert pm.quantity_weighted_mean(trades, "대") == Decimal("175")
    missing = [*trades, pm.PriceTrade.from_mapping({"record_id": "c", "unit_price": "300", "unit": "대"})]
    assert pm.quantity_weighted_mean(missing, "대") is None


def test_institution_names_are_not_merged_by_similarity() -> None:
    assert pm.institution_key("부산대학교 병원") == pm.institution_key("부산대학교병원")
    assert pm.institution_key("부산대학교병원") != pm.institution_key("양산부산대학교병원")


def test_data_as_of_older_than_three_days_is_stale() -> None:
    today = date(2026, 10, 12)
    assert not pm.data_as_of_stale("2026-10-09", today=today)
    assert pm.data_as_of_stale("2026-10-08", today=today)
    assert pm.data_as_of_stale(None, today=today)


# ── Wording ──


@pytest.mark.parametrize("name", NAMES)
def test_labels_and_reasons_make_no_judgment(name: str) -> None:
    result = contract(load(name))
    texts = [result.comparison.label, result.comparison.reason, result.evidence.label, *result.evidence.reasons]
    for text in texts:
        assert not any(term in text for term in JUDGMENT_TERMS), text


def test_in_range_label_keeps_the_condition_caveat() -> None:
    assert pm.STATUS_LABELS[pm.STATUS_IN_RANGE].endswith("(조건 미확인)")


@pytest.mark.parametrize("name", NAMES)
def test_current_conclusion_sentence_makes_no_judgment(name: str) -> None:
    case = load(name)
    price_stats, _cards, split = dashboard(case)
    conclusion = rs.build_conclusion(price_stats, quote_unit_price=case.quote, unit=split.main_unit)
    for text in (conclusion.headline, conclusion.detail or "", conclusion.quote_line or ""):
        assert not any(term in text for term in JUDGMENT_TERMS), text


# ── Document and code agree ──


def test_document_states_the_contract_thresholds() -> None:
    doc = DOC.read_text(encoding="utf-8")
    assert pm.MIN_COMPARABLE_TRADES == qr.MIN_COMPARABLE_TRADES == 3
    assert pm.QUOTE_CHECK_THRESHOLD_PERCENT == qr.QUOTE_CHECK_THRESHOLD_PERCENT
    assert pm.OUTLIER_FACTOR == rs.OUTLIER_FACTOR
    assert f"+{pm.QUOTE_CHECK_THRESHOLD_PERCENT}%" in doc
    assert f"가격 계산 {pm.EVIDENCE_HIGH_MIN_PRICED}건 이상" in doc
    assert f"구매 기관 {pm.EVIDENCE_HIGH_MIN_INSTITUTIONS}곳 이상" in doc
    assert f"{pm.DATA_AS_OF_STALE_DAYS}일 넘게" in doc
    assert f"{pm.OUTLIER_FACTOR}배" in doc
    for label in pm.STATUS_LABELS.values():
        assert label in doc
    for label in pm.LEVEL_LABELS.values():
        assert label in doc
