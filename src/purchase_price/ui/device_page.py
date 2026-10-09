"""Wording, state notices and plain tables for the 의료기기 허가·안전 page.

The page (pages/4_의료기기_조회.py) calls the official MFDS and 나라장터 APIs; this module only
turns their results into plain Korean text and small HTML blocks so the wording and the state
rules are unit-testable:

* a recall / sale-stop hit is a red banner that sits above every other result block;
* a lookup that failed says "확인하지 못했습니다" and offers a retry - it never turns into "0건";
* a lookup that worked but found nothing says what was searched and what to try next.

Screen-specific CSS uses the ``pc-dev-`` prefix; the shared look comes from ui/theme.py.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from purchase_price.services.matching import exact_model_match
from purchase_price.ui.theme import (
    TONE_DANGER,
    TONE_INFO,
    TONE_MUTED,
    TONE_OK,
    TONE_WARN,
    chips_html,
    esc,
    metric_card_html,
    metric_row_html,
    notice_html,
)

DEVICE_PAGE_LAYOUT_V1 = True

PAGE_TITLE = "의료기기 허가·안전"
PAGE_SUBTITLE = (
    "허가 여부, 회수·판매중지, 공급사, UDI-DI를 한곳에서 확인합니다. "
    "모델명이 정확히 같은 등록만 같은 제품으로 봅니다."
)
TAB_PERMIT = "허가·시장조사"
TAB_SAFETY = "안전·공급사"
TAB_UDI = "UDI-DI"
TAB_NAMES = (TAB_PERMIT, TAB_SAFETY, TAB_UDI)

SEARCH_BUTTON = "허가정보 조회"
RECALL_BUTTON = "회수·판매중지 확인"
COMPANY_BUTTON = "업체 허가·신고 확인"
UDI_BUTTON = "UDI-DI 조회"
RETRY_BUTTON = "다시 시도"

RECALL_TITLE = "관련 회수·판매중지 정보가 있습니다."
RECALL_ACTION = "대상 모델·제조번호·조치일을 원문에서 확인한 뒤 구매를 진행하세요."

_MAX_ERROR_CHARS = 140
_AUTH_MARKERS = (
    "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
    "SERVICE_ACCESS_DENIED_ERROR",
    "PERMISSION_DENIED",
    "CODE=30",
)
_TIMEOUT_MARKERS = ("TIMEOUT", "TIMED OUT", "TRANSPORT")
_URL_PATTERN = re.compile(r"https?://\S+")
_KEY_PATTERN = re.compile(r"(?i)(service[_-]?key|api[_-]?key|key)=\S+")

DEVICE_CSS = """
<style>
[data-testid="stForm"] {background:var(--pc-surface); border:1px solid var(--pc-border);
  border-radius:13px; padding:18px 20px 14px; box-shadow:0 2px 11px rgba(23,52,89,.035);}
[data-testid="stTabs"] [data-baseweb="tab-list"] {gap:6px; border-bottom:1px solid var(--pc-border);}
[data-testid="stTabs"] button[data-baseweb="tab"] {padding:10px 14px; height:auto;}
[data-testid="stTabs"] button[data-baseweb="tab"] p {font-size:13px; font-weight:700;}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {height:3px;}
.pc-dev-lead {font-size:13px; color:var(--pc-muted); margin:6px 0 14px 0; line-height:1.6;}
.pc-dev-section {margin:22px 0 4px 0;}
.pc-dev-section .pc-section-title {margin:0 0 4px 0;}
.pc-dev-section .pc-subtitle {margin:0 0 10px 0;}
.pc-dev-hint {font-size:12px; color:var(--pc-muted); line-height:1.6; margin:6px 0 0 0;}
.pc-notice.pc-ok {background:#EFFAF5; border-color:#BDE5D3; color:#0F5F46;}
.pc-dev-one {max-width:280px; margin:0 0 14px 0;}
.pc-dev-detail {display:block; margin-top:4px; font-size:11.5px; opacity:.85;}
</style>
"""


# ---------------------------------------------------------------- small text helpers

def _eul_reul(word: str) -> str:
    """The object particle that fits the last Hangul syllable of ``word`` (을/를)."""

    for char in reversed(word.strip()):
        code = ord(char)
        if 0xAC00 <= code <= 0xD7A3:
            return "을" if (code - 0xAC00) % 28 else "를"
        if char.isalnum():
            break
    return "를"


def safe_error_text(error: object) -> str:
    """One short plain line for the screen: no URLs, no keys, no stack traces, no error codes."""

    text = " ".join(str(error or "").split())
    upper = text.upper()
    if any(marker in upper for marker in _AUTH_MARKERS):
        return "식약처 서비스 사용 승인이 확인되지 않았습니다. 서비스키 등록을 확인해야 합니다."
    if any(marker in upper for marker in _TIMEOUT_MARKERS) or "시간 초과" in text:
        return "서버가 제때 응답하지 않았습니다."
    server_error = re.search(r"HTTP\s*(5\d\d)", upper)
    if server_error:
        return f"서버 오류가 났습니다 (HTTP {server_error.group(1)})."
    text = _URL_PATTERN.sub("", text)
    text = _KEY_PATTERN.sub("", text)
    text = " ".join(text.split())
    if len(text) > _MAX_ERROR_CHARS:
        text = text[: _MAX_ERROR_CHARS - 1] + "…"
    return text


def section_html(title: str, hint: str = "") -> str:
    hint_html = f'<div class="pc-subtitle">{esc(hint)}</div>' if hint else ""
    return f'<div class="pc-dev-section"><div class="pc-section-title">{esc(title)}</div>{hint_html}</div>'


# ---------------------------------------------------------------- state notices

def connection_chips_html(*, mfds_ready: bool, g2b_ready: bool) -> str:
    def _state(name: str, ready: bool) -> str:
        return f"{esc(name)} <b>{'사용 가능' if ready else '사용 불가'}</b>"

    return chips_html([_state("식약처 자료", mfds_ready), _state("나라장터 자료", g2b_ready)])


def missing_key_notice_html(what: str) -> str:
    return notice_html(
        f"<b>{esc(what)}을 조회할 수 없습니다.</b> 식약처 조회용 서비스키가 설정되지 않았습니다. "
        "관리자에게 설정을 요청해 주세요.",
        TONE_WARN,
    )


def handoff_notice_html(source: str, filled: str) -> str:
    where = source or "가격 조사"
    return notice_html(
        f"<b>{esc(where)}에서 확인한 제품 정보를 입력칸에 채웠습니다.</b> {esc(filled)}"
        f"<br>내용을 확인한 뒤 각 탭의 ‘{esc(SEARCH_BUTTON)}’ 같은 버튼을 눌러야 조회가 시작됩니다.",
        TONE_INFO,
        icon="i",
    )


def lookup_failed_html(what: str, detail: str = "") -> str:
    """Failed live lookup: say so, offer a retry, and never read as "0건" / "없음"."""

    detail_text = safe_error_text(detail)
    detail_html = f'<span class="pc-dev-detail">원인: {esc(detail_text)}</span>' if detail_text else ""
    return notice_html(
        f"<b>{esc(what)}{_eul_reul(what)} 확인하지 못했습니다 ({RETRY_BUTTON})</b><br>"
        "확인하지 못한 것이며, 결과가 없다는 뜻이 아닙니다. 잠시 뒤 아래 ‘다시 시도’를 눌러 주세요."
        f"{detail_html}",
        TONE_WARN,
    )


def not_found_html(searched: str, tips: Sequence[str]) -> str:
    """Lookup worked but returned nothing: what was searched and what to try next."""

    tip_text = " · ".join(esc(tip) for tip in tips if tip)
    next_html = f"<br>다음을 해 보세요: {tip_text}" if tip_text else ""
    return notice_html(
        f"<b>{esc(searched)}에 해당하는 자료를 찾지 못했습니다.</b>{next_html}",
        TONE_MUTED,
        icon="i",
    )


def idle_html(lead: str, detail: str = "", tone: str = TONE_MUTED) -> str:
    """A plain one-or-two sentence notice for "nothing asked yet" and "input needed"."""

    detail_html = f" {esc(detail)}" if detail else ""
    return notice_html(f"<b>{esc(lead)}</b>{detail_html}", tone, icon="i")


def single_metric_html(card_html: str) -> str:
    return f'<div class="pc-dev-one">{card_html}</div>'


def authorization_pending_html(what: str) -> str:
    return notice_html(
        f"<b>{esc(what)}{_eul_reul(what)} 확인하지 못했습니다.</b> 식약처 조회 서비스의 사용 승인이 "
        "확인되지 않았습니다. 승인 전에는 ‘해당 없음’으로 보지 말고 식약처 사이트에서 직접 확인하세요.",
        TONE_WARN,
    )


# ---------------------------------------------------------------- recall / sale stop

@dataclass(frozen=True)
class RecallView:
    """How one recall lookup is shown. ``banner`` is non-empty only for a hit."""

    state: str  # hit | none | failed | not_authorized | not_connected | not_checked
    card_value: str
    card_sub: str
    card_tone: str
    banner: str = ""
    notice: str = ""
    rows: tuple[dict[str, str], ...] = ()

    @property
    def is_hit(self) -> bool:
        return self.state == "hit"


def recall_rows(records: Iterable[Any]) -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "모델명": str(getattr(item, "model_name", "") or ""),
            "품목명": str(getattr(item, "product_name", "") or ""),
            "제조사": str(getattr(item, "manufacturer_name", "") or ""),
            "회수 구분": str(getattr(item, "report_kind_name", "") or ""),
            "처리 상태": str(getattr(item, "report_state_name", "") or ""),
            "보고일": str(getattr(item, "report_submit_date", "") or ""),
            "회수 사유": str(getattr(item, "reason", "") or ""),
        }
        for item in records
    )


def recall_view(lookup: object | None, *, searched: str = "") -> RecallView:
    """Map a ``MfdsRecallLookupResult`` (or a look-alike) to what the screen shows."""

    status = str(getattr(lookup, "status", "") or "") if lookup is not None else ""
    records = tuple(getattr(lookup, "records", ()) or ()) if lookup is not None else ()
    what = "회수·판매중지 정보"
    if status == "success" and records:
        banner = notice_html(
            f"<b>{esc(RECALL_TITLE)}</b> {esc(RECALL_ACTION)}",
            TONE_DANGER,
            icon="!",
        )
        return RecallView(
            "hit",
            f"{len(records)}건 있음",
            "원문에서 대상 확인 필요",
            TONE_DANGER,
            banner=banner,
            rows=recall_rows(records),
        )
    if status in {"success", "success_0"}:
        key = f"‘{searched}’ " if searched else ""
        return RecallView(
            "none",
            "확인된 회수 없음",
            "조회한 식약처 자료 기준",
            TONE_OK,
            notice=notice_html(
                f"{esc(key)}기준으로 조회한 식약처 회수·판매중지 자료에서는 찾지 못했습니다. "
                "전체 이력이 없다는 뜻은 아니므로 중요한 구매는 식약처 사이트에서 한 번 더 확인하세요.",
                TONE_INFO,
                icon="i",
            ),
        )
    if status == "not_authorized":
        return RecallView(
            "not_authorized",
            "사용 승인 필요",
            "해당 없음으로 보지 마세요",
            TONE_WARN,
            notice=authorization_pending_html(what),
        )
    if status == "not_configured":
        return RecallView(
            "not_connected",
            "연결 안 됨",
            "식약처 사이트에서 직접 확인",
            TONE_WARN,
            notice=missing_key_notice_html(what),
        )
    if status == "failure":
        detail = str(getattr(lookup, "error_message", "") or "")
        return RecallView(
            "failed",
            "확인하지 못함",
            f"{RETRY_BUTTON}해 주세요",
            TONE_WARN,
            notice=lookup_failed_html(what, detail),
        )
    return RecallView("not_checked", "확인 전", "모델명이나 품목명으로 확인합니다", TONE_MUTED)


# ---------------------------------------------------------------- 허가·시장조사 tab

@dataclass(frozen=True)
class MarketParams:
    product_name: str = ""
    model_name: str = ""
    manufacturer: str = ""
    specification: str = ""
    intended_use: str = ""

    def chips(self) -> list[str]:
        pairs = (
            ("품목명", self.product_name),
            ("모델명", self.model_name),
            ("업체", self.manufacturer),
            ("규격", self.specification),
        )
        return [f"{esc(label)} <b>{esc(value)}</b>" for label, value in pairs if value.strip()]


@dataclass
class MarketResult:
    """Everything one 허가정보 조회 produced; kept in session state so reruns do not repeat calls."""

    params: MarketParams
    checked_at: str = ""
    records: tuple[Any, ...] = ()
    records_error: str = ""
    exact: Any = None
    business_error: str = ""
    procurement: Any = None
    procurement_error: str = ""
    procurement_note: str = ""
    discovery: Any = None
    supplier_rows: list[dict[str, str]] = field(default_factory=list)
    recall: Any = None

    @property
    def records_failed(self) -> bool:
        return bool(self.records_error)

    @property
    def active_count(self) -> int:
        return sum(1 for item in self.records if getattr(item, "active_for_domestic_candidate", False))


def sale_status_text(record: Any) -> str:
    if str(getattr(record, "cancellation_status", "") or "").strip():
        return "효력 없음"
    if getattr(record, "export_only", None) is True:
        return "수출 전용"
    return "유효"


def permit_rows(records: Sequence[Any], query_model: str = "") -> list[dict[str, str]]:
    """Registration table; rows whose model matches the typed model exactly come first."""

    model = query_model.strip()
    rows: list[tuple[bool, dict[str, str]]] = []
    for item in records:
        same = bool(model) and exact_model_match(model, getattr(item, "model_name", None))
        permit_date = getattr(item, "permit_date", None)
        rows.append(
            (
                same,
                {
                    "입력한 모델과": "같음" if same else "",
                    "품목명": str(getattr(item, "product_name", "") or ""),
                    "모델명": str(getattr(item, "model_name", "") or ""),
                    "허가번호": str(getattr(item, "permit_number", "") or ""),
                    "업종": str(getattr(item, "industry_type", "") or ""),
                    "허가일": permit_date.isoformat() if permit_date else "",
                    "상태": sale_status_text(item),
                },
            )
        )
    # Same model first, then registrations still in force, then the newest permits.
    rows.sort(key=lambda pair: (not pair[0], pair[1]["상태"] != "유효", _reverse_date(pair[1]["허가일"])))
    return [row for _, row in rows]


def _reverse_date(iso: str) -> str:
    """Sort key that puts the newest ISO date first (empty dates last)."""

    if not iso:
        return "~"
    return "".join(chr(0x7E - (ord(char) - 0x30)) if char.isdigit() else char for char in iso)


def supplier_evidence_text(evidence: str) -> str:
    """Short table text: drop the long disclaimer (the note below the table says it once)."""

    return evidence.split(";")[0].strip()


def identity_notice_html(model_name: str, exact: Any) -> str:
    """One sentence on whether the typed model was found as the same registration."""

    if exact is None or not model_name.strip():
        return ""
    if getattr(exact, "ambiguous", False):
        return notice_html(
            "<b>같은 모델명이 서로 다른 허가번호에 걸려 있어 하나로 정하지 않았습니다.</b> "
            "허가번호와 업체를 보고 직접 고르세요.",
            TONE_WARN,
        )
    if getattr(exact, "confirmed", False):
        permits = ", ".join(
            str(getattr(item, "permit_number", "") or "허가번호 미표기")
            for item in getattr(exact, "exact_matches", ())
        )
        return notice_html(
            f"<b>모델명 ‘{esc(model_name)}’과 정확히 같은 등록을 확인했습니다.</b> 허가번호 {esc(permits)}",
            TONE_OK,
            icon="✓",
        )
    return notice_html(
        f"<b>품목 조회 결과 안에서 모델명 ‘{esc(model_name)}’과 정확히 같은 등록을 찾지 못했습니다.</b> "
        "모델명 철자를 확인하거나 위 표에서 비슷한 모델을 직접 살펴보세요.",
        TONE_WARN,
    )


def permit_summary_cards(result: MarketResult) -> str:
    """Four equal-height cards: 등록 수, 효력 있는 등록, 입력 모델 확인, 회수·판매중지."""

    params = result.params
    if result.records_failed:
        registered = metric_card_html("식약처 등록", "확인하지 못함", f"{RETRY_BUTTON}해 주세요", TONE_WARN)
        active = metric_card_html("효력 있는 등록", "확인하지 못함", "취소·수출 전용 제외", TONE_WARN)
    else:
        count = len(result.records)
        registered = metric_card_html(
            "식약처 등록",
            f"{count}건",
            f"품목명 ‘{params.product_name}’으로 찾은 등록",
            TONE_OK if count else TONE_MUTED,
        )
        active_count = result.active_count
        active = metric_card_html(
            "효력 있는 등록",
            f"{active_count}건",
            "취소·수출 전용 제외",
            TONE_OK if active_count else TONE_MUTED,
        )
    exact = result.exact
    if result.records_failed or not params.model_name.strip():
        same = metric_card_html("입력한 모델과 같은 등록", "—", "모델명을 넣으면 확인합니다", TONE_MUTED)
    elif getattr(exact, "ambiguous", False):
        same = metric_card_html("입력한 모델과 같은 등록", "여러 허가번호", "하나로 정하지 못함", TONE_WARN)
    elif getattr(exact, "confirmed", False):
        count = len(exact.exact_matches)
        same = metric_card_html("입력한 모델과 같은 등록", f"{count}건", "모델명이 정확히 같음", TONE_OK)
    else:
        same = metric_card_html("입력한 모델과 같은 등록", "찾지 못함", "품목 결과 안에 같은 모델명 없음", TONE_WARN)
    recall = recall_view(result.recall, searched=params.model_name or params.product_name)
    recall_card = metric_card_html("회수·판매중지", recall.card_value, recall.card_sub, recall.card_tone)
    return metric_row_html([registered, active, same, recall_card])


def searched_chips_html(params: MarketParams, checked_at: str) -> str:
    chips = params.chips()
    if checked_at:
        chips.append(f"확인 시각 <b>{esc(checked_at)}</b>")
    return chips_html(chips)


def permit_not_found_html(params: MarketParams) -> str:
    return not_found_html(
        f"식약처 등록 자료에서 품목명 ‘{params.product_name}’",
        (
            "식약처에 등록된 품목명 그대로 넣어 보세요 (예: 심장충격기)",
            "띄어쓰기와 철자를 확인하세요",
            "모델명은 비워 두고 품목명만 먼저 찾아도 됩니다",
        ),
    )


# ---------------------------------------------------------------- procurement cases

def procurement_rows(items: Iterable[Any]) -> list[dict[str, object]]:
    """Plain table of public price/delivery cases: confirmed-same-product rows first."""

    from purchase_price.services.price_conditions import build_price_condition_profile

    rows: list[tuple[int, dict[str, object]]] = []
    for item in items:
        profile = build_price_condition_profile(item)
        grade = str(getattr(getattr(item, "match_grade", ""), "value", getattr(item, "match_grade", "")))
        same_product = grade.upper() in {"A", "B"}
        transaction_date = getattr(item, "transaction_date", None)
        rows.append(
            (
                0 if same_product else 1,
                {
                    "거래일": transaction_date.isoformat() if transaction_date else "",
                    "1개당 가격(원)": int(item.price),
                    "수량·단위": profile.quantity_unit,
                    "부가세": profile.vat,
                    "같은 제품 여부": "같은 제품으로 확인" if same_product else "참고용 (가격 판단 제외)",
                    "출처": str(getattr(item, "source_name", "") or ""),
                    "거래 조건": str(getattr(item, "conditions", "") or ""),
                    "원문 링크": str(getattr(item, "source_url", "") or ""),
                },
            )
        )
    rows.sort(key=lambda pair: pair[0])
    return [row for _, row in rows]


def procurement_state(run: Any) -> tuple[str, str]:
    """(state, detail) for the search run: ``found``, ``empty``, ``failed`` or ``skipped``."""

    statuses = tuple(getattr(run, "source_statuses", ()) or ())
    results = tuple(getattr(run, "results", ()) or ())
    failed = [s for s in statuses if not s.succeeded and not s.skipped]
    if results:
        return "found", ""
    if failed:
        detail = " ".join(str(s.error or "") for s in failed)
        return "failed", detail
    if statuses and all(s.skipped for s in statuses):
        return "skipped", " ".join(str(s.note or "") for s in statuses if s.note)
    return "empty", ""


def procurement_partial_notice(run: Any) -> str:
    """Some sources failed while others returned rows: warn that the list may be incomplete."""

    statuses = tuple(getattr(run, "source_statuses", ()) or ())
    failed = [s for s in statuses if not s.succeeded and not s.skipped]
    if not failed or not tuple(getattr(run, "results", ()) or ()):
        return ""
    names = ", ".join(sorted({str(s.source_name) for s in failed}))
    return notice_html(
        f"<b>{esc(names)}의 자료는 확인하지 못했습니다.</b> 아래 목록에서 빠진 거래가 있을 수 있습니다.",
        TONE_WARN,
    )


def procurement_empty_html(params: MarketParams) -> str:
    return not_found_html(
        "나라장터 공개 거래에서 ‘" + f"{params.product_name} {params.model_name}".strip() + "’",
        (
            "모델명 철자를 확인하세요",
            "‘가격 조사’ 화면에서 같은 모델을 검색해 거래 기간을 넓혀 보세요",
        ),
    )


def discovery_rows(discovery: Any) -> list[dict[str, object]]:
    return [
        {
            "거래일": candidate.transaction_date.isoformat() if candidate.transaction_date else "",
            "나라장터 표기": candidate.title,
            "세부품명": candidate.classification_name,
            "표기 금액(원)": int(candidate.price),
            "살펴볼 순서": candidate.relevance,
            "찾은 이유": candidate.match_reason,
        }
        for candidate in getattr(discovery, "candidates", ())
    ]


def discovery_state(discovery: Any) -> str:
    """``failed``, ``partial``, ``empty`` or ``found``."""

    status = str(getattr(discovery, "status", "") or "")
    if status == "failure":
        return "failed"
    if status == "partial":
        return "partial"
    if not getattr(discovery, "candidates", ()):
        return "empty"
    return "found"


SUPPLIER_NOTE = (
    "식약처 업 허가·신고는 의료기기를 취급할 자격이 있다는 근거일 뿐, 특정 모델의 공식 총판·대리점이라는 뜻은 아닙니다."
)


# ---------------------------------------------------------------- 안전·공급사 tab

def safety_key_chips_html(
    model_name: str,
    permit_numbers: Sequence[str],
    product_name: str = "",
    *,
    checked_at: str = "",
) -> str:
    chips: list[str] = []
    if model_name.strip():
        chips.append(f"모델명 <b>{esc(model_name.strip())}</b>")
    if product_name.strip():
        chips.append(f"품목명 <b>{esc(product_name.strip())}</b>")
    chips.extend(f"허가번호 <b>{esc(number)}</b>" for number in permit_numbers)
    if checked_at:
        chips.append(f"확인 시각 <b>{esc(checked_at)}</b>")
    return chips_html(chips)


def safety_not_checked_html(has_keys: bool) -> str:
    if has_keys:
        text = (
            f"<b>아직 확인하지 않았습니다.</b> ‘{RECALL_BUTTON}’을 누르면 식약처 자료에서 찾습니다. "
            "확인 전에는 안전하다는 뜻이 아닙니다."
        )
    else:
        text = (
            "<b>모델명 또는 품목명을 넣어 주세요.</b> 입력한 값으로 식약처 회수·판매중지 자료를 찾습니다. "
            "확인 전에는 안전하다는 뜻이 아닙니다."
        )
    return notice_html(text, TONE_MUTED, icon="i")


def business_rows(records: Iterable[Any]) -> list[dict[str, str]]:
    return [
        {
            "업체": str(getattr(item, "company_name", "") or ""),
            "업종": str(getattr(item, "industry_type", "") or ""),
            "영업 상태": str(getattr(item, "business_status", "") or ""),
            "허가·신고번호": str(getattr(item, "business_permit_number", "") or ""),
            "주소": str(getattr(item, "address", "") or ""),
            "지금 취급 가능": "예" if getattr(item, "is_active", False) else "아니오",
        }
        for item in records
    ]


def company_not_found_html(company: str) -> str:
    return not_found_html(
        f"식약처 업 허가·신고 자료에서 업체 ‘{company}’",
        (
            "회사 이름의 (주)·유한회사 같은 표기를 빼고 핵심 이름만 넣어 보세요",
            "영문 이름이면 한글 이름으로도 찾아 보세요",
        ),
    )


# ---------------------------------------------------------------- UDI-DI tab

def udi_rows(records: Iterable[Any]) -> list[dict[str, str]]:
    return [
        {
            "UDI-DI": str(getattr(item, "udi_di", "") or ""),
            "업체": str(getattr(item, "company_name", "") or ""),
            "업체 구분": str(getattr(item, "company_type", "") or ""),
            "코드 체계": str(getattr(item, "code_system_name", "") or ""),
        }
        for item in records
    ]


def udi_not_found_html(udi_di: str) -> str:
    return not_found_html(
        f"식약처 UDI 자료에서 UDI-DI ‘{udi_di}’",
        (
            "번호를 한 글자씩 다시 확인하세요 (일부만 같아서는 찾지 않습니다)",
            "모델명으로는 UDI-DI를 찾을 수 없으니 제품 라벨이나 제조사 자료에서 번호를 확인하세요",
        ),
    )

