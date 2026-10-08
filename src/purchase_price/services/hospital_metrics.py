"""Deterministic hospital management metrics (ratios, growth, peer position).

Every number on the Benchmark screen comes from these functions, never from an AI step.
A metric whose inputs are missing is ``None``; nothing is estimated or back-filled.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, DivisionByZero, InvalidOperation

# Standardised KHIDI income-statement / balance-sheet account keys.
ACCOUNT_LABELS: dict[str, str] = {
    "medical_revenue": "의료수익",
    "inpatient_revenue": "입원수익",
    "outpatient_revenue": "외래수익",
    "medical_expense": "의료비용",
    "labor_cost": "인건비",
    "material_cost": "재료비",
    "drug_cost": "약품비",
    "supply_cost": "진료재료비",
    "admin_cost": "관리운영비",
    "medical_profit": "의료이익(손실)",
    "non_medical_revenue": "의료외수익",
    "non_medical_expense": "의료외비용",
    "net_income": "당기순이익",
    "total_assets": "자산총계",
    "total_liabilities": "부채총계",
    "total_equity": "자본총계",
    "current_assets": "유동자산",
    "current_liabilities": "유동부채",
    "short_term_borrowings": "단기차입금",
    "employee_short_term_borrowings": "임직원단기차입금",
    "current_long_term_debt": "유동성장기부채",
    "long_term_borrowings": "장기차입금",
    "foreign_long_term_borrowings": "외화장기차입금",
    "borrowings": "차입금",
    "disclosed_bed_count": "병상수(공시 일반현황)",
}
BED_COUNT_KEY = "disclosed_bed_count"

# The KHIDI balance sheet has no single "차입금" line; borrowings are the sum of these lines.
BORROWING_COMPONENTS: tuple[str, ...] = (
    "short_term_borrowings",
    "employee_short_term_borrowings",
    "current_long_term_debt",
    "long_term_borrowings",
    "foreign_long_term_borrowings",
)

# metric_key -> (label, unit, direction). direction: "higher_better" | "lower_better" | "neutral"
METRIC_SPECS: dict[str, tuple[str, str, str]] = {
    "revenue_growth": ("의료수익 증가율", "%", "higher_better"),
    "revenue_cagr_3y": ("의료수익 3년 연평균 증가율", "%", "higher_better"),
    "revenue_cagr_5y": ("의료수익 5년 연평균 증가율", "%", "higher_better"),
    "medical_margin": ("의료이익률", "%", "higher_better"),
    "net_margin": ("순이익률", "%", "higher_better"),
    "labor_ratio": ("인건비율", "%", "lower_better"),
    "material_ratio": ("재료비율", "%", "lower_better"),
    "drug_ratio": ("약품비율", "%", "lower_better"),
    "supply_ratio": ("진료재료비율", "%", "lower_better"),
    "admin_ratio": ("관리운영비율", "%", "lower_better"),
    "debt_ratio": ("부채비율", "%", "lower_better"),
    "current_ratio": ("유동비율", "%", "higher_better"),
    "borrowing_ratio": ("차입금 비중", "%", "lower_better"),
    "revenue_per_bed": ("병상당 의료수익", "원", "higher_better"),
    "labor_per_bed": ("병상당 인건비", "원", "neutral"),
    "material_per_bed": ("병상당 재료비", "원", "neutral"),
}

Accounts = Mapping[str, Decimal | int | float | None]


def _dec(value: Decimal | int | float | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation:
        return None


def ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    try:
        return numerator / denominator
    except (DivisionByZero, InvalidOperation):
        return None


def percent(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    value = ratio(numerator, denominator)
    return None if value is None else value * 100


def growth_rate(current: Decimal | None, previous: Decimal | None) -> Decimal | None:
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / abs(previous) * 100


def cagr(start: Decimal | None, end: Decimal | None, years: int) -> Decimal | None:
    if start is None or end is None or years <= 0 or start <= 0 or end <= 0:
        return None
    return (Decimal((float(end) / float(start)) ** (1.0 / years)) - 1) * 100


def borrowings_total(accounts: Accounts) -> Decimal | None:
    """Reported ``borrowings`` if present, else the sum of the KHIDI borrowing lines.

    ``None`` when no borrowing line is reported at all (a missing line is never read as 0).
    """

    direct = _dec(accounts.get("borrowings"))
    if direct is not None:
        return direct
    parts = [_dec(accounts.get(key)) for key in BORROWING_COMPONENTS]
    present = [part for part in parts if part is not None]
    return sum(present, Decimal(0)) if present else None


def debt_ratio(liabilities: Decimal | None, equity: Decimal | None) -> Decimal | None:
    """부채비율. Undefined (``None``) when equity is zero or negative (자본잠식)."""

    if equity is None or equity <= 0:
        return None
    return percent(liabilities, equity)


def compute_metrics(
    accounts: Accounts,
    *,
    previous_accounts: Accounts | None = None,
    history: Mapping[int, Accounts] | None = None,
    fiscal_year: int | None = None,
    bed_count: int | None = None,
) -> dict[str, Decimal | None]:
    """Compute every metric in ``METRIC_SPECS`` for one hospital-year."""

    get = lambda key, source=accounts: _dec(source.get(key)) if source else None  # noqa: E731
    revenue = get("medical_revenue")
    drug = get("drug_cost")
    supply = get("supply_cost")
    material = None if drug is None and supply is None else (drug or Decimal(0)) + (supply or Decimal(0))
    labor = get("labor_cost")
    beds = Decimal(bed_count) if bed_count else None

    result: dict[str, Decimal | None] = {
        "revenue_growth": growth_rate(
            revenue, get("medical_revenue", previous_accounts) if previous_accounts else None
        ),
        "revenue_cagr_3y": None,
        "revenue_cagr_5y": None,
        "medical_margin": percent(get("medical_profit"), revenue),
        "net_margin": percent(get("net_income"), revenue),
        "labor_ratio": percent(labor, revenue),
        "material_ratio": percent(material, revenue),
        "drug_ratio": percent(drug, revenue),
        "supply_ratio": percent(supply, revenue),
        "admin_ratio": percent(get("admin_cost"), revenue),
        "debt_ratio": debt_ratio(get("total_liabilities"), get("total_equity")),
        "current_ratio": percent(get("current_assets"), get("current_liabilities")),
        "borrowing_ratio": percent(borrowings_total(accounts), get("total_assets")),
        "revenue_per_bed": ratio(revenue, beds),
        "labor_per_bed": ratio(labor, beds),
        "material_per_bed": ratio(material, beds),
    }
    if history and fiscal_year is not None:
        for years, key in ((3, "revenue_cagr_3y"), (5, "revenue_cagr_5y")):
            base = history.get(fiscal_year - years)
            if base is not None:
                result[key] = cagr(_dec(base.get("medical_revenue")), revenue, years)
    return result


POSITION_ABOVE = "above"
POSITION_AVERAGE = "average"
POSITION_BELOW = "below"


def peer_average(values: Iterable[Decimal | None]) -> Decimal | None:
    present = [v for v in values if v is not None]
    return sum(present, Decimal(0)) / len(present) if present else None


def position(
    value: Decimal | None, average: Decimal | None, *, tolerance: Decimal = Decimal("1")
) -> str | None:
    """Compare to the peer average with a +/- ``tolerance`` band (percentage points)."""

    if value is None or average is None:
        return None
    diff = value - average
    if abs(diff) <= tolerance:
        return POSITION_AVERAGE
    return POSITION_ABOVE if diff > 0 else POSITION_BELOW


def position_label(metric_key: str, pos: str | None) -> str:
    if pos is None:
        return "비교 불가"
    direction = METRIC_SPECS.get(metric_key, ("", "", "neutral"))[2]
    if pos == POSITION_AVERAGE:
        return "평균"
    if direction == "lower_better":
        return "높은 편" if pos == POSITION_ABOVE else "낮은 편"
    return "평균 이상" if pos == POSITION_ABOVE else "평균 이하"


@dataclass(frozen=True)
class ComparisonRow:
    metric_key: str
    label: str
    unit: str
    value: Decimal | None
    peer_average: Decimal | None
    peer_count: int
    position: str | None

    @property
    def position_text(self) -> str:
        return position_label(self.metric_key, self.position)


def compare_to_peers(
    target_metrics: Mapping[str, Decimal | None],
    peer_metrics: Sequence[Mapping[str, Decimal | None]],
    *,
    metric_keys: Sequence[str] | None = None,
) -> list[ComparisonRow]:
    rows: list[ComparisonRow] = []
    for key in metric_keys or tuple(METRIC_SPECS):
        label, unit, _ = METRIC_SPECS[key]
        peer_values = [m.get(key) for m in peer_metrics]
        avg = peer_average(peer_values)
        tolerance = Decimal("1") if unit == "%" else (abs(avg) * Decimal("0.05") if avg else Decimal("1"))
        rows.append(
            ComparisonRow(
                metric_key=key,
                label=label,
                unit=unit,
                value=target_metrics.get(key),
                peer_average=avg,
                peer_count=sum(1 for v in peer_values if v is not None),
                position=position(target_metrics.get(key), avg, tolerance=tolerance),
            )
        )
    return rows


def fiscal_period_warnings(
    periods: Mapping[str, tuple[str, str] | None], target_id: str
) -> list[str]:
    """Names of hospitals whose fiscal period differs from the target's (or is unknown)."""

    target = periods.get(target_id)
    return [
        name
        for name, period in periods.items()
        if name != target_id and (period is None or target is None or period != target)
    ]


def format_metric(value: Decimal | None, unit: str) -> str:
    if value is None:
        return "자료 없음"
    if unit == "%":
        return f"{value:.1f}%"
    if unit == "원":
        if abs(value) >= 100_000_000:
            return f"{value / 100_000_000:,.1f}억원"
        return f"{value:,.0f}원"
    return f"{value}"


# --- deterministic findings ("해석") -----------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """One plain-Korean sentence derived only from computed numbers.

    AI explanation hook: a later explanation layer may take ``Finding`` objects (``text`` plus
    the numbers in ``value`` / ``peer_average`` / ``gap_history``) as its only input and rephrase
    or connect them. It must not add numbers that are not here; every figure on the screen stays
    computed by this module.
    """

    metric_key: str
    text: str
    value: Decimal | None
    peer_average: Decimal | None
    gap_history: tuple[tuple[int, Decimal], ...] = ()


def _has_final_consonant(word: str) -> bool:
    last = word.strip()[-1:] if word.strip() else ""
    if not ("가" <= last <= "힣"):
        return False
    return (ord(last) - ord("가")) % 28 != 0


def _subject(word: str) -> str:
    return f"{word}{'이' if _has_final_consonant(word) else '가'}"


def gap_trend(gaps: Sequence[tuple[int, Decimal]], *, years: int = 3) -> str | None:
    """"widening" / "narrowing" when the absolute gap moved one way over ``years`` consecutive years."""

    recent = sorted(gaps)[-years:]
    if len(recent) < years or any(b[0] - a[0] != 1 for a, b in zip(recent, recent[1:], strict=False)):
        return None
    sizes = [abs(gap) for _, gap in recent]
    signs = {gap > 0 for _, gap in recent if gap != 0}
    if len(signs) > 1:
        return None
    if all(b > a for a, b in zip(sizes, sizes[1:], strict=False)):
        return "widening"
    if all(b < a for a, b in zip(sizes, sizes[1:], strict=False)):
        return "narrowing"
    return None


def describe_findings(
    rows: Sequence[ComparisonRow],
    gap_history: Mapping[str, Sequence[tuple[int, Decimal]]] | None = None,
    *,
    min_gap_points: Decimal = Decimal("1"),
    min_gap_percent: Decimal = Decimal("5"),
) -> list[Finding]:
    """Turn peer comparisons into sentences such as
    "재료비율이 비교군 평균보다 2.7%p 높습니다. 최근 3년간 차이가 커지고 있습니다."

    Only rows with both a value and a peer average produce a sentence, and only when the gap is
    larger than ``min_gap_points`` (%p, for ratios) or ``min_gap_percent`` (%, for 원 metrics).
    ``gap_history`` maps metric_key to ``[(fiscal_year, value - peer_average), ...]``.
    """

    findings: list[Finding] = []
    for row in rows:
        if row.value is None or row.peer_average is None:
            continue
        diff = row.value - row.peer_average
        if row.unit == "%":
            if abs(diff) <= min_gap_points:
                continue
            amount = f"{abs(diff):.1f}%p"
            direction = "높습니다" if diff > 0 else "낮습니다"
        else:
            if row.peer_average == 0:
                continue
            relative = diff / abs(row.peer_average) * 100
            if abs(relative) <= min_gap_percent:
                continue
            amount = f"{abs(relative):.1f}%"
            direction = "많습니다" if diff > 0 else "적습니다"
        text = f"{_subject(row.label)} 비교군 평균보다 {amount} {direction}."
        history = tuple(sorted((gap_history or {}).get(row.metric_key, ())))
        trend = gap_trend(history)
        if trend == "widening":
            text += " 최근 3년간 차이가 커지고 있습니다."
        elif trend == "narrowing":
            text += " 최근 3년간 차이가 줄고 있습니다."
        findings.append(Finding(row.metric_key, text, row.value, row.peer_average, history))
    return findings
