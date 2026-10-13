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


def test_material_ratio_needs_both_cost_accounts() -> None:
    """A missing 약품비 or 진료재료비 must not turn into a smaller 'complete' 재료비 (H-02)."""

    only_drug = hm.compute_metrics({"medical_revenue": 100, "drug_cost": 10, "supply_cost": None})
    only_supply = hm.compute_metrics({"medical_revenue": 100, "supply_cost": 10})
    assert only_drug["material_ratio"] is None and only_supply["material_ratio"] is None
    assert only_drug["drug_ratio"] == Decimal("10")  # the single account is still shown on its own
    both = hm.compute_metrics({"medical_revenue": 100, "drug_cost": 10, "supply_cost": 5})
    assert both["material_ratio"] == Decimal("15")


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


def _comparison_row(
    key: str,
    value: str,
    peer_average: str,
    *,
    peer_count: int = 4,
) -> hm.ComparisonRow:
    label, unit, _ = hm.METRIC_SPECS[key]
    return hm.ComparisonRow(
        key,
        label,
        unit,
        Decimal(value),
        Decimal(peer_average),
        peer_count,
        "above" if Decimal(value) > Decimal(peer_average) else "below",
    )


def test_management_briefing_ranks_differences_and_separates_recent_changes() -> None:
    rows = [
        _comparison_row("medical_margin", "4", "2"),
        _comparison_row("labor_ratio", "50", "45"),
        _comparison_row("revenue_per_bed", "120", "100"),
        _comparison_row("admin_ratio", "17", "14"),
    ]
    history = {
        "medical_margin": [(2022, Decimal("1.1")), (2023, Decimal("1.5")), (2024, Decimal("2"))],
        "labor_ratio": [(2022, Decimal("1")), (2023, Decimal("3")), (2024, Decimal("5"))],
        "revenue_per_bed": [(2022, Decimal("5")), (2023, Decimal("10")), (2024, Decimal("20"))],
        "admin_ratio": [(2022, Decimal("1.1")), (2023, Decimal("2")), (2024, Decimal("3"))],
    }

    briefing = hm.build_management_briefing(
        rows,
        history,
        fiscal_year=2024,
        peer_count=4,
    )

    assert briefing.heading == "2024 회계연도 공시 기준 · 비교병원 4곳"
    assert [finding.metric_key for finding in briefing.differences] == [
        "labor_ratio",
        "revenue_per_bed",
        "admin_ratio",
    ]
    assert briefing.differences[0].text == "인건비율은 비교군 평균보다 5.0%p 높습니다."
    assert briefing.differences[1].text == "병상당 의료수익은 비교군 평균보다 20.0% 많습니다."
    assert len(briefing.trends) == 2
    assert all("최근 3년" in finding.text for finding in briefing.trends)
    assert any("환자 수, 진료단가, 환자구성" in text for text in briefing.followups)
    assert any("인력 구성" in text for text in briefing.followups)


def test_management_briefing_holds_comparison_below_three_valid_peers() -> None:
    rows = [_comparison_row("labor_ratio", "50", "40", peer_count=2)]
    briefing = hm.build_management_briefing(
        rows,
        {"labor_ratio": [(2022, Decimal("4")), (2023, Decimal("7")), (2024, Decimal("10"))]},
        fiscal_year=2024,
        peer_count=2,
    )

    assert briefing.heading == "2024 회계연도 공시 기준 · 비교병원 2곳"
    assert briefing.status == "비교 보류: 유효한 비교병원이 3곳 미만입니다."
    assert briefing.differences == ()
    assert briefing.trends == ()


def test_management_briefing_uses_thresholds_and_has_no_banned_judgment_terms() -> None:
    rows = [
        _comparison_row("medical_margin", "3", "2"),  # exactly 1%p: inside tolerance
        _comparison_row("revenue_per_bed", "105", "100"),  # exactly 5%: inside tolerance
    ]
    briefing = hm.build_management_briefing(rows, {}, fiscal_year=2024, peer_count=4)

    assert briefing.differences == ()
    assert briefing.status == "허용폭을 넘는 차이가 없거나 비교할 자료가 부족합니다."
    assert hm.briefing_banned_term("\n".join(briefing.lines)) is None


def test_management_briefing_distinguishes_missing_target_data_from_missing_peers() -> None:
    label, unit, _ = hm.METRIC_SPECS["labor_ratio"]
    row = hm.ComparisonRow("labor_ratio", label, unit, None, Decimal("45"), 4, None)

    briefing = hm.build_management_briefing([row], {}, fiscal_year=2024, peer_count=4)

    assert briefing.status == "기준 병원의 이 회계연도 자료가 없어 비교 문장을 만들 수 없습니다."


def test_management_briefing_uses_natural_topic_particle() -> None:
    briefing = hm.build_management_briefing(
        [_comparison_row("labor_per_bed", "110", "100")],
        {},
        fiscal_year=2024,
        peer_count=4,
    )

    assert briefing.differences[0].text.startswith("병상당 인건비는 ")


def test_management_briefing_normalizes_trend_strength_across_units() -> None:
    rows = [
        _comparison_row("labor_ratio", "58", "50"),
        _comparison_row("revenue_per_bed", "110000000", "100000000"),
    ]
    briefing = hm.build_management_briefing(
        rows,
        {
            "labor_ratio": [(2022, Decimal("1")), (2023, Decimal("3")), (2024, Decimal("8"))],
            "revenue_per_bed": [
                (2022, Decimal("1000000")),
                (2023, Decimal("2000000")),
                (2024, Decimal("4000000")),
            ],
        },
        fiscal_year=2024,
        peer_count=4,
        max_trends=1,
    )

    assert [finding.metric_key for finding in briefing.trends] == ["labor_ratio"]


def test_management_briefing_trend_states_direction_against_average() -> None:
    briefing = hm.build_management_briefing(
        [_comparison_row("admin_ratio", "10", "20")],
        {"admin_ratio": [(2022, Decimal("-2")), (2023, Decimal("-5")), (2024, Decimal("-10"))]},
        fiscal_year=2024,
        peer_count=4,
    )

    assert "평균보다 낮은 쪽 차이가 커졌습니다" in briefing.trends[0].text


def test_management_briefing_explains_bed_count_basis_for_per_bed_metrics() -> None:
    briefing = hm.build_management_briefing(
        [_comparison_row("revenue_per_bed", "120", "100")],
        {},
        fiscal_year=2024,
        peer_count=4,
    )

    assert any("회계공시 병상수" in text and "심평원 허가병상수" in text for text in briefing.followups)


def test_management_briefing_lines_match_screen_order_and_keep_no_difference_notice() -> None:
    briefing = hm.build_management_briefing(
        [
            _comparison_row("labor_ratio", "46", "45", peer_count=4),
            _comparison_row("medical_margin", "4", "2", peer_count=2),
        ],
        {},
        fiscal_year=2024,
        peer_count=4,
    )

    assert briefing.lines[1].startswith("비교 보류:")
    assert "허용폭을 넘는 차이가 없거나 비교할 자료가 부족합니다." in briefing.lines[1]


def test_management_briefing_uses_the_same_rounding_for_threshold_and_display() -> None:
    briefing = hm.build_management_briefing(
        [
            _comparison_row("medical_margin", "3.04", "2"),
            _comparison_row("revenue_per_bed", "105.04", "100"),
        ],
        {},
        fiscal_year=2024,
        peer_count=4,
    )

    assert briefing.differences == ()
    assert briefing.status == "허용폭을 넘는 차이가 없거나 비교할 자료가 부족합니다."
