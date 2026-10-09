"""같은 품목 시장 screen block: other models, the category's price level, who bought, who sells.

Shown as the main body when the searched model has no same-model 나라장터 trade, as a section
below the result when it has, and inside the 품목 overview (``?q=가스마취기``). The numbers come
from services.category_market; this module only words and lays them out. Sizes follow
DESIGN_DECISIONS.md (GPT mockup): cards 99px high, 22px values, 12px tables. Class prefix ``cm-``.

New module, so a Streamlit process that keeps older modules after a deploy never mixes it up.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any

import streamlit as st

from purchase_price.services.category_market import (
    KIND_ENTRY_ERROR,
    KIND_EQUIPMENT,
    KIND_OTHER_UNIT,
    KIND_PRICE_GAP,
    MACHINE_UNIT,
    MACHINE_UNIT_LABEL,
    RULE_NOTE,
    CategoryMarket,
    CategoryModel,
    CategoryTrade,
    ClassifiedTrade,
)
from purchase_price.services.g2b_delivery_record import g2b_url_for_source_record
from purchase_price.ui.theme import (
    TONE_INFO,
    TONE_MUTED,
    TONE_OK,
    esc,
    metric_card_html,
)

CATEGORY_MARKET_V1 = True
# Runtime marker: the block names the 거래 기간 it was limited to (2026-10-10).
CATEGORY_MARKET_PERIOD_V1 = True
# Runtime marker: the 계산에서 뺀 거래 box lists 입력 오류 의심 lines with their reason.
CATEGORY_MARKET_ENTRY_ERRORS_V1 = True
# Runtime marker (2026-10-10): identical recent purchases from separate delivery requests are
# shown once with their count.
CATEGORY_MARKET_RECENT_GROUPED_V1 = True
SECTION_TITLE = "같은 품목 시장"
MODELS_TAB = "같은 품목의 다른 모델"
BUYERS_TAB = "도입 기관"
SUPPLIERS_TAB = "구할 수 있는 곳"
BUYER_ROW_LIMIT = 300

CSS = """
<style>
.cm-cq {container-type:inline-size;}
.cm-head {padding:22px 24px !important; margin:0 0 13px 0;}
.cm-eyebrow {display:flex; align-items:center; gap:6px; color:var(--pc-teal); font-weight:800; font-size:12px;
  margin-bottom:10px;}
.cm-eyebrow::before {content:''; width:8px; height:8px; border-radius:50%; background:currentColor;}
.cm-headline {font-size:22px; font-weight:800; line-height:1.45; letter-spacing:-0.6px; color:var(--pc-navy);
  margin:0 0 8px 0; word-break:keep-all;}
.cm-headline.cm-small {font-size:19px;}
.cm-basis {font-size:12.5px; color:#5B6C82; line-height:1.6; word-break:keep-all;}
.cm-cq .pc-metrics {margin:0 0 13px 0;}
.cm-cq .pc-metric .pc-value {white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
.cm-grid {display:grid; grid-template-columns:minmax(0,1.35fr) minmax(0,1fr); gap:13px; margin:0 0 6px 0;}
.cm-grid > .pc-card {padding:18px 20px;}
.cm-card-title {font-size:15px; font-weight:800; color:var(--pc-navy); margin:0 0 10px 0; letter-spacing:-0.3px;}
.cm-card-title span {font-size:12px; font-weight:400; color:var(--pc-muted); margin-left:6px;}
.cm-grid .pc-table td, .cm-grid .pc-table th {padding:9px 10px;}
.cm-grid .pc-table td:first-child {font-weight:700; color:#25466B;}
.cm-empty {font-size:12px; color:#66768D; line-height:1.6; margin:8px 0 0 0;}
.cm-recent {margin:14px 0 0 0; padding-top:12px; border-top:1px solid #EDF1F6;}
.cm-recent-title {font-size:12px; font-weight:700; color:#5B6C82; margin:0 0 6px 0;}
.cm-recent-row {display:flex; gap:10px; align-items:baseline; font-size:12px; color:#3E536C; line-height:1.5;
  padding:4px 0;}
.cm-recent-row .cm-date {color:#7A899B; flex:none; width:78px; font-variant-numeric:tabular-nums;}
.cm-recent-row .cm-who {flex:1 1 auto; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;}
.cm-recent-row .cm-price {flex:none; font-weight:700; color:var(--pc-navy); font-variant-numeric:tabular-nums;}
.cm-excluded {background:#FFFBF2 !important; border-color:#F3E3C1 !important;}
.cm-excluded ul {list-style:none; margin:0; padding:0;}
.cm-excluded li {position:relative; font-size:12.5px; color:#4E3B12; line-height:1.55; padding:0 0 0 14px; margin:0 0 7px 0;
  word-break:keep-all;}
.cm-excluded li::before {content:''; position:absolute; left:0; top:7px; width:6px; height:6px; border-radius:50%;
  background:#D97706;}
.cm-excluded li b {color:#6B4A0B;}
.cm-excluded li span {color:#8A6A2E; font-size:11.5px;}
.cm-rule {font-size:11.5px; color:#7A6A4A; line-height:1.6; margin:10px 0 0 0; padding-top:10px;
  border-top:1px solid #F1E4C8; word-break:keep-all;}
.cm-strip {display:flex; flex-wrap:wrap; gap:10px 28px; padding:12px 18px !important; margin:0 0 14px 0;}
.cm-strip-item {display:flex; align-items:center; gap:8px; min-width:0; flex:1 1 320px;}
.cm-strip-label {font-size:12px; font-weight:700; color:#5B6C82; white-space:nowrap;}
.cm-strip-note {font-size:11.5px; color:#7A899B; line-height:1.5; min-width:0; overflow:hidden; text-overflow:ellipsis;
  white-space:nowrap;}
.st-key-cm_block [data-baseweb="tab-list"] {gap:20px;}
.st-key-cm_block [data-baseweb="tab"] p {font-size:13px;}
.st-key-cm_block [data-baseweb="tab"][aria-selected="true"] p {font-weight:800;}
.st-key-cm_block [data-baseweb="tab-highlight"] {height:3px;}
.st-key-cm_block h4 {font-size:17px; font-weight:700; color:var(--pc-navy); letter-spacing:-0.4px; padding:0;
  margin-top:18px;}
@container (max-width: 760px) {
  .cm-grid {grid-template-columns:1fr;}
  .cm-cq .pc-metrics {grid-template-columns:repeat(2,minmax(0,1fr));}
}
@container (max-width: 420px) {
  .cm-cq .pc-metrics {grid-template-columns:1fr;}
}
</style>
"""


# ── Words ──


def won(value: Decimal | None) -> str:
    return f"{value:,.0f}원" if value is not None else "—"


def unit_text(unit: str | None) -> str:
    """'1대' for the machine group (대·세트·식), '1 box' otherwise; '1단위' when unknown."""

    if not unit:
        return "1단위"
    if unit == MACHINE_UNIT:
        return "1대"
    return f"1{unit}" if len(unit) <= 2 and not unit.isascii() else f"1 {unit}"


def product_label(market: CategoryMarket) -> str:
    return market.product_name or market.code_names or "같은 품목"


def period_text(market: CategoryMarket) -> str:
    """'최근 3년(2023-10-10 이후)' / '전체' / '' when the market was not limited."""

    if not market.period_label:
        return ""
    if not market.period_start:
        return "전체"
    return f"{market.period_label}({market.period_start} 이후)"


def _empty_in_period(market: CategoryMarket, product: str) -> str:
    """No equipment purchase: say whether a wider 거래 기간 has some."""

    if market.outside_period and market.period_start:
        return (
            f"같은 품목({product})의 나라장터 장비 구매는 {period_text(market)} 안에 없습니다 · "
            f"거래 기간을 넓히면 {market.outside_period:,}건이 있습니다"
        )
    return f"같은 품목({product})의 나라장터 장비 구매는 수집한 자료에 아직 없습니다"


def headline_text(market: CategoryMarket, *, searched_model: str = "", has_direct: bool = False) -> str:
    product = product_label(market)
    count = len(market.equipment)
    if not count:
        return _empty_in_period(market, product)
    if searched_model and not has_direct:
        return f"{searched_model}의 나라장터 거래는 없지만, 같은 품목({product}) 장비 구매가 {count:,}건 있습니다"
    if searched_model:
        return f"같은 품목({product})의 다른 모델까지 보면 장비 구매가 {count:,}건 있습니다"
    return f"{product} 장비 구매가 나라장터에 {count:,}건 있습니다"


def basis_text(market: CategoryMarket) -> str:
    parts: list[str] = []
    period = period_text(market)
    if period:
        parts.append(f"거래 기간 {period}")
    codes = " · ".join(f"{code.name}({code.code})" if code.name else code.code for code in market.codes)
    if codes:
        excluded = len(market.trades) - len(market.equipment)
        text = f"나라장터 세부품명 {codes} 거래 {len(market.trades):,}건"
        if excluded:
            text += f" 중 부품·수리·동물용 {excluded:,}건을 뺀 수"
        parts.append(text)
    level = market.level
    if level.first_date and level.latest_date:
        parts.append(f"{level.first_date} ~ {level.latest_date} 거래")
    if market.data_as_of:
        parts.append(f"나라장터 {market.data_as_of} 수집분")
    if market.truncated:
        parts.append("거래가 많아 최근 거래부터 일부만 셈")
    return " · ".join(parts)


def headline_html(market: CategoryMarket, *, searched_model: str = "", has_direct: bool = False) -> str:
    small = " cm-small" if has_direct else ""
    eyebrow = "다른 모델까지 본 시장" if has_direct else SECTION_TITLE
    if market.period_label:
        eyebrow += f" · {market.period_label}"
    return (
        '<div class="pc-card cm-head" id="category-market-head-v1">'
        f'<div class="cm-eyebrow">{esc(eyebrow)} · 참고 시세</div>'
        f'<div class="cm-headline{small}">{esc(headline_text(market, searched_model=searched_model, has_direct=has_direct))}</div>'
        f'<div class="cm-basis">{esc(basis_text(market))}</div></div>'
    )


def metric_cards_html(market: CategoryMarket) -> str:
    level = market.level
    per = unit_text(level.unit)
    if level.median is not None:
        note = f"장비 구매 {level.count:,}건 기준 · {won(level.low)} ~ {won(level.high)}"
        if level.count < 3:
            note = f"장비 구매 {level.count}건뿐이라 참고만 · {won(level.low)} ~ {won(level.high)}"
        price = metric_card_html(f"{per} 가운데 값 (참고 시세)", won(level.median), note, tone=TONE_INFO)
    else:
        price = metric_card_html("참고 시세", "계산 안 됨", "가격을 셀 장비 구매가 없습니다", tone=TONE_MUTED)
    equipment = market.equipment
    latest = level.latest_date
    buyers = metric_card_html(
        f"장비 구매 · {market.period_label}" if market.period_label else "장비 구매",
        f"{len(equipment):,}건",
        f"구매 기관 {market.institutions:,}곳" + (f" · 최근 {latest}" if latest else ""),
        tone=TONE_OK if equipment else TONE_MUTED,
    )
    models = metric_card_html(
        "식약처 등록 모델",
        f"{len(market.models):,}개",
        f"그중 나라장터 거래가 있는 모델 {market.traded_models:,}개",
        tone=TONE_OK if market.traded_models else TONE_MUTED,
    )
    suppliers = metric_card_html(
        "납품업체 (나라장터)",
        f"{len(market.suppliers):,}곳",
        f"식약처 제조·수입업체 {len(market.companies):,}곳",
        tone=TONE_OK if market.suppliers else TONE_MUTED,
    )
    return f'<div class="cm-cq"><div class="pc-metrics" id="category-market-cards-v1">{price}{buyers}{models}{suppliers}</div></div>'


def year_table_html(market: CategoryMarket) -> str:
    per = unit_text(market.level.unit)
    period = f" · {market.period_label}" if market.period_label else ""
    title = f'<div class="cm-card-title">연도별 시세<span>장비 구매 · {esc(per)} 가격{esc(period)}</span></div>'
    if not market.years:
        empty = "가격을 셀 장비 구매가 없습니다."
        if market.outside_period and market.period_start:
            empty = f"{period_text(market)} 안에는 가격을 셀 장비 구매가 없습니다. 위 거래 기간을 넓혀 보세요."
        return f'<div class="pc-card">{title}<p class="cm-empty">{esc(empty)}</p></div>'
    rows = "".join(
        f'<tr><td>{esc(year.year)}년</td><td class="pc-num">{year.count:,}건</td>'
        f'<td class="pc-num">{esc(won(year.median))}</td>'
        f'<td class="pc-num">{esc(won(year.low))} ~ {esc(won(year.high))}</td></tr>'
        for year in market.years
    )
    unit_note = ""
    if market.level.unit == MACHINE_UNIT:
        unit_note = f'<div class="cm-empty">{MACHINE_UNIT_LABEL}로 적힌 거래를 장비 1대로 보고 함께 셌습니다.</div>'
    return (
        f'<div class="pc-card">{title}<table class="pc-table"><thead><tr><th>연도</th><th class="pc-num">건수</th>'
        f'<th class="pc-num">가운데 값</th><th class="pc-num">최저 ~ 최고</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>{unit_note}{recent_html(market)}</div>"
    )


RECENT_SHOWN = 3


def recent_groups(market: CategoryMarket, *, limit: int = RECENT_SHOWN) -> list[tuple[Any, int]]:
    """Newest equipment purchases, one entry per (date, 기관, 모델, 1단위 가격) with its count.

    Separate delivery requests can look identical (화성시문화관광재단 bought three HR-701PLUS on
    2026-10-01 in three requests, each change order 00); they are real purchases, so they are
    counted, not dropped, and shown once with "납품요구 3건".
    """

    groups: dict[tuple[str, str, str, str], list[Any]] = {}
    for row in market.trades:
        if row.kind != KIND_EQUIPMENT:
            continue
        trade = row.trade
        key = (trade.transaction_date, trade.institution, trade.model_label, str(trade.unit_price))
        if key not in groups and len(groups) >= limit:
            break
        groups.setdefault(key, []).append(trade)
    return [(trades[0], len(trades)) for trades in groups.values()]


def recent_html(market: CategoryMarket, *, limit: int = RECENT_SHOWN) -> str:
    """The newest equipment purchases in one line each (date · 기관 · 모델 · 1단위 가격)."""

    groups = recent_groups(market, limit=limit)
    if not groups:
        return ""
    lines = "".join(
        f'<div class="cm-recent-row"><span class="cm-date">{esc(trade.transaction_date)}</span>'
        f'<span class="cm-who">{esc(trade.institution)} · {esc(trade.model_label)}'
        + (f" · 납품요구 {count}건" if count > 1 else "")
        + f'</span><span class="cm-price">{esc(won(trade.unit_price))}</span></div>'
        for trade, count in groups
    )
    return (
        '<div class="cm-recent"><div class="cm-recent-title">최근 장비 구매 · 전체는 아래 ‘도입 기관’</div>'
        f"{lines}</div>"
    )


def exclusion_box_html(market: CategoryMarket) -> str:
    items = []
    for exclusion in market.exclusions:
        where = "시세에서만 뺌" if exclusion.kind in {KIND_OTHER_UNIT, KIND_PRICE_GAP} else "시세·도입 기관에서 뺌"
        if exclusion.kind == KIND_ENTRY_ERROR:
            # The reason itself is the example: it names the typed 단가·수량 and says to check the 원문.
            example = f"<br><span>{esc(exclusion.examples[0])}</span>" if exclusion.examples else ""
        else:
            example = f"<br><span>예: 「{esc(exclusion.examples[0])}」</span>" if exclusion.examples else ""
        items.append(f"<li><b>{esc(exclusion.label)} {exclusion.count:,}건</b> · {where}{example}</li>")
    body = "<ul>" + "".join(items) + "</ul>" if items else '<p class="cm-empty">뺀 거래가 없습니다.</p>'
    return (
        '<div class="pc-card cm-excluded" id="category-market-rules-v1">'
        '<div class="cm-card-title">계산에서 뺀 거래</div>'
        f'{body}<div class="cm-rule">{esc(RULE_NOTE)}</div></div>'
    )


def no_trade_headline(market: CategoryMarket, searched_model: str) -> str:
    """The conclusion headline when the model has no trade but its 품목 has some."""

    product = product_label(market)
    count = len(market.equipment)
    if not count:
        if market.outside_period and market.period_start:
            return (
                f"{searched_model}의 나라장터 거래는 없습니다 · 같은 품목({product}) 장비 구매도 "
                f"{market.period_label} 안에는 없고, 거래 기간을 넓히면 {market.outside_period:,}건이 있습니다"
            )
        return f"{searched_model}의 나라장터 거래는 없습니다 · 같은 품목({product})의 다른 모델을 아래에 모았습니다"
    within = f"{market.period_label} " if market.period_label and market.period_start else ""
    return (
        f"{searched_model}의 나라장터 거래는 없습니다 · 같은 품목({product}) {within}장비 구매 {count:,}건으로 "
        "시세를 보여 드립니다"
    )


def no_trade_basis(market: CategoryMarket) -> str:
    text = "참고 시세는 같은 품목의 다른 모델 거래입니다. 같은 제품의 가격이 아니니 성능·구성을 함께 확인하세요."
    basis = basis_text(market)
    return f"{text} {basis}" if basis else text


_STRIP_TONES = {"ok": TONE_OK, "warn": "warn", "danger": "danger", "neutral": TONE_MUTED}


def status_strip_html(cards: Sequence[object]) -> str:
    """식약처 허가 · 안전·회수 as one compact line (label, dot + word, note) instead of big cards."""

    items = []
    for card in cards:
        tone = _STRIP_TONES.get(str(getattr(card, "tone", "")), TONE_MUTED)
        items.append(
            '<div class="cm-strip-item">'
            f'<span class="cm-strip-label">{esc(getattr(card, "label", ""))}</span>'
            f'<span class="pc-pill pc-{tone}">{esc(getattr(card, "value", ""))}</span>'
            f'<span class="cm-strip-note">{esc(getattr(card, "note", ""))}</span></div>'
        )
    return f'<div class="pc-card cm-strip" id="category-market-status-v1">{"".join(items)}</div>'


def summary_html(
    market: CategoryMarket,
    *,
    searched_model: str = "",
    has_direct: bool = False,
    show_headline: bool = True,
) -> str:
    head = headline_html(market, searched_model=searched_model, has_direct=has_direct) if show_headline else ""
    return (
        CSS
        + f'<div class="cm-cq" id="category-market-v1">{head}</div>'
        + metric_cards_html(market)
        + f'<div class="cm-cq"><div class="cm-grid">{year_table_html(market)}{exclusion_box_html(market)}</div></div>'
    )


# ── Tables ──


def _status_word(status: str) -> str:
    words = {
        "국내 정상": "판매 가능",
        "국내 정상(품목)": "판매 가능(허가 기준)",
        "취소·취하": "취소됨",
        "취소·취하(품목)": "취소됨(허가 기준)",
        "수출용": "수출 전용",
        "수출용(품목)": "수출 전용(허가 기준)",
    }
    return words.get(status, status) or "확인 전"


def model_rows(models: Sequence[CategoryModel]) -> list[dict[str, object]]:
    rows = []
    for model in models:
        if model.trade_count is None:
            trades = "조회 불가"
        elif model.trade_count:
            trades = f"{model.trade_count:,}건"
        else:
            trades = "나라장터 거래 없음"
        notes = []
        if model.veterinary_count:
            notes.append(f"동물용 구매 {model.veterinary_count}건 포함")
        if model.parts_count:
            notes.append(f"부품·수리 {model.parts_count}건 포함")
        rows.append(
            {
                "모델": f"▶ {model.model}" if model.current else model.model,
                "제조·수입업체": model.company or "확인 안 됨",
                "같은 제품 거래": trades,
                "가운데 값": won(model.median) if model.median is not None else "",
                "거래 범위": f"{won(model.low)} ~ {won(model.high)}" if model.low is not None else "",
                "최근 거래": model.latest,
                "참고": " · ".join(notes),
                "허가번호": model.permit_number,
                "허가 상태": _status_word(model.status),
                "등급": f"{model.grade}등급" if model.grade else "",
            }
        )
    return rows


def _quantity(trade: CategoryTrade) -> str:
    if trade.quantity is None:
        return trade.unit or ""
    number = format(trade.quantity.normalize(), "f")
    return f"{number} {trade.unit}".strip()


_KIND_NOTES = {
    KIND_EQUIPMENT: "",
    KIND_OTHER_UNIT: "다른 단위 · 시세에서 뺌",
    KIND_PRICE_GAP: "가격이 크게 다름 · 시세에서 뺌",
}


def buyer_rows(
    rows: Sequence[ClassifiedTrade],
    *,
    include_excluded: bool = False,
    limit: int = BUYER_ROW_LIMIT,
) -> tuple[list[dict[str, object]], list[ClassifiedTrade]]:
    """(table rows, the trades in the same order) for 도입 기관; equipment only unless asked."""

    picked = [row for row in rows if include_excluded or row.is_equipment][:limit]
    table = []
    for row in picked:
        trade = row.trade
        note = _KIND_NOTES.get(row.kind)
        if note is None:
            note = f"{_KIND_LABEL.get(row.kind, row.kind)} · {row.reason}".strip(" ·")
        table.append(
            {
                "날짜": trade.transaction_date,
                "구매 기관": trade.institution,
                "모델": trade.model_label,
                "수량": _quantity(trade),
                "1단위 가격": won(trade.unit_price),
                "납품업체": trade.supplier,
                "사업명": trade.business_name,
                "구분": note,
                "나라장터": g2b_url_for_source_record(trade.source_record_id),
            }
        )
    return table, picked


_KIND_LABEL = {"parts": "부품·수리", "veterinary": "동물용", KIND_ENTRY_ERROR: "입력 오류 의심"}


def supplier_rows(market: CategoryMarket) -> list[dict[str, object]]:
    return [
        {
            "납품업체": item.name,
            "납품 건수": f"{item.count}건",
            "최근 납품": item.latest,
            "구매 기관": f"{item.institutions}곳",
            "납품한 모델": " / ".join(item.models[:4]) + (f" 외 {len(item.models) - 4}개" if len(item.models) > 4 else ""),
        }
        for item in market.suppliers
    ]


def company_rows(market: CategoryMarket) -> list[dict[str, object]]:
    return [
        {
            "제조·수입업체 (식약처)": item.name,
            "등록 모델": f"{item.model_count}개",
            "나라장터 거래가 있는 모델": f"{item.traded_model_count}개",
            "대표 모델": " / ".join(item.models),
            "최근 허가일": item.latest_permit,
        }
        for item in market.companies
    ]


def trade_dialog_row(trade: CategoryTrade) -> dict[str, object]:
    """The keys the dashboard's trade dialog reads (same as a 거래 전체 row)."""

    return {
        "원천기록": trade.source_record_id,
        "원문근거키": trade.raw_object_key,
        "총액": won(trade.total_amount) if trade.total_amount is not None else "미확인",
        "수량": format(trade.quantity.normalize(), "f") if trade.quantity is not None else "",
        "단위": trade.unit or "미확인",
        "가격": won(trade.unit_price),
        "거래일": trade.transaction_date or "미확인",
        "구매처": trade.institution or "미확인",
        "사업명": trade.business_name,
    }


def tab_labels(market: CategoryMarket) -> tuple[str, str, str]:
    return (
        f"{MODELS_TAB} {len(market.models):,}개",
        f"{BUYERS_TAB} {len(market.equipment):,}건",
        f"{SUPPLIERS_TAB} {len(market.suppliers):,}곳",
    )


# ── Streamlit ──

AUTO_HEIGHT_ROWS = 10


def _table_height(rows: int, cap: int) -> int | str:
    """Short tables size to their rows (no empty filler row); long ones scroll inside ``cap`` px."""

    return "auto" if rows <= AUTO_HEIGHT_ROWS else cap


def render_category_market(
    market: CategoryMarket,
    *,
    key: str,
    searched_model: str = "",
    has_direct: bool = False,
    section_heading: bool = False,
    show_headline: bool = True,
    on_open_model: Callable[[CategoryModel], None],
    on_open_trade: Callable[[Mapping[str, object]], None],
    render_company_lookup: Callable[[str, str], None] | None = None,
    model_count_note: str = "",
) -> None:
    with st.container(key="cm_block"):
        if section_heading:
            st.markdown(f"#### {SECTION_TITLE}" + (f" · {market.period_label}" if market.period_label else ""))
        st.markdown(
            summary_html(market, searched_model=searched_model, has_direct=has_direct, show_headline=show_headline),
            unsafe_allow_html=True,
        )
        models_tab, buyers_tab, suppliers_tab = st.tabs(list(tab_labels(market)))
        with models_tab:
            _render_models(market, key=key, on_open_model=on_open_model, count_note=model_count_note)
        with buyers_tab:
            _render_buyers(market, key=key, on_open_trade=on_open_trade)
        with suppliers_tab:
            _render_suppliers(market, key=key, render_company_lookup=render_company_lookup)


def _render_models(
    market: CategoryMarket,
    *,
    key: str,
    on_open_model: Callable[[CategoryModel], None],
    count_note: str = "",
) -> None:
    if not market.models:
        st.info("식약처에 같은 품목으로 등록된 모델을 찾지 못했습니다.")
        return
    rows = model_rows(market.models)
    event = st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"cm_models::{key}",
        height=_table_height(len(rows), 430),
        column_config={
            "모델": st.column_config.TextColumn("모델", width="medium"),
            "가운데 값": st.column_config.TextColumn("가운데 값", width=110),
            "거래 범위": st.column_config.TextColumn("거래 범위", width=200),
            "참고": st.column_config.TextColumn("참고", width=150),
        },
    )
    picked = list(getattr(getattr(event, "selection", None), "rows", []) or [])
    if picked and 0 <= picked[0] < len(market.models):
        on_open_model(market.models[picked[0]])
    st.caption(
        "식약처에 같은 품목으로 등록된 모델 전부입니다. 나라장터 거래가 있는 모델이 위에 오고, ▶ 표시는 검색한 모델입니다. "
        "행을 누르면 그 모델의 가격 조사로 이동합니다. 성능이나 대체 가능 여부는 판단하지 않습니다. "
        "거래 건수는 모델명이 같은 나라장터 거래만"
        + (f" {market.data_as_of} 수집분 전체 기간으로" if market.data_as_of else " 전체 기간으로")
        + " 셉니다"
        + (" (위 거래 기간과 상관없이)." if market.period_start else ".")
        + (f" {count_note}" if count_note else "")
    )


def _render_buyers(
    market: CategoryMarket,
    *,
    key: str,
    on_open_trade: Callable[[Mapping[str, object]], None],
) -> None:
    excluded = len(market.trades) - len(market.equipment)
    include = False
    if excluded:
        include = st.checkbox(
            f"부품·수리·동물용·입력 오류 의심 거래 {excluded}건도 보기",
            value=False,
            key=f"cm_buyers_all::{key}",
        )
    rows, picked_rows = buyer_rows(market.trades, include_excluded=include)
    if not rows:
        st.info("같은 품목의 나라장터 장비 구매가 없습니다.")
        return
    table_key = f"cm_buyers::{key}::{int(include)}"
    applied_key = f"{table_key}::applied"
    event = st.dataframe(
        rows,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key=table_key,
        height=_table_height(len(rows), 430),
        column_config={"나라장터": st.column_config.LinkColumn("나라장터", display_text="열기")},
    )
    picked = list(getattr(getattr(event, "selection", None), "rows", []) or [])
    chosen = picked[0] if picked else None
    if chosen != st.session_state.get(applied_key):
        st.session_state[applied_key] = chosen
        if chosen is not None and 0 <= chosen < len(picked_rows):
            on_open_trade(trade_dialog_row(picked_rows[chosen].trade))
    shown_limit = len(rows) >= BUYER_ROW_LIMIT
    st.caption(
        "누가 언제 샀는지 최근 순으로 보여줍니다. 모델이 적히지 않은 거래(수요기관규격)는 '모델 미기재'로 두고, "
        "사업명으로 무엇을 샀는지 확인하세요. 행을 누르면 조달청 공개 원문이 열립니다."
        + (f" 최근 {BUYER_ROW_LIMIT}건까지만 보여줍니다." if shown_limit else "")
    )


def _render_suppliers(
    market: CategoryMarket,
    *,
    key: str,
    render_company_lookup: Callable[[str, str], None] | None,
) -> None:
    st.markdown("##### 나라장터에 납품한 업체")
    suppliers = supplier_rows(market)
    if suppliers:
        st.dataframe(suppliers, use_container_width=True, hide_index=True, height=_table_height(len(suppliers), 360))
        st.caption(
            "같은 품목 장비를 나라장터로 납품한 업체입니다(부품·수리·동물용 거래 제외). 납품 실적이 있다고 공식 총판이라는 "
            "뜻은 아닙니다."
        )
    else:
        st.caption("같은 품목 장비를 납품한 업체가 없습니다.")
    st.markdown("##### 식약처에 등록한 제조·수입업체")
    companies = company_rows(market)
    if not companies:
        st.caption("식약처에 같은 품목으로 등록한 업체를 찾지 못했습니다.")
        return
    st.dataframe(companies, use_container_width=True, hide_index=True, height=_table_height(len(companies), 360))
    st.caption(
        "제품을 들여오거나 만드는 회사로, 위 납품업체와는 다른 관계입니다. 이름이 비슷해도 같은 회사로 보지 않습니다. "
        "공개 자료에는 전화번호가 없어 보여주지 않습니다. 주소는 아래에서 식약처 업허가로 확인할 수 있습니다."
    )
    if render_company_lookup is not None:
        selected = st.selectbox(
            "업체 하나 주소 확인",
            options=[item.name for item in market.companies],
            key=f"cm_company::{key}",
        )
        if selected:
            render_company_lookup(selected, f"cm::{key}")
