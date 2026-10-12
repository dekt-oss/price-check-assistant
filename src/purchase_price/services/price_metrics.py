"""가격 지표 계약 (UX v1.1 Phase P0): one definition for every same-model price number.

The result screen, the quote review page and the Excel export each grew their own median, count
and unit rules (inventory: ``docs/metrics/price.md``). This module is the contract the later phases
call instead. It does not change any screen by itself; ``tests/test_price_metrics.py`` pins it to the
current result screen on the golden fixtures in ``tests/fixtures/price/`` and records where the
older paths differ.

Rules (``docs/metrics/price.md`` is the plain-language copy; keep both in step):

* Input is same-model trades only: 식약처 identity exact or a verified alias (match grade A/B).
  Similar-item (C/D/X) trades are never priced here.
* 입력 오류 의심 lines (``price_entry_check.entry_error``: unit price 10원 or less, swapped 단가/수량)
  are counted and listed, never priced.
* Period: a trade is in the period when its date is on or after the cutoff; a trade without a
  readable date stays in every period (same as the screen).
* Unit: units are compared case-insensitively after collapsing spaces. 대 and set are different
  units here (a set's machine count is not in the record). The main unit is the most common one;
  on a tie the unit with the most recent trade, then the unit name. A unit chosen over all periods
  (``preferred_unit``) wins whenever the period has a trade in it. Lines without a unit stay with
  the main unit. Other-unit lines are counted, not priced.
* Price: the source unit price only. Lines whose price was calculated (total / quantity) are
  counted separately and not priced. (The DB loader can calculate one when 단가 is empty; the
  2026-10-10 index has 0 such lines, so this matches the screen today.)
* Median: sorted; with an even count the mean of the two middle values. No arithmetic mean.
* Outliers (3 times above or below the median) are flagged, not removed, and only when 3 or more
  lines are priced.
* Quote position: signed difference to the median, in won and percent (one decimal). The status
  is one of four (never "적정", "싸다", "비싸다").
* Evidence level: 높음 / 보통 / 제한적 with the reasons; never a numeric score.

Pure functions over plain values; no Streamlit, no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from purchase_price.services.price_entry_check import entry_error

# Runtime marker: callers holding an older copy check this before using the contract.
PRICE_METRICS_V1 = True
# Runtime marker (P3): price_trend and SameModelSummary.priced_trades.
PRICE_TREND_V1 = True

# ── Thresholds (docs/metrics/price.md §4). Change both together. ──
MIN_COMPARABLE_TRADES = 3
QUOTE_CHECK_THRESHOLD_PERCENT = Decimal("20")
OUTLIER_FACTOR = Decimal("3")
OUTLIER_MIN_PRICED = 3
EVIDENCE_HIGH_MIN_PRICED = 10
EVIDENCE_HIGH_MIN_INSTITUTIONS = 3
EVIDENCE_RECENT_DAYS = 365
DATA_AS_OF_STALE_DAYS = 3

STATUS_IN_RANGE = "in_range"
STATUS_CHECK = "check"
STATUS_INSUFFICIENT = "insufficient"
STATUS_IDENTITY_NEEDED = "identity_needed"
STATUS_LABELS = {
    STATUS_IN_RANGE: "거래 범위 안 (조건 미확인)",
    STATUS_CHECK: "확인 필요",
    STATUS_INSUFFICIENT: "비교 근거 부족",
    STATUS_IDENTITY_NEEDED: "동일 제품 확인 필요",
}

LEVEL_HIGH = "high"
LEVEL_NORMAL = "normal"
LEVEL_LIMITED = "limited"
LEVEL_LABELS = {LEVEL_HIGH: "높음", LEVEL_NORMAL: "보통", LEVEL_LIMITED: "제한적"}

BASIS_SOURCE = "source_unit_price"


# ── Input ──


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value).replace(",", "").replace("원", "").strip())
    except Exception:
        return None
    return number if number.is_finite() else None


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


@dataclass(frozen=True)
class PriceTrade:
    """One same-model 나라장터 line (current change order) in plain values."""

    record_id: str
    unit_price: Decimal | None
    unit: str = ""
    quantity: Decimal | None = None
    total_amount: Decimal | None = None
    trade_date: str = ""
    institution: str = ""
    supplier: str = ""
    unit_price_basis: str = BASIS_SOURCE

    @classmethod
    def from_candidate(cls, candidate: Any) -> PriceTrade:
        """From a Track B quote candidate (or anything with the same attribute names)."""

        basis = getattr(candidate, "unit_price_basis", BASIS_SOURCE)
        return cls(
            record_id=_text(getattr(candidate, "source_record_id", "")),
            unit_price=_decimal(getattr(candidate, "price", None)),
            unit=_text(getattr(candidate, "unit", "")),
            quantity=_decimal(getattr(candidate, "quantity", None)),
            total_amount=_decimal(getattr(candidate, "total_amount", None)),
            trade_date=_text(getattr(candidate, "transaction_date", "")),
            institution=_text(getattr(candidate, "demand_institution", "")),
            supplier=_text(getattr(candidate, "supplier", "")),
            unit_price_basis=str(getattr(basis, "value", basis) or BASIS_SOURCE),
        )

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> PriceTrade:
        """From a golden-fixture row (``tests/fixtures/price/*.json``)."""

        return cls(
            record_id=_text(row.get("record_id")),
            unit_price=_decimal(row.get("unit_price")),
            unit=_text(row.get("unit")),
            quantity=_decimal(row.get("quantity")),
            total_amount=_decimal(row.get("total_amount")),
            trade_date=_text(row.get("trade_date")),
            institution=_text(row.get("institution")),
            supplier=_text(row.get("supplier")),
            unit_price_basis=_text(row.get("unit_price_basis")) or BASIS_SOURCE,
        )

    @property
    def date_value(self) -> date | None:
        try:
            return date.fromisoformat(self.trade_date[:10])
        except ValueError:
            return None

    @property
    def entry_error_reason(self) -> str | None:
        price = self.unit_price if self.unit_price is not None else Decimal("0")
        found = entry_error(price, self.quantity, self.total_amount, self.unit)
        return found.reason if found is not None else None


# ── Small rules ──


def unit_key(unit: object) -> str:
    text = _text(unit)
    return "" if text in {"", "미확인"} else text.casefold()


def main_unit(trades: Sequence[PriceTrade]) -> str | None:
    """Most common unit; tie -> unit with the latest trade -> unit name. Display text of the first
    spelling seen."""

    counts: dict[str, int] = {}
    latest: dict[str, str] = {}
    display: dict[str, str] = {}
    for trade in trades:
        key = unit_key(trade.unit)
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
        latest[key] = max(latest.get(key, ""), trade.trade_date)
        display.setdefault(key, trade.unit)
    if not counts:
        return None
    key = max(counts, key=lambda item: (counts[item], latest.get(item, ""), item))
    return display[key]


def median(values: Iterable[Decimal]) -> Decimal | None:
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def percent_difference(value: Decimal, base: Decimal) -> Decimal:
    return ((value - base) / base * 100).quantize(Decimal("0.1"))


def in_period(trade: PriceTrade, cutoff: date | None) -> bool:
    if cutoff is None:
        return True
    traded = trade.date_value
    return traded is None or traded >= cutoff


_INSTITUTION_NOISE = re.compile(r"[\s()（）\[\]]")


def institution_key(name: object) -> str:
    """Spaces and brackets only. Names are never merged by similarity (edit distance)."""

    return _INSTITUTION_NOISE.sub("", str(name or "")).casefold()


# ── Same-model summary ──


@dataclass(frozen=True)
class SameModelSummary:
    cutoff: date | None
    main_unit: str | None
    # The period has no trade in the unit chosen over all periods, so it uses its own main unit.
    unit_changed: bool
    # Same-model lines in the period, every unit, entry errors included.
    confirmed_count: int
    # Lines whose price entered the median (main unit, source unit price, no entry error).
    priced_count: int
    entry_error_count: int
    other_unit_count: int
    other_units: tuple[str, ...]
    calculated_price_count: int
    median: Decimal | None
    low: Decimal | None
    high: Decimal | None
    # Sum of quantities of the priced lines, only when every priced line states a quantity.
    total_quantity: Decimal | None
    first_date: str
    latest_date: str
    institution_count: int
    supplier_count: int
    outlier_count: int
    prices: tuple[Decimal, ...] = field(default=(), repr=False)
    # The lines behind ``prices`` (P3 trend buckets read their dates).
    priced_trades: tuple[PriceTrade, ...] = field(default=(), repr=False)

    @property
    def excluded_count(self) -> int:
        return self.confirmed_count - self.priced_count

    @property
    def mixed_units(self) -> bool:
        return self.other_unit_count > 0


def summarize_same_model(
    trades: Iterable[PriceTrade],
    *,
    cutoff: date | None = None,
    preferred_unit: str | None = None,
) -> SameModelSummary:
    in_scope = [trade for trade in trades if in_period(trade, cutoff)]
    errors = [trade for trade in in_scope if trade.entry_error_reason is not None]
    valid = [trade for trade in in_scope if trade.entry_error_reason is None]

    keys = {unit_key(trade.unit) for trade in valid} - {""}
    preferred_key = unit_key(preferred_unit) if preferred_unit else ""
    changed = bool(preferred_key and keys and preferred_key not in keys)
    if preferred_key and preferred_key in keys:
        chosen_key = preferred_key
        chosen = next(trade.unit for trade in valid if unit_key(trade.unit) == preferred_key)
    else:
        chosen = main_unit(valid)
        chosen_key = unit_key(chosen)
    kept = [trade for trade in valid if unit_key(trade.unit) in {"", chosen_key}]
    other = [trade for trade in valid if unit_key(trade.unit) not in {"", chosen_key}]

    calculated = [trade for trade in kept if trade.unit_price_basis != BASIS_SOURCE]
    priced = [
        trade
        for trade in kept
        if trade.unit_price_basis == BASIS_SOURCE and trade.unit_price is not None and trade.unit_price > 0
    ]
    prices = tuple(sorted(trade.unit_price for trade in priced if trade.unit_price is not None))
    mid = median(prices)
    outliers = 0
    if mid is not None and mid > 0 and len(prices) >= OUTLIER_MIN_PRICED:
        outliers = sum(1 for price in prices if price >= mid * OUTLIER_FACTOR or price * OUTLIER_FACTOR <= mid)
    quantities = [trade.quantity for trade in priced]
    total_quantity = (
        sum(quantities, Decimal("0")) if priced and all(q is not None and q > 0 for q in quantities) else None
    )
    dates = sorted(trade.trade_date[:10] for trade in in_scope if trade.date_value is not None)
    return SameModelSummary(
        cutoff=cutoff,
        main_unit=chosen,
        unit_changed=changed,
        confirmed_count=len(in_scope),
        priced_count=len(prices),
        entry_error_count=len(errors),
        other_unit_count=len(other),
        other_units=_first_spellings(other),
        calculated_price_count=len(calculated),
        median=mid,
        low=prices[0] if prices else None,
        high=prices[-1] if prices else None,
        total_quantity=total_quantity,
        first_date=dates[0] if dates else "",
        latest_date=dates[-1] if dates else "",
        institution_count=len({institution_key(t.institution) for t in valid if institution_key(t.institution)}),
        supplier_count=len({institution_key(t.supplier) for t in valid if institution_key(t.supplier)}),
        outlier_count=outliers,
        prices=prices,
        priced_trades=tuple(priced),
    )


def _first_spellings(trades: Iterable[PriceTrade]) -> tuple[str, ...]:
    """One display text per unit key ('set' and 'SET' are one unit), in first-seen order."""

    seen: dict[str, str] = {}
    for trade in trades:
        seen.setdefault(unit_key(trade.unit), trade.unit)
    return tuple(seen.values())


def quantity_weighted_mean(summary_trades: Iterable[PriceTrade], unit: str | None) -> Decimal | None:
    """Σ(unit price × quantity) ÷ Σquantity over one unit. Detail view only; None when any line
    lacks a quantity (a partial weight would mislead)."""

    key = unit_key(unit)
    lines = [
        trade
        for trade in summary_trades
        if unit_key(trade.unit) in {"", key}
        and trade.entry_error_reason is None
        and trade.unit_price_basis == BASIS_SOURCE
        and trade.unit_price is not None
        and trade.unit_price > 0
    ]
    if not lines or any(trade.quantity is None or trade.quantity <= 0 for trade in lines):
        return None
    weight = sum((trade.quantity for trade in lines if trade.quantity is not None), Decimal("0"))
    total = sum(
        (trade.unit_price * trade.quantity for trade in lines if trade.unit_price is not None and trade.quantity is not None),
        Decimal("0"),
    )
    return (total / weight).quantize(Decimal("1")) if weight > 0 else None


# ── Quote comparison ──


@dataclass(frozen=True)
class QuoteComparison:
    status: str
    difference_amount: Decimal | None
    difference_percent: Decimal | None
    reason: str

    @property
    def label(self) -> str:
        return STATUS_LABELS[self.status]


def compare_quote(
    quote_unit_price: Decimal | None,
    summary: SameModelSummary,
    *,
    identity_confirmed: bool = True,
    threshold: Decimal = QUOTE_CHECK_THRESHOLD_PERCENT,
    min_priced: int = MIN_COMPARABLE_TRADES,
) -> QuoteComparison:
    quote = quote_unit_price if quote_unit_price is not None and quote_unit_price > 0 else None
    mid = summary.median
    amount = (quote - mid) if quote is not None and mid is not None else None
    percent = percent_difference(quote, mid) if quote is not None and mid is not None and mid > 0 else None
    if not identity_confirmed:
        return QuoteComparison(
            STATUS_IDENTITY_NEEDED,
            amount,
            percent,
            "검색한 모델과 같은 제품인지 확인되지 않아 견적과 비교하지 않았습니다.",
        )
    if summary.priced_count == 0:
        return QuoteComparison(STATUS_INSUFFICIENT, None, None, "같은 제품으로 확인된 나라장터 거래가 없습니다.")
    if summary.priced_count < min_priced or mid is None or mid <= 0:
        return QuoteComparison(
            STATUS_INSUFFICIENT,
            amount,
            percent,
            f"가격 계산에 쓴 같은 제품 거래가 {summary.priced_count}건뿐이라 가운데 값으로 비교하기에는 부족합니다.",
        )
    if quote is None:
        return QuoteComparison(STATUS_INSUFFICIENT, None, None, "견적 단가가 없어 비교하지 않았습니다.")
    if percent is not None and percent > threshold:
        return QuoteComparison(
            STATUS_CHECK,
            amount,
            percent,
            f"견적 단가가 같은 제품 거래 {summary.priced_count}건의 가운데 값보다 {percent}% 높아 "
            f"기준({threshold:g}%)을 넘었습니다.",
        )
    return QuoteComparison(
        STATUS_IN_RANGE,
        amount,
        percent,
        "가운데 값과의 차이가 기준 안입니다. VAT·설치·옵션 조건이 같은지는 확인하지 않았습니다.",
    )


# ── Evidence level ──


@dataclass(frozen=True)
class EvidenceLevel:
    level: str
    reasons: tuple[str, ...]

    @property
    def label(self) -> str:
        return LEVEL_LABELS[self.level]


def evidence_level(
    summary: SameModelSummary,
    *,
    identity_exact: bool,
    today: date,
) -> EvidenceLevel:
    """높음 needs all of: ≥10 priced lines, ≥3 institutions, a trade in the last 12 months, one unit,
    an unambiguous identity. 제한적 when fewer than 3 lines are priced or the identity is ambiguous
    (``identity_exact=False``: the model name has several 식약처 registrations). Match grade B alone
    does not lower the level: a model-only search leaves the manufacturer unconfirmed (grade B)
    for almost every trade.
    Everything else is 보통. Mixed units hold the level at 보통 only: 54% of medical models with 3+
    trades in 3 years mix units (audit 2026-10-12) and the median already uses the main unit.
    Reasons name every condition that held the level down."""

    limiting: list[str] = []
    if summary.priced_count < MIN_COMPARABLE_TRADES:
        limiting.append(f"가격 계산 거래 {summary.priced_count}건")
    if not identity_exact:
        limiting.append("같은 모델명의 식약처 등록이 여러 건이라 같은 제품인지 모호함")
    if limiting:
        return EvidenceLevel(LEVEL_LIMITED, tuple(limiting))

    holding: list[str] = []
    if summary.mixed_units:
        holding.append(f"다른 단위 거래 {summary.other_unit_count}건은 가격 계산에서 뺌")
    if summary.priced_count < EVIDENCE_HIGH_MIN_PRICED:
        holding.append(f"가격 계산 거래 {summary.priced_count}건(10건 미만)")
    if summary.institution_count < EVIDENCE_HIGH_MIN_INSTITUTIONS:
        holding.append(f"구매 기관 {summary.institution_count}곳(3곳 미만)")
    latest = _date(summary.latest_date)
    if latest is None or (today - latest).days > EVIDENCE_RECENT_DAYS:
        holding.append("최근 12개월 거래 없음")
    if holding:
        return EvidenceLevel(LEVEL_NORMAL, tuple(holding))
    return EvidenceLevel(
        LEVEL_HIGH,
        (
            f"가격 계산 거래 {summary.priced_count}건",
            f"구매 기관 {summary.institution_count}곳",
            f"최근 거래 {summary.latest_date}",
        ),
    )


def _date(text: str) -> date | None:
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def data_as_of_stale(data_as_of: str | None, *, today: date, days: int = DATA_AS_OF_STALE_DAYS) -> bool:
    found = _date(data_as_of or "")
    return found is None or (today - found).days > days


def category_allowed_in_conclusion(summary: SameModelSummary) -> bool:
    """The same-품목 reference price may sit in the conclusion only while same-model evidence is
    short (fewer than MIN_COMPARABLE_TRADES priced lines)."""

    return summary.priced_count < MIN_COMPARABLE_TRADES


# ── Result contract (what P1 renders) ──


@dataclass(frozen=True)
class PriceResult:
    summary: SameModelSummary
    comparison: QuoteComparison
    evidence: EvidenceLevel
    period_label: str
    data_as_of: str | None
    data_as_of_stale: bool
    show_category_in_conclusion: bool


def build_price_result(
    trades: Iterable[PriceTrade],
    *,
    quote_unit_price: Decimal | None,
    identity_confirmed: bool,
    identity_exact: bool,
    period_label: str,
    cutoff: date | None,
    preferred_unit: str | None,
    data_as_of: str | None,
    today: date,
) -> PriceResult:
    summary = summarize_same_model(trades, cutoff=cutoff, preferred_unit=preferred_unit)
    return PriceResult(
        summary=summary,
        comparison=compare_quote(quote_unit_price, summary, identity_confirmed=identity_confirmed),
        evidence=evidence_level(summary, identity_exact=identity_exact, today=today),
        period_label=period_label,
        data_as_of=data_as_of,
        data_as_of_stale=data_as_of_stale(data_as_of, today=today),
        show_category_in_conclusion=category_allowed_in_conclusion(summary),
    )


# ── 기간별 가격 변동 (UX v1.1 P3) ──

TREND_MIN_PER_BUCKET = 3
TREND_MIN_BUCKETS = 2
GRANULARITY_LABELS = {"month": "월별", "quarter": "분기별", "year": "연도별"}


@dataclass(frozen=True)
class TrendBucket:
    key: str  # sortable: '2026-03', '2026-Q1', '2026'
    label: str  # '2026년 3월', '2026년 1분기', '2026년'
    count: int
    median: Decimal | None
    low: Decimal | None
    high: Decimal | None
    # Enough lines (TREND_MIN_PER_BUCKET) for its median to be compared with another bucket.
    enough: bool
    # The bucket contains today, so more trades can still arrive.
    ongoing: bool


@dataclass(frozen=True)
class PriceTrend:
    granularity: str | None  # None: too few lines in every granularity, draw no chart
    buckets: tuple[TrendBucket, ...]
    change_from: TrendBucket | None
    change_to: TrendBucket | None
    change_percent: Decimal | None

    @property
    def caption(self) -> str:
        if self.granularity is None:
            return (
                f"거래가 {TREND_MIN_PER_BUCKET}건 이상인 기간이 {TREND_MIN_BUCKETS}개가 안 돼 기간별 그래프를 "
                "그리지 않았습니다. 연도별 표를 보세요."
            )
        return (
            f"{GRANULARITY_LABELS[self.granularity]} · 거래가 {TREND_MIN_PER_BUCKET}건 이상인 구간만 가운데 값을 "
            "비교합니다(회색은 비교에서 뺀 구간). 거래가 없는 기간은 잇지 않습니다."
        )

    @property
    def change_sentence(self) -> str | None:
        if self.change_from is None or self.change_to is None or self.change_percent is None:
            return None
        ongoing = " (진행 중인 구간)" if self.change_to.ongoing else ""
        basis = f"(각 {self.change_from.count}건·{self.change_to.count}건 기준)"
        if self.change_percent == 0:
            return f"{self.change_to.label}{ongoing} 가운데 값은 {_with_gwa(self.change_from.label)} 같습니다 {basis}."
        moved = f"{abs(self.change_percent)}% {'높습니다' if self.change_percent > 0 else '낮습니다'}"
        return f"{self.change_to.label}{ongoing} 가운데 값은 {self.change_from.label}보다 {moved} {basis}."


def _with_gwa(word: str) -> str:
    """'2026년 5월' -> '2026년 5월과', '2026년 1분기' -> '2026년 1분기와' (과 after a final consonant)."""

    last = word[-1:] if word else ""
    has_final = "가" <= last <= "힣" and (ord(last) - ord("가")) % 28 != 0
    return f"{word}{'과' if has_final else '와'}"


def _bucket_key(day: date, granularity: str) -> tuple[str, str]:
    if granularity == "month":
        return f"{day.year:04d}-{day.month:02d}", f"{day.year}년 {day.month}월"
    if granularity == "quarter":
        quarter = (day.month - 1) // 3 + 1
        return f"{day.year:04d}-Q{quarter}", f"{day.year}년 {quarter}분기"
    return f"{day.year:04d}", f"{day.year}년"


def _buckets(trades: Sequence[PriceTrade], granularity: str, today: date) -> tuple[TrendBucket, ...]:
    groups: dict[str, list[Decimal]] = {}
    labels: dict[str, str] = {}
    for trade in trades:
        day = trade.date_value
        if day is None or trade.unit_price is None:
            continue
        key, label = _bucket_key(day, granularity)
        groups.setdefault(key, []).append(trade.unit_price)
        labels[key] = label
    today_key = _bucket_key(today, granularity)[0]
    output = []
    for key in sorted(groups):
        prices = sorted(groups[key])
        output.append(
            TrendBucket(
                key=key,
                label=labels[key],
                count=len(prices),
                median=median(prices),
                low=prices[0],
                high=prices[-1],
                enough=len(prices) >= TREND_MIN_PER_BUCKET,
                ongoing=key == today_key,
            )
        )
    return tuple(output)


def price_trend(summary: SameModelSummary, *, today: date) -> PriceTrend:
    """The finest of month / quarter / year in which at least TREND_MIN_BUCKETS buckets hold
    TREND_MIN_PER_BUCKET priced lines each (2026-10-12 audit: 79% of medical models with 3+
    trades in 3 years qualify for none). The change compares the two latest such buckets; no
    words like 상승·하락·추세 are produced."""

    for granularity in ("month", "quarter", "year"):
        buckets = _buckets(summary.priced_trades, granularity, today)
        enough = [bucket for bucket in buckets if bucket.enough]
        if len(enough) >= TREND_MIN_BUCKETS:
            before, after = enough[-2], enough[-1]
            percent = (
                percent_difference(after.median, before.median)
                if after.median is not None and before.median is not None and before.median > 0
                else None
            )
            return PriceTrend(granularity, buckets, before, after, percent)
    return PriceTrend(None, _buckets(summary.priced_trades, "year", today), None, None, None)
