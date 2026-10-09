"""Plain-language result summary for the purchasing team (UI simplification, 2026-10).

The search result opens with one conclusion sentence, a price band and short tables; full
tables stay one click away. This module only rearranges results that are already computed
(it never widens a price range, mixes reference trades into the direct band, or calls a
quote "적정"), so the wording is unit-testable and the page stays thin.

New module so a Streamlit hot reload that keeps older modules never sees a half-updated import.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

TONE_OK = "ok"
TONE_WARN = "warn"
TONE_NEUTRAL = "neutral"

SUMMARY_ROW_LIMIT = 5
OUTLIER_FACTOR = Decimal("3")
OUTLIER_SHOWN = 3
# Runtime marker: the dashboard reloads a retained copy that lacks price_outlier_rows.
OUTLIERS_V1 = True
# Runtime marker: unit-aware conclusion, unit groups and total/quantity/unit-price rows.
UNIT_AWARE_V1 = True
UNIT_AWARE_V2 = True
G2B_LINK_COLUMN_V1 = True
BUSINESS_NAME_V1 = True
BUSINESS_NAME_MAX_CHARS = 40
OVERVIEW_ROW_LIMIT = 10
# Runtime marker (2026-10-09 acceptance fixes): overview_model_keys, collected-count labels,
# quote_item_rows(current_index=...).
RESULT_SUMMARY_V3 = True
# Runtime marker (2026-10-10): entry_error_line / entry_error_notice and the excluded count in the
# conclusion; 입력 오류 의심 trades never enter a price.
ENTRY_ERRORS_V1 = True
# Overview and same-item tables count the collected index only (no live days, all periods).
COLLECTED_TRADES_LABEL = "같은 제품 거래(수집분)"

# Words that only make sense to the developers. The screen uses the plain words instead.
BANNED_SCREEN_TERMS: tuple[str, ...] = (
    "identity",
    "Identity",
    "exact",
    "Track B",
    "serving index",
    "워크스페이스",
    "품목 책임주체",
    "직접 동일성",
    "형명",
)

# Data keys stay stable for the Excel export and the presenters; only the table headers change.
COLUMN_LABELS: dict[str, str] = {
    "품목 책임주체": "제조·수입업체(식약처)",
    "실제 조달 공급업체": "납품업체(나라장터)",
    "실제 납품업체": "납품업체(나라장터)",
    "공급업체": "납품업체",
    "식약처 품목번호": "허가번호",
    "식약처 상태": "판매 상태",
    "식약처 처리일": "허가일",
    "나라장터 직접거래": "같은 제품 거래",
    "나라장터 거래": "같은 제품 거래",
    "나라장터 가격범위": "거래 가격범위",
    "나라장터 직접가격 모델": "거래가 있는 모델",
    "나라장터 상태": "거래 자료 상태",
    "직접거래건수": "거래 건수",
    "수요기관수": "납품 기관 수",
    "최근거래": "최근 거래",
    "최근거래일": "최근 거래",
    "최근 식약처 처리일": "최근 허가일",
    "원문근거해시": "원문 확인값",
    "원문근거키": "원문 위치",
    "매칭근거": "같은 제품으로 본 이유",
    "매칭등급": "같은 제품 판단",
    "가격": "대당 단가",
    "판매처": "납품업체",
    "구매처": "구매 기관",
    "현재 모델": "검색한 모델",
}

_STATUS_WORDS = {
    "국내 정상": "판매 가능",
    "국내 정상(품목)": "판매 가능(허가 기준)",
    "취소·취하": "취소됨",
    "취소·취하(품목)": "취소됨(허가 기준)",
    "수출용": "수출 전용",
    "수출용(품목)": "수출 전용(허가 기준)",
    "상태 미확인": "확인 안 됨",
}


def _won(value: Decimal | None) -> str:
    return f"{value:,.0f}원" if value is not None else "미확인"


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("원", "").strip())
    except Exception:
        return None


@dataclass(frozen=True)
class PriceBand:
    low: Decimal
    high: Decimal
    median: Decimal | None
    quote: Decimal | None = None


@dataclass(frozen=True)
class Conclusion:
    headline: str
    detail: str | None
    quote_line: str | None
    caveat: str | None
    tone: str
    band: PriceBand | None


def entry_error_notice(count: int) -> str:
    return (
        f"단가가 10원 이하로 적힌 거래 {count}건(입력 오류 의심)은 "
        "가격 계산에서 뺐습니다. 원문을 확인하세요."
    )


def _percent(value: Decimal, base: Decimal) -> Decimal:
    return ((value - base) / base * 100).quantize(Decimal("0.1"))


def _direction(delta: Decimal) -> str:
    if delta > 0:
        return f"{delta:.1f}% 높습니다"
    if delta < 0:
        return f"{abs(delta):.1f}% 낮습니다"
    return "같습니다"


def build_conclusion(
    stats: Any,
    *,
    quote_unit_price: Decimal | None,
    unavailable: bool = False,
    unit: str | None = None,
) -> Conclusion:
    """One sentence on what the product traded for and where the quote sits.

    Only same-product (A/B) trades enter the numbers. The wording describes a position and
    never says a quote is fair, cheap or expensive.
    """

    direct = int(getattr(stats, "direct_count", 0) or 0)
    references = int(getattr(stats, "reference_count", 0) or 0)
    excluded = int(getattr(stats, "entry_error_count", 0) or 0)
    low = getattr(stats, "min_price", None)
    high = getattr(stats, "max_price", None)
    mid = getattr(stats, "median_price", None)
    latest = getattr(stats, "latest_transaction_date", None)
    quote = quote_unit_price if quote_unit_price is not None and quote_unit_price > 0 else None
    caveat = (
        "VAT·설치·옵션 같은 조건이 같은지는 확인하지 않은 비교입니다."
        if quote is not None and direct and low is not None
        else None
    )

    if unavailable:
        return Conclusion(
            headline="나라장터 가격 자료에 연결하지 못해 거래가를 확인하지 못했습니다.",
            detail="잠시 뒤 다시 검색하세요.",
            quote_line=(
                "거래가를 불러오지 못해 견적 위치를 계산하지 않았습니다." if quote else None
            ),
            caveat=None,
            tone=TONE_WARN,
            band=None,
        )

    if direct == 0 or low is None or high is None:
        notes = []
        if excluded:
            notes.append(entry_error_notice(excluded))
        if references:
            notes.append(
                f"이름이 비슷한 품목의 거래 {references}건은 같은 제품인지 확인되지 않아 "
                "가격 비교에 넣지 않았습니다. 아래에서 참고만 하세요."
            )
        detail = " ".join(notes) or None
        return Conclusion(
            headline="같은 제품으로 확인된 나라장터 거래가 없습니다.",
            detail=detail,
            quote_line=(
                "같은 제품 거래가 없어 견적 위치를 계산하지 않았습니다." if quote else None
            ),
            caveat=None,
            tone=TONE_NEUTRAL,
            band=None,
        )

    latest_text = f" · 최근 거래 {latest}" if latest else ""
    per = per_unit_label(unit)
    if direct == 1:
        quote_line = None
        if quote is not None:
            quote_line = (
                f"내 견적가 {_won(quote)}은 이 1건보다 {_direction(_percent(quote, low))}. "
                "1건뿐이라 가격대를 판단하기에는 부족합니다."
            )
        return Conclusion(
            headline=f"같은 제품의 나라장터 거래는 1건이고, {per}{_won(low)}에 거래됐습니다.",
            detail=latest_text.removeprefix(" · ") or None,
            quote_line=quote_line,
            caveat=caveat,
            tone=TONE_OK,
            band=None,
        )

    if low == high:
        quote_line = None
        if quote is not None:
            quote_line = f"내 견적가 {_won(quote)}은 이 거래가보다 {_direction(_percent(quote, low))}."
        return Conclusion(
            headline=f"같은 제품이 나라장터에서 {direct}번 거래됐고, 모두 {per}{_won(low)}이었습니다.",
            detail=latest_text.removeprefix(" · ") or None,
            quote_line=quote_line,
            caveat=caveat,
            tone=TONE_OK,
            band=None,
        )

    if direct == 2:
        headline = f"같은 제품의 나라장터 거래는 2건이고, {per}{_won(low)}과 {_won(high)}에 거래됐습니다."
        band = None
    else:
        headline = (
            f"같은 제품이 나라장터에서 {direct}번 거래됐고, {per}가운데 값(중앙값)은 {_won(mid)}입니다."
        )
        band = PriceBand(low=low, high=high, median=mid, quote=quote)

    quote_line = None
    if quote is not None:
        if quote > high:
            where = "지금까지 거래된 가장 높은 값보다도 높습니다"
        elif quote < low:
            where = "지금까지 거래된 가장 낮은 값보다도 낮습니다"
        else:
            where = "거래된 가격 범위 안에 있습니다"
        if direct == 2 or mid is None:
            quote_line = f"내 견적가 {_won(quote)}은 {where}. 2건뿐이라 가격대를 판단하기에는 부족합니다."
        else:
            quote_line = (
                f"내 견적가 {_won(quote)}은 중앙값보다 {_direction(_percent(quote, mid))}. {where}."
            )

    return Conclusion(
        headline=headline,
        detail=f"{per}거래가 {_won(low)} ~ {_won(high)}{latest_text}",
        quote_line=quote_line,
        caveat=caveat,
        tone=TONE_OK,
        band=band,
    )


BAND_CSS = """
<style>
.pr-conclusion {border:1px solid rgba(128,128,128,0.28); border-radius:0.6rem; padding:0.85rem 1rem 0.6rem 1rem; margin:0.3rem 0 0.6rem 0;}
.pr-conclusion.pr-warn {border-left:4px solid #d97706;}
.pr-conclusion.pr-ok {border-left:4px solid #1D4ED8;}
.pr-conclusion.pr-neutral {border-left:4px solid #94a3b8;}
.pr-headline {font-size:1.12rem; font-weight:700; line-height:1.5; word-break:keep-all;}
.pr-detail {font-size:0.86rem; opacity:0.75; margin-top:0.15rem;}
.pr-quote-line {font-size:1rem; font-weight:600; margin-top:0.45rem; color:#92400e; word-break:keep-all;}
.pr-caveat {font-size:0.8rem; opacity:0.7; margin-top:0.15rem;}
.pr-band {position:relative; height:74px; margin:0.5rem 0.4rem 0.1rem 0.4rem;}
.pr-track {position:absolute; top:40px; left:0; right:0; height:4px; background:rgba(128,128,128,0.25); border-radius:2px;}
.pr-range {position:absolute; top:35px; height:14px; background:rgba(29,78,216,0.14); border:1px solid #1D4ED8; border-radius:7px;}
.pr-median {position:absolute; top:33px; width:18px; height:18px; margin-left:-9px; border-radius:50%; background:#1D4ED8; border:2px solid #fff;}
.pr-mark {position:absolute; top:17px; width:0; height:0; margin-left:-8px; border-left:8px solid transparent; border-right:8px solid transparent; border-top:13px solid #b45309;}
.pr-label {position:absolute; font-size:0.74rem; white-space:nowrap; transform:translateX(-50%);}
.pr-label.pr-top {top:0; color:#b45309; font-weight:600;}
.pr-label.pr-bottom {top:56px; opacity:0.75;}
.pr-label.pr-mid {top:56px; color:#1D4ED8; font-weight:600;}
</style>
"""


def _position(value: Decimal, low: Decimal, high: Decimal) -> float:
    if high <= low:
        return 50.0
    return float((value - low) / (high - low) * 100)


def _label_left(percent: float) -> float:
    """Keep centered labels inside the band."""

    return min(max(percent, 7.0), 93.0)


def render_price_band_html(band: PriceBand) -> str:
    """Trade range as a bar, the median as a dot and the quote as a triangle above it."""

    axis_low = min(band.low, band.quote) if band.quote is not None else band.low
    axis_high = max(band.high, band.quote) if band.quote is not None else band.high
    low_at = _position(band.low, axis_low, axis_high)
    high_at = _position(band.high, axis_low, axis_high)
    parts = [
        '<div class="pr-band" id="purchase-price-band-v1">',
        '<div class="pr-track"></div>',
        f'<div class="pr-range" style="left:{low_at:.2f}%; width:{max(high_at - low_at, 0.8):.2f}%"></div>',
    ]
    mid_at: float | None = None
    if band.median is not None:
        mid_at = _position(band.median, axis_low, axis_high)
        parts.append(f'<div class="pr-median" style="left:{mid_at:.2f}%"></div>')
    if band.quote is not None:
        quote_at = _position(band.quote, axis_low, axis_high)
        parts.append(f'<div class="pr-mark" style="left:{quote_at:.2f}%"></div>')
        parts.append(
            f'<div class="pr-label pr-top" style="left:{_label_left(quote_at):.2f}%">'
            f"내 견적 {html.escape(_won(band.quote))}</div>"
        )
    parts.append(
        f'<div class="pr-label pr-bottom" style="left:{_label_left(low_at):.2f}%">'
        f"최저 {html.escape(_won(band.low))}</div>"
    )
    parts.append(
        f'<div class="pr-label pr-bottom" style="left:{_label_left(high_at):.2f}%">'
        f"최고 {html.escape(_won(band.high))}</div>"
    )
    if mid_at is not None and 18 < mid_at < 82 and abs(mid_at - low_at) > 14 and abs(high_at - mid_at) > 14:
        parts.append(
            f'<div class="pr-label pr-mid" style="left:{mid_at:.2f}%">'
            f"중앙값 {html.escape(_won(band.median))}</div>"
        )
    parts.append("</div>")
    return "".join(parts)


def render_conclusion_html(conclusion: Conclusion) -> str:
    lines = [
        f'<div class="pr-conclusion pr-{html.escape(conclusion.tone)}" id="purchase-conclusion-v1">',
        f'<div class="pr-headline">{html.escape(conclusion.headline)}</div>',
    ]
    if conclusion.detail:
        lines.append(f'<div class="pr-detail">{html.escape(conclusion.detail)}</div>')
    if conclusion.quote_line:
        lines.append(f'<div class="pr-quote-line">{html.escape(conclusion.quote_line)}</div>')
    if conclusion.caveat:
        lines.append(f'<div class="pr-caveat">{html.escape(conclusion.caveat)}</div>')
    if conclusion.band is not None:
        lines.append(render_price_band_html(conclusion.band))
    lines.append("</div>")
    return BAND_CSS + "".join(lines)


def short_basis_line(
    *,
    track_b_data_as_of: str | None,
    live_checked_until: str | None = None,
    live_failed: bool = False,
    mfds_coverage_percent: float | None = None,
    mfds_complete: bool = False,
) -> str:
    """One quiet line under the cards; the long version stays in the detail section."""

    parts: list[str] = []
    if track_b_data_as_of:
        text = f"나라장터 {track_b_data_as_of} 수집분"
        if live_checked_until:
            text += f" + {live_checked_until}까지 실시간 확인"
        elif live_failed:
            text += " (최근 며칠 실시간 확인 실패)"
        parts.append(text)
    if not mfds_complete and mfds_coverage_percent is not None:
        parts.append(f"식약처 자료 {mfds_coverage_percent:.0f}% 수집 중이라 빠진 모델이 있을 수 있음")
    return "자료 기준 · " + " · ".join(parts) if parts else ""


def display_rows(rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """Rename data keys to the plain table headers and plain status words."""

    output: list[dict[str, object]] = []
    for row in rows:
        renamed: dict[str, object] = {}
        for key, value in row.items():
            label = COLUMN_LABELS.get(key, key)
            if isinstance(value, str):
                value = plain_status(value)
            renamed[label] = value
        output.append(renamed)
    return output


def plain_status(text: str) -> str:
    return _STATUS_WORDS.get(text, text)


def price_group_summary_rows(
    group_rows: Sequence[Mapping[str, object]],
    *,
    limit: int = SUMMARY_ROW_LIMIT,
) -> list[dict[str, object]]:
    """Top groups by trade count; the model column only when more than one model appears."""

    multiple_models = len({str(row.get("모델") or "") for row in group_rows}) > 1
    ordered = sorted(group_rows, key=lambda row: -int(row.get("거래건수") or 0))
    output: list[dict[str, object]] = []
    for row in ordered[:limit]:
        summary: dict[str, object] = {}
        if multiple_models:
            summary["모델"] = row.get("모델") or ""
        summary.update(
            {
                "규격": row.get("규격") or "",
                "거래조건": row.get("거래조건") or "",
                "건수": row.get("거래건수") or 0,
                "최저": row.get("최저단가") or "",
                "중앙값": row.get("중앙값") or "",
                "최고": row.get("최고단가") or "",
                "최근 거래": row.get("최근거래일") or "",
            }
        )
        output.append(summary)
    return output


def supplier_summary_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    limit: int | None = SUMMARY_ROW_LIMIT,
) -> list[dict[str, object]]:
    selected = rows if limit is None else rows[:limit]
    return [
        {
            "납품업체": row.get("공급업체") or "",
            "거래 건수": row.get("직접거래건수") or 0,
            "납품 기관 수": row.get("수요기관수") or 0,
            "최저": _won(_decimal(row.get("최저단가"))) if row.get("최저단가") is not None else "",
            "최고": _won(_decimal(row.get("최고단가"))) if row.get("최고단가") is not None else "",
            "최근 거래": row.get("최근거래일") or "",
        }
        for row in selected
    ]


def _trade_count(value: object) -> int:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else 0


def same_item_summary_rows(
    view_rows: Sequence[Mapping[str, object]],
    *,
    limit: int = SUMMARY_ROW_LIMIT,
) -> list[dict[str, object]]:
    """Searched model first, then the most-traded models; company repeated on every row."""

    filled: list[dict[str, object]] = []
    company = ""
    for row in view_rows:
        company = str(row.get("품목 책임주체") or "") or company
        filled.append({**row, "_company": company})

    def order(row: Mapping[str, object]) -> tuple[int, int, str]:
        current = str(row.get("모델") or "").startswith("▶")
        return (0 if current else 1, -_trade_count(row.get("나라장터 거래")), str(row.get("모델") or ""))

    return [
        {
            "모델": row.get("모델") or "",
            "제조·수입업체": row.get("_company") or "",
            COLLECTED_TRADES_LABEL: row.get("나라장터 거래") or "",
            "가격범위": row.get("가격범위") or "",
            "최근 거래": row.get("최근거래") or "",
        }
        for row in sorted(filled, key=order)[:limit]
    ]


def _crosslink_count(row: Mapping[str, object]) -> int:
    try:
        return int(row.get("나라장터 직접거래") or 0)
    except (TypeError, ValueError):
        return 0


def _overview_ordered(
    crosslinks: Sequence[Mapping[str, object]],
    limit: int | None,
) -> list[Mapping[str, object]]:
    seen: set[str] = set()
    ordered: list[Mapping[str, object]] = []
    for row in sorted(crosslinks, key=lambda row: (-_crosslink_count(row), str(row.get("모델") or ""))):
        model = str(row.get("모델") or "").strip()
        if not model or model in seen:
            continue
        seen.add(model)
        ordered.append(row)
    return ordered if limit is None else ordered[:limit]


def overview_model_rows(
    crosslinks: Sequence[Mapping[str, object]],
    *,
    limit: int | None = OVERVIEW_ROW_LIMIT,
) -> list[dict[str, object]]:
    """Company/product-name overview: models with trades first, most-traded first.

    The counts come from the collected index (all periods, without the last few live days), so
    the column says 수집분; an opened model can show a few more trades.
    """

    return [
        {
            "모델": row.get("모델") or "",
            "제조·수입업체": row.get("품목 책임주체") or "",
            COLLECTED_TRADES_LABEL: (
                f"{_crosslink_count(row)}건" if row.get("나라장터 직접거래") is not None else "조회 불가"
            ),
            "가격범위": (row.get("나라장터 가격범위") or "") if _crosslink_count(row) else "",
            "최근 거래": row.get("최근거래") or "",
        }
        for row in _overview_ordered(crosslinks, limit)
    ]


def overview_model_keys(
    crosslinks: Sequence[Mapping[str, object]],
    *,
    limit: int | None = OVERVIEW_ROW_LIMIT,
) -> list[tuple[str, str, str]]:
    """(허가번호, 모델, 제조·수입업체) for each overview_model_rows row, in the same order, so a
    clicked row opens exactly that registration instead of every product with the model name."""

    return [
        (
            str(row.get("식약처 품목번호") or "").strip(),
            str(row.get("모델") or "").strip(),
            str(row.get("품목 책임주체") or "").strip(),
        )
        for row in _overview_ordered(crosslinks, limit)
    ]


def collected_counts_note(track_b_data_as_of: str | None) -> str:
    """Why an overview/same-item count can be a few lower than the opened result."""

    when = f"나라장터 {track_b_data_as_of} 수집분" if track_b_data_as_of else "수집해 둔 나라장터 자료"
    return (
        f"건수는 {when}의 전체 기간 기준입니다. 모델을 열면 그 뒤 며칠의 실시간 거래와 고른 거래 기간이 "
        "반영돼 건수가 조금 다를 수 있습니다."
    )


def quote_item_rows(
    items: Sequence[Any],
    results: Mapping[int, Mapping[str, object]],
    *,
    current_index: int | None = None,
) -> list[dict[str, object]]:
    """Master table for an uploaded quote. Items not opened yet show what happens on click;
    the item shown below the table is marked with ▶."""

    rows: list[dict[str, object]] = []
    for index, item in enumerate(items):
        title = " · ".join(
            str(part)
            for part in (getattr(item, "product_name", None), getattr(item, "model_name", None))
            if part
        ) or f"품목 {index + 1}"
        if index == current_index:
            title = f"▶ {title}"
        quote = getattr(item, "unit_price", None)
        result = results.get(index)
        if result is None:
            median_text, position, status = "—", "선택하면 조사", "조사 전"
        elif result.get("needs_choice"):
            median_text, position, status = "—", "—", "제품 고르기 필요"
        else:
            median_value = result.get("median_price")
            median_text = _won(median_value) if median_value is not None else "—"
            direct = int(result.get("direct_count") or 0)
            if direct == 0:
                position, status = "비교 불가", "같은 제품 거래 0건"
            elif quote is None or median_value is None:
                position, status = "—", "확인됨"
            elif direct < 3:
                position, status = f"{_percent(Decimal(str(quote)), median_value):+.1f}%", f"거래 {direct}건뿐"
            else:
                position, status = f"{_percent(Decimal(str(quote)), median_value):+.1f}%", "확인됨"
        rows.append(
            {
                "#": index + 1,
                "품목·모델": title,
                "견적 단가": _won(Decimal(str(quote))) if quote is not None else "미확인",
                "거래 중앙값": median_text,
                "중앙값 대비": position,
                "상태": status,
            }
        )
    return rows


def has_banned_term(text: str) -> str | None:
    return next((term for term in BANNED_SCREEN_TERMS if term in text), None)


def price_outlier_rows(
    rows: Sequence[Mapping[str, object]],
    median_price: Decimal | None,
    *,
    factor: Decimal = OUTLIER_FACTOR,
) -> list[Mapping[str, object]]:
    """Same-product trades priced ``factor`` times above or below the median, farthest first.

    These usually differ in unit (set vs 대), contract type or bundled options; the buyer checks
    them against the archived public record instead of the app guessing why.
    """

    if median_price is None or median_price <= 0:
        return []
    found: list[tuple[Decimal, Mapping[str, object]]] = []
    for row in rows:
        price = _decimal(row.get("가격"))
        if price is None or price <= 0:
            continue
        ratio = price / median_price if price >= median_price else median_price / price
        if ratio >= factor:
            found.append((ratio, row))
    return [row for _ratio, row in sorted(found, key=lambda item: -item[0])]


def entry_error_line(row: Mapping[str, object]) -> str:
    """One 입력 오류 의심 trade for the box: when, who, what for, and the numbers as typed."""

    parts = []
    for key in ("거래일", "구매처"):
        value = str(row.get(key) or "").strip()
        if value and value != "미확인":
            parts.append(value)
    business_name = " ".join(str(row.get("사업명") or "").split())
    if business_name:
        if len(business_name) > BUSINESS_NAME_MAX_CHARS:
            business_name = business_name[: BUSINESS_NAME_MAX_CHARS - 1] + "…"
        parts.append(f"사업명 「{business_name}」")
    total = str(row.get("총액") or "").strip()
    if total and total != "미확인":
        parts.append(f"거래 총액 {total}")
    return " · ".join(parts)


def outlier_line(row: Mapping[str, object], median_price: Decimal, main_unit: str | None = None) -> str:
    price = _decimal(row.get("가격"))
    parts = [trade_amount_line(row)]
    if price is not None and median_price > 0:
        ratio = price / median_price if price >= median_price else median_price / price
        direction = "높음" if price >= median_price else "낮음"
        parts.append(f"{per_unit_label(main_unit)}중앙값의 {ratio:.1f}배 {direction}")
    business_name = " ".join(str(row.get("사업명") or "").split())
    if business_name:
        if len(business_name) > BUSINESS_NAME_MAX_CHARS:
            business_name = business_name[: BUSINESS_NAME_MAX_CHARS - 1] + "…"
        parts.append(f"사업명 「{business_name}」")
    for key in ("거래조건", "구매처", "거래일"):
        value = str(row.get(key) or "").strip()
        if value and value != "미확인":
            parts.append(value)
    return " · ".join(parts)


# ── 단위(대·set 등)를 섞지 않고, 거래 총액 → 수량 → 1단위 가격 순으로 보여주기 ──


def unit_key(unit: object) -> str:
    text = " ".join(str(unit or "").split())
    return "" if text in {"", "미확인"} else text.casefold()


def _unit_display(units: Iterable[object]) -> dict[str, str]:
    display: dict[str, str] = {}
    for unit in units:
        key = unit_key(unit)
        if key and key not in display:
            display[key] = " ".join(str(unit).split())
    return display


@dataclass(frozen=True)
class UnitSplit:
    """Same-product trades split by the most common unit; unknown units stay with it."""

    kept: tuple[Any, ...]
    other: tuple[Any, ...]
    main_unit: str | None
    other_units: tuple[str, ...]

    @property
    def mixed(self) -> bool:
        return bool(self.other)


def split_by_main_unit(candidates: Sequence[Any]) -> UnitSplit:
    keys = [unit_key(getattr(candidate, "unit", None)) for candidate in candidates]
    counts: dict[str, int] = {}
    for key in keys:
        if key:
            counts[key] = counts.get(key, 0) + 1
    display = _unit_display(getattr(candidate, "unit", None) for candidate in candidates)
    if len(counts) <= 1:
        main = next(iter(counts), None)
        return UnitSplit(tuple(candidates), (), display.get(main) if main else None, ())
    main = max(counts, key=lambda key: (counts[key], key))
    kept = tuple(c for c, key in zip(candidates, keys, strict=True) if key in {"", main})
    other = tuple(c for c, key in zip(candidates, keys, strict=True) if key not in {"", main})
    other_units = tuple(dict.fromkeys(display[key] for key in keys if key not in {"", main}))
    return UnitSplit(kept, other, display[main], other_units)


def per_unit_label(unit: str | None) -> str:
    return f"1{unit}당 " if unit and len(unit) <= 2 and not unit.isascii() else (f"1 {unit}당 " if unit else "")


def unit_note(split: UnitSplit) -> str | None:
    if not split.mixed:
        return None
    others = "·".join(split.other_units)
    return (
        f"단위가 다른 거래 {len(split.other)}건({others})은 {split.main_unit} 단위 가격과 섞지 않고 "
        "아래 표에 따로 보여줍니다. 1세트가 몇 대인지는 원문에 없어 대당 가격으로 나누지 않습니다."
    )


def _quantity(value: object) -> Decimal | None:
    number = _decimal(value)
    return number if number is not None and number > 0 else None


def _number(value: Decimal) -> str:
    return f"{value:,.0f}" if value == value.to_integral_value() else f"{value.normalize():,}"


def trade_amount_line(row: Mapping[str, object]) -> str:
    """'73,026,000원 ÷ 2 set = 1 set당 36,513,000원' (or just the unit price when total is unknown)."""

    price = _decimal(row.get("가격"))
    total = _decimal(row.get("총액"))
    quantity = _quantity(row.get("수량"))
    unit = " ".join(str(row.get("단위") or "").split())
    unit = "" if unit == "미확인" else unit
    label = per_unit_label(unit or None).strip() or "1단위당"
    if total is not None and quantity is not None:
        return f"{_won(total)} ÷ {_number(quantity)}{(' ' + unit) if unit else ''} = {label} {_won(price)}"
    return f"{label} {_won(price)}"


def trade_table_rows(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Full trade list, total amount first, then quantity and the price for one unit."""

    output: list[dict[str, object]] = []
    for row in rows:
        unit = " ".join(str(row.get("단위") or "").split())
        unit = "" if unit == "미확인" else unit
        quantity = _quantity(row.get("수량"))
        price = _decimal(row.get("가격"))
        output.append(
            {
                "거래일": row.get("거래일") or "",
                "모델": row.get("모델") or "",
                "거래 총액": row.get("총액") if row.get("총액") not in (None, "미확인") else "확인 안 됨",
                "수량": f"{_number(quantity)} {unit}".strip() if quantity is not None else "확인 안 됨",
                "1단위 가격": f"{_won(price)} / {unit}" if unit else _won(price),
                # Next to the price, so the link is visible without scrolling the wide table.
                "나라장터": _g2b_url(row.get("원천기록")),
                # What the institution bought it for: explains a set, a package or an odd price.
                "사업명": row.get("사업명") or "",
                "거래조건": row.get("거래조건") or "",
                "납품업체": row.get("판매처") or "",
                "구매 기관": row.get("구매처") or "",
                "규격": row.get("규격") or "",
            }
        )
    return output


def _g2b_url(source_record_id: object) -> str | None:
    from purchase_price.services.g2b_delivery_record import g2b_url_for_source_record

    return g2b_url_for_source_record(source_record_id)


def unit_group_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    limit: int = SUMMARY_ROW_LIMIT,
) -> list[dict[str, object]]:
    """Groups by model (when several), unit and trade condition; never mixes units in a price."""

    multiple_models = len({str(row.get("모델") or "") for row in rows}) > 1
    display = _unit_display(row.get("단위") for row in rows)
    groups: dict[tuple[str, str, str], list[Mapping[str, object]]] = {}
    for row in rows:
        # "SET" and "set" are one unit; show the first spelling seen.
        key = (
            str(row.get("모델") or "") if multiple_models else "",
            unit_key(row.get("단위")),
            str(row.get("거래조건") or ""),
        )
        groups.setdefault(key, []).append(row)

    summaries: list[tuple[int, dict[str, object]]] = []
    for (model, unit_id, condition), members in groups.items():
        unit = display.get(unit_id, "")
        prices = sorted(p for p in (_decimal(m.get("가격")) for m in members) if p is not None)
        if not prices:
            continue
        quantities = [_quantity(m.get("수량")) for m in members]
        totals = [_decimal(m.get("총액")) for m in members]
        mid = prices[len(prices) // 2] if len(prices) % 2 else (prices[len(prices) // 2 - 1] + prices[len(prices) // 2]) / 2
        label = per_unit_label(unit or None).strip() or "1단위당"
        row: dict[str, object] = {}
        if multiple_models:
            row["모델"] = model
        row.update(
            {
                "단위": unit or "확인 안 됨",
                "거래조건": condition,
                "건수": len(members),
                "총수량": (
                    f"{_number(sum(q for q in quantities if q is not None))} {unit}".strip()
                    if all(q is not None for q in quantities)
                    else "일부 확인 안 됨"
                ),
                "거래 총액 합계": (
                    _won(sum(t for t in totals if t is not None))
                    if all(t is not None for t in totals)
                    else "일부 확인 안 됨"
                ),
                f"{label} 중앙값" if unit else "1단위 중앙값": _won(mid),
                "1단위 최저~최고": _won(prices[0]) if prices[0] == prices[-1] else f"{prices[0]:,.0f} ~ {prices[-1]:,.0f}원",
                "최근 거래": max((str(m.get("거래일") or "") for m in members), default=""),
            }
        )
        summaries.append((len(members), row))
    ordered = [row for _count, row in sorted(summaries, key=lambda item: -item[0])]
    # One shared header across groups: name the median column generically when units differ.
    if len({tuple(r.keys()) for r in ordered}) > 1:
        normalized = []
        for r in ordered:
            normalized.append({("1단위 중앙값" if k.endswith("중앙값") else k): v for k, v in r.items()})
        ordered = normalized
    return ordered[:limit]


# ── 거래 기간: 기본 최근 3년, 거래가 없으면 5년·전체로 넓히기 ──

SEARCH_PERIOD_V1 = True
# Runtime marker: blue palette (design step 2, 2026-10-09); the result screen uses result_layout.
RESULT_LAYOUT_V2 = True
PERIOD_CHOICES: tuple[tuple[str, int | None], ...] = (
    ("최근 3년", 3),
    ("최근 5년", 5),
    ("전체", None),
)
DEFAULT_PERIOD_LABEL = "최근 3년"


def period_years(label: object) -> int | None:
    return dict(PERIOD_CHOICES).get(str(label or ""), 3)


def period_cutoff(years: int | None, today: date) -> date | None:
    """First day included; None means every collected year."""

    if years is None:
        return None
    try:
        return today.replace(year=today.year - years) + timedelta(days=1)
    except ValueError:  # 2월 29일
        return today.replace(year=today.year - years, day=28) + timedelta(days=1)


def _trade_date(value: object) -> date | None:
    text = str(value or "").strip()[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def in_period(value: object, cutoff: date | None) -> bool:
    """Trades without a readable date stay visible in every period."""

    if cutoff is None:
        return True
    traded = _trade_date(value)
    return traded is None or traded >= cutoff


def filter_candidates(candidates: Iterable[Any], cutoff: date | None) -> tuple[Any, ...]:
    return tuple(c for c in candidates if in_period(getattr(c, "transaction_date", None), cutoff))


def filter_rows(rows: Iterable[Mapping[str, object]], cutoff: date | None) -> list[Mapping[str, object]]:
    return [row for row in rows if in_period(row.get("거래일"), cutoff)]


@dataclass(frozen=True)
class PeriodChoice:
    label: str
    cutoff: date | None
    widened_from: str | None = None

    @property
    def note(self) -> str | None:
        if self.widened_from is None:
            return None
        return f"{self.widened_from} 안에는 같은 제품 거래가 없어 {self.label}으로 넓혀 보여줍니다."


def choose_period(
    direct_dates: Sequence[object],
    *,
    requested: object,
    user_chose: bool,
    today: date,
) -> PeriodChoice:
    """Use the requested period; when the reader did not pick one, widen until a trade shows up."""

    label = str(requested or DEFAULT_PERIOD_LABEL)
    if label not in dict(PERIOD_CHOICES):
        label = DEFAULT_PERIOD_LABEL
    if user_chose:
        return PeriodChoice(label, period_cutoff(period_years(label), today))
    for candidate_label, years in PERIOD_CHOICES:
        cutoff = period_cutoff(years, today)
        if any(in_period(value, cutoff) for value in direct_dates):
            widened = DEFAULT_PERIOD_LABEL if candidate_label != DEFAULT_PERIOD_LABEL else None
            return PeriodChoice(candidate_label, cutoff, widened)
    return PeriodChoice(DEFAULT_PERIOD_LABEL, period_cutoff(3, today))


def period_caption(choice: PeriodChoice, *, oldest_collected: str | None = None) -> str:
    if choice.cutoff is None:
        since = f"{oldest_collected} 이후 수집된 " if oldest_collected else "수집된 "
        return f"거래 기간 · 전체 ({since}모든 거래)"
    return f"거래 기간 · {choice.label} ({choice.cutoff.isoformat()} 이후 거래)"


def year_summary_rows(
    rows: Sequence[Mapping[str, object]],
    *,
    main_unit: str | None,
) -> list[dict[str, object]]:
    """One line per year, newest first. Prices use only the main unit (대·set are never mixed)."""

    main = unit_key(main_unit)
    years: dict[str, list[Mapping[str, object]]] = {}
    for row in rows:
        traded = _trade_date(row.get("거래일"))
        years.setdefault(str(traded.year) if traded else "날짜 미확인", []).append(row)
    output: list[dict[str, object]] = []
    ordered = sorted((y for y in years if y.isdigit()), reverse=True) + [
        y for y in years if not y.isdigit()
    ]
    label = per_unit_label(main_unit).strip() or "1단위"
    for year in ordered:
        year_rows = years[year]
        prices = sorted(
            price
            for row in year_rows
            if (price := _decimal(row.get("가격"))) is not None
            and (not main or unit_key(row.get("단위")) in {"", main})
        )
        other = sum(
            1 for row in year_rows if main and unit_key(row.get("단위")) not in {"", main}
        )
        quantity = sum(
            (q for row in year_rows if (q := _quantity(row.get("수량"))) is not None
             and (not main or unit_key(row.get("단위")) in {"", main})),
            Decimal("0"),
        )
        output.append(
            {
                "연도": year,
                "거래 건수": len(year_rows),
                "총수량": f"{_number(quantity)} {main_unit or ''}".strip() if quantity else "확인 안 됨",
                f"{label} 중앙값": _won(_median(prices)) if prices else "—",
                f"{label} 최저~최고": (
                    f"{_won(prices[0])} ~ {_won(prices[-1])}" if prices else "—"
                ),
                "다른 단위 거래": f"{other}건" if other else "",
            }
        )
    return output


def _median(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2
