"""병원 구매정보 도우미 홈.

구매 업무(가격 조사 · 견적서 검토 · 의료기기 허가·안전)와 병원 경영 정보(병원 뉴스 · 병원 경영 비교)로
들어가는 한 화면. 숫자는 모두 이 세션에서 실제로 확인된 것만 보여 주고, 아직 연계되지 않은 자료는 그렇게 말한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st
from streamlit.errors import StreamlitPageNotFoundError

from purchase_price.config import get_settings
from purchase_price.services import hospital_benchmark, hospital_report
from purchase_price.services import news_radar as radar
from purchase_price.services import news_radar_index as nri
from purchase_price.services.hospital_master import PEER_GROUP_LABELS, PEER_REGION
from purchase_price.services.news_radar import NewsRadarState, seoul_time_text, summarize
from purchase_price.ui.runtime_secrets import hydrate_streamlit_runtime_secrets
from purchase_price.ui.theme import (
    APP_NAME,
    TONE_INFO,
    TONE_MUTED,
    TONE_OK,
    TONE_WARN,
    esc,
    metric_card_html,
    metric_row_html,
    page_header_html,
)

hydrate_streamlit_runtime_secrets()

NEWS_STATE_KEY = "news_radar_state"
# Written by the 가격 조사 page (pages/1_대시보드.py _remember_search): [(검색어, "HH:MM"), ...], newest first.
RECENT_SEARCHES_KEY = "home_recent_searches"
RECENT_SHOWN = 3
# Runtime marker (UX v1.1 I0-a): the price card shows this session's recent searches.
HOME_RECENT_SEARCHES_V1 = True
# Runtime marker (UX v1.1 I0-b): the news card counts the auto-collected 주요 이슈 (H1 index) and the
# management card shows the newest 경영 브리핑 first line (H2) instead of session-only numbers.
HOME_TRACK_H_CARDS_V1 = True
HOME_SUBTITLE = "구매 업무와 병원 경영 정보를 한곳에서 확인합니다."
# The stored news list is re-read at most this often (same as the 병원 뉴스 page).
NEWS_INDEX_CACHE_SECONDS = 300
# 우리 병원 for the home briefing; the 병원 경영 비교 page opens on the same hospital and peer group.
BRIEFING_TARGET_ID = "H-BUSAN-PAIK"
BRIEFING_PEER_KIND = PEER_REGION

# (제목, 설명, 이동할 페이지, 아이콘). 사이드 메뉴의 이름과 같게 둔다.
PURCHASE_CARDS = (
    (
        "가격 조사",
        "제품명·모델명으로 나라장터 거래가격과 공급업체를 찾습니다.",
        "pages/1_대시보드.py",
        "🔎",
    ),
    (
        "견적서 검토",
        "견적서 파일을 올리면 품목마다 나라장터 거래가격과 나란히 비교합니다.",
        "pages/2_견적_검토.py",
        "📋",
    ),
    (
        "의료기기 허가·안전",
        "식약처 허가, 회수·판매중지, 공급업체, UDI-DI를 확인합니다.",
        "pages/4_의료기기_조회.py",
        "🏥",
    ),
)
MANAGEMENT_CARDS = (
    (
        "병원 뉴스",
        "등록한 키워드로 병원·정책·경쟁기관 기사를 자동으로 확인합니다.",
        "pages/20_병원_News_Radar.py",
        "📰",
    ),
    (
        "병원 경영 비교",
        "공개 회계·병상 자료로 병원을 같은 기준에서 비교합니다.",
        "pages/21_병원_경영_Benchmark.py",
        "📈",
    ),
)

HOME_CSS = """
<style>
.pc-home-metrics .pc-metrics {grid-template-columns:repeat(3,minmax(0,1fr));}
.pc-home-group {font-size:17px; font-weight:700; color:var(--pc-navy); margin:26px 0 12px 0;}
.pc-home-recent {font-size:13px; color:#5B6C82; margin:-4px 0 10px 0; line-height:1.8; word-break:keep-all;}
.pc-home-recent a {color:#1D4ED8; font-weight:700; text-decoration:none; white-space:nowrap;}
.pc-home-recent a:focus-visible {outline:2px solid #376FD0; outline-offset:2px; border-radius:3px;}
.pc-home-card h4 {font-size:16px; font-weight:800; color:var(--pc-navy); margin:2px 0 6px 0;}
.pc-home-card p {font-size:13px; color:#5B6C82; line-height:1.6; margin:0 0 6px 0; min-height:42px; word-break:keep-all;}
[data-testid="stColumn"] > [data-testid="stVerticalBlock"]:has(.pc-home-card) {
  position:relative;
  transition:border-color 140ms ease, box-shadow 140ms ease, transform 140ms ease;
}
[data-testid="stColumn"] > [data-testid="stVerticalBlock"]:has(.pc-home-card):hover {
  border-color:#7FA6E8;
  box-shadow:0 8px 20px rgba(25, 62, 116, 0.10);
  transform:translateY(-1px);
}
[data-testid="stColumn"] > [data-testid="stVerticalBlock"]:has(.pc-home-card):focus-within {
  border-color:#376FD0;
  box-shadow:0 0 0 3px rgba(55, 111, 208, 0.18);
}
[data-testid="stColumn"] > [data-testid="stVerticalBlock"]:has(.pc-home-card) [data-testid="stElementContainer"]:has(> [data-testid="stPageLink"]) {
  position:absolute;
  inset:0;
  z-index:2;
}
[data-testid="stColumn"] > [data-testid="stVerticalBlock"]:has(.pc-home-card) [data-testid="stPageLink"] {
  width:100%;
  height:100%;
}
[data-testid="stColumn"] > [data-testid="stVerticalBlock"]:has(.pc-home-card) [data-testid="stPageLink"] > div,
[data-testid="stColumn"] > [data-testid="stVerticalBlock"]:has(.pc-home-card) [data-testid="stPageLink"] a {
  width:100%;
  height:100%;
  min-height:100%;
  border:0;
  background:transparent;
  font-size:0;
}
[data-testid="stColumn"] > [data-testid="stVerticalBlock"]:has(.pc-home-card) [data-testid="stPageLink"] a > span {
  position:absolute;
  width:1px;
  height:1px;
  padding:0;
  margin:-1px;
  overflow:hidden;
  clip:rect(0, 0, 0, 0);
  white-space:nowrap;
  border:0;
}
[data-testid="stColumn"] > [data-testid="stVerticalBlock"]:has(.pc-home-card) [data-testid="stPageLink"] a::after {
  content:"→";
  position:absolute;
  right:16px;
  bottom:13px;
  color:#376FD0;
  font-size:20px;
  line-height:1;
}
[data-testid="stColumn"] > [data-testid="stVerticalBlock"]:has(.pc-home-card) [data-testid="stPageLink"] a:hover {
  background:transparent;
}
</style>
"""


def recent_searches(state: object) -> list[tuple[str, str]]:
    """(검색어, 시각) pairs the 가격 조사 page stored in this session; anything malformed is skipped."""

    items = []
    for item in state if isinstance(state, (list, tuple)) else ():
        if isinstance(item, (list, tuple)) and len(item) == 2 and str(item[0]).strip():
            items.append((str(item[0]).strip(), str(item[1] or "").strip()))
    return items


def recent_links_html(items: list[tuple[str, str]]) -> str:
    """'최근 조사 · PNB-704 (14:05) · …' as links that reopen the result (root URL = 가격 조사)."""

    from urllib.parse import quote

    if not items:
        return ""
    links = " · ".join(
        f'<a href="./?q={esc(quote(query))}" target="_self">{esc(query)}</a>'
        + (f" ({esc(when)})" if when else "")
        for query, when in items[:RECENT_SHOWN]
    )
    return f'<div class="pc-home-recent" id="home-recent-searches-v1">최근 조사 · {links}</div>'


def news_overview(
    index: nri.NewsRadarIndex, groups: tuple[radar.KeywordGroup, ...], *, now: datetime
) -> tuple[int, int, datetime | None]:
    """(최근 3일 주요 이슈 수, 오늘 제목 일치 기사 수, 마지막 자동 확인 시각) from the stored list.

    Same window as the 병원 뉴스 page (latest article within 72 hours). Only issues that more than one
    article reported count here — a single article is a cluster too, and counting those would show
    dozens of "주요 이슈". Today's count covers title-matching articles only. The home has no group
    toggles, so every group counts.
    """

    keywords = [keyword for group in groups for keyword in group.keywords]
    issue_count = sum(
        1 for issue in radar.recent_news_issues(index.issues, now=now) if issue.article_count >= 2
    )
    relevant = (
        ranked.entry
        for ranked in radar.rank_entries(index.items.values(), keywords, include_ignored=True)
        if ranked.relevant
    )
    today_count = summarize(relevant, today=radar.to_seoul(now).date()).today
    last_run = index.last_run
    return issue_count, today_count, last_run.finished_at if last_run is not None else None


def briefing_line(briefing: object) -> str:
    """The one sentence the home shows under the briefing heading: the hold/status text, else the
    largest difference. Never a judgement — the briefing itself is built without them."""

    status = getattr(briefing, "status", None)
    if status:
        return str(status)
    differences = getattr(briefing, "differences", ())
    return str(differences[0].text) if differences else "허용폭을 넘는 차이가 없습니다."


def _news_store() -> nri.NewsRadarStore | None:
    try:
        return nri.resolve_store(get_settings())
    except Exception:  # broken settings must not take the home down
        return None


@st.cache_data(ttl=NEWS_INDEX_CACHE_SECONDS, show_spinner=False)
def _load_news_overview(source: str) -> tuple[int, int, datetime | None] | tuple[()] | None:
    """Stored-list numbers; ``()`` when no list has been collected yet; None when it cannot be read.
    ``source`` only keys the cache."""

    del source
    store = _news_store()
    if store is None:
        return None
    try:
        index = store.read_index()
    except Exception:
        return None
    if index is None:
        return ()
    return news_overview(index, radar.load_keyword_groups(), now=datetime.now(UTC))


@st.cache_data(show_spinner=False)
def _latest_briefing() -> tuple[str, int, int, str] | None:
    """(병원 이름, 회계연도, 비교병원 수, 한 줄) for 우리 병원 vs 지역 비교군 on the newest 회계연도.

    None when the committed 회계정보 공시 data is missing. The sentence comes from the same
    ``ManagementBriefing`` the 병원 경영 비교 page and its downloads use.
    """

    try:
        data = hospital_benchmark.load_benchmark_data()
        years = data.fiscal_years
        target = data.master.get(BRIEFING_TARGET_ID) or next(
            (hospital for hospital in data.master.hospitals if hospital.group == "core"), None
        )
        if not years or target is None:
            return None
        report = hospital_report.build_report(data, target, BRIEFING_PEER_KIND, max(years))
    except Exception:
        return None
    briefing = report.briefing
    return target.short_name, briefing.fiscal_year, briefing.peer_count, briefing_line(briefing)


def _page_link(path: str, label: str, icon: str) -> None:
    """Link to a sibling page; when this file runs on its own (startup smoke) just say so."""

    try:
        st.page_link(path, label=label, icon=icon, width="stretch")
    except StreamlitPageNotFoundError:
        st.caption(f"{label} (홈 화면에서 열 수 있습니다)")


def _card_row(cards: tuple[tuple[str, str, str, str], ...], per_row: int = 3) -> None:
    columns = st.columns(per_row)
    for column, (title, text, path, icon) in zip(columns, cards, strict=False):
        with column, st.container(border=True, height=142):
            st.markdown(
                f'<div class="pc-home-card"><h4>{esc(title)}</h4><p>{esc(text)}</p></div>',
                unsafe_allow_html=True,
            )
            _page_link(path, f"{title} 화면으로 이동", icon)


st.markdown(HOME_CSS, unsafe_allow_html=True)
st.markdown(page_header_html(APP_NAME, subtitle=HOME_SUBTITLE), unsafe_allow_html=True)

recent = recent_searches(st.session_state.get(RECENT_SEARCHES_KEY))
naver_ready = get_settings().naver_configured
news_store = _news_store()

if news_store is not None:
    # Auto-collected list (H1): the same 주요 이슈 the 병원 뉴스 page shows at the top.
    overview = _load_news_overview(news_store.describe())
    if overview is None:
        news_card = metric_card_html(
            "병원 뉴스 · 최근 3일 주요 이슈",
            "확인 안 됨",
            "자동 수집 자료를 불러오지 못했습니다. 병원 뉴스 화면에서 다시 확인해 주세요.",
            TONE_WARN,
        )
    elif overview == ():
        news_card = metric_card_html(
            "병원 뉴스 · 최근 3일 주요 이슈",
            "0건",
            "아직 자동 수집 자료가 없습니다. 다음 자동 확인 뒤 표시됩니다.",
            TONE_MUTED,
        )
    else:
        issue_count, today_count, last_checked = overview
        news_card = metric_card_html(
            "병원 뉴스 · 최근 3일 주요 이슈",
            f"{issue_count}건",
            f"기사 2건 이상 묶인 이슈 · 오늘 기사 {today_count}건 · 자동 확인 {seoul_time_text(last_checked)}",
            TONE_OK if issue_count else TONE_MUTED,
        )
else:
    # No stored list (no R2 and no local file): fall back to what this session checked by hand.
    radar_state = st.session_state.get(NEWS_STATE_KEY)
    if not isinstance(radar_state, NewsRadarState):
        radar_state = NewsRadarState()
    radar_summary = summarize(radar_state.entries.values())
    if radar_state.last_scan_at is None:
        news_sub = (
            "이 세션에서 아직 기사를 확인하지 않았습니다."
            if naver_ready
            else "뉴스 검색 연결 설정이 아직 없습니다."
        )
        news_tone = TONE_MUTED if naver_ready else TONE_WARN
    else:
        news_sub = f"마지막 확인 {seoul_time_text(radar_state.last_scan_at)}"
        news_tone = TONE_OK
    news_card = metric_card_html("병원 뉴스 · 새 관심기사", f"{radar_summary.unread}건", news_sub, news_tone)

latest = _latest_briefing()
if latest is None:
    management_card = metric_card_html(
        "병원 경영 비교 · 최신 경영 브리핑",
        "자료 없음",
        "회계공시 자료가 아직 올라와 있지 않습니다.",
        TONE_WARN,
    )
else:
    target_name, fiscal_year, peer_count, line = latest
    management_card = metric_card_html(
        f"병원 경영 비교 · {target_name} 브리핑",
        f"{fiscal_year}년 공시 기준",
        f"{PEER_GROUP_LABELS.get(BRIEFING_PEER_KIND, BRIEFING_PEER_KIND)} {peer_count}곳 · {line}",
        TONE_WARN if line.startswith("기준 병원") else TONE_INFO,
    )

st.markdown(
    '<div class="pc-home-group">오늘의 현황</div>'
    '<div class="pc-home-metrics">'
    + metric_row_html(
        [
            news_card,
            management_card,
            (
                metric_card_html(
                    "가격 조사 · 이번 접속 최근 조사",
                    recent[0][0],
                    f"{recent[0][1]} 조사 · 모두 {len(recent)}건" if recent[0][1] else f"모두 {len(recent)}건",
                    TONE_OK,
                )
                if recent
                else metric_card_html(
                    "가격 조사", "제품·견적 검색", "나라장터 거래가격과 식약처 자료로 확인합니다.", TONE_INFO
                )
            ),
        ]
    )
    + "</div>",
    unsafe_allow_html=True,
)

st.markdown('<div class="pc-home-group">구매 업무</div>', unsafe_allow_html=True)
if recent:
    st.markdown(recent_links_html(recent), unsafe_allow_html=True)
_card_row(PURCHASE_CARDS)

st.markdown('<div class="pc-home-group">병원 경영 정보</div>', unsafe_allow_html=True)
_card_row(MANAGEMENT_CARDS)
