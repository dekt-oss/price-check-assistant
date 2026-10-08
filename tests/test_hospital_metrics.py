from __future__ import annotations

from decimal import Decimal

from purchase_price.services import hospital_metrics as hm

ACCOUNTS = {
    "medical_revenue": 500_000_000_000,
    "labor_cost": 230_000_000_000,
    "drug_cost": 60_000_000_000,
    "supply_cost": 90_000_000_000,
    "admin_cost": 70_000_000_000,
    "medical_profit": 20_000_000_000,
    "net_income": 12_000_000_000,
    "total_liabilities": 300_000_000_000,
    "total_equity": 400_000_000_000,
    "current_assets": 180_000_000_000,
    "current_liabilities": 120_000_000_000,
    "borrowings": 50_000_000_000,
    "total_assets": 700_000_000_000,
}


def test_ratios_are_computed_deterministically() -> None:
    result = hm.compute_metrics(
        ACCOUNTS, previous_accounts={"medical_revenue": 460_000_000_000}, bed_count=1_000
    )
    assert result["medical_margin"] == Decimal("4")
    assert result["net_margin"] == Decimal("2.4")
    assert result["labor_ratio"] == Decimal("46")
    assert result["material_ratio"] == Decimal("30")
    assert result["drug_ratio"] == Decimal("12")
    assert result["supply_ratio"] == Decimal("18")
    assert result["admin_ratio"] == Decimal("14")
    assert result["debt_ratio"] == Decimal("75")
    assert result["current_ratio"] == Decimal("150")
    assert result["borrowing_ratio"].quantize(Decimal("0.01")) == Decimal("7.14")
    assert result["revenue_per_bed"] == Decimal("500000000")
    assert result["revenue_growth"].quantize(Decimal("0.01")) == Decimal("8.70")


def test_missing_inputs_stay_none_instead_of_being_estimated() -> None:
    result = hm.compute_metrics({"medical_revenue": 100}, bed_count=None)
    assert result["labor_ratio"] is None
    assert result["material_ratio"] is None
    assert result["revenue_per_bed"] is None
    assert result["revenue_growth"] is None
    assert hm.compute_metrics({})["medical_margin"] is None
    assert hm.percent(Decimal(1), Decimal(0)) is None


def test_cagr_uses_history_years() -> None:
    history = {2020: {"medical_revenue": 100}, 2022: {"medical_revenue": 121}}
    result = hm.compute_metrics({"medical_revenue": 133.1}, history=history, fiscal_year=2025)
    assert result["revenue_cagr_5y"].quantize(Decimal("0.01")) == Decimal("5.89")
    assert result["revenue_cagr_3y"].quantize(Decimal("0.01")) == Decimal("3.23")
    assert hm.cagr(Decimal(0), Decimal(10), 3) is None


def test_peer_comparison_labels_follow_metric_direction() -> None:
    target = {"labor_ratio": Decimal("48"), "medical_margin": Decimal("6"), "admin_ratio": Decimal("14.5")}
    peers = [
        {"labor_ratio": Decimal("44"), "medical_margin": Decimal("3"), "admin_ratio": Decimal("14")},
        {"labor_ratio": Decimal("46"), "medical_margin": Decimal("5"), "admin_ratio": None},
    ]
    rows = {
        row.metric_key: row
        for row in hm.compare_to_peers(
            target, peers, metric_keys=["labor_ratio", "medical_margin", "admin_ratio", "net_margin"]
        )
    }
    assert rows["labor_ratio"].peer_average == Decimal("45")
    assert rows["labor_ratio"].position_text == "높은 편"
    assert rows["medical_margin"].position_text == "평균 이상"
    assert rows["admin_ratio"].peer_count == 1
    assert rows["admin_ratio"].position_text == "평균"
    assert rows["net_margin"].position_text == "비교 불가"


def test_fiscal_period_warnings_flag_different_or_unknown_periods() -> None:
    periods = {
        "A": ("2025-01-01", "2025-12-31"),
        "B": ("2025-01-01", "2025-12-31"),
        "C": ("2025-03-01", "2026-02-28"),
        "D": None,
    }
    assert hm.fiscal_period_warnings(periods, "A") == ["C", "D"]


def test_format_metric_speaks_plainly() -> None:
    assert hm.format_metric(None, "%") == "자료 없음"
    assert hm.format_metric(Decimal("46.27"), "%") == "46.3%"
    assert hm.format_metric(Decimal("500000000"), "원") == "5.0억원"
    assert hm.format_metric(Decimal("1500"), "원") == "1,500원"
