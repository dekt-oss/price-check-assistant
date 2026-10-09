"""같은 품목 시장: every 나라장터 trade of the searched product's category, not only the exact model.

"Flow-c has no trade" still leaves the buyer's real question open: what do 가스마취기 cost, which
makers and models exist, who sells them and which hospitals bought one recently. This module
answers that from the same serving index, under explicit rules:

* The category is the 나라장터 세부품명번호 (10-digit detail code) whose class name equals the
  식약처 품목명 ("가스 마취기" = "가스마취기"), plus the codes the same-품목 models were actually
  bought under. Codes for animal use (class name contains "동물") are never added.
* Rows are classified by the 사업명, 구매 기관 and 품명/규격 text (rules below, unit-tested and
  shown on screen as a short note):
  - 동물용: 동물용·동물병원·실험동물·야생동물·수의과·사육곰·veterinary(vet) - a veterinary
    purchase is not a hospital price.
  - 부품·수리: 부품·소모품·소모성·수리·점검·유지보수·센서·필터·배터리·케이블·부속·액세서리 -
    a flow sensor or a repair is not the price of the machine.
  - Equipment purchases that remain are listed as 도입 기관 and counted for 납품업체, including the
    many lines whose model is not stated ("수요기관규격" -> "모델 미기재").
  - The price level uses the most common unit only, and drops prices more than 3 times above or
    below the middle value (a bundle booked on one line, or a part the words did not catch).
* Nothing here claims two models are equivalent; the screen calls it 참고 시세.

Pure functions over plain values, plus one SQL loader. Class prefix for the UI: ``cm-``.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from purchase_price.services.matching import normalize_text

# Runtime marker: the market follows the result screen's 거래 기간 (within_period, 2026-10-10).
CATEGORY_MARKET_PERIOD_V1 = True
CATEGORY_TRADE_LIMIT = 6000
PRICE_FACTOR = Decimal("3")
PRICE_RULE_MIN_ROWS = 4
MODEL_CODE_MIN_SHARE = 0.2

KIND_EQUIPMENT = "equipment"
KIND_OTHER_UNIT = "other_unit"
KIND_PRICE_GAP = "price_gap"
KIND_PARTS = "parts"
KIND_VETERINARY = "veterinary"
EQUIPMENT_KINDS = (KIND_EQUIPMENT, KIND_OTHER_UNIT, KIND_PRICE_GAP)

KIND_LABELS = {
    KIND_EQUIPMENT: "장비 구매",
    KIND_OTHER_UNIT: "장비 구매 · 다른 단위",
    KIND_PRICE_GAP: "장비 구매 · 가격이 크게 다름",
    KIND_PARTS: "부품·수리",
    KIND_VETERINARY: "동물용",
}

PART_KEYWORDS = (
    "부품",
    "소모품",
    "소모성",
    "수리",
    "점검",
    "유지보수",
    "센서",
    "sensor",
    "필터",
    "배터리",
    "케이블",
    "부속",
    "액세서리",
    "악세사리",
)
# Whole words only: bare "동물" also hits "마을공동물품" and bare "수의" hits "소액수의(계약)" and
# "성수의료재단" (found on the 저출력심장충격기 trades), so the list names animal uses explicitly.
VETERINARY_KEYWORDS = (
    "동물용",
    "동물병원",
    "동물의료",
    "실험동물",
    "야생동물",
    "반려동물",
    "대동물",
    "소동물",
    "동물실험",
    "사육곰",
    "수의과",
    "수의학",
    "수의사",
    "veterinary",
)
# "WATO EX-20Vet" / "Vet AG" but not "veterinary" (already a keyword) or "velvet".
_VET_WORD = re.compile(r"(?<![a-z])vet(?![a-z])", re.IGNORECASE)
UNSTATED_MODEL_WORDS = frozenset({"", "수요기관규격", "기타물품포함", "미확인", "없음"})
UNSTATED_MODEL_LABEL = "모델 미기재"
# 대 · 세트 · 식 · set all mean "one machine" on an equipment line (화순 "가스마취기 2대", 부산대
# "마취기 2SET", 공주 Atlan "2식" are the same kind of purchase), so they form one unit group;
# 개 / box / roll and other units stay separate.
MACHINE_UNIT = "대"
MACHINE_UNIT_LABEL = "대·세트·식"
_UNIT_ALIASES = {
    "대": MACHINE_UNIT,
    "set": MACHINE_UNIT,
    "세트": MACHINE_UNIT,
    "식": MACHINE_UNIT,
    "조": MACHINE_UNIT,
    "ea": "개",
    "개": "개",
}

RULE_NOTE = (
    "사업명·구매 기관·품명에 '동물용·동물병원·실험동물·수의과' 등이 있으면 동물용, '부품·소모품·수리·점검·센서·필터' "
    "등이 있으면 부품·수리로 보고 시세와 도입 기관에서 뺐습니다. 대·세트·식은 장비 1대로 보고, 시세는 가장 많은 단위 거래만 씁니다. "
    "가운데 값과 3배 넘게 차이 나는 거래(묶음 계약·부품일 수 있음)는 시세 계산에서만 뺐습니다."
)


# ── Rows ──


@dataclass(frozen=True)
class CategoryTrade:
    """One current (latest change order, not cancelled) 나라장터 delivery line of the category."""

    source_record_id: str
    raw_object_key: str
    transaction_date: str
    institution: str
    manufacturer: str
    model_name: str
    quantity: Decimal | None
    unit: str
    unit_price: Decimal
    total_amount: Decimal | None
    supplier: str
    business_name: str
    product_title: str
    specification: str
    detail_code: str

    @property
    def model_stated(self) -> bool:
        return normalize_text(self.model_name) not in {normalize_text(w) for w in UNSTATED_MODEL_WORDS}

    @property
    def model_label(self) -> str:
        if not self.model_stated:
            return UNSTATED_MODEL_LABEL
        maker = "" if normalize_text(self.manufacturer) in {normalize_text(w) for w in UNSTATED_MODEL_WORDS} else self.manufacturer
        return " ".join(part for part in (maker.strip(), self.model_name.strip()) if part)

    @property
    def year(self) -> str:
        return self.transaction_date[:4] if len(self.transaction_date) >= 4 else ""


@dataclass(frozen=True)
class ClassifiedTrade:
    trade: CategoryTrade
    kind: str
    reason: str = ""

    @property
    def is_equipment(self) -> bool:
        return self.kind in EQUIPMENT_KINDS


def unit_group(unit: object) -> str:
    """대 / 식 / 세트(set, SET, 세트) ... as one comparable key; '' when unknown."""

    text = "".join(str(unit or "").split()).casefold()
    if text in {"", "미확인"}:
        return ""
    return _UNIT_ALIASES.get(text, text)


def _texts(trade: CategoryTrade, *fields_: str) -> str:
    return " ".join(str(getattr(trade, name, "") or "") for name in fields_)


def veterinary_reason(trade: CategoryTrade) -> str:
    text = _texts(trade, "business_name", "institution", "product_title", "specification", "model_name")
    lowered = text.casefold()
    for word in VETERINARY_KEYWORDS:
        if word in lowered:
            return f"'{word}'"
    if _VET_WORD.search(text):
        return "'vet'"
    return ""


def parts_reason(trade: CategoryTrade) -> str:
    lowered = _texts(trade, "business_name", "product_title", "specification").casefold()
    for word in PART_KEYWORDS:
        if word in lowered:
            return f"'{word}'"
    return ""


def classify_trade(trade: CategoryTrade) -> ClassifiedTrade:
    """Text rules only; the unit and price rules need the whole category (see classify_trades)."""

    reason = veterinary_reason(trade)
    if reason:
        return ClassifiedTrade(trade, KIND_VETERINARY, reason)
    reason = parts_reason(trade)
    if reason:
        return ClassifiedTrade(trade, KIND_PARTS, reason)
    return ClassifiedTrade(trade, KIND_EQUIPMENT)


def median(values: Sequence[Decimal]) -> Decimal | None:
    ordered = sorted(values)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def classify_trades(trades: Iterable[CategoryTrade]) -> tuple[tuple[ClassifiedTrade, ...], str | None]:
    """All rules in order; returns (rows newest first, main unit display text)."""

    rows = [classify_trade(trade) for trade in trades]
    equipment_units = Counter(unit_group(row.trade.unit) for row in rows if row.is_equipment)
    equipment_units.pop("", None)
    main_key = max(equipment_units, key=lambda key: (equipment_units[key], key)) if equipment_units else None
    main_display = None
    if main_key == MACHINE_UNIT:
        main_display = MACHINE_UNIT
    elif main_key is not None:
        main_display = next(
            (" ".join(row.trade.unit.split()) for row in rows if unit_group(row.trade.unit) == main_key),
            main_key,
        )

    out: list[ClassifiedTrade] = []
    for row in rows:
        if row.kind == KIND_EQUIPMENT and main_key is not None and unit_group(row.trade.unit) not in {"", main_key}:
            out.append(ClassifiedTrade(row.trade, KIND_OTHER_UNIT, f"단위 {row.trade.unit}"))
        else:
            out.append(row)

    priced = [row.trade.unit_price for row in out if row.kind == KIND_EQUIPMENT]
    middle = median(priced) if len(priced) >= PRICE_RULE_MIN_ROWS else None
    if middle is not None and middle > 0:
        final: list[ClassifiedTrade] = []
        for row in out:
            price = row.trade.unit_price
            if row.kind == KIND_EQUIPMENT and (price > middle * PRICE_FACTOR or price * PRICE_FACTOR < middle):
                direction = "높음" if price > middle else "낮음"
                final.append(ClassifiedTrade(row.trade, KIND_PRICE_GAP, f"가운데 값보다 3배 넘게 {direction}"))
            else:
                final.append(row)
        out = final
    out.sort(key=lambda row: (row.trade.transaction_date, row.trade.source_record_id), reverse=True)
    return tuple(out), main_display


# ── Summaries ──


@dataclass(frozen=True)
class PriceLevel:
    unit: str | None
    count: int
    median: Decimal | None
    low: Decimal | None
    high: Decimal | None
    first_date: str = ""
    latest_date: str = ""


@dataclass(frozen=True)
class YearLevel:
    year: str
    count: int
    median: Decimal | None
    low: Decimal | None
    high: Decimal | None


@dataclass(frozen=True)
class Exclusion:
    kind: str
    label: str
    count: int
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class CategoryModel:
    model: str
    company: str
    permit_number: str
    grade: str
    status: str
    trade_count: int | None
    median: Decimal | None
    low: Decimal | None
    high: Decimal | None
    latest: str
    current: bool = False
    veterinary_count: int = 0
    parts_count: int = 0

    @property
    def has_trades(self) -> bool:
        return bool(self.trade_count)


@dataclass(frozen=True)
class SupplierSummary:
    name: str
    count: int
    latest: str
    institutions: int
    models: tuple[str, ...]


@dataclass(frozen=True)
class CompanySummary:
    name: str
    model_count: int
    traded_model_count: int
    models: tuple[str, ...]
    latest_permit: str


@dataclass(frozen=True)
class DetailCode:
    code: str
    name: str


@dataclass(frozen=True)
class CategoryMarket:
    status: str
    product_name: str
    codes: tuple[DetailCode, ...] = ()
    trades: tuple[ClassifiedTrade, ...] = ()
    level: PriceLevel = field(default_factory=lambda: PriceLevel(None, 0, None, None, None))
    years: tuple[YearLevel, ...] = ()
    exclusions: tuple[Exclusion, ...] = ()
    models: tuple[CategoryModel, ...] = ()
    suppliers: tuple[SupplierSummary, ...] = ()
    companies: tuple[CompanySummary, ...] = ()
    data_as_of: str = ""
    truncated: bool = False
    # The 거래 기간 the trades were limited to (within_period); "" = every collected trade.
    period_label: str = ""
    period_start: str = ""
    # Equipment purchases of the category that fall before period_start.
    outside_period: int = 0

    @property
    def equipment(self) -> tuple[ClassifiedTrade, ...]:
        return tuple(row for row in self.trades if row.is_equipment)

    @property
    def institutions(self) -> int:
        return len({row.trade.institution for row in self.equipment if row.trade.institution})

    @property
    def traded_models(self) -> int:
        return sum(1 for model in self.models if model.has_trades)

    @property
    def code_names(self) -> str:
        return " · ".join(dict.fromkeys(code.name for code in self.codes if code.name))

    @property
    def has_content(self) -> bool:
        return bool(self.trades or self.models)


def price_level(rows: Sequence[ClassifiedTrade], unit: str | None) -> PriceLevel:
    kept = [row.trade for row in rows if row.kind == KIND_EQUIPMENT]
    prices = sorted(trade.unit_price for trade in kept)
    dates = sorted(trade.transaction_date for trade in (row.trade for row in rows if row.is_equipment) if trade.transaction_date)
    return PriceLevel(
        unit=unit,
        count=len(prices),
        median=median(prices),
        low=prices[0] if prices else None,
        high=prices[-1] if prices else None,
        first_date=dates[0] if dates else "",
        latest_date=dates[-1] if dates else "",
    )


def year_levels(rows: Sequence[ClassifiedTrade]) -> tuple[YearLevel, ...]:
    by_year: dict[str, list[Decimal]] = defaultdict(list)
    for row in rows:
        if row.kind == KIND_EQUIPMENT and row.trade.year:
            by_year[row.trade.year].append(row.trade.unit_price)
    return tuple(
        YearLevel(year, len(prices), median(prices), min(prices), max(prices))
        for year, prices in sorted(by_year.items(), reverse=True)
    )


def example_text(row: ClassifiedTrade) -> str:
    """The text that shows why the row was left out: the 규격 when the parts word is there
    ("(부품)스탠드형보관함" under an "AED 구매" 사업명), else the 사업명."""

    trade = row.trade
    word = row.reason.strip("'").casefold()
    if row.kind == KIND_PARTS and word and word in trade.specification.casefold() and word not in trade.business_name.casefold():
        return trade.specification
    return trade.business_name or trade.product_title


def exclusions(rows: Sequence[ClassifiedTrade]) -> tuple[Exclusion, ...]:
    output: list[Exclusion] = []
    for kind in (KIND_PARTS, KIND_VETERINARY, KIND_OTHER_UNIT, KIND_PRICE_GAP):
        matched = [row for row in rows if row.kind == kind]
        if not matched:
            continue
        examples = tuple(dict.fromkeys(text[:30] for text in (example_text(row) for row in matched) if text))[:2]
        output.append(Exclusion(kind, KIND_LABELS[kind], len(matched), examples))
    return tuple(output)


def supplier_summaries(rows: Sequence[ClassifiedTrade]) -> tuple[SupplierSummary, ...]:
    grouped: dict[str, list[CategoryTrade]] = defaultdict(list)
    for row in rows:
        if row.is_equipment and row.trade.supplier.strip():
            grouped[row.trade.supplier.strip()].append(row.trade)
    summaries = []
    for name, trades in grouped.items():
        models = Counter(trade.model_label for trade in trades)
        summaries.append(
            SupplierSummary(
                name=name,
                count=len(trades),
                latest=max((trade.transaction_date for trade in trades), default=""),
                institutions=len({trade.institution for trade in trades if trade.institution}),
                models=tuple(
                    f"{label} {count}건" if count > 1 else label
                    for label, count in sorted(models.items(), key=lambda item: (-item[1], item[0]))
                ),
            )
        )
    summaries.sort(key=lambda item: item.name)
    summaries.sort(key=lambda item: item.latest, reverse=True)
    summaries.sort(key=lambda item: -item.count)
    return tuple(summaries)


def _text(value: object) -> str:
    return str(value or "").strip()


def _key(permit: object, model: object) -> tuple[str, str]:
    return normalize_text(_text(permit)), normalize_text(_text(model))


def model_summaries(
    crosslinks: Sequence[Mapping[str, object]],
    identity_records: Sequence[Any],
    *,
    model_medians: Mapping[tuple[str, str], Decimal] | None = None,
    status_labels: Mapping[str, str] | None = None,
    trades: Sequence[ClassifiedTrade] = (),
) -> tuple[CategoryModel, ...]:
    """Every registered model of the 품목: models with 나라장터 trades first (most first), then the
    rest by company and name. ``crosslinks`` are the dashboard's per-model trade rows."""

    records: dict[tuple[str, str], Any] = {}
    for record in identity_records:
        records.setdefault(_key(getattr(record, "permit_number", ""), getattr(record, "model_name", "")), record)
    flagged: dict[str, Counter[str]] = defaultdict(Counter)
    for row in trades:
        if row.kind in {KIND_VETERINARY, KIND_PARTS} and row.trade.model_stated:
            flagged[normalize_text(row.trade.model_name)][row.kind] += 1

    seen: set[tuple[str, str, str]] = set()
    models: list[CategoryModel] = []
    for link in crosslinks:
        model = _text(link.get("모델"))
        permit = _text(link.get("식약처 품목번호"))
        company = _text(link.get("품목 책임주체"))
        dedupe = (normalize_text(permit), normalize_text(model), normalize_text(company))
        if not model or dedupe in seen:
            continue
        seen.add(dedupe)
        key = _key(permit, model)
        record = records.get(key)
        count = link.get("나라장터 직접거래")
        low = high = None
        price_text = _text(link.get("나라장터 가격범위"))
        numbers = [Decimal(part.replace(",", "")) for part in re.findall(r"\d[\d,]*", price_text)]
        if len(numbers) >= 2 and count:
            low, high = numbers[0], numbers[1]
        status = ""
        if status_labels:
            status = status_labels.get("".join(permit.split()), "")
        marks = flagged.get(normalize_text(model), Counter())
        models.append(
            CategoryModel(
                model=model,
                company=company,
                permit_number=permit,
                grade=_text(getattr(record, "grade", "")) if record is not None else "",
                status=status,
                trade_count=None if count is None else int(count or 0),
                median=(model_medians or {}).get(key) if count else None,
                low=low,
                high=high,
                latest=_text(link.get("최근거래")),
                current=bool(link.get("현재 모델")),
                veterinary_count=marks[KIND_VETERINARY],
                parts_count=marks[KIND_PARTS],
            )
        )
    return tuple(
        sorted(
            models,
            key=lambda item: (
                0 if item.has_trades else 1,
                -(item.trade_count or 0),
                0 if item.current else 1,
                item.company,
                item.model,
            ),
        )
    )


def company_summaries(models: Sequence[CategoryModel], identity_records: Sequence[Any]) -> tuple[CompanySummary, ...]:
    by_company: dict[str, list[CategoryModel]] = defaultdict(list)
    for model in models:
        by_company[model.company or "업체 미확인"].append(model)
    latest_permit: dict[str, str] = {}
    for record in identity_records:
        company = _text(getattr(record, "registered_company", "")) or "업체 미확인"
        permit_date = _text(getattr(record, "permit_date", ""))
        if permit_date > latest_permit.get(company, ""):
            latest_permit[company] = permit_date
    summaries = [
        CompanySummary(
            name=name,
            model_count=len({normalize_text(item.model) for item in items}),
            traded_model_count=sum(1 for item in items if item.has_trades),
            models=tuple(dict.fromkeys(item.model for item in items))[:3],
            latest_permit=latest_permit.get(name, ""),
        )
        for name, items in by_company.items()
    ]
    return tuple(sorted(summaries, key=lambda item: (-item.traded_model_count, -item.model_count, item.name)))


def build_category_market(
    trades: Iterable[CategoryTrade],
    *,
    product_name: str,
    codes: Sequence[DetailCode] = (),
    crosslinks: Sequence[Mapping[str, object]] = (),
    identity_records: Sequence[Any] = (),
    model_medians: Mapping[tuple[str, str], Decimal] | None = None,
    status_labels: Mapping[str, str] | None = None,
    data_as_of: str = "",
    truncated: bool = False,
) -> CategoryMarket:
    rows, unit = classify_trades(trades)
    models = model_summaries(
        crosslinks,
        identity_records,
        model_medians=model_medians,
        status_labels=status_labels,
        trades=rows,
    )
    return CategoryMarket(
        status="success" if rows or models else "success_0",
        product_name=product_name,
        codes=tuple(codes),
        trades=rows,
        level=price_level(rows, unit),
        years=year_levels(rows),
        exclusions=exclusions(rows),
        models=models,
        suppliers=supplier_summaries(rows),
        companies=company_summaries(models, identity_records),
        data_as_of=data_as_of,
        truncated=truncated,
    )


def with_status_labels(market: CategoryMarket, status_labels: Mapping[str, str]) -> CategoryMarket:
    """Fill 허가 상태 later (the item-status index is read when the result is drawn)."""

    if not status_labels:
        return market
    models = tuple(
        model
        if model.status
        else CategoryModel(**{**model.__dict__, "status": status_labels.get("".join(model.permit_number.split()), "")})
        for model in market.models
    )
    return CategoryMarket(**{**market.__dict__, "models": models})


def _trade_day(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return None


def within_period(market: CategoryMarket, cutoff: date | None, *, label: str = "") -> CategoryMarket:
    """The same market limited to the chosen 거래 기간 (trades on or after ``cutoff``).

    The trades are classified again inside the period, so the price level, the year table, the
    left-out counts and the 납품업체 list all follow the period the result screen shows. A trade
    without a readable date stays (as in the same-product tables). The 식약처 model list does not
    depend on the period; its trade counts come from the per-model rows (see the screen note).
    """

    if cutoff is None:
        return CategoryMarket(**{**market.__dict__, "period_label": label, "period_start": "", "outside_period": 0})
    kept: list[CategoryTrade] = []
    for row in market.trades:
        day = _trade_day(row.trade.transaction_date)
        if day is None or day >= cutoff:
            kept.append(row.trade)
    rows, unit = classify_trades(kept)
    outside = len(market.equipment) - sum(1 for row in rows if row.is_equipment)
    return CategoryMarket(
        **{
            **market.__dict__,
            "trades": rows,
            "level": price_level(rows, unit),
            "years": year_levels(rows),
            "exclusions": exclusions(rows),
            "suppliers": supplier_summaries(rows),
            "period_label": label,
            "period_start": cutoff.isoformat(),
            "outside_period": max(outside, 0),
        }
    )


# ── Category codes ──


def model_detail_codes(code_counts: Mapping[str, int], *, min_share: float = MODEL_CODE_MIN_SHARE) -> tuple[str, ...]:
    """Codes that hold at least ``min_share`` of the same-품목 models' direct trades: a model bought
    once under a neighbouring code (a part, a bundle) does not pull that whole code in."""

    total = sum(code_counts.values())
    if not total:
        return ()
    return tuple(
        code
        for code, count in sorted(code_counts.items(), key=lambda item: (-item[1], item[0]))
        if code and count / total >= min_share
    )


def is_veterinary_class(name: object) -> bool:
    return "동물" in str(name or "")


# ── SQL ──


def resolve_detail_codes(
    session: Any,
    product_names: Iterable[str],
    *,
    model_code_counts: Mapping[str, int] | None = None,
) -> tuple[DetailCode, ...]:
    """Detail codes whose class name equals a 식약처 품목명, plus the main codes of its models."""

    from sqlalchemy import select

    from purchase_price.models import TrackBDeliveryLine

    keys = sorted({normalize_text(name) for name in product_names if normalize_text(name)})
    found: dict[str, str] = {}
    if keys:
        rows = session.execute(
            select(TrackBDeliveryLine.detail_code, TrackBDeliveryLine.product_class)
            .where(TrackBDeliveryLine.class_key.in_(keys))
            .distinct()
        ).all()
        for code, name in rows:
            if code and not is_veterinary_class(name):
                found.setdefault(str(code), str(name or ""))
    extra = [code for code in model_detail_codes(model_code_counts or {}) if code not in found]
    if extra:
        rows = session.execute(
            select(TrackBDeliveryLine.detail_code, TrackBDeliveryLine.product_class)
            .where(TrackBDeliveryLine.detail_code.in_(extra))
            .limit(len(extra) * 50)
        ).all()
        names: dict[str, str] = {}
        for code, name in rows:
            names.setdefault(str(code), str(name or ""))
        for code in extra:
            if not is_veterinary_class(names.get(code)):
                found.setdefault(code, names.get(code, ""))
    return tuple(DetailCode(code, name) for code, name in found.items())


def load_category_trades(
    session: Any,
    codes: Sequence[str],
    *,
    limit: int = CATEGORY_TRADE_LIMIT,
) -> tuple[tuple[CategoryTrade, ...], bool]:
    """Current lines of the codes, newest first: (trades, truncated)."""

    from sqlalchemy import and_, exists, inspect, or_, select
    from sqlalchemy.orm import aliased

    from purchase_price.models import TrackBDeliveryLine as Line

    if not codes:
        return (), False
    try:
        columns = {str(column["name"]) for column in inspect(session.get_bind()).get_columns(Line.__tablename__)}
    except Exception:
        columns = set()
    newer = aliased(Line)
    current = ~exists(
        select(1).where(
            newer.delivery_request_number == Line.delivery_request_number,
            newer.product_sequence == Line.product_sequence,
            newer.change_order_number > Line.change_order_number,
        )
    )
    selected = [
        Line.delivery_request_number,
        Line.change_order,
        Line.product_sequence,
        Line.raw_object_key,
        Line.transaction_date,
        Line.demand_institution,
        Line.manufacturer,
        Line.model_name,
        Line.quantity,
        Line.unit,
        Line.unit_price,
        Line.total_amount,
        Line.supplier,
        Line.product_title,
        Line.specification,
        Line.detail_code,
    ]
    has_business = "business_name" in columns
    if has_business:
        selected.append(Line.business_name)
    rows = session.execute(
        select(*selected)
        .where(
            Line.detail_code.in_(list(codes)),
            current,
            Line.identity_conflict.is_(False),
            or_(Line.quantity.is_(None), Line.quantity != 0),
            or_(
                Line.unit_price > 0,
                and_(Line.unit_price.is_(None), Line.total_amount > 0, Line.quantity > 0),
            ),
        )
        .order_by(Line.transaction_date.desc(), Line.id.desc())
        .limit(limit + 1)
    ).all()
    trades: list[CategoryTrade] = []
    for row in rows[:limit]:
        price = row.unit_price
        if (price is None or price <= 0) and row.total_amount and row.quantity:
            price = Decimal(str(row.total_amount)) / Decimal(str(row.quantity))
        if price is None or price <= 0:
            continue
        when = row.transaction_date
        trades.append(
            CategoryTrade(
                source_record_id=(
                    f"delivery:{row.delivery_request_number}|change:{row.change_order}|line:{row.product_sequence}"
                ),
                raw_object_key=_text(row.raw_object_key),
                transaction_date=when.isoformat() if isinstance(when, date) else _text(when),
                institution=_text(row.demand_institution),
                manufacturer=_text(row.manufacturer),
                model_name=_text(row.model_name),
                quantity=Decimal(str(row.quantity)) if row.quantity is not None else None,
                unit=_text(row.unit),
                unit_price=Decimal(str(price)),
                total_amount=Decimal(str(row.total_amount)) if row.total_amount is not None else None,
                supplier=_text(row.supplier),
                business_name=_text(row.business_name) if has_business else "",
                product_title=_text(row.product_title),
                specification=_text(row.specification),
                detail_code=_text(row.detail_code),
            )
        )
    return tuple(trades), len(rows) > limit


# ── Identity reconciliation (식약처 card vs the ▶ row) ──


def identity_from_same_product(records: Iterable[Any], model_name: str) -> tuple[Any, ...]:
    """Records of the same-품목 list whose model equals the searched model, when they name exactly
    one registration (허가번호·업체·품목). Empty when none or several match: never guess."""

    key = normalize_text(model_name)
    if not key:
        return ()
    matched = tuple(record for record in records if normalize_text(getattr(record, "model_name", "")) == key)
    registrations = {
        (
            normalize_text(getattr(record, "permit_number", "")),
            normalize_text(getattr(record, "registered_company", "")),
            normalize_text(getattr(record, "product_name", "")),
        )
        for record in matched
    }
    return matched if len(registrations) == 1 else ()
