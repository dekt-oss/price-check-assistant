"""Fixed result header for the purchase workspace (W3, issue #204).

The first screen after a search answers four questions at a glance, in plain words:
how much it traded for, who actually supplied it, what the MFDS record says, and whether
a recall/sales-stop notice exists. Everything else (tables, raw evidence, safety lookup
details) stays one click away in the area tabs below the header.

This module is pure presentation: it turns already-computed results into small cards and
one-line captions so the Streamlit page stays thin and the wording is unit-testable. It
lives in a new module so a Streamlit hot reload that keeps older modules never sees a
partially updated import.
"""

from __future__ import annotations

import html
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

TONE_OK = "ok"
TONE_WARN = "warn"
TONE_DANGER = "danger"
TONE_NEUTRAL = "neutral"

# Runtime marker: the dashboard reloads a retained pre-2026-10 copy of this module (hot reload).
PLAIN_WORDING_2026_10 = True

# Safety codes stay internal; the header shows what they mean.
_SAFETY_TEXT: dict[str, tuple[str, str, str]] = {
    "RED": ("회수·판매중지 해당", "이 모델에 일치하는 공식 회수·판매중지 기록이 있습니다", TONE_DANGER),
    "AMBER": ("관련 안전정보 있음", "품목·업체 수준의 회수 기록이 있어 원문 확인이 필요합니다", TONE_WARN),
    "CHECKED_NONE": ("확인된 회수 없음", "식약처 회수·판매중지 공식 자료 기준", TONE_OK),
    "CHECK_FAILED": ("안전정보 조회 실패", "회수·판매중지 여부를 확인하지 못했습니다", TONE_WARN),
    "NOT_CONNECTED": ("안전정보 미연결", "회수·판매중지 자료에 연결되지 않았습니다", TONE_WARN),
    "NOT_AUTHORIZED": ("안전정보 인증 미승인", "회수·판매중지 API 사용 승인이 필요합니다", TONE_WARN),
}


@dataclass(frozen=True)
class SummaryCard:
    key: str
    label: str
    value: str
    note: str
    tone: str = TONE_NEUTRAL


def _won(value: Decimal | None) -> str:
    return f"{value:,.0f}원" if value is not None else "미확인"


def safety_card(status_value: str) -> SummaryCard:
    value, note, tone = _SAFETY_TEXT.get(
        str(status_value or "").upper(),
        ("안전정보 미확인", "회수·판매중지 여부를 확인하지 못했습니다", TONE_WARN),
    )
    return SummaryCard("safety", "안전정보", value, note, tone)


def safety_needs_banner(status_value: str) -> bool:
    """Only a matching or related recall interrupts the page above the cards."""

    return str(status_value or "").upper() in {"RED", "AMBER"}


def price_card(stats: Any, *, unavailable: bool = False) -> SummaryCard:
    direct_count = int(getattr(stats, "direct_count", 0) or 0)
    reference_count = int(getattr(stats, "reference_count", 0) or 0)
    min_price = getattr(stats, "min_price", None)
    max_price = getattr(stats, "max_price", None)
    if unavailable:
        return SummaryCard(
            "price",
            "거래가",
            "조회 불가",
            "나라장터 가격 자료에 연결하지 못했습니다",
            TONE_WARN,
        )
    if direct_count == 0 or min_price is None or max_price is None:
        note = (
            f"비슷한 품목 거래 {reference_count}건은 비교에서 제외"
            if reference_count
            else "나라장터 기준"
        )
        return SummaryCard("price", "거래가", "같은 제품 거래 0건", note, TONE_NEUTRAL)

    median = getattr(stats, "median_price", None)
    parts = [f"같은 제품 거래 {direct_count}건"]
    if min_price == max_price:
        value = _won(min_price)
    elif direct_count >= 3 and median is not None:
        value = _won(median)
        parts.insert(0, "중앙값")
    else:
        value = f"{min_price:,.0f} ~ {max_price:,.0f}원"
    latest = getattr(stats, "latest_transaction_date", None)
    if latest:
        parts.append(f"최근 {latest}")
    return SummaryCard("price", "거래가", value, " · ".join(parts), TONE_OK)


def supplier_card(stats: Any) -> SummaryCard:
    suppliers = int(getattr(stats, "supplier_count", 0) or 0)
    institutions = int(getattr(stats, "demand_institution_count", 0) or 0)
    if not suppliers:
        return SummaryCard("supplier", "납품업체", "확인 안 됨", "같은 제품 거래의 납품업체 없음", TONE_NEUTRAL)
    note = f"{institutions}개 기관에 납품" if institutions else "나라장터 기준"
    return SummaryCard("supplier", "납품업체", f"{suppliers}곳", note, TONE_OK)


_MFDS_METRIC_TONE = {
    "품목번호 확인": TONE_OK,
    "exact 확인": TONE_OK,
    "품목 확인": TONE_NEUTRAL,
    "복수 품목번호": TONE_WARN,
    "0건": TONE_NEUTRAL,
    "조회 실패": TONE_WARN,
    "조회 대기": TONE_NEUTRAL,
    "대상 아님": TONE_NEUTRAL,
}

# Internal metric codes stay; the card shows plain words.
_MFDS_METRIC_VALUE = {
    "품목번호 확인": "허가 확인",
    "exact 확인": "허가 확인",
    "품목 확인": "품목만 확인",
    "복수 품목번호": "허가 여러 건",
    "0건": "찾지 못함",
    "조회 대기": "확인 전",
    "대상 아님": "해당 없음",
}


def mfds_card(
    mfds_metric: str,
    *,
    permit_numbers: Sequence[str] = (),
    companies: Sequence[str] = (),
    coverage_percent: float | None = None,
    model_count: int | None = None,
    active_model_count: int | None = None,
) -> SummaryCard:
    value = _MFDS_METRIC_VALUE.get(mfds_metric, mfds_metric)
    tone = _MFDS_METRIC_TONE.get(mfds_metric, TONE_NEUTRAL)
    if permit_numbers:
        note = " / ".join(list(dict.fromkeys(permit_numbers))[:2])
        if companies:
            note += f" · {companies[0]}"
    elif mfds_metric == "조회 대기":
        note = "아래 '식약처에서 확인' 버튼으로 조회 (약 30초)"
    elif mfds_metric == "복수 품목번호":
        note = "같은 모델명이 여러 허가에 있어 상세 자료에서 확인"
    elif mfds_metric == "조회 실패":
        note = "식약처 조회에 실패해 다시 시도가 필요합니다"
    elif mfds_metric == "품목 확인" and model_count:
        active = f"(판매 가능 {active_model_count}개)" if active_model_count is not None else ""
        note = f"같은 품목 등록 모델 {model_count}개{active} · 이 모델명과 같은 등록은 못 찾음"
    elif mfds_metric == "0건" and coverage_percent is not None and coverage_percent < 100:
        note = f"지금까지 모은 식약처 자료({coverage_percent:.0f}%)에서 찾지 못했습니다"
    elif mfds_metric == "0건":
        note = "연결된 식약처 자료에서 찾지 못했습니다"
    elif mfds_metric == "대상 아님":
        note = "의료기기로 분류되지 않은 품목"
    else:
        note = "식약처 허가정보"
    return SummaryCard("mfds", "식약처 허가", value, note, tone)


def most_common_text(rows: Iterable[Mapping[str, object]], key: str) -> str | None:
    values = [
        str(row.get(key) or "").strip()
        for row in rows
        if str(row.get(key) or "").strip() not in {"", "미확인"}
    ]
    if not values:
        return None
    return Counter(values).most_common(1)[0][0]


def procurement_product_name(rows: Iterable[Mapping[str, object]]) -> str | None:
    """나라장터 titles read "품명, 제조사, 모델, 규격"; the class name is the first part."""

    names = [
        {"품목/모델": str(row.get("품목/모델") or "").split(",")[0].strip()}
        for row in rows
    ]
    return most_common_text(names, "품목/모델")


def identity_line(
    *,
    product_name: str | None = None,
    permit_numbers: Sequence[str] = (),
    permit_type: str | None = None,
    companies: Sequence[str] = (),
    procurement_product: str | None = None,
    procurement_maker: str | None = None,
) -> str:
    """One line under the heading: what the searched product is, from the best source."""

    parts: list[str] = []
    if product_name:
        parts.append(product_name)
    elif procurement_product:
        parts.append(f"나라장터 품명 {procurement_product}")
        if procurement_maker and not companies:
            parts.append(f"제조사 {procurement_maker}")
    unique_permits = list(dict.fromkeys(p for p in permit_numbers if p))
    if unique_permits:
        label = permit_type or "허가번호"
        extra = f" 외 {len(unique_permits) - 1}건" if len(unique_permits) > 1 else ""
        parts.append(f"{label} {unique_permits[0]}{extra}")
    unique_companies = list(dict.fromkeys(c for c in companies if c))
    if unique_companies:
        extra = f" 외 {len(unique_companies) - 1}곳" if len(unique_companies) > 1 else ""
        parts.append(f"제조·수입 {unique_companies[0]}{extra}")
    return " · ".join(parts)


def data_basis_line(
    *,
    track_b_data_as_of: str | None,
    live_note: str | None = None,
    mfds_coverage_percent: float | None = None,
    mfds_complete: bool = False,
) -> str:
    parts: list[str] = []
    if track_b_data_as_of:
        parts.append(f"나라장터 {track_b_data_as_of}까지 수집")
    if live_note:
        parts.append(live_note)
    if mfds_complete:
        parts.append("식약처 제품정보 전체 수집 완료")
    elif mfds_coverage_percent is not None:
        parts.append(f"식약처 제품정보 {mfds_coverage_percent:.0f}% 수집 중")
    return "자료 기준 · " + " · ".join(parts) if parts else ""


DIRECT_TABLE_COLUMNS: tuple[str, ...] = (
    "거래일",
    "모델",
    "규격",
    "수량/단위",
    "가격",
    "총액",
    "거래조건",
    "판매처",
    "구매처",
    "매칭근거",
)


def direct_table_columns(rows: Sequence[Mapping[str, object]]) -> list[str]:
    """Columns shown by default; the full set stays in the expander and the Excel export."""

    if not rows:
        return list(DIRECT_TABLE_COLUMNS)
    available = set(rows[0].keys())
    return [column for column in DIRECT_TABLE_COLUMNS if column in available]


HEADER_CSS = """
<style>
/* Hidden deployment/diagnostic marker spans still occupy a flex row; collapse those rows. */
[data-testid="stElementContainer"]:has(span[id^="purchase-"]):not(:has(.pw-cards)) {display:none;}
.pw-cards {display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:0.6rem; margin:0.4rem 0 0.5rem 0;}
@media (max-width: 900px) {.pw-cards {grid-template-columns:repeat(2,minmax(0,1fr));}}
@media (max-width: 520px) {.pw-cards {grid-template-columns:1fr;}}
.pw-card {border:1px solid rgba(128,128,128,0.28); border-left-width:4px; border-radius:0.5rem; padding:0.6rem 0.75rem;}
.pw-card .pw-label {font-size:0.8rem; opacity:0.72;}
.pw-card .pw-value {font-size:1.22rem; font-weight:700; line-height:1.35; margin:0.1rem 0; word-break:keep-all;}
.pw-card .pw-note {font-size:0.8rem; opacity:0.8; line-height:1.35;}
.pw-ok {border-left-color:#16a34a;}
.pw-warn {border-left-color:#d97706;}
.pw-danger {border-left-color:#dc2626;}
.pw-neutral {border-left-color:#94a3b8;}
</style>
"""


def render_cards_html(cards: Sequence[SummaryCard]) -> str:
    items = "".join(
        f'<div class="pw-card pw-{html.escape(card.tone)}" data-card="{html.escape(card.key)}">'
        f'<div class="pw-label">{html.escape(card.label)}</div>'
        f'<div class="pw-value">{html.escape(card.value)}</div>'
        f'<div class="pw-note">{html.escape(card.note)}</div>'
        "</div>"
        for card in cards
    )
    return f'<div class="pw-cards" id="purchase-workspace-header-v1">{items}</div>'
