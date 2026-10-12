"""기간별 가격 (UX v1.1 P3a): granularity choice, no false trend, chart data equals the table."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from purchase_price.services import price_metrics as pm
from purchase_price.ui import price_trend as ui

FIXTURES = Path(__file__).parent / "fixtures" / "price"
TODAY = date(2026, 10, 12)
TREND_WORDS = ("상승", "하락", "추세", "오르", "내리", "급등", "급락")


def summary_of(rows: list[tuple[str, str]], unit: str = "대") -> pm.SameModelSummary:
    trades = [
        pm.PriceTrade.from_mapping({"record_id": str(i), "unit_price": price, "unit": unit, "trade_date": day})
        for i, (day, price) in enumerate(rows)
    ]
    return pm.summarize_same_model(trades)


def fixture_summary(name: str) -> pm.SameModelSummary:
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    trades = [pm.PriceTrade.from_mapping(row) for row in data["trades"]]
    valid = [t for t in trades if t.entry_error_reason is None]
    return pm.summarize_same_model(trades, cutoff=date(2023, 10, 13), preferred_unit=pm.main_unit(valid))


def test_dense_model_uses_months() -> None:
    rows = [(f"2026-0{m}-{d:02d}", str(100 + d)) for m in (7, 8) for d in (1, 2, 3)]
    trend = pm.price_trend(summary_of(rows), today=TODAY)
    assert trend.granularity == "month"
    assert [b.label for b in trend.buckets] == ["2026년 7월", "2026년 8월"]
    assert trend.change_percent == Decimal("0.0")
    assert trend.change_sentence == "2026년 8월 가운데 값은 2026년 7월과 같습니다 (각 3건·3건 기준)."
    assert pm._with_gwa("2026년 1분기") == "2026년 1분기와"


def test_falls_back_to_quarter_then_year() -> None:
    quarters = [("2026-01-05", "100"), ("2026-02-05", "100"), ("2026-03-05", "100"),
                ("2026-04-05", "110"), ("2026-05-05", "110"), ("2026-06-05", "110")]
    assert pm.price_trend(summary_of(quarters), today=TODAY).granularity == "quarter"
    years = [("2024-01-05", "100"), ("2024-06-05", "100"), ("2024-11-05", "100"),
             ("2025-01-05", "120"), ("2025-06-05", "120"), ("2025-11-05", "120")]
    trend = pm.price_trend(summary_of(years), today=TODAY)
    assert trend.granularity == "year"
    assert trend.change_percent == Decimal("20.0")
    assert trend.change_sentence == "2025년 가운데 값은 2024년보다 20.0% 높습니다 (각 3건·3건 기준)."


def test_sparse_model_draws_no_chart_and_says_why() -> None:
    trend = pm.price_trend(fixture_summary("few_trades"), today=TODAY)
    assert trend.granularity is None
    assert trend.change_sentence is None
    assert ui.trend_chart(trend) is None
    assert "그리지 않았습니다" in trend.caption


def test_thin_buckets_are_kept_but_never_compared() -> None:
    rows = [("2024-02-01", "100"), ("2024-05-01", "100"), ("2024-08-01", "100"),
            ("2025-03-01", "999"),
            ("2026-01-01", "90"), ("2026-02-01", "90"), ("2026-03-01", "90")]
    trend = pm.price_trend(summary_of(rows), today=TODAY)
    assert trend.granularity == "year"
    thin = [b for b in trend.buckets if not b.enough]
    assert [b.label for b in thin] == ["2025년"]
    assert (trend.change_from.label, trend.change_to.label) == ("2024년", "2026년")
    assert trend.change_to.ongoing
    assert "(진행 중인 구간)" in (trend.change_sentence or "")
    assert trend.change_percent == Decimal("-10.0")


def test_trend_uses_only_priced_lines_of_the_main_unit() -> None:
    summary = fixture_summary("many_mixed_units")
    trend = pm.price_trend(summary, today=TODAY)
    assert sum(b.count for b in trend.buckets) == summary.priced_count == 16


def test_wording_never_claims_a_trend() -> None:
    for name in ("many_single_unit", "many_mixed_units", "few_trades", "entry_errors_and_outlier"):
        trend = pm.price_trend(fixture_summary(name), today=TODAY)
        for text in (trend.caption, trend.change_sentence or ""):
            assert not any(word in text for word in TREND_WORDS), text


def test_table_rows_match_the_chart_data_newest_first() -> None:
    trend = pm.price_trend(fixture_summary("many_single_unit"), today=TODAY)
    rows = ui.trend_rows(trend, unit="대")
    frame = ui.trend_frame(trend)
    assert len(rows) == len(frame) == len(trend.buckets)
    assert rows[0]["기간"].startswith(trend.buckets[-1].label)
    assert {"기간", "거래 건수", "1대당 가운데 값", "최저~최고", "비교"} <= set(rows[0])
    chart = ui.trend_chart(trend, quote=Decimal("12000000"))
    if trend.granularity is not None:
        assert chart is not None


def test_chart_spec_is_valid_with_and_without_a_quote() -> None:
    rows = [(f"2026-0{m}-{d:02d}", str(100 + d)) for m in (7, 8) for d in (1, 2, 3)] + [("2026-09-01", "500")]
    trend = pm.price_trend(summary_of(rows), today=TODAY)
    for quote in (None, Decimal("150")):
        spec = ui.trend_chart(trend, quote=quote).to_dict()
        assert len(spec["layer"]) == (4 if quote else 3)
