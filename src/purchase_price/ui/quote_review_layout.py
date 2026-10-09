"""견적서 검토 screen: item table, verdict rule and the selected-item card (design step 4).

Layout follows GPT's quote mockup (item table on the left, the selected item on the right with
이전/다음), the verdict follows Claude Design's three words. The verdict compares the quote with
the median of same-product trades as a percentage; it never says "outside min–max", because a
quote can sit under the highest trade and still be far above what most buyers paid.

Everything here except the two ``render_*`` helpers is pure so the wording and the rule are
unit-tested. New module, so a Production process that keeps older modules loaded never imports
half of it.
"""

from __future__ import annotations

import html
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from statistics import median
from typing import Any

from purchase_price.services.safety_support import SafetyCheckStatus
from purchase_price.ui import result_summary
from purchase_price.ui.theme import TONE_MUTED, TONE_OK, TONE_WARN, pill_html
from purchase_price.ui.track_b_transactions import (
    category_reference_candidates,
    reference_candidates,
    strict_comparison_candidates,
)

QUOTE_REVIEW_LAYOUT_V1 = True

# A quote this many percent above the median of same-product trades is flagged for a check.
QUOTE_CHECK_THRESHOLD_PERCENT = Decimal("20")
# Below this many same-product trades the median is too thin to judge a quote against.
MIN_COMPARABLE_TRADES = 3

VERDICT_IN_RANGE = "거래 범위 안"
VERDICT_CHECK = "확인 필요"
VERDICT_INSUFFICIENT = "판단 부족"
VERDICT_ORDER = (VERDICT_CHECK, VERDICT_INSUFFICIENT, VERDICT_IN_RANGE)
VERDICT_TONES = {
    VERDICT_CHECK: TONE_WARN,
    VERDICT_INSUFFICIENT: TONE_MUTED,
    VERDICT_IN_RANGE: TONE_OK,
}
# Background colours of the 판정 labels inside st.dataframe (same as the pc-pill colours).
VERDICT_TABLE_COLORS = {
    VERDICT_CHECK: "#FFE9C7",
    VERDICT_INSUFFICIENT: "#E6EBF2",
    VERDICT_IN_RANGE: "#D5F2E6",
}


def rule_sentence(
    threshold: Decimal = QUOTE_CHECK_THRESHOLD_PERCENT,
    min_trades: int = MIN_COMPARABLE_TRADES,
) -> str:
    """The verdict rule in plain words, shown on the screen under the summary cards."""

    return (
        f"같은 제품 거래가 {min_trades}건 이상일 때만 판정합니다. 견적 단가가 거래 가운데 값(중앙값)보다 "
        f"{threshold:g}% 넘게 높으면 '{VERDICT_CHECK}', 그렇지 않으면 '{VERDICT_IN_RANGE}'입니다. "
        f"거래가 {min_trades}건 미만이거나 견적 단가가 없으면 '{VERDICT_INSUFFICIENT}'으로 둡니다. "
        "어느 경우든 VAT·설치·구성 조건이 같은지는 따로 확인해야 합니다."
    )


@dataclass(frozen=True)
class QuoteVerdict:
    kind: str
    label: str
    reason: str

    @property
    def tone(self) -> str:
        return VERDICT_TONES.get(self.kind, TONE_MUTED)


def percent_difference(quote: Decimal, base: Decimal) -> Decimal:
    return ((quote - base) / base * 100).quantize(Decimal("0.1"))


def quote_verdict(
    *,
    quote_unit_price: Decimal | None,
    median_price: Decimal | None,
    comparable_count: int,
    threshold: Decimal = QUOTE_CHECK_THRESHOLD_PERCENT,
    min_trades: int = MIN_COMPARABLE_TRADES,
) -> QuoteVerdict:
    """판단 부족 below ``min_trades`` trades, 확인 필요 above the median by more than ``threshold`` %."""

    if comparable_count < min_trades or median_price is None or median_price <= 0:
        if comparable_count <= 0:
            reason = "같은 제품으로 확인된 나라장터 거래가 없어 비교하지 않았습니다."
        else:
            reason = (
                f"같은 제품 거래가 {comparable_count}건뿐이라 가운데 값으로 판단하기에는 부족합니다."
            )
        return QuoteVerdict(VERDICT_INSUFFICIENT, VERDICT_INSUFFICIENT, reason)
    if quote_unit_price is None or quote_unit_price <= 0:
        return QuoteVerdict(
            VERDICT_INSUFFICIENT,
            VERDICT_INSUFFICIENT,
            "견적서에서 단가를 읽지 못해 거래 가격과 비교하지 않았습니다.",
        )
    delta = percent_difference(quote_unit_price, median_price)
    if delta > threshold:
        return QuoteVerdict(
            VERDICT_CHECK,
            f"{VERDICT_CHECK} (가운데 값보다 {delta:.1f}% 높음)",
            f"견적 단가가 같은 제품 거래 {comparable_count}건의 가운데 값보다 {delta:.1f}% 높습니다. "
            f"기준({threshold:g}%)을 넘었습니다.",
        )
    if delta >= 0:
        where = f"가운데 값보다 {delta:.1f}% 높지만 기준({threshold:g}%) 안입니다."
    else:
        where = f"가운데 값보다 {abs(delta):.1f}% 낮습니다."
    return QuoteVerdict(
        VERDICT_IN_RANGE,
        VERDICT_IN_RANGE,
        f"견적 단가가 같은 제품 거래 {comparable_count}건의 {where}",
    )


# ── 품목 하나의 비교 결과 ──


@dataclass(frozen=True)
class QuoteItemComparison:
    index: int
    title: str
    subtitle: str
    quantity_text: str
    quote_unit_price: Decimal | None
    quote_unit: str
    comparable_count: int
    other_unit_count: int
    reference_count: int
    median_price: Decimal | None
    low_price: Decimal | None
    high_price: Decimal | None
    main_unit: str | None
    period_label: str
    delta_percent: Decimal | None
    verdict: QuoteVerdict
    data_problem: str | None
    check_points: tuple[str, ...]

    @property
    def number(self) -> int:
        return self.index + 1


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        number = Decimal(str(value))
    except Exception:
        return None
    return number if number.is_finite() else None


def _number(value: Decimal) -> str:
    return f"{value:,.0f}" if value == value.to_integral_value() else f"{value.normalize():,}"


def item_title(item: Any, index: int) -> str:
    return _text(getattr(item, "model_name", "")) or _text(getattr(item, "product_name", "")) or (
        f"품목 {index + 1}"
    )


def item_subtitle(item: Any) -> str:
    model = _text(getattr(item, "model_name", ""))
    parts = [
        _text(getattr(item, "product_name", "")) if model else "",
        _text(getattr(item, "manufacturer", "")),
        _text(getattr(item, "specification", "")),
    ]
    return " · ".join(part for part in parts if part)


def quantity_text(item: Any) -> str:
    quantity = _decimal(getattr(item, "quantity", None))
    unit = _text(getattr(item, "unit", ""))
    if quantity is None:
        return unit or "—"
    return f"{_number(quantity)} {unit}".strip()


def _data_problem(track_b: Any, *, failed: bool) -> str | None:
    if track_b is None:
        if failed:
            return "거래 자료를 불러오지 못했습니다. 화면 아래 '다시 조사'를 누르세요."
        return "아직 거래 자료를 찾지 않았습니다."
    status = str(getattr(track_b, "status", "") or "")
    if status in {"unavailable", "not_ingested"}:
        return "나라장터 가격 자료를 아직 쓸 수 없습니다. 잠시 뒤 '가격 다시 검색'을 누르세요."
    if status == "insufficient_identity":
        return "품명이나 모델명을 읽지 못해 거래를 찾지 못했습니다. '추출 내용 확인·수정'에서 고쳐 주세요."
    return None


def _same_unit(left: str, right: str | None) -> bool:
    return result_summary.unit_key(left) == result_summary.unit_key(right)


def _check_points(
    *,
    item: Any,
    verdict: QuoteVerdict,
    delta: Decimal | None,
    comparable_count: int,
    other_unit_count: int,
    reference_count: int,
    main_unit: str | None,
    period_note: str | None,
    data_problem: str | None,
    safety_status: str,
) -> tuple[str, ...]:
    points: list[str] = []
    if safety_status == SafetyCheckStatus.MATCH.value:
        points.append("식약처 회수·판매중지 기록과 맞는 내용이 있습니다. 의료기기 허가·안전 화면에서 먼저 확인하세요.")
    if data_problem:
        points.append(data_problem)
    if verdict.kind == VERDICT_CHECK:
        points.append("구성품·설치·보증 조건이 거래된 제품과 같은지 견적처에 확인하세요.")
    elif delta is not None and delta < -QUOTE_CHECK_THRESHOLD_PERCENT and comparable_count:
        points.append(
            f"가운데 값보다 {abs(delta):.1f}% 낮습니다. 빠진 구성품이 없는지 확인하세요."
        )
    if 0 < comparable_count < MIN_COMPARABLE_TRADES:
        points.append(
            f"같은 제품 거래가 {comparable_count}건뿐입니다. 차이 %는 참고만 하고 가격 조사 화면에서 거래 원문을 보세요."
        )
    if comparable_count == 0 and reference_count and not data_problem:
        points.append(
            f"이름이 비슷한 거래 {reference_count}건은 같은 제품인지 확인되지 않아 비교에서 뺐습니다."
        )
    quote_unit = _text(getattr(item, "unit", ""))
    if quote_unit and main_unit and not _same_unit(quote_unit, main_unit):
        points.append(
            f"견적 단위({quote_unit})와 거래 단위({main_unit})가 다릅니다. "
            f"1{main_unit}에 무엇이 들어 있는지 거래 원문으로 확인하세요."
        )
    if other_unit_count and main_unit:
        points.append(
            f"단위가 다른 거래 {other_unit_count}건은 {main_unit} 단위 가격과 섞지 않았습니다."
        )
    if period_note:
        points.append(period_note)
    if not _text(getattr(item, "vat_status", "")):
        points.append("견적서에 부가세 포함 여부가 없습니다. 거래가는 부가세 포함 금액입니다.")
    return tuple(dict.fromkeys(points))


def build_item_comparison(
    index: int,
    item: Any,
    track_b: Any,
    *,
    today: date,
    failed: bool = False,
    safety_status: str = "",
) -> QuoteItemComparison:
    """Same numbers as the 가격 조사 result: default period (최근 3년, widened when empty),
    same-product (A/B) trades only, and only the most common unit in the median."""

    quote = _decimal(getattr(item, "unit_price", None))
    quote = quote if quote is not None and quote > 0 else None
    data_problem = _data_problem(track_b, failed=failed)

    direct = strict_comparison_candidates(track_b) if track_b is not None else ()
    references = (
        (*category_reference_candidates(track_b), *reference_candidates(track_b))
        if track_b is not None
        else ()
    )
    choice = result_summary.choose_period(
        [getattr(candidate, "transaction_date", None) for candidate in direct],
        requested=result_summary.DEFAULT_PERIOD_LABEL,
        user_chose=False,
        today=today,
    )
    direct = result_summary.filter_candidates(direct, choice.cutoff)
    references = result_summary.filter_candidates(references, choice.cutoff)
    split = result_summary.split_by_main_unit(direct)
    prices = sorted(
        price
        for price in (_decimal(getattr(candidate, "price", None)) for candidate in split.kept)
        if price is not None and price > 0
    )
    count = len(prices)
    mid = Decimal(str(median(prices))) if prices else None
    delta = percent_difference(quote, mid) if quote is not None and mid is not None and mid > 0 else None

    verdict = quote_verdict(quote_unit_price=quote, median_price=mid, comparable_count=count)
    if data_problem and count == 0:
        verdict = QuoteVerdict(VERDICT_INSUFFICIENT, VERDICT_INSUFFICIENT, data_problem)

    return QuoteItemComparison(
        index=index,
        title=item_title(item, index),
        subtitle=item_subtitle(item),
        quantity_text=quantity_text(item),
        quote_unit_price=quote,
        quote_unit=_text(getattr(item, "unit", "")),
        comparable_count=count,
        other_unit_count=len(split.other),
        reference_count=len(references),
        median_price=mid,
        low_price=prices[0] if prices else None,
        high_price=prices[-1] if prices else None,
        main_unit=split.main_unit,
        period_label=choice.label,
        delta_percent=delta,
        verdict=verdict,
        data_problem=data_problem,
        check_points=_check_points(
            item=item,
            verdict=verdict,
            delta=delta,
            comparable_count=count,
            other_unit_count=len(split.other),
            reference_count=len(references),
            main_unit=split.main_unit,
            period_note=choice.note,
            data_problem=data_problem,
            safety_status=safety_status,
        ),
    )


# ── 요약 카드와 표 ──


@dataclass(frozen=True)
class VerdictCounts:
    total: int
    check: tuple[str, ...]
    insufficient: tuple[str, ...]
    in_range: tuple[str, ...]


def verdict_counts(comparisons: Sequence[QuoteItemComparison]) -> VerdictCounts:
    def titles(kind: str) -> tuple[str, ...]:
        return tuple(c.title for c in comparisons if c.verdict.kind == kind)

    return VerdictCounts(
        total=len(comparisons),
        check=titles(VERDICT_CHECK),
        insufficient=titles(VERDICT_INSUFFICIENT),
        in_range=titles(VERDICT_IN_RANGE),
    )


def _short_list(titles: Iterable[str], *, limit: int = 3) -> str:
    names = list(titles)
    if not names:
        return "해당 품목 없음"
    shown = " · ".join(names[:limit])
    return shown + (f" 외 {len(names) - limit}개" if len(names) > limit else "")


def summary_cards_html(counts: VerdictCounts, *, file_name: str) -> str:
    cards = [
        _metric_card("견적서 품목", f"{counts.total}개", _file_tag(file_name), None),
        _metric_card(VERDICT_CHECK, f"{len(counts.check)}개", html.escape(_short_list(counts.check)), TONE_WARN),
        _metric_card(
            VERDICT_INSUFFICIENT,
            f"{len(counts.insufficient)}개",
            html.escape(_short_list(counts.insufficient)),
            TONE_MUTED,
        ),
        _metric_card(
            VERDICT_IN_RANGE, f"{len(counts.in_range)}개", html.escape(_short_list(counts.in_range)), TONE_OK
        ),
    ]
    return '<div class="qr-metrics">' + "".join(cards) + "</div>"


def _file_tag(file_name: str) -> str:
    name = _text(file_name) or "올린 파일"
    return f'<span class="qr-filetag" title="{html.escape(name)}">{html.escape(name)}</span>'


def _metric_card(label: str, value: str, sub_html: str, tone: str | None) -> str:
    dot = f'<span class="pc-dot pc-{tone}"></span>' if tone else ""
    return (
        f'<div class="pc-card pc-metric qr-metric">{dot}<div class="pc-label">{html.escape(label)}</div>'
        f'<div class="pc-value">{html.escape(value)}</div><div class="pc-sub">{sub_html}</div></div>'
    )


TABLE_COLUMNS = ("번호", "품목 / 모델", "수량", "견적 단가", "거래 가운데 값", "차이 %", "판정")


def table_rows(comparisons: Sequence[QuoteItemComparison], items: Sequence[Any] = ()) -> list[dict[str, object]]:
    """Rows for st.dataframe. Money stays numeric so the grid right-aligns it.

    The trade count lives in the detail card; the table keeps to what fits beside it.
    """

    rows: list[dict[str, object]] = []
    for c in comparisons:
        item = items[c.index] if c.index < len(items) else None
        product = _text(getattr(item, "product_name", "")) if item is not None else ""
        label = c.title if not product or product == c.title else f"{c.title} · {product}"
        rows.append(
            {
                "번호": c.number,
                "품목 / 모델": label,
                "수량": c.quantity_text,
                "견적 단가": float(c.quote_unit_price) if c.quote_unit_price is not None else None,
                "거래 가운데 값": float(c.median_price) if c.median_price is not None else None,
                "차이 %": float(c.delta_percent) if c.delta_percent is not None else None,
                "판정": [c.verdict.kind],
            }
        )
    return rows


# ── 선택한 품목의 견적 조건 ──


@dataclass(frozen=True)
class ConditionRow:
    label: str
    value: str
    status: str
    tone: str


def _joined(*values: object) -> str:
    return " · ".join(dict.fromkeys(text for text in (_text(value) for value in values) if text))


def condition_rows(item: Any, *, main_unit: str | None) -> list[ConditionRow]:
    """What the quote says about the conditions that change a price. Missing means 'ask'."""

    unit = _text(getattr(item, "unit", ""))
    if unit and main_unit:
        unit_status, unit_tone = ("거래와 같음", TONE_OK) if _same_unit(unit, main_unit) else ("거래와 다름", TONE_WARN)
        unit_value = f"견적 {unit} · 거래 {main_unit}"
    elif unit:
        unit_status, unit_tone, unit_value = "거래 단위 없음", TONE_MUTED, f"견적 {unit}"
    else:
        unit_status, unit_tone, unit_value = "견적서에 없음", TONE_WARN, "단위가 적혀 있지 않음"

    rows = [ConditionRow("단위", unit_value, unit_status, unit_tone)]
    for label, value in (
        ("부가세", _joined(getattr(item, "vat_status", ""))),
        ("설치·운송", _joined(getattr(item, "installation_condition", ""), getattr(item, "delivery_condition", ""))),
        ("구성·옵션", _joined(getattr(item, "option_condition", ""), getattr(item, "specification", ""))),
        ("보증·유지보수", _joined(getattr(item, "warranty_condition", ""), getattr(item, "maintenance_condition", ""))),
    ):
        if value:
            rows.append(ConditionRow(label, value, "견적서에 있음", TONE_OK))
        else:
            rows.append(ConditionRow(label, "적혀 있지 않음", "견적처에 확인", TONE_WARN))
    return rows


def condition_table_html(rows: Sequence[ConditionRow]) -> str:
    body = "".join(
        f"<tr><td class=\"qr-cond-label\">{html.escape(row.label)}</td><td>{html.escape(row.value)}</td>"
        f"<td class=\"qr-cond-status\">{pill_html(row.status, row.tone)}</td></tr>"
        for row in rows
    )
    return (
        '<table class="pc-table qr-cond"><thead><tr><th>구분</th><th>견적서 내용</th>'
        f'<th class="qr-cond-status">상태</th></tr></thead><tbody>{body}</tbody></table>'
    )


# ── 오른쪽 상세 카드 ──


def _won(value: Decimal | None) -> str:
    return f"{value:,.0f}원" if value is not None else "—"


def _per_unit(unit: str | None) -> str:
    return result_summary.per_unit_label(unit).strip() or "1단위당"


def detail_card_html(comparison: QuoteItemComparison, *, total: int) -> str:
    c = comparison
    tone = c.verdict.tone
    quote_sub = _per_unit(c.quote_unit or None) if c.quote_unit_price is not None else "견적서에 단가 없음"
    if c.median_price is not None:
        median_sub = f"같은 제품 {c.comparable_count}건 · {_per_unit(c.main_unit)} · {c.period_label}"
    else:
        median_sub = "같은 제품 거래 없음" if c.data_problem is None else "거래 자료 없음"

    if c.delta_percent is not None:
        sign = "+" if c.delta_percent > 0 else ""
        headline = f"가운데 값보다 {sign}{c.delta_percent:.1f}%"
        headline_class = f"qr-delta qr-{tone}"
    else:
        headline = "차이를 계산하지 않았습니다"
        headline_class = "qr-delta qr-muted"

    points = "".join(f"<li>{html.escape(point)}</li>" for point in c.check_points) or (
        "<li>추가로 확인할 점이 없습니다. 그래도 VAT·설치 조건은 견적서 원문으로 확인하세요.</li>"
    )
    range_line = ""
    if c.low_price is not None and c.high_price is not None and c.comparable_count >= 2:
        range_line = (
            f'<div class="qr-range">거래 가격 {_won(c.low_price)} ~ {_won(c.high_price)}</div>'
        )
    subtitle = f'<div class="qr-hint">{html.escape(c.subtitle)}</div>' if c.subtitle else ""
    return (
        '<div class="qr-detail">'
        f'<span class="pc-pill pc-info">선택한 품목 {c.number} / {total}</span>'
        f'<div class="qr-detail-title">{html.escape(c.title)}</div>{subtitle}'
        '<div class="qr-prices">'
        f'<div class="qr-cell"><div class="qr-lbl">견적 단가</div><div class="qr-num">{_won(c.quote_unit_price)}</div>'
        f'<div class="qr-lbl">{html.escape(quote_sub)}</div></div>'
        f'<div class="qr-cell"><div class="qr-lbl">거래 가운데 값</div><div class="qr-num">{_won(c.median_price)}</div>'
        f'<div class="qr-lbl">{html.escape(median_sub)}</div></div>'
        "</div>"
        '<div class="qr-divider"></div>'
        '<div class="qr-lbl qr-strong">비교 결과</div>'
        f'<div class="{headline_class}">{html.escape(headline)}</div>'
        f'<div class="qr-verdict">{pill_html(c.verdict.label, tone)}</div>'
        f'<p class="qr-reason">{html.escape(c.verdict.reason)}</p>'
        f"{range_line}"
        f'<div class="qr-points"><b>확인할 점</b><ul>{points}</ul></div>'
        "</div>"
    )


LAYOUT_CSS = """
<style>
.qr-metrics {display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin:4px 0 12px 0;}
.qr-metric {display:flex; flex-direction:column;}
.qr-metric .pc-sub {overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
.qr-filetag {display:inline-block; max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
  vertical-align:bottom; font-size:11px; color:#567399; border:1px solid #D2E0F0; background:#F3F8FD;
  padding:3px 8px; border-radius:6px;}
.qr-rule {font-size:12px; color:#5B6C82; line-height:1.6; margin:0 0 14px 0; padding:10px 14px;
  background:#F3F8FD; border:1px solid #D2E0F0; border-radius:9px;}
.qr-rule b {color:#25466B;}
.qr-section-title {font-size:17px; font-weight:700; color:var(--pc-navy); margin:0;}
.qr-section-sub {font-size:12px; color:var(--pc-muted); margin:2px 0 0 0;}
.qr-foot {font-size:11px; color:#8694A6; margin:4px 0 0 0; line-height:1.6;}
.qr-detail .pc-pill {margin-bottom:10px;}
.qr-detail-title {font-size:20px; font-weight:800; color:var(--pc-navy); letter-spacing:-0.5px; line-height:1.35;
  word-break:keep-all;}
.qr-hint {font-size:12px; color:#7B8A9C; margin:4px 0 0 0;}
.qr-prices {display:grid; grid-template-columns:1fr 1fr; gap:9px; margin:14px 0 14px 0;}
.qr-cell {padding:13px 14px; background:#F6F9FC; border-radius:9px; min-height:92px;}
.qr-num {font-size:18px; font-weight:800; color:var(--pc-navy); margin:6px 0; font-variant-numeric:tabular-nums;
  word-break:keep-all;}
.qr-lbl {font-size:11px; color:#6A7D90; line-height:1.5;}
.qr-strong {font-weight:700; font-size:12px;}
.qr-divider {height:1px; background:#E9EEF4; margin:2px 0 12px 0;}
.qr-delta {font-size:22px; font-weight:800; letter-spacing:-0.4px; margin:4px 0 8px 0;}
.qr-delta.qr-warn {color:#B45309;} .qr-delta.qr-ok {color:#047857;} .qr-delta.qr-muted {color:#596A80; font-size:17px;}
.qr-reason {font-size:13px; color:#4E5F75; line-height:1.65; margin:8px 0 6px 0; word-break:keep-all;}
.qr-range {font-size:12px; color:#6A7D90; margin:0 0 8px 0;}
.qr-points {padding:12px 14px; background:#FFF8E9; border:1px solid #F7E3C1; border-radius:9px; color:#7A5310;
  font-size:12px; line-height:1.7; margin:12px 0 4px 0;}
.qr-points b {color:#8F6113;}
.qr-points ul {margin:4px 0 0 0; padding-left:18px;}
.qr-points li {margin:0;}
.qr-cond {margin-top:4px;}
.qr-cond td {vertical-align:middle; color:#33475F; word-break:keep-all;}
.qr-cond th, .qr-cond td {padding:8px 10px !important; font-size:12px; border-left:0 !important; border-right:0 !important;}
.qr-cond th {background:#F5F8FC !important; font-size:11px; color:var(--pc-muted);}
.qr-cond-label {width:110px; font-weight:700; color:#25466B !important; white-space:nowrap;}
.qr-cond-status {width:120px; text-align:right;}
.qr-subhead {font-size:15px; font-weight:700; color:var(--pc-navy); margin:18px 0 8px 0;}
.st-key-qr_table_card,.st-key-qr_detail_card {border-radius:13px !important; box-shadow:0 2px 11px rgba(23,52,89,.035);
  border-color:#DCE4EE !important;}
.st-key-qr_detail_card button[kind="primary"], .st-key-qr_detail_card button[kind="secondary"] {border-radius:9px;}
@media (max-width: 900px) { .qr-metrics {grid-template-columns:repeat(2,minmax(0,1fr));} }
</style>
"""
