"""Wiring for the Benchmark screen: committed CSV/JSON -> per hospital-year metrics.

Production (Streamlit Cloud) has no PostgreSQL, so ``data/hospital_financial.csv`` and
``data/hospital_master.json`` are the serving store. Everything here only reads those files and
calls ``hospital_metrics``; no number is created outside that module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from purchase_price.services import hospital_master as master_service
from purchase_price.services import hospital_metrics as hm
from purchase_price.services import khidi_financials as khidi

# Accounts a headline metric needs; used to tell the reader which inputs are missing.
REQUIRED_ACCOUNTS: tuple[str, ...] = (
    "medical_revenue",
    "labor_cost",
    "drug_cost",
    "supply_cost",
    "admin_cost",
    "medical_profit",
    "net_income",
    "total_assets",
    "total_liabilities",
    "total_equity",
)


@dataclass(frozen=True)
class BenchmarkData:
    master: master_service.HospitalMaster
    years: dict[tuple[str, int], khidi.HospitalYear]

    @property
    def fiscal_years(self) -> list[int]:
        return sorted({year for _, year in self.years}, reverse=True)

    def years_for(self, hospital_id: str) -> list[int]:
        return sorted(year for hid, year in self.years if hid == hospital_id)

    def get(self, hospital_id: str, year: int) -> khidi.HospitalYear | None:
        return self.years.get((hospital_id, year))


def load_benchmark_data(
    csv_path: Path | None = None,
    master_path: Path | None = None,
) -> BenchmarkData:
    """Read the committed files (paths are looked up at call time so tests can point elsewhere)."""

    master = master_service.load_hospital_master(master_path or master_service.DEFAULT_MASTER_FILE)
    rows = khidi.load_financial_csv(csv_path or khidi.DEFAULT_FINANCIAL_CSV)
    return BenchmarkData(master, khidi.group_hospital_years(rows))


def metrics_for(
    data: BenchmarkData, hospital: master_service.Hospital, year: int
) -> dict[str, Decimal | None] | None:
    """Metrics for one hospital-year, or ``None`` when that year is not loaded ("자료 없음")."""

    current = data.get(hospital.hospital_id, year)
    if current is None:
        return None
    previous = data.get(hospital.hospital_id, year - 1)
    history = {
        hy.fiscal_year: hy.accounts
        for (hid, _), hy in data.years.items()
        if hid == hospital.hospital_id and hy.fiscal_year < year
    }
    return hm.compute_metrics(
        current.accounts,
        previous_accounts=previous.accounts if previous else None,
        history=history,
        fiscal_year=year,
        bed_count=hospital.bed_count,
    )


_EMPTY: dict[str, Decimal | None] = {key: None for key in hm.METRIC_SPECS}


def compare(
    data: BenchmarkData,
    target: master_service.Hospital,
    peers: Sequence[master_service.Hospital],
    year: int,
    metric_keys: Sequence[str],
) -> list[hm.ComparisonRow]:
    target_metrics = metrics_for(data, target, year) or _EMPTY
    peer_metrics = [m for p in peers if (m := metrics_for(data, p, year)) is not None]
    return hm.compare_to_peers(target_metrics, peer_metrics, metric_keys=metric_keys)


def gap_history(
    data: BenchmarkData,
    target: master_service.Hospital,
    peers: Sequence[master_service.Hospital],
    year: int,
    metric_keys: Sequence[str],
    *,
    span: int = 3,
) -> dict[str, list[tuple[int, Decimal]]]:
    """``{metric: [(year, target - peer_average)]}`` for the ``span`` years ending at ``year``."""

    result: dict[str, list[tuple[int, Decimal]]] = {key: [] for key in metric_keys}
    for y in range(year - span + 1, year + 1):
        for row in compare(data, target, peers, y, metric_keys):
            if row.value is not None and row.peer_average is not None:
                result[row.metric_key].append((y, row.value - row.peer_average))
    return result


def trend_table(
    data: BenchmarkData,
    hospitals: Sequence[master_service.Hospital],
    metric_key: str,
    years: Sequence[int],
) -> dict[str, dict[int, Decimal | None]]:
    """``{short_name: {year: value}}``; a year without data stays ``None`` (a gap, not a guess)."""

    table: dict[str, dict[int, Decimal | None]] = {}
    for hospital in hospitals:
        row: dict[int, Decimal | None] = {}
        for year in years:
            metrics = metrics_for(data, hospital, year)
            if metric_key in hm.ACCOUNT_LABELS:
                hy = data.get(hospital.hospital_id, year)
                row[year] = hy.accounts.get(metric_key) if hy else None
            else:
                row[year] = metrics.get(metric_key) if metrics else None
        table[hospital.short_name] = row
    return table


@dataclass(frozen=True)
class QualityReport:
    period_mismatch: list[str]
    no_data: list[str]
    missing_accounts: dict[str, list[str]]
    bed_counts: dict[str, str]
    unverified_types: list[str]
    negative_equity: list[str]
    fetched: dict[str, str]


def _period_text(period: tuple[str, str] | None) -> str:
    return f"{period[0]} ~ {period[1]}" if period else "기간 확인 안 됨"


def quality_report(
    data: BenchmarkData,
    target: master_service.Hospital,
    peers: Sequence[master_service.Hospital],
    year: int,
) -> QualityReport:
    """Data-quality notes for the chosen year (plan section 5)."""

    hospitals = [target, *peers]
    loaded = {h.short_name: data.get(h.hospital_id, year) for h in hospitals}
    periods = {name: hy.period for name, hy in loaded.items() if hy is not None}
    mismatch: list[str] = []
    if loaded.get(target.short_name) is not None:
        for name in hm.fiscal_period_warnings(periods, target.short_name):
            mismatch.append(f"{name}: {_period_text(periods.get(name))}")
    missing: dict[str, list[str]] = {}
    negative: list[str] = []
    fetched: dict[str, str] = {}
    for name, hy in loaded.items():
        if hy is None:
            continue
        absent = [
            hm.ACCOUNT_LABELS[key] for key in REQUIRED_ACCOUNTS if hy.accounts.get(key) is None
        ]
        if absent:
            missing[name] = absent
        equity = hy.accounts.get("total_equity")
        if equity is not None and equity <= 0:
            negative.append(name)
        fetched[name] = hy.fetched_at[:10]
    return QualityReport(
        period_mismatch=mismatch,
        no_data=[name for name, hy in loaded.items() if hy is None],
        missing_accounts=missing,
        bed_counts={
            h.short_name: (
                f"{h.bed_count:,}병상 ({h.bed_count_as_of} 기준)"
                if h.bed_count is not None
                else "병상수 자료 없음"
            )
            for h in hospitals
        },
        unverified_types=[h.short_name for h in hospitals if not h.type_verified],
        negative_equity=negative,
        fetched=fetched,
    )


def target_period(data: BenchmarkData, hospital_id: str, year: int) -> tuple[str, str] | None:
    hy = data.get(hospital_id, year)
    return hy.period if hy else None


def as_float_series(values: Mapping[int, Decimal | None], scale: Decimal = Decimal(1)) -> dict[int, float | None]:
    return {year: (float(v / scale) if v is not None else None) for year, v in values.items()}
