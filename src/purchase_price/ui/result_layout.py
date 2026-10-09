"""HTML blocks for the price search result screen (design steps 2–3, 2026-10-09).

Layout follows Claude Design's A안 (conclusion card with the price rail on the left, a fixed
"최종 판단 전에 확인하세요" panel on the right, four status-dot cards, one chip row); sizes follow
the GPT mockup. Everything here is pure presentation over results the page already computed,
so the wording and the check points are unit-testable. Class prefix ``rl-``.

New module, so a Streamlit process that keeps older modules after a deploy never mixes it up.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from purchase_price.ui.theme import (
    TONE_DANGER,
    TONE_INFO,
    TONE_MUTED,
    TONE_OK,
    TONE_WARN,
    esc,
    metric_card_html,
    pill_html,
)

RESULT_LAYOUT_V1 = True
# Runtime marker (2026-10-09 acceptance fixes): top-aligned conclusion with the chip row inside,
# narrow-width settings card, empty state, record table. The dashboard reloads a retained copy.
RESULT_LAYOUT_V2 = True
# The 판매 가능 확인 line names its list and explains a different registered-model count.
RESULT_LAYOUT_V3 = True

RESULT_CSS = """
<style>
/* Hidden marker spans still take a flex row; collapse those rows (kept from the old header CSS). */
[data-testid="stElementContainer"]:has(span[id^="purchase-"]):not(:has(.rl-keep)) {display:none;}
.rl-sr {position:absolute !important; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden;
  clip:rect(0,0,0,0); white-space:nowrap; border:0;}
.rl-head .pc-title {margin:0 0 6px 0; line-height:1.25;}
.rl-head .pc-subtitle {font-size:12.5px; margin:0;}
.rl-head .pc-chips {margin:10px 0 0 0;}
/* Width-aware blocks: the main column is ~1040px at 1440 but ~620px at 1024 (sidebar open). */
.rl-cq {container-type:inline-size;}
.rl-lead {display:grid; grid-template-columns:minmax(0,1fr) 265px; gap:13px; margin:0 0 13px 0;}
.rl-lead > .pc-card {padding:22px 24px;}
/* Top-aligned with the panel title: rail right under the basis line, the basis chips at the
   card bottom, so a taller panel leaves no blank band above or below the conclusion. */
.rl-lead > .pc-card:first-child {display:flex; flex-direction:column; justify-content:flex-start;}
.rl-lead .rl-price {margin-top:0;}
.rl-foot {margin-top:auto; padding-top:16px;}
.rl-foot .rl-chiprow {margin:0; padding-top:12px; border-top:1px solid #EDF1F6;}
#purchase-workspace-header-v1 .pc-value {white-space:nowrap; overflow:hidden; text-overflow:ellipsis;}
@container (max-width: 760px) {
  .rl-lead {grid-template-columns:1fr;}
  .rl-cq .pc-metrics {grid-template-columns:repeat(2,minmax(0,1fr));}
}
@container (max-width: 420px) {
  .rl-cq .pc-metrics {grid-template-columns:1fr;}
}
.rl-done {display:flex; align-items:center; gap:7px; font-size:12px; color:#2F5A43; margin:-4px 0 12px 2px;}
.rl-done::before {content:'✓'; font-weight:800; color:#047857;}
.rl-done.rl-warn {color:#825510;} .rl-done.rl-warn::before {content:'!'; color:#B45309;}
.rl-empty {padding:26px 28px !important; margin:4px 0 14px 0;}
.rl-empty ul {margin:14px 0 0 0; padding:0 0 0 18px;}
.rl-empty li {font-size:13px; color:#3E536C; line-height:1.7;}
.rl-empty .rl-basis {margin-top:2px;}
.rl-record {width:100%; border-collapse:collapse; font-size:12.5px; margin:4px 0 8px 0;}
.rl-record th, .rl-record td {padding:7px 10px; border-bottom:1px solid #E9EEF4; text-align:left; vertical-align:top;}
.rl-record th {width:28%; color:#5B6C82; font-weight:600; background:#F7FAFD; white-space:nowrap;}
.rl-record td {color:#172B4D; word-break:break-all;}
.rl-quote-hint {font-size:12px; color:#7A899B;}
.rl-quote-hint b {font-size:13px; color:var(--pc-navy); font-weight:800;}
.rl-quote-strip {font-size:13px; color:#3E536C; line-height:1.6;}
.rl-quote-strip b {color:var(--pc-navy);}
.st-key-rl_quote_strip {background:#F3F8FD; border:1px solid #D2E0F0; border-radius:11px; padding:8px 16px;}
.st-key-rl_quote_strip [data-testid="stPageLink"] a {justify-content:flex-end;}
.st-key-rl_quote_strip [data-testid="stPageLink"] p {font-weight:700; color:#1D4ED8;}
.rl-eyebrow {display:flex; align-items:center; gap:6px; color:var(--pc-teal); font-weight:800;
  font-size:12px; margin-bottom:11px;}
.rl-eyebrow::before {content:''; width:8px; height:8px; border-radius:50%; background:currentColor;}
.rl-eyebrow.rl-warn {color:#9A5D0A;}
.rl-eyebrow.rl-muted {color:var(--pc-muted);}
.rl-headline {font-size:22px; font-weight:800; line-height:1.5; letter-spacing:-0.6px;
  color:var(--pc-navy); margin:0 0 9px 0; word-break:keep-all;}
.rl-headline em {font-style:normal;}
.rl-headline em.rl-up {color:#B42318;}
.rl-headline em.rl-down {color:#1D4ED8;}
.rl-basis {font-size:12.5px; color:#5B6C82; line-height:1.6; word-break:keep-all;}
.rl-rail-wrap {position:relative; margin:24px 22px 4px 22px;}
.rl-rail {position:relative; height:11px; border-radius:9px;
  background:linear-gradient(90deg,#E3EBF5 0%,#A9C3EE 50%,#E3EBF5 100%);}
.rl-tick {position:absolute; top:-6px; width:3px; height:23px; margin-left:-1.5px; border-radius:2px;}
.rl-tick.rl-mid, .rl-key.rl-mid {background:#0F766E;}
.rl-tick.rl-quote, .rl-key.rl-quote {background:#B42318;}
.rl-tick.rl-quote.rl-down, .rl-key.rl-quote.rl-down {background:#1D4ED8;}
.rl-out {position:absolute; top:-5px; font-size:15px; line-height:21px; font-weight:800; color:#B42318;}
.rl-out.rl-down {color:#1D4ED8;}
.rl-out.rl-right {right:-20px;} .rl-out.rl-left {left:-20px;}
.rl-rail-labels {display:flex; justify-content:space-between; flex-wrap:wrap; gap:4px 18px;
  margin:16px 0 0 0; font-size:11.5px; color:#62748C; line-height:1.6;}
.rl-rail-labels b {color:#253D56; font-weight:700;}
.rl-rail-labels > span:last-child {text-align:right; margin-left:auto;}
.rl-key {display:inline-block; width:3px; height:11px; border-radius:2px; margin:0 5px -1px 0;}
.rl-sep {color:#B5C0CE; margin:0 6px;}
.rl-points {display:flex; flex-wrap:wrap; gap:10px; margin:18px 0 2px 0;}
.rl-point {background:#F6F9FC; border:1px solid #E3EAF3; border-radius:10px; padding:12px 16px; min-width:170px;}
.rl-point .rl-point-label {font-size:11.5px; color:#6A7D90;}
.rl-point .rl-point-value {font-size:18px; font-weight:800; color:var(--pc-navy); margin-top:4px;}
.rl-point.rl-quote-point {background:#FFF7F6; border-color:#F5D3CE;}
.rl-panel {background:#F7FAFD !important; padding:20px !important;}
.rl-panel h3 {font-size:15px; font-weight:800; color:var(--pc-navy); margin:0 0 10px 0; padding:0; letter-spacing:-0.3px;}
.rl-panel ul {list-style:none; padding:0; margin:12px 0 0 0;}
.rl-panel li {position:relative; font-size:11.5px; line-height:1.6; color:#4E6178; padding:0 0 0 14px; margin:0 0 7px 0;
  word-break:keep-all;}
.rl-panel li::before {content:''; position:absolute; left:0; top:7px; width:6px; height:6px; border-radius:50%;
  background:#A3AFBF;}
.rl-panel li.rl-warn::before {background:#D97706;} .rl-panel li.rl-danger::before {background:#B42318;}
.rl-panel li.rl-info::before {background:#1D4ED8;} .rl-panel li.rl-ok::before {background:#047857;}
.rl-panel li.rl-general {color:#7A899B; font-size:11.5px;}
.rl-chiprow {display:flex; flex-wrap:wrap; gap:7px; margin:0 0 6px 0;}
.rl-chiprow .pc-chip {font-size:11.5px;}
.rl-chiprow .pc-chip.rl-warn {background:#FFF3DF; color:#8A5207;}
.rl-chiprow .pc-chip.rl-warn b {color:#7A4806;}
.rl-chiprow .pc-chip.rl-danger {background:#FFF3F1; color:#912018;}
.rl-bignums {display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; margin:2px 0 14px 0;}
.rl-bignum {background:#F6F9FC; border:1px solid #E3EAF3; border-radius:10px; padding:14px 16px;}
.rl-bignum .rl-bignum-label {font-size:12px; color:var(--pc-muted);}
.rl-bignum .rl-bignum-value {font-size:22px; font-weight:800; color:var(--pc-navy); margin-top:4px; word-break:keep-all;}
.rl-bignum.rl-main {background:#EEF4FF; border-color:#CFDDF7;}
.rl-outlier-head {font-size:13px; font-weight:800; color:#825510;}
.rl-section-note {font-size:12px; color:#7A899B; margin:-6px 0 8px 0;}
/* Streamlit pieces on the result screen */
.st-key-rl_settings {background:var(--pc-surface); border:1px solid var(--pc-border); border-radius:13px;
  box-shadow:0 2px 11px rgba(23,52,89,.035); padding:10px 18px; margin:0 0 2px 0;}
.st-key-rl_settings .rl-setting-label {font-size:12px; font-weight:700; color:#62748C; white-space:nowrap;}
.st-key-rl_settings .rl-setting-unit {font-size:12px; color:#7A899B; white-space:nowrap;}
.st-key-rl_settings input {font-weight:800; font-size:15px;}
.st-key-rl_settings input::placeholder {font-weight:400; font-size:13px;}
.st-key-rl_settings [data-testid="stColumn"]:nth-child(4) [data-testid="stMarkdownContainer"] {text-align:right;}
.st-key-rl_settings [data-testid="stColumn"]:last-child [data-testid="stVerticalBlock"] {align-items:flex-end;}
/* Below ~860px of card width: price input and its hint on the first line, the period control on
   its own second line (the ::after item forces the break), so nothing overlaps or clips. */
.st-key-rl_settings {container-type:inline-size;}
@container (max-width: 860px) {
  .st-key-rl_settings [data-testid="stHorizontalBlock"] {flex-wrap:wrap; row-gap:6px;}
  .st-key-rl_settings [data-testid="stHorizontalBlock"]::after {content:''; order:1; flex:0 0 100%; height:0;}
  .st-key-rl_settings [data-testid="stColumn"] {min-width:0 !important;}
  .st-key-rl_settings [data-testid="stColumn"]:nth-child(1) {flex:0 0 78px !important; width:78px !important;}
  .st-key-rl_settings [data-testid="stColumn"]:nth-child(2) {flex:0 0 190px !important; width:190px !important;}
  .st-key-rl_settings [data-testid="stColumn"]:nth-child(3) {flex:1 1 0 !important; width:auto !important;}
  .st-key-rl_settings [data-testid="stColumn"]:nth-child(4) {order:2; flex:0 0 78px !important; width:78px !important;}
  .st-key-rl_settings [data-testid="stColumn"]:nth-child(4) [data-testid="stMarkdownContainer"] {text-align:left;}
  .st-key-rl_settings [data-testid="stColumn"]:nth-child(5) {order:2; flex:1 1 0 !important; width:auto !important;}
  .st-key-rl_settings [data-testid="stColumn"]:last-child [data-testid="stVerticalBlock"] {align-items:flex-start;}
  .st-key-rl_settings .rl-setting-unit {white-space:normal;}
}
@container (max-width: 480px) {
  .st-key-rl_settings [data-testid="stColumn"]:nth-child(2) {flex:1 1 0 !important; width:auto !important;}
  .st-key-rl_settings [data-testid="stColumn"]:nth-child(3) {order:1; flex:0 0 100% !important; width:100% !important;}
}
.st-key-rl_mfds_action {margin-top:-10px;}
.st-key-rl_mfds_action button p {font-size:12px; color:#1D4ED8; font-weight:700; white-space:nowrap;}
.st-key-rl_result h4 {margin-top:18px;}
.st-key-rl_outliers {background:#FFF9EA; border:1px solid #F8E2B5; border-radius:10px; padding:12px 16px;}
.st-key-rl_outliers [data-testid="stMarkdownContainer"] p {font-size:12.5px; color:#5A4210;}
.st-key-rl_outliers button [data-testid="stMarkdownContainer"] p {color:#1D4ED8; font-weight:700; font-size:12.5px;}
.st-key-rl_outliers button:hover [data-testid="stMarkdownContainer"] p {text-decoration:underline;}
.st-key-rl_result h4 {font-size:17px; font-weight:700; color:var(--pc-navy); letter-spacing:-0.4px; padding:0;}
.st-key-rl_result [data-baseweb="tab-list"] {gap:20px;}
.st-key-rl_result [data-baseweb="tab"] p {font-size:13px;}
.st-key-rl_result [data-baseweb="tab"][aria-selected="true"] p {font-weight:800;}
.st-key-rl_result [data-baseweb="tab-highlight"] {height:3px;}
@media (max-width: 900px) {
  .rl-lead {grid-template-columns:1fr;}
  .rl-bignums {grid-template-columns:1fr;}
}
</style>
"""


def _won(value: Decimal | None) -> str:
    return f"{value:,.0f}원" if value is not None else "미확인"


def _decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("원", "").strip())
    except Exception:
        return None


def unit_phrase(unit: str | None) -> str:
    """'1대', '1 set'; empty when the unit is unknown."""

    if not unit:
        return ""
    return f"1{unit}" if len(unit) <= 2 and not unit.isascii() else f"1 {unit}"


def _per(unit: str | None) -> str:
    phrase = unit_phrase(unit)
    return f"{phrase}당 " if phrase else ""


# ── Header ──


def header_title(heading: str, product_name: str | None) -> str:
    """'환자감시장치 M40': the product name in front of the model when it is short and new."""

    heading = " ".join(str(heading or "").split())
    product = " ".join(str(product_name or "").split())
    if not product or len(product) > 14 or product.casefold() in heading.casefold():
        return heading
    return f"{product} {heading}"


def header_subtitle(
    *,
    title: str,
    identity_product: str | None = None,
    procurement_product: str | None = None,
    procurement_maker: str | None = None,
    companies: Sequence[str] = (),
    permit_type: str | None = None,
    permit_numbers: Sequence[str] = (),
) -> str:
    """One muted line: 나라장터 품명 · 제조사 · 식약처 허가번호, whatever is known."""

    parts: list[str] = []
    for label, name in (("식약처 품목", identity_product), ("나라장터 품명", procurement_product)):
        if name and name not in title and not any(name in part for part in parts):
            parts.append(f"{label} {name}")
    unique_companies = list(dict.fromkeys(c for c in companies if c))
    if unique_companies:
        extra = f" 외 {len(unique_companies) - 1}곳" if len(unique_companies) > 1 else ""
        parts.append(f"제조·수입 {unique_companies[0]}{extra}")
    elif procurement_maker:
        parts.append(f"제조사 {procurement_maker}")
    unique_permits = list(dict.fromkeys(p for p in permit_numbers if p))
    if unique_permits:
        extra = f" 외 {len(unique_permits) - 1}건" if len(unique_permits) > 1 else ""
        parts.append(f"식약처 {permit_type or '허가'} {unique_permits[0]}{extra}")
    return " · ".join(parts)


def header_html(*, title: str, subtitle: str, chips: Iterable[str], marker_heading: str) -> str:
    chip_items = "".join(f'<span class="pc-chip">{esc(chip)}</span>' for chip in chips if chip)
    return (
        '<div class="rl-head rl-keep">'
        # The production smoke waits for the "<검색어> 거래가격" heading; screen readers read it too.
        f'<div class="rl-sr"><h2>{esc(marker_heading)}</h2></div>'
        f'<div class="pc-title">{esc(title)}</div>'
        + (f'<div class="pc-subtitle">{esc(subtitle)}</div>' if subtitle else "")
        + (f'<div class="pc-chips">{chip_items}</div>' if chip_items else "")
        + "</div>"
    )


# ── 최종 판단 전에 확인하세요 ──


@dataclass(frozen=True)
class CheckPoint:
    tone: str
    text: str


# Words in 사업명 that mark a bundle purchase (vehicle, emergency or subsidy programme), where the
# price often covers more than the device alone. Order = how they are named on screen.
BUNDLE_KEYWORDS: tuple[str, ...] = (
    "구급차",
    "구급",
    "소방",
    "119",
    "응급",
    "지원사업",
    "보강사업",
    "확충",
    "구축",
    "패키지",
    "일괄",
)
BUNDLE_WARN_SHARE = Decimal("0.3")


def bundle_keyword_hits(rows: Iterable[Mapping[str, object]]) -> tuple[int, int, tuple[str, ...]]:
    """(rows with a bundle word in 사업명, rows checked, words found most-common first)."""

    total = 0
    matched = 0
    words: Counter[str] = Counter()
    for row in rows:
        total += 1
        name = " ".join(str(row.get("사업명") or "").split())
        found = [word for word in BUNDLE_KEYWORDS if word in name]
        # "구급차" already covers "구급"; count the longer word only.
        if "구급차" in found and "구급" in found:
            found.remove("구급")
        if found:
            matched += 1
            words.update(found)
    ordered = tuple(word for word, _count in sorted(words.items(), key=lambda item: (-item[1], BUNDLE_KEYWORDS.index(item[0]))))
    return matched, total, ordered


def check_points(
    rows: Sequence[Mapping[str, object]],
    *,
    direct_count: int,
    unavailable: bool = False,
    other_unit_count: int = 0,
    other_units: Sequence[str] = (),
    main_unit: str | None = None,
    outlier_count: int = 0,
    live_failed: bool = False,
    widened_note: str | None = None,
    partial: bool = False,
) -> list[CheckPoint]:
    """What to check before deciding, computed from the comparison trades only.

    ``rows`` are the same-product trades that entered the price (main unit). Nothing here
    judges the quote; each point says what in the data could make the comparison unfair.
    """

    points: list[CheckPoint] = []
    if unavailable:
        points.append(CheckPoint(TONE_WARN, "나라장터 가격 자료에 연결하지 못했습니다. 잠시 뒤 다시 검색하세요."))
        return points
    if direct_count == 0:
        points.append(
            CheckPoint(TONE_MUTED, "같은 제품으로 확인된 거래가 없어 가격을 비교하지 않았습니다.")
        )
    elif direct_count < 3:
        points.append(
            CheckPoint(
                TONE_WARN,
                f"같은 제품 거래가 {direct_count}건뿐이라 가격대를 판단하기에는 부족합니다.",
            )
        )
    matched, total, words = bundle_keyword_hits(rows)
    if matched and total:
        share = Decimal(matched) / Decimal(total)
        quoted = "·".join(f"'{word}'" for word in words[:2])
        percent = share * 100
        share_text = "1% 미만" if percent < 1 else f"{percent:.0f}%"
        points.append(
            CheckPoint(
                TONE_WARN if share >= BUNDLE_WARN_SHARE else TONE_INFO,
                f"비교 거래 {total}건 중 {matched}건({share_text})의 사업명에 {quoted}이 들어 있습니다. "
                "묶음 구매일 수 있어 구성품·설치 조건을 확인하세요.",
            )
        )
    if outlier_count:
        points.append(
            CheckPoint(
                TONE_WARN,
                f"가운데 값과 3배 넘게 다른 거래가 {outlier_count}건 있습니다. "
                "'거래 전체' 탭에서 원문을 확인하세요.",
            )
        )
    if other_unit_count:
        units = "·".join(other_units) or "다른 단위"
        base = f"{main_unit} 단위 " if main_unit else ""
        points.append(
            CheckPoint(
                TONE_INFO,
                f"단위가 다른 거래 {other_unit_count}건({units})은 {base}가격에 섞지 않고 따로 보여줍니다.",
            )
        )
    if live_failed:
        points.append(
            CheckPoint(
                TONE_WARN,
                "나라장터 실시간 확인에 실패해 최근 며칠 거래가 빠졌을 수 있습니다.",
            )
        )
    if widened_note:
        points.append(CheckPoint(TONE_INFO, widened_note))
    if partial:
        points.append(
            CheckPoint(TONE_INFO, "거래가 많아 최근 거래만 계산에 넣었습니다. 더 오래된 거래는 Excel에 있습니다.")
        )
    return points


GENERAL_CHECK = "VAT·설치·옵션 조건이 같은지는 원문에서 확인하세요."


def check_panel_html(points: Sequence[CheckPoint]) -> str:
    warn = [p for p in points if p.tone in {TONE_WARN, TONE_DANGER}]
    if warn:
        pill = pill_html(f"확인할 점 {len(warn)}가지", TONE_WARN)
    elif points:
        pill = pill_html("참고할 점 있음", TONE_INFO)
    else:
        pill = pill_html("눈에 띄는 점 없음", TONE_OK)
    items = [f'<li class="rl-{esc(p.tone)}">{esc(p.text)}</li>' for p in points]
    if not points:
        items.append('<li class="rl-ok">거래 자료에서 따로 확인할 점을 찾지 못했습니다.</li>')
    items.append(f'<li class="rl-general">{esc(GENERAL_CHECK)}</li>')
    return (
        '<div class="pc-card rl-panel" id="purchase-check-points-v1">'
        f"<h3>최종 판단 전에 확인하세요</h3>{pill}<ul>{''.join(items)}</ul></div>"
    )


# ── Conclusion card ──


@dataclass(frozen=True)
class LeadView:
    eyebrow: str
    eyebrow_tone: str
    headline_html: str
    basis: str


def _delta(quote: Decimal, base: Decimal) -> Decimal:
    return ((quote - base) / base * 100).quantize(Decimal("0.1"))


def _delta_html(delta: Decimal) -> str:
    if delta > 0:
        return f'<em class="rl-up">{delta:.1f}% 높습니다</em>'
    if delta < 0:
        return f'<em class="rl-down">{abs(delta):.1f}% 낮습니다</em>'
    return "<em>같습니다</em>"


def lead_view(
    stats: Any,
    conclusion: Any,
    *,
    quote: Decimal | None,
    unit: str | None,
    warn_count: int = 0,
    unavailable: bool = False,
) -> LeadView:
    """Eyebrow, one headline (the quote position when a quote is entered) and one basis line."""

    direct = int(getattr(stats, "direct_count", 0) or 0)
    low = getattr(stats, "min_price", None)
    high = getattr(stats, "max_price", None)
    mid = getattr(stats, "median_price", None)
    latest = getattr(stats, "latest_transaction_date", None)
    quote = quote if quote is not None and quote > 0 else None
    eyebrow = "나라장터 같은 제품 거래 비교"
    tone = TONE_OK
    if warn_count:
        eyebrow += f" · 확인할 점 {warn_count}가지"
        tone = TONE_WARN
    if unavailable or direct == 0 or low is None or high is None:
        return LeadView(
            "나라장터 같은 제품 거래 비교",
            TONE_MUTED,
            esc(conclusion.headline),
            " ".join(part for part in (conclusion.detail, conclusion.quote_line) if part),
        )

    phrase = unit_phrase(unit)
    scope = f"같은 제품 {phrase} 단위 거래" if phrase else "같은 제품 거래"
    latest_text = f" · 최근 거래 {latest}" if latest else ""
    if quote is None:
        if direct >= 3 and low != high:
            basis = f"{scope} {direct}건 기준 · {_per(unit)}거래가 {_won(low)} ~ {_won(high)}{latest_text}"
        else:
            basis = f"{scope} {direct}건 기준{latest_text}"
        return LeadView(eyebrow, tone, esc(conclusion.headline), basis)

    quote_text = esc(_won(quote))
    if direct >= 3 and low != high and mid is not None:
        headline = (
            f"내 견적가 {quote_text}은 {esc(_per(unit))}거래 가운데 값보다 {_delta_html(_delta(quote, mid))}."
        )
        basis = f"{scope} {direct}건 기준 · 가운데 값 {_won(mid)}{latest_text}"
    elif direct == 2 and low != high:
        if quote > high:
            where = "두 거래가보다 모두 높습니다"
        elif quote < low:
            where = "두 거래가보다 모두 낮습니다"
        else:
            where = "두 거래가 사이에 있습니다"
        headline = f"내 견적가 {quote_text}은 {where}."
        basis = f"{scope} 2건 기준{latest_text}"
    else:
        target = "이 1건" if direct == 1 else "이 거래가"
        headline = f"내 견적가 {quote_text}은 {target}보다 {_delta_html(_delta(quote, low))}."
        basis = f"{scope} {direct}건 기준{latest_text}"
    return LeadView(eyebrow, tone, headline, basis)


def _rail_position(value: Decimal, low: Decimal, high: Decimal) -> float:
    if high <= low:
        return 50.0
    return float((value - low) / (high - low) * 100)


def price_rail_html(
    *, low: Decimal, high: Decimal, median: Decimal | None, quote: Decimal | None = None
) -> str:
    """Trade range as a bar with the median and quote as ticks; labels in one wrapped line.

    The labels never sit on the bar, so close values cannot overlap: they read left to right in
    price order, split into a left and a right group. A quote outside the range gets an arrow
    beyond the bar end instead of being clipped.
    """

    parts = ['<div class="rl-rail-wrap rl-keep" id="purchase-price-band-v1"><div class="rl-rail">']
    # (value, position, order among equal values, key mark, name, note)
    items: list[tuple[Decimal, float, int, str, str, str]] = [
        (low, 0.0, 0, "", "최저", ""),
        (high, 100.0, 3, "", "최고", ""),
    ]
    if median is not None:
        at = _rail_position(median, low, high)
        parts.append(f'<span class="rl-tick rl-mid" style="left:{at:.2f}%"></span>')
        items.append((median, at, 1, '<i class="rl-key rl-mid"></i>', "가운데 값", ""))
    if quote is not None:
        direction = "rl-up" if median is None or quote >= median else "rl-down"
        at = _rail_position(quote, low, high)
        note = ""
        if quote > high:
            parts.append(f'<span class="rl-out rl-right {direction}" aria-hidden="true">▶</span>')
            note = " (최고보다 높음)"
        elif quote < low:
            parts.append(f'<span class="rl-out rl-left {direction}" aria-hidden="true">◀</span>')
            note = " (최저보다 낮음)"
        else:
            parts.append(f'<span class="rl-tick rl-quote {direction}" style="left:{at:.2f}%"></span>')
        items.append((quote, at, 2, f'<i class="rl-key rl-quote {direction}"></i>', "내 견적", note))
    parts.append("</div>")
    # Equal prices share one label ("가운데 값·최고 1,980,000원"), so no two labels repeat a number.
    groups: list[list[tuple[Decimal, float, int, str, str, str]]] = []
    for item in sorted(items, key=lambda item: (item[0], item[2])):
        if groups and groups[-1][0][0] == item[0]:
            groups[-1].append(item)
        else:
            groups.append([item])
    labelled: list[tuple[float, str]] = []
    for group in groups:
        marks = "".join(dict.fromkeys(member[3] for member in group if member[3]))
        names = "·".join(member[4] for member in group)
        notes = "".join(member[5] for member in group)
        at = sum(member[1] for member in group) / len(group)
        labelled.append((at, f"{marks}{names} <b>{esc(_won(group[0][0]))}</b>{notes}"))
    sep = '<span class="rl-sep">·</span>'
    left = sep.join(text for at, text in labelled if at < 50)
    right = sep.join(text for at, text in labelled if at >= 50)
    parts.append(f'<div class="rl-rail-labels"><span>{left}</span><span>{right}</span></div></div>')
    return "".join(parts)


def price_points_html(stats: Any, *, quote: Decimal | None, unit: str | None) -> str:
    """One or two trade prices (no bar): a bar would only show a single point."""

    direct = int(getattr(stats, "direct_count", 0) or 0)
    low = getattr(stats, "min_price", None)
    high = getattr(stats, "max_price", None)
    latest = getattr(stats, "latest_transaction_date", None)
    if not direct or low is None or high is None:
        return ""
    per = _per(unit)
    points: list[tuple[str, str, str]] = []
    if low == high:
        label = f"{per}거래가" + (f" · {latest}" if direct == 1 and latest else f" · {direct}건 모두")
        points.append((label, _won(low), ""))
    else:
        points.append((f"{per}낮은 거래가", _won(low), ""))
        points.append((f"{per}높은 거래가", _won(high), ""))
    if quote is not None and quote > 0:
        points.append(("내 견적", _won(quote), " rl-quote-point"))
    cells = "".join(
        f'<div class="rl-point{extra}"><div class="rl-point-label">{esc(label)}</div>'
        f'<div class="rl-point-value">{esc(value)}</div></div>'
        for label, value, extra in points
    )
    return f'<div class="rl-points rl-keep" id="purchase-price-band-v1">{cells}</div>'


def lead_row_html(lead: LeadView, *, price_html: str, panel_html: str, foot_html: str = "") -> str:
    """Conclusion card (eyebrow, headline, basis, rail, then the basis chips at the bottom) and
    the check panel, inside a width-aware wrapper so they stack when the column is narrow."""

    eyebrow_class = {TONE_WARN: " rl-warn", TONE_MUTED: " rl-muted"}.get(lead.eyebrow_tone, "")
    basis = f'<div class="rl-basis">{esc(lead.basis)}</div>' if lead.basis else ""
    return (
        '<div class="rl-cq rl-keep"><div class="rl-lead rl-keep">'
        '<div class="pc-card" id="purchase-conclusion-v1">'
        f'<div class="rl-eyebrow{eyebrow_class}">{esc(lead.eyebrow)}</div>'
        f'<div class="rl-headline">{lead.headline_html}</div>{basis}'
        + (f'<div class="rl-price">{price_html}</div>' if price_html else "")
        + (f'<div class="rl-foot">{foot_html}</div>' if foot_html else "")
        + "</div>"
        f"{panel_html}</div></div>"
    )


# ── Four cards ──

_CARD_TONES = {"ok": TONE_OK, "warn": TONE_WARN, "danger": TONE_DANGER, "neutral": TONE_MUTED}


def cards_html(cards: Sequence[Any]) -> str:
    """workspace_header SummaryCards as equal-height cards with a status dot and a word."""

    items = "".join(
        metric_card_html(card.label, card.value, card.note, tone=_CARD_TONES.get(card.tone, TONE_MUTED))
        for card in cards
    )
    # Two columns when the main column is narrow, so a value never breaks inside "1,980,000원".
    return f'<div class="rl-cq rl-keep"><div class="pc-metrics rl-keep" id="purchase-workspace-header-v1">{items}</div></div>'


def mfds_check_done_html(
    *,
    status: str,
    active_model_count: int,
    model_count: int,
    companies_before: int,
    companies_after: int,
    registered_model_count: int | None = None,
) -> str:
    """One line where the 'check sale status' button was, saying what the check changed.

    ``registered_model_count``: the models listed below (식약처 제품정보). The 형명 model list this
    check reads is a different 식약처 dataset, so the two totals differ (HeartOn A16-DS: 168 here,
    134 below); say so instead of showing two unexplained totals.
    """

    if status == "failure":
        return (
            '<div class="rl-done rl-warn rl-keep">식약처 모델 목록을 불러오지 못했습니다. '
            "가격 결과는 그대로이며, 잠시 뒤 다시 확인하세요.</div>"
        )
    if status not in {"success", "success_0"}:
        return ""
    parts = ["식약처 판매 가능·취소 확인 완료"]
    if model_count:
        parts.append(f"식약처 모델 목록의 같은 품목 모델 {model_count:,}개 중 판매 가능 {active_model_count:,}개")
        if registered_model_count and registered_model_count != model_count:
            parts.append(
                f"아래 표의 등록 모델 {registered_model_count:,}개는 식약처 제품정보 기준이라 개수가 다릅니다"
            )
    else:
        parts.append("식약처 모델 목록에서 같은 품목 모델을 찾지 못했습니다")
    if companies_before and companies_after != companies_before:
        parts.append(
            f"아래 제조·수입업체 목록은 판매 가능한 모델이 있는 {companies_after}곳만 남겼습니다"
            f"(전체 {companies_before}곳)"
        )
    return f'<div class="rl-done rl-keep">{esc(" · ".join(parts))}</div>'


def nothing_found(
    *,
    direct_count: int,
    reference_count: int,
    identity_found: bool,
    price_unavailable: bool,
    mfds_records: int = 0,
    recall_records: int = 0,
) -> bool:
    """True when the search matched nothing anywhere, so no product result should be drawn.

    A failed price lookup is not "nothing found" (it says so instead), and any MFDS or recall
    hit means there is something to show.
    """

    return (
        not price_unavailable
        and not identity_found
        and direct_count == 0
        and reference_count == 0
        and mfds_records == 0
        and recall_records == 0
    )


def not_found_html(query: str, *, basis: str = "") -> str:
    """Empty state: what was searched, where we looked, and what to try next."""

    shown = " ".join(str(query or "").split()) or "검색어"
    basis_html = f'<div class="rl-basis">{esc(basis)}</div>' if basis else ""
    return (
        '<div class="pc-card rl-empty rl-keep" id="purchase-not-found-v1">'
        '<div class="rl-eyebrow rl-muted">검색 결과 없음</div>'
        f'<div class="rl-headline">‘{esc(shown)}’에 맞는 제품을 찾지 못했습니다.</div>'
        '<div class="rl-basis">나라장터 거래 자료와 식약처 허가 자료 모두에서 이 검색어와 같은 모델·품목·업체를 '
        "찾지 못했습니다. 그래서 가격·허가·회수 정보를 보여주지 않습니다.</div>"
        f"{basis_html}"
        "<ul>"
        "<li><b>철자</b>를 확인하세요. 띄어쓰기와 하이픈(-)은 빼도 됩니다.</li>"
        "<li><b>모델명만</b> 넣어 보세요. 예: DFM100, HeartOn A16-DS</li>"
        "<li><b>업체명</b>이나 <b>품목명</b>으로 찾아보세요. 예: 메디아나, 환자감시장치</li>"
        "</ul></div>"
    )


def quote_hint_html(quote: Decimal | None, unit: str | None, *, invalid: bool = False) -> str:
    """Next to the price input: the parsed value with thousands separators, or how to fill it."""

    phrase = unit_phrase(unit)
    if invalid:
        return '<span class="rl-quote-hint">숫자로만 입력하세요 (쉼표는 괜찮습니다)</span>'
    if quote is not None and quote > 0:
        per = f" · {phrase} 기준" if phrase else ""
        return f'<span class="rl-quote-hint"><b>= {esc(_won(quote))}</b>{esc(per)}</span>'
    base = f"원 / {phrase} 기준" if phrase else "원"
    return f'<span class="rl-setting-unit">{esc(base)} · 넣으면 결론과 막대에 위치가 표시됩니다</span>'


def record_fields_html(fields: Iterable[tuple[str, object]]) -> str:
    """The archived record as a plain two-column table sized to its rows (no empty filler rows)."""

    rows = "".join(
        f"<tr><th>{esc(label)}</th><td>{esc(value)}</td></tr>"
        for label, value in fields
        if str(label or "").strip()
    )
    return f'<table class="rl-record rl-keep"><tbody>{rows}</tbody></table>'


def price_card_label(stats: Any, unit: str | None) -> str:
    direct = int(getattr(stats, "direct_count", 0) or 0)
    low = getattr(stats, "min_price", None)
    high = getattr(stats, "max_price", None)
    if direct >= 3 and low is not None and low != high:
        return f"{_per(unit)}거래 가운데 값"
    return f"{_per(unit)}거래가" if direct else "거래가"


# ── Chip row ──


@dataclass(frozen=True)
class Chip:
    label: str
    text: str
    tone: str = TONE_MUTED


def period_chip(choice: Any, *, oldest_collected: str = "2021년") -> Chip:
    if getattr(choice, "cutoff", None) is None:
        text = f"전체 ({oldest_collected} 이후 수집된 모든 거래)"
    else:
        text = f"{choice.label} ({choice.cutoff.isoformat()} 이후 거래)"
    widened = getattr(choice, "widened_from", None)
    if widened:
        return Chip("기간", f"{text} · {widened} 안에 거래가 없어 넓힘", TONE_WARN)
    return Chip("기간", text)


def unit_chip(split: Any) -> Chip | None:
    main = getattr(split, "main_unit", None)
    if getattr(split, "mixed", False):
        others = "·".join(getattr(split, "other_units", ()) or ())
        return Chip(
            "단위",
            f"{unit_phrase(main)} 기준 · 단위 다른 거래 {len(split.other)}건({others}) 따로 표시",
            TONE_WARN,
        )
    if main:
        return Chip("단위", f"모두 {main} 단위")
    return None


def outlier_chip(count: int, *, has_median: bool) -> Chip | None:
    if not has_median:
        return None
    if count:
        return Chip("이상 거래", f"가운데 값과 3배 넘게 다른 거래 {count}건", TONE_WARN)
    return Chip("이상 거래", "없음")


def basis_chip(
    *,
    track_b_data_as_of: str | None,
    index_updated_at: str | None = None,
    live_checked_until: str | None = None,
    live_failed: bool = False,
    mfds_coverage_percent: float | None = None,
    mfds_complete: bool = False,
) -> Chip | None:
    """A live-check failure is said as a failure, never as '0건'."""

    if track_b_data_as_of:
        text = f"나라장터 {track_b_data_as_of} 수집분"
        tone = TONE_MUTED
        if live_checked_until:
            text += f" + {live_checked_until}까지 실시간 확인"
        elif live_failed:
            text += " · 최근 며칠 실시간 확인 실패(빠진 거래가 있을 수 있음)"
            tone = TONE_WARN
    elif index_updated_at:
        text, tone = f"나라장터 자료 갱신 {index_updated_at}", TONE_MUTED
    else:
        return None
    if not mfds_complete and mfds_coverage_percent is not None:
        text += f" · 식약처 자료 {mfds_coverage_percent:.0f}% 수집 중"
    return Chip("자료 기준", text, tone)


def chip_row_html(chips: Iterable[Chip | None]) -> str:
    items = [
        f'<span class="pc-chip rl-{esc(chip.tone)}">{esc(chip.label)} · <b>{esc(chip.text)}</b></span>'
        for chip in chips
        if chip is not None
    ]
    if not items:
        return ""
    return '<div class="rl-chiprow rl-keep" id="purchase-result-chips-v1">' + "".join(items) + "</div>"


# ── Trade dialog ──


def trade_numbers_html(row: Mapping[str, object]) -> str:
    """거래 총액 · 수량 · 1단위 가격, big, in that order (a set total is not a unit price)."""

    unit = " ".join(str(row.get("단위") or "").split())
    unit = "" if unit == "미확인" else unit
    total = str(row.get("총액") or "")
    quantity = _decimal(row.get("수량"))
    price = _decimal(row.get("가격"))
    quantity_text = (
        (f"{quantity:,.0f}" if quantity == quantity.to_integral_value() else f"{quantity.normalize():,}")
        + (f" {unit}" if unit else "")
        if quantity is not None and quantity > 0
        else "확인 안 됨"
    )
    cells = (
        ("거래 총액", total if total and total != "미확인" else "확인 안 됨", ""),
        ("수량", quantity_text, ""),
        (f"{unit_phrase(unit) or '1단위'} 가격", _won(price), " rl-main"),
    )
    return '<div class="rl-bignums rl-keep">' + "".join(
        f'<div class="rl-bignum{extra}"><div class="rl-bignum-label">{esc(label)}</div>'
        f'<div class="rl-bignum-value">{esc(value)}</div></div>'
        for label, value, extra in cells
    ) + "</div>"


def trade_dialog_title(row: Mapping[str, object]) -> str:
    parts = [str(row.get(key) or "").strip() for key in ("거래일", "구매처")]
    parts = [part for part in parts if part and part != "미확인"]
    return "거래 원문" + (" · " + " · ".join(parts) if parts else "")
