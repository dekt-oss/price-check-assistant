"""Benchmark wiring: CSV -> per hospital-year metrics, findings and data-quality notes."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from purchase_price.services import hospital_benchmark as benchmark
from purchase_price.services import hospital_master as master_service
from purchase_price.services import hospital_metrics as hm
from purchase_price.services import khidi_financials as khidi

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "21_병원_경영_Benchmark.py"

# Two hospitals x three years. A = 부산백 (3월 회계연도), B = 부산대 (1월 회계연도).
# A's labor ratio gap to B widens: 44/40, 46/40, 48/40 (per 100 of revenue).
YEARS = {
    ("H-BUSAN-PAIK", 2022): {"medical_revenue": 1000, "labor_cost": 440, "drug_cost": 150, "supply_cost": 150, "admin_cost": 160, "medical_profit": 30, "net_income": 20, "total_assets": 900, "total_liabilities": 600, "total_equity": 300},
    ("H-BUSAN-PAIK", 2023): {"medical_revenue": 1100, "labor_cost": 506, "drug_cost": 165, "supply_cost": 165, "admin_cost": 176, "medical_profit": 22, "net_income": 11, "total_assets": 900, "total_liabilities": 700, "total_equity": 200},
    ("H-BUSAN-PAIK", 2024): {"medical_revenue": 1000, "labor_cost": 480, "drug_cost": 150, "supply_cost": 150, "admin_cost": 160, "medical_profit": -10, "net_income": 5, "total_assets": 900, "total_liabilities": 910, "total_equity": -10},
    ("H-PNUH", 2022): {"medical_revenue": 2000, "labor_cost": 800, "drug_cost": 300, "supply_cost": 300, "admin_cost": 300, "medical_profit": 60, "net_income": 40, "total_assets": 3000, "total_liabilities": 1500, "total_equity": 1500},
    ("H-PNUH", 2023): {"medical_revenue": 2000, "labor_cost": 800, "drug_cost": 300, "supply_cost": 300, "admin_cost": 300, "medical_profit": 60, "net_income": 40, "total_assets": 3000, "total_liabilities": 1500, "total_equity": 1500},
    ("H-PNUH", 2024): {"medical_revenue": 2000, "labor_cost": 800, "drug_cost": 300, "supply_cost": 300, "admin_cost": 300, "medical_profit": 60, "net_income": 40, "total_assets": 3000, "total_liabilities": 1500},
}
PERIODS = {"H-BUSAN-PAIK": ("{y}-03-01", "{n}-02-28"), "H-PNUH": ("{y}-01-01", "{y}-12-31")}


def _write_fixture(path: Path) -> Path:
    rows = []
    for (hospital_id, year), accounts in YEARS.items():
        start, end = (p.format(y=year, n=year + 1) for p in PERIODS[hospital_id])
        for key, amount in accounts.items():
            rows.append(
                khidi.FinancialRow(
                    hospital_id=hospital_id,
                    fiscal_year=year,
                    fiscal_period_start=date.fromisoformat(start),
                    fiscal_period_end=date.fromisoformat(end),
                    account_code=key,
                    account_name=hm.ACCOUNT_LABELS[key],
                    amount=Decimal(amount),
                    source=khidi.SOURCE_KHIDI,
                    source_url="https://haspa.khidi.or.kr/api/total-is/x?y=0",
                    fetched_at="2026-10-08T20:00:00+09:00",
                )
            )
    khidi.write_financial_csv(khidi.merge_rows([], rows), path)
    return path


def _unsynced_master(path: Path) -> Path:
    """The committed hospital list without HIRA bed counts, as these tests were written for."""

    payload = json.loads(master_service.DEFAULT_MASTER_FILE.read_text(encoding="utf-8"))
    for raw in payload["hospitals"]:
        raw["bed_count"] = None
        raw["bed_count_as_of"] = None
        raw["type_verified"] = False
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture()
def data(tmp_path: Path) -> benchmark.BenchmarkData:
    return benchmark.load_benchmark_data(
        _write_fixture(tmp_path / "fin.csv"), _unsynced_master(tmp_path / "master.json")
    )


def _h(data: benchmark.BenchmarkData, hospital_id: str):
    return data.master.get(hospital_id)


def test_metrics_use_previous_year_and_never_fill_missing_years(data) -> None:
    a = _h(data, "H-BUSAN-PAIK")
    m2023 = benchmark.metrics_for(data, a, 2023)
    assert m2023["revenue_growth"] == Decimal(10)
    assert m2023["labor_ratio"] == Decimal(46)
    assert m2023["material_ratio"] == Decimal(30)
    assert benchmark.metrics_for(data, a, 2022)["revenue_growth"] is None  # no 2021
    assert benchmark.metrics_for(data, a, 2024)["revenue_cagr_3y"] is None  # needs 2021
    assert benchmark.metrics_for(data, a, 2021) is None
    # Negative equity: debt ratio is not computed.
    assert benchmark.metrics_for(data, a, 2024)["debt_ratio"] is None
    # No bed count in the master yet -> per-bed metrics stay empty.
    assert benchmark.metrics_for(data, a, 2024)["revenue_per_bed"] is None


def test_peer_comparison_and_findings_from_numbers_only(data) -> None:
    a, b = _h(data, "H-BUSAN-PAIK"), _h(data, "H-PNUH")
    keys = ("labor_ratio", "material_ratio", "net_margin")
    rows = {r.metric_key: r for r in benchmark.compare(data, a, [b], 2024, keys)}
    assert rows["labor_ratio"].value == Decimal(48)
    assert rows["labor_ratio"].peer_average == Decimal(40)
    assert rows["labor_ratio"].position_text == "높은 편"
    history = benchmark.gap_history(data, a, [b], 2024, keys)
    assert history["labor_ratio"] == [(2022, Decimal(4)), (2023, Decimal(6)), (2024, Decimal(8))]
    findings = {f.metric_key: f.text for f in hm.describe_findings(list(rows.values()), history)}
    assert findings["labor_ratio"] == "인건비율이 비교군 평균보다 8.0%p 높습니다. 최근 3년간 차이가 커지고 있습니다."
    assert "material_ratio" not in findings  # 30% vs 30%: no sentence
    assert findings["net_margin"].startswith("순이익률이 비교군 평균보다 1.5%p 낮습니다.")


def test_trend_table_keeps_gaps(data) -> None:
    a = _h(data, "H-BUSAN-PAIK")
    table = benchmark.trend_table(data, [a], "medical_revenue", [2020, 2021, 2022, 2023, 2024])
    assert table["부산백병원"] == {2020: None, 2021: None, 2022: Decimal(1000), 2023: Decimal(1100), 2024: Decimal(1000)}
    ratio = benchmark.trend_table(data, [a], "labor_ratio", [2021, 2022])
    assert ratio["부산백병원"] == {2021: None, 2022: Decimal(44)}


def test_quality_report_flags_period_missing_accounts_and_beds(data) -> None:
    a, b = _h(data, "H-BUSAN-PAIK"), _h(data, "H-PNUH")
    kosin = _h(data, "H-KOSIN")
    report = benchmark.quality_report(data, a, [b, kosin], 2024)
    assert report.period_mismatch == ["부산대병원: 2024-01-01 ~ 2024-12-31"]
    assert report.no_data == ["고신대복음병원"]
    assert report.missing_accounts == {"부산대병원": ["자본총계"]}
    assert report.negative_equity == ["부산백병원"]
    assert report.bed_counts["부산백병원"] == "병상수 자료 없음"
    assert "부산백병원" in report.unverified_types
    assert report.fetched == {"부산백병원": "2026-10-08", "부산대병원": "2026-10-08"}


def test_findings_particles_and_thresholds() -> None:
    row = hm.ComparisonRow("revenue_per_bed", "병상당 의료수익", "원", Decimal(110), Decimal(100), 2, "above")
    (finding,) = hm.describe_findings([row])
    assert finding.text == "병상당 의료수익이 비교군 평균보다 10.0% 많습니다."
    small = hm.ComparisonRow("labor_ratio", "인건비율", "%", Decimal("40.5"), Decimal(40), 2, "average")
    assert hm.describe_findings([small]) == []
    none = hm.ComparisonRow("labor_ratio", "인건비율", "%", None, Decimal(40), 2, None)
    assert hm.describe_findings([none]) == []
    assert hm.gap_trend([(2022, Decimal(5)), (2023, Decimal(4)), (2024, Decimal(2))]) == "narrowing"
    assert hm.gap_trend([(2022, Decimal(-2)), (2023, Decimal(1)), (2024, Decimal(4))]) is None
    assert hm.gap_trend([(2021, Decimal(1)), (2023, Decimal(2)), (2024, Decimal(3))]) is None


def test_borrowings_are_summed_from_disclosed_lines_only() -> None:
    assert hm.borrowings_total({}) is None
    assert hm.borrowings_total({"short_term_borrowings": 10, "long_term_borrowings": 5}) == Decimal(15)
    assert hm.borrowings_total({"borrowings": 7, "long_term_borrowings": 5}) == Decimal(7)
    metrics = hm.compute_metrics({"total_assets": 100, "current_long_term_debt": 4, "long_term_borrowings": 6})
    assert metrics["borrowing_ratio"] == Decimal(10)
    assert hm.debt_ratio(Decimal(10), Decimal(0)) is None


def _run_page(monkeypatch, csv_path: Path) -> AppTest:
    monkeypatch.setattr(khidi, "DEFAULT_FINANCIAL_CSV", csv_path)
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    app.run()
    assert not app.exception, [e.value for e in app.exception]
    return app


def test_page_shows_no_numbers_when_no_accounts_are_loaded(monkeypatch, tmp_path: Path) -> None:
    empty = tmp_path / "empty.csv"
    khidi.write_financial_csv([], empty)
    app = _run_page(monkeypatch, empty)
    headline = app.dataframe[1].value  # [0] is the peer list
    assert set(headline["부산백병원"]) == {"자료 없음"}
    assert set(headline["비교군 평균"]) == {"자료 없음"}
    assert not any("해석" in m.value for m in app.markdown)
    assert any("회계자료가 아직" in i.value for i in app.info)


def test_page_shows_loaded_values_and_quality_box(monkeypatch, tmp_path: Path) -> None:
    app = _run_page(monkeypatch, _write_fixture(tmp_path / "fin.csv"))
    headline = app.dataframe[1].value
    labor = headline[headline["지표"] == "인건비율"].iloc[0]
    assert labor["부산백병원"] == "48.0%"
    assert labor["위치"] == "높은 편"
    assert any("인건비율이 비교군 평균보다" in m.value for m in app.markdown)
    warnings = " ".join(w.value for w in app.warning)
    assert "부산대병원: 2024-01-01 ~ 2024-12-31" in warnings
    assert "2024 회계자료 없음" in warnings  # region peers without data say so, never a number


def test_committed_data_covers_all_master_hospitals() -> None:
    data = benchmark.load_benchmark_data()
    for hospital in data.master.hospitals:
        assert data.years_for(hospital.hospital_id), hospital.hospital_id
    assert json.loads((ROOT / "data" / "hospital_master.json").read_text(encoding="utf-8"))
