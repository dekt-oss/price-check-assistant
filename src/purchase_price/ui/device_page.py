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
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from statistics import median
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from purchase_price.evidence_domain import IdentityEvidenceStatus
from purchase_price.services.matching import exact_model_match
from purchase_price.ui import product_identity, result_layout, result_summary
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
from purchase_price.ui.track_b_transactions import (
    category_reference_candidates,
    entry_error_candidates,
    reference_candidates,
    strict_comparison_candidates,
)

DEVICE_PAGE_LAYOUT_V1 = True
DEVICE_PAGE_UDI_INPUT_V1 = True
# 2026-10-10: the result header is the shared labelled product block (ui/product_identity.py).
DEVICE_PAGE_IDENTITY_V1 = True
# 2026-10-10: the trade summary counts 입력 오류 의심 lines out and says so (same rule as 가격 조사).
DEVICE_PAGE_ENTRY_ERRORS_V1 = True
# 2026-10-10: the identity block and the trade card state the same period and count
# ("같은 제품 거래 390건 (전체 기간) · 최근 3년 267건").
DEVICE_PAGE_TRADE_PERIOD_V1 = True

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
NOT_APPROVED_TEXT = "식약처 조회 서비스가 아직 연결되지 않았습니다."
_TIMEOUT_MARKERS = ("TIMEOUT", "TIMED OUT", "TRANSPORT")
_URL_PATTERN = re.compile(r"https?://\S+")
_KEY_PATTERN = re.compile(r"(?i)(service[_-]?key|api[_-]?key|key)=\S+")

try:
    SEOUL = ZoneInfo("Asia/Seoul")
except ZoneInfoNotFoundError:  # no tz database (bare Windows); Korea has no DST
    SEOUL = timezone(timedelta(hours=9), name="KST")


def kst_now() -> datetime:
    """Streamlit Cloud runs in UTC; every time shown on this page is Korean time."""

    return datetime.now(SEOUL)


def kst_time_text(value: datetime | None = None, fmt: str = "%m-%d %H:%M") -> str:
    moment = value or kst_now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(SEOUL).strftime(fmt)


def won_text(value: object) -> str:
    """'1,980,000원' for a number; '미확인' when there is no usable number."""

    try:
        number = Decimal(str(value).replace(",", "").replace("원", "").strip())
    except Exception:
        return "미확인"
    if not number.is_finite():
        return "미확인"
    return f"{number:,.0f}원"


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
.pc-dev-trades .pc-metric .pc-value {font-size:18px; overflow-wrap:anywhere;}
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


def is_not_approved_error(error: object) -> bool:
    """True when a lookup failed because the service is not approved for the deployed key."""

    upper = str(error or "").upper()
    return any(marker in upper for marker in _AUTH_MARKERS) or str(error or "") == NOT_APPROVED_TEXT


def safe_error_text(error: object) -> str:
    """One short plain line for the screen: no URLs, no keys, no stack traces, no error codes."""

    text = " ".join(str(error or "").split())
    upper = text.upper()
    if any(marker in upper for marker in _AUTH_MARKERS):
        return NOT_APPROVED_TEXT
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

SERVICE_PERMIT = "permit"
SERVICE_RECALL = "recall"
SERVICE_COMPANY = "company"
SERVICE_UDI = "udi"
SERVICE_G2B = "g2b"
SERVICE_LABELS = {
    SERVICE_PERMIT: "식약처 허가정보",
    SERVICE_RECALL: "회수·판매중지",
    SERVICE_COMPANY: "업체 허가·신고",
    SERVICE_UDI: "UDI-DI",
    SERVICE_G2B: "나라장터 자료",
}
STATE_READY = "ready"
STATE_PENDING = "pending"
STATE_OFF = "off"
_STATE_WORDS = {STATE_READY: "사용 가능", STATE_PENDING: "연결 전", STATE_OFF: "사용 불가"}


def connection_chips_html(
    *,
    mfds_ready: bool,
    g2b_ready: bool,
    service_states: Mapping[str, str] | None = None,
) -> str:
    """One chip per data service. ``service_states`` holds what the last call of each one showed:
    ``pending`` (the service is not approved yet, so the chip says 연결 전), ``ready``."""

    states = dict(service_states or {})
    chips: list[str] = []
    for service, label in SERVICE_LABELS.items():
        configured = g2b_ready if service == SERVICE_G2B else mfds_ready
        state = STATE_OFF if not configured else states.get(service, STATE_READY)
        chips.append(f"{esc(label)} <b>{_STATE_WORDS.get(state, _STATE_WORDS[STATE_READY])}</b>")
    return chips_html(chips)


def missing_key_notice_html(what: str) -> str:
    return notice_html(
        f"<b>{esc(what)}{_eul_reul(what)} 조회할 수 없습니다.</b> 식약처 자료 연결 설정이 없습니다. "
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

    if is_not_approved_error(detail):
        return notice_html(
            f"<b>{esc(what)}{_eul_reul(what)} 확인하지 못했습니다.</b><br>"
            "이 조회 서비스가 아직 연결되지 않았습니다. ‘없음’이라는 뜻이 아니니 식약처 사이트에서 직접 확인하세요.",
            TONE_WARN,
        )
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
    track_b: Any = None
    track_b_live: str = ""
    track_b_error: str = ""
    trades: TradeSummary | None = None
    supplier_rows: list[dict[str, str]] = field(default_factory=list)
    recall: Any = None
    # The 식약처 identity index answer for the typed model (permit, company, grade, UDI-DI) and the
    # item-status labels of its permits; both empty when the model was not typed or not found.
    identity: Any = None
    status_labels: dict[str, str] = field(default_factory=dict)

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


def index_exact_permits(result: MarketResult) -> tuple[str, ...]:
    """Permit numbers of the typed model in the full 허가 목록 index (the header's source); () if none.

    The 식약처 API lookup only returns the first rows of the product name, so a model missing there
    can still be a confirmed registration in the full list. Ambiguous hits are left to the person.
    """

    identity = getattr(result, "identity", None)
    if getattr(identity, "status", "") != "success":
        return ()
    if getattr(identity, "match_type", "") not in {"model", "udi", "permit"}:
        return ()
    if getattr(identity, "identity_status", None) == IdentityEvidenceStatus.AMBIGUOUS:
        return ()
    return tuple(getattr(identity, "permit_numbers", ()) or ())


def identity_notice_html(model_name: str, exact: Any, index_permits: Sequence[str] = ()) -> str:
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
    if index_permits:
        return notice_html(
            f"<b>식약처 전체 허가 목록에서 모델명 ‘{esc(model_name)}’과 정확히 같은 등록을 확인했습니다.</b> "
            f"허가번호 {esc(', '.join(index_permits))} · 위 표는 품목명 조회 결과의 일부라 이 등록이 안 보일 수 있습니다.",
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
    elif index_exact_permits(result):
        same = metric_card_html(
            "입력한 모델과 같은 등록",
            f"{len(index_exact_permits(result))}건",
            "식약처 전체 허가 목록에서 확인",
            TONE_OK,
        )
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


def meta_chips_html(params: MarketParams, checked_at: str) -> str:
    """The chips the product block does not show: 규격 and when the lookup ran."""

    chips = []
    if params.specification.strip():
        chips.append(f"규격 <b>{esc(params.specification.strip())}</b>")
    if checked_at:
        chips.append(f"확인 시각 <b>{esc(checked_at)}</b>")
    return chips_html(chips)


def identity_header_fields(result: MarketResult) -> list[product_identity.IdentityField]:
    """The same labelled product grid as 가격 조사: 모델명, 품목명, 업체, 허가번호, 등급, UDI-DI when known."""

    params = result.params
    exact = result.exact
    exact_records = tuple(getattr(exact, "exact_matches", ()) or ()) if getattr(exact, "confirmed", False) else ()
    workspace = SimpleNamespace(exact_records=exact_records, exact_confirmed=bool(exact_records))
    identity = getattr(result, "identity", None)
    try:
        candidates = strict_comparison_candidates(result.track_b) if result.track_b is not None else ()
    except Exception:
        candidates = ()
    fields = product_identity.matched_product_fields(
        identity=identity,
        workspace=workspace,
        candidates=candidates,
        fallback_model=params.model_name,
        status_labels=getattr(result, "status_labels", None) or {},
    )
    if getattr(exact, "ambiguous", False):
        fields = [
            replace(f, status="허가 여러 건", tone=TONE_WARN) if f.key == "model" else f for f in fields
        ]
    trades = getattr(result, "trades", None)
    if trades is not None and candidates and getattr(trades, "all_period_count", 0):
        # The trade card below counts the default period; say both so 390 and 267 read as one story.
        note = trade_period_note(trades)
        fields = [replace(f, note=note) if f.key == "detail_class" else f for f in fields]
    typed_product = " ".join(params.product_name.split())
    typed_maker = " ".join(params.manufacturer.split())
    adjusted = []
    for item in fields:
        if item.key == "model" and not item.value:
            item = replace(item, empty_text="입력 안 함")
        elif item.key == "mfds_product" and not item.value and typed_product:
            item = replace(item, value=typed_product, note="검색한 품목명")
        elif item.key == "company" and not item.value and typed_maker:
            item = replace(item, value=typed_maker, note="입력한 업체 (식약처 확인 전)")
        adjusted.append(item)
    udis = list(
        dict.fromkeys(
            str(getattr(record, "udi_di", "") or "").strip()
            for record in (getattr(identity, "records", ()) or ())
            if str(getattr(record, "udi_di", "") or "").strip()
        )
    ) if getattr(identity, "status", "") == "success" and getattr(identity, "match_type", "") in {"model", "udi", "permit"} else []
    if udis:
        adjusted.append(
            product_identity.IdentityField(
                "udi", "UDI-DI", udis[0], note=f"외 {len(udis) - 1}건" if len(udis) > 1 else ""
            )
        )
    return adjusted


def identity_header_html(result: MarketResult) -> str:
    return product_identity.identity_html(
        identity_header_fields(result), element_id="device-product-identity-v1"
    )


def permit_not_found_html(params: MarketParams) -> str:
    return not_found_html(
        f"식약처 등록 자료에서 품목명 ‘{params.product_name}’",
        (
            "식약처에 등록된 품목명 그대로 넣어 보세요 (예: 심장충격기)",
            "띄어쓰기와 철자를 확인하세요",
            "모델명은 비워 두고 품목명만 먼저 찾아도 됩니다",
        ),
    )


# ---------------------------------------------------------------- 나라장터 same-product trades

TRADE_TABLE_LIMIT = 10
LIVE_FAILURE_NOTE = "나라장터 실시간 확인에 실패해 최근 며칠 거래가 빠졌을 수 있습니다."


@dataclass(frozen=True)
class TradeSummary:
    """The same numbers 가격 조사 shows: default period (widened when empty), same-product (A/B)
    trades only, and only the most common unit in the median."""

    count: int
    median_price: Decimal | None
    low_price: Decimal | None
    high_price: Decimal | None
    main_unit: str | None
    period_label: str
    period_note: str | None
    reference_count: int
    other_unit_count: int
    trades: tuple[Any, ...] = ()
    entry_error_count: int = 0
    # Same-product trades of every period (before the period filter); 0 when not known.
    all_period_count: int = 0


def _positive_decimal(value: object) -> Decimal | None:
    try:
        number = Decimal(str(value))
    except Exception:
        return None
    return number if number.is_finite() and number > 0 else None


def build_trade_summary(track_b: Any, today: date | None = None) -> TradeSummary:
    today = today or kst_now().date()
    direct = strict_comparison_candidates(track_b)
    all_period_count = len(direct)
    references = (*category_reference_candidates(track_b), *reference_candidates(track_b))
    choice = result_summary.choose_period(
        [getattr(candidate, "transaction_date", None) for candidate in direct],
        requested=result_summary.DEFAULT_PERIOD_LABEL,
        user_chose=False,
        today=today,
    )
    direct = result_summary.filter_candidates(direct, choice.cutoff)
    references = result_summary.filter_candidates(references, choice.cutoff)
    split = result_summary.split_by_main_unit(direct)
    entry_errors = result_summary.filter_candidates(
        [candidate for candidate, _error in entry_error_candidates(track_b)], choice.cutoff
    )
    priced = [
        (candidate, price)
        for candidate in split.kept
        if (price := _positive_decimal(getattr(candidate, "price", None))) is not None
    ]
    prices = sorted(price for _, price in priced)
    ordered = sorted(
        (candidate for candidate, _ in priced),
        key=lambda candidate: str(getattr(candidate, "transaction_date", "") or ""),
        reverse=True,
    )
    return TradeSummary(
        count=len(prices),
        median_price=Decimal(str(median(prices))) if prices else None,
        low_price=prices[0] if prices else None,
        high_price=prices[-1] if prices else None,
        main_unit=split.main_unit,
        period_label=choice.label,
        period_note=choice.note,
        reference_count=len(references),
        other_unit_count=len(split.other),
        trades=tuple(ordered),
        entry_error_count=len(entry_errors),
        all_period_count=all_period_count,
    )


def trade_period_note(summary: TradeSummary) -> str:
    """'같은 제품 거래 390건 (전체 기간) · 최근 3년 267건': the one wording both the product block and
    the trade card use, so the two counts never look like a disagreement."""

    return result_layout.trade_count_note(
        all_period_count=summary.all_period_count or summary.count,
        period_count=summary.count,
        period_label=summary.period_label,
    )


def track_b_unavailable(track_b: Any) -> bool:
    return str(getattr(track_b, "status", "") or "") in {"unavailable", "not_ingested"}


def entry_error_note_html(summary: TradeSummary) -> str:
    """Says how many lines were left out of the price as 입력 오류 의심 (same wording as 가격 조사)."""

    if not summary.entry_error_count:
        return ""
    return (
        '<div class="pc-dev-hint">입력 오류 의심 '
        f"{summary.entry_error_count:,}건은 단가가 10원 이하로 적혀 있어 가격 계산에서 뺐습니다. "
        "가격 조사 화면에서 원문을 확인하세요.</div>"
    )


def _count_card_sub(summary: TradeSummary) -> str:
    sub = f"나라장터 · {summary.period_label}"
    if summary.all_period_count and summary.all_period_count != summary.count:
        sub += f" (전체 기간 {summary.all_period_count:,}건)"
    return sub


def trade_summary_cards(summary: TradeSummary) -> str:
    """Four equal cards: 같은 제품 거래, 가운데 값, 가격 범위, 참고 거래."""

    per = result_summary.per_unit_label(summary.main_unit).strip()
    count_card = metric_card_html(
        "같은 제품 거래",
        f"{summary.count:,}건",
        _count_card_sub(summary),
        TONE_OK if summary.count else TONE_MUTED,
    )
    if summary.count:
        middle = metric_card_html(
            "거래 가운데 값",
            won_text(summary.median_price),
            f"{per} 가격" if per else "1단위 가격",
            TONE_INFO,
        )
        spread = metric_card_html(
            "거래 가격 범위",
            f"{summary.low_price:,.0f} ~ {summary.high_price:,.0f}원",
            "가장 싼 거래 ~ 가장 비싼 거래",
            TONE_INFO,
        )
    else:
        middle = metric_card_html("거래 가운데 값", "—", "같은 제품 거래가 없어 계산하지 않음", TONE_MUTED)
        spread = metric_card_html("거래 가격 범위", "—", "같은 제품 거래가 없어 계산하지 않음", TONE_MUTED)
    reference = metric_card_html(
        "참고 거래",
        f"{summary.reference_count}건",
        "같은 제품인지 확인 전 · 가격 판단 제외",
        TONE_MUTED,
    )
    return f'<div class="pc-dev-trades">{metric_row_html([count_card, middle, spread, reference])}</div>'


def trade_rows(summary: TradeSummary, limit: int = TRADE_TABLE_LIMIT) -> list[dict[str, str]]:
    """Newest same-product trades with money written as '1,980,000원'."""

    per = result_summary.per_unit_label(summary.main_unit).strip() or "1단위"
    price_column = f"{per} 가격"
    rows: list[dict[str, str]] = []
    for candidate in summary.trades[:limit]:
        quantity = _positive_decimal(getattr(candidate, "quantity", None))
        unit = str(getattr(candidate, "unit", "") or "").strip()
        quantity_text = ""
        if quantity is not None:
            quantity_text = f"{quantity:,.0f}" + (f" {unit}" if unit and unit != "미확인" else "")
        rows.append(
            {
                "거래일": str(getattr(candidate, "transaction_date", "") or ""),
                price_column: won_text(getattr(candidate, "price", None)),
                "수량": quantity_text,
                "공급업체": str(getattr(candidate, "supplier", "") or ""),
                "수요기관": str(getattr(candidate, "demand_institution", "") or ""),
            }
        )
    return rows


def trade_supplier_rows(summary: TradeSummary, limit: int = 10) -> list[dict[str, str]]:
    """Suppliers named on the same-product trades, most trades first."""

    groups: dict[str, list[Any]] = {}
    for candidate in summary.trades:
        name = str(getattr(candidate, "supplier", "") or "").strip()
        if name:
            groups.setdefault(name, []).append(candidate)
    ordered = sorted(groups.items(), key=lambda pair: (-len(pair[1]), pair[0].casefold()))
    rows: list[dict[str, str]] = []
    for name, trades in ordered[:limit]:
        latest = max(str(getattr(trade, "transaction_date", "") or "") for trade in trades)
        rows.append(
            {
                "업체": name,
                "자료 출처": "나라장터 납품 기록",
                "설명": f"같은 제품 거래 {len(trades)}건" + (f" · 가장 최근 {latest}" if latest else ""),
            }
        )
    return rows


def trade_empty_html(params: MarketParams, summary: TradeSummary) -> str:
    name = f"{params.product_name} {params.model_name}".strip()
    extra = (
        f"<br>같은 제품인지 확인 전인 참고 거래 {summary.reference_count}건은 ‘가격 조사’에서 볼 수 있습니다."
        if summary.reference_count
        else ""
    )
    return notice_html(
        f"<b>나라장터에서 ‘{esc(name)}’과 같은 제품으로 확인된 거래를 찾지 못했습니다.</b>{extra}"
        "<br>다음을 해 보세요: 모델명 철자를 확인하세요 · ‘가격 조사’ 화면에서 같은 모델을 검색해 거래 기간을 넓혀 보세요",
        TONE_MUTED,
        icon="i",
    )


def trade_unavailable_html() -> str:
    return notice_html(
        "<b>나라장터 거래 자료를 아직 쓸 수 없습니다.</b> 잠시 뒤 다시 시도하거나 ‘가격 조사’에서 확인하세요. "
        "‘거래가 없다’는 뜻이 아닙니다.",
        TONE_WARN,
    )

SUPPLIER_NOTE = (
    "식약처 업체 허가·신고는 의료기기를 취급할 자격이 있다는 근거일 뿐, 특정 모델의 공식 총판·대리점이라는 뜻은 아닙니다."
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
        f"식약처 업체 허가·신고 자료에서 업체 ‘{company}’",
        (
            "회사 이름의 (주)·유한회사 같은 표기를 빼고 핵심 이름만 넣어 보세요",
            "영문 이름이면 한글 이름으로도 찾아 보세요",
        ),
    )


# ---------------------------------------------------------------- UDI-DI tab

def check_udi_di_input(text: str) -> tuple[str, str]:
    """(다듬은 UDI-DI, 문제 설명). 문제가 없으면 설명은 빈 문자열.

    UDI-DI는 보통 숫자 14자리(GTIN-14)입니다. 숫자만 넣었는데 14자리가 아니거나 0만 이어진 번호는
    식약처에 보내지 않고 바로 알려 줍니다. HIBC(+)·ICCBBA(=)처럼 문자가 섞인 번호는 그대로 통과시킵니다.
    """

    cleaned = "".join(str(text or "").split()).replace("-", "")
    if not cleaned:
        return "", "UDI-DI를 넣어 주세요."
    if cleaned.isascii() and cleaned.isdigit():
        if set(cleaned) == {"0"}:
            return cleaned, "0만 이어진 번호는 실제 UDI-DI가 아닙니다. 제품 라벨에 적힌 번호를 다시 확인해 주세요."
        if len(cleaned) != 14:
            return cleaned, (
                f"UDI-DI는 숫자 14자리입니다. 입력한 번호는 {len(cleaned)}자리입니다. "
                "제품 라벨에 적힌 번호를 다시 확인해 주세요."
            )
        return cleaned, ""
    if not cleaned.isascii() or not cleaned.replace("+", "").replace("=", "").isalnum():
        return cleaned, "UDI-DI에는 숫자와 영문자만 쓸 수 있습니다. 제품 라벨에 적힌 번호를 다시 확인해 주세요."
    if len(cleaned) < 8:
        return cleaned, "UDI-DI로 보기에는 너무 짧습니다. 제품 라벨에 적힌 번호를 다시 확인해 주세요."
    return cleaned, ""


def udi_match_note_html(udi_di: str, count: int) -> str:
    return notice_html(
        f"<b>입력한 UDI-DI ‘{esc(udi_di)}’와 번호가 똑같은 등록 {count}건입니다.</b> "
        "일부만 같은 번호는 보여주지 않습니다.",
        TONE_MUTED,
        icon="i",
    )


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


def udi_product_rows(records: Iterable[Any]) -> list[dict[str, str]]:
    return [
        {
            "UDI-DI": str(getattr(item, "udi_di", "") or ""),
            "품목명": str(getattr(item, "product_name", "") or ""),
            "모델명": str(getattr(item, "model_name", "") or ""),
            "허가번호": str(getattr(item, "permit_number", "") or ""),
            "허가일": str(getattr(item, "permit_date", "") or ""),
            "제조·수입업체": str(getattr(item, "company_name", "") or ""),
        }
        for item in records
    ]


UDI_NOT_CONNECTED_TEXT = (
    "<b>UDI-DI 조회 서비스가 아직 연결되지 않았습니다.</b> "
    "식약처 의료기기 통합정보시스템(UDI)에서 직접 확인하세요."
)
UDI_PORTAL_BUTTON = "식약처 의료기기 통합정보시스템(UDI)에서 확인"


def udi_not_connected_html() -> str:
    return notice_html(UDI_NOT_CONNECTED_TEXT, TONE_WARN)

def udi_not_found_html(udi_di: str) -> str:
    return not_found_html(
        f"식약처 UDI 자료에서 UDI-DI ‘{udi_di}’",
        (
            "번호를 한 글자씩 다시 확인하세요 (일부만 같아서는 찾지 않습니다)",
            "모델명으로는 UDI-DI를 찾을 수 없으니 제품 라벨이나 제조사 자료에서 번호를 확인하세요",
        ),
    )

