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
OVERVIEW_ROW_LIMIT = 10

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
) -> Conclusion:
    """One sentence on what the product traded for and where the quote sits.

    Only same-product (A/B) trades enter the numbers. The wording describes a position and
    never says a quote is fair, cheap or expensive.
    """

    direct = int(getattr(stats, "direct_count", 0) or 0)
    references = int(getattr(stats, "reference_count", 0) or 0)
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
        detail = (
            f"이름이 비슷한 품목의 거래 {references}건은 같은 제품인지 확인되지 않아 "
            "가격 비교에 넣지 않았습니다. 아래에서 참고만 하세요."
            if references
            else None
        )
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
    if direct == 1:
        quote_line = None
        if quote is not None:
            quote_line = (
                f"내 견적가 {_won(quote)}은 이 1건보다 {_direction(_percent(quote, low))}. "
                "1건뿐이라 가격대를 판단하기에는 부족합니다."
            )
        return Conclusion(
            headline=f"같은 제품의 나라장터 거래는 1건이고, {_won(low)}에 거래됐습니다.",
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
            headline=f"같은 제품이 나라장터에서 {direct}번 거래됐고, 모두 {_won(low)}이었습니다.",
            detail=latest_text.removeprefix(" · ") or None,
            quote_line=quote_line,
            caveat=caveat,
            tone=TONE_OK,
            band=None,
        )

    if direct == 2:
        headline = f"같은 제품의 나라장터 거래는 2건이고, {_won(low)}과 {_won(high)}에 거래됐습니다."
        band = None
    else:
        headline = (
            f"같은 제품이 나라장터에서 {direct}번 거래됐고, 가운데 값(중앙값)은 {_won(mid)}입니다."
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
        detail=f"거래가 {_won(low)} ~ {_won(high)}{latest_text}",
        quote_line=quote_line,
        caveat=caveat,
        tone=TONE_OK,
        band=band,
    )


BAND_CSS = """
<style>
.pr-conclusion {border:1px solid rgba(128,128,128,0.28); border-radius:0.6rem; padding:0.85rem 1rem 0.6rem 1rem; margin:0.3rem 0 0.6rem 0;}
.pr-conclusion.pr-warn {border-left:4px solid #d97706;}
.pr-conclusion.pr-ok {border-left:4px solid #1f6f8b;}
.pr-conclusion.pr-neutral {border-left:4px solid #94a3b8;}
.pr-headline {font-size:1.12rem; font-weight:700; line-height:1.5; word-break:keep-all;}
.pr-detail {font-size:0.86rem; opacity:0.75; margin-top:0.15rem;}
.pr-quote-line {font-size:1rem; font-weight:600; margin-top:0.45rem; color:#92400e; word-break:keep-all;}
.pr-caveat {font-size:0.8rem; opacity:0.7; margin-top:0.15rem;}
.pr-band {position:relative; height:74px; margin:0.5rem 0.4rem 0.1rem 0.4rem;}
.pr-track {position:absolute; top:40px; left:0; right:0; height:4px; background:rgba(128,128,128,0.25); border-radius:2px;}
.pr-range {position:absolute; top:35px; height:14px; background:rgba(31,111,139,0.18); border:1px solid #1f6f8b; border-radius:7px;}
.pr-median {position:absolute; top:33px; width:18px; height:18px; margin-left:-9px; border-radius:50%; background:#1f6f8b; border:2px solid #fff;}
.pr-mark {position:absolute; top:17px; width:0; height:0; margin-left:-8px; border-left:8px solid transparent; border-right:8px solid transparent; border-top:13px solid #b45309;}
.pr-label {position:absolute; font-size:0.74rem; white-space:nowrap; transform:translateX(-50%);}
.pr-label.pr-top {top:0; color:#b45309; font-weight:600;}
.pr-label.pr-bottom {top:56px; opacity:0.75;}
.pr-label.pr-mid {top:56px; color:#1f6f8b; font-weight:600;}
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
            "같은 제품 거래": row.get("나라장터 거래") or "",
            "가격범위": row.get("가격범위") or "",
            "최근 거래": row.get("최근거래") or "",
        }
        for row in sorted(filled, key=order)[:limit]
    ]


def overview_model_rows(
    crosslinks: Sequence[Mapping[str, object]],
    *,
    limit: int | None = OVERVIEW_ROW_LIMIT,
) -> list[dict[str, object]]:
    """Company/product-name overview: models with trades first, most-traded first."""

    def count(row: Mapping[str, object]) -> int:
        try:
            return int(row.get("나라장터 직접거래") or 0)
        except (TypeError, ValueError):
            return 0

    seen: set[str] = set()
    ordered: list[Mapping[str, object]] = []
    for row in sorted(crosslinks, key=lambda row: (-count(row), str(row.get("모델") or ""))):
        model = str(row.get("모델") or "").strip()
        if not model or model in seen:
            continue
        seen.add(model)
        ordered.append(row)
    selected = ordered if limit is None else ordered[:limit]
    return [
        {
            "모델": row.get("모델") or "",
            "제조·수입업체": row.get("품목 책임주체") or "",
            "같은 제품 거래": f"{count(row)}건" if row.get("나라장터 직접거래") is not None else "조회 불가",
            "가격범위": (row.get("나라장터 가격범위") or "") if count(row) else "",
            "최근 거래": row.get("최근거래") or "",
        }
        for row in selected
    ]


def quote_item_rows(
    items: Sequence[Any],
    results: Mapping[int, Mapping[str, object]],
) -> list[dict[str, object]]:
    """Master table for an uploaded quote. Items not opened yet show what happens on click."""

    rows: list[dict[str, object]] = []
    for index, item in enumerate(items):
        title = " · ".join(
            str(part)
            for part in (getattr(item, "product_name", None), getattr(item, "model_name", None))
            if part
        ) or f"품목 {index + 1}"
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


def outlier_line(row: Mapping[str, object], median_price: Decimal) -> str:
    price = _decimal(row.get("가격"))
    parts = [_won(price)]
    if price is not None and median_price > 0:
        ratio = price / median_price if price >= median_price else median_price / price
        direction = "높음" if price >= median_price else "낮음"
        parts.append(f"중앙값의 {ratio:.1f}배 {direction}")
    for key in ("수량/단위", "거래조건", "구매처", "거래일"):
        value = str(row.get(key) or "").strip()
        if value and value != "미확인":
            parts.append(value)
    return " · ".join(parts)
