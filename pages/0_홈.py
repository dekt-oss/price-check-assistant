"""병원 구매정보 도우미 홈.

구매 업무(가격 조사 · 견적서 검토 · 의료기기 허가·안전)와 병원 경영 정보(병원 뉴스 · 병원 경영 비교)로
들어가는 한 화면. 숫자는 모두 이 세션에서 실제로 확인된 것만 보여 주고, 아직 연계되지 않은 자료는 그렇게 말한다.
"""

from __future__ import annotations

import streamlit as st
from streamlit.errors import StreamlitPageNotFoundError

from purchase_price.config import get_settings
from purchase_price.services.hospital_master import load_hospital_master
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
HOME_SUBTITLE = "구매 업무와 병원 경영 정보를 한곳에서 확인합니다."

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
.pc-home-card h4 {font-size:16px; font-weight:800; color:var(--pc-navy); margin:2px 0 6px 0;}
.pc-home-card p {font-size:13px; color:#5B6C82; line-height:1.6; margin:0 0 6px 0; min-height:42px; word-break:keep-all;}
</style>
"""


def _page_link(path: str, label: str, icon: str) -> None:
    """Link to a sibling page; when this file runs on its own (startup smoke) just say so."""

    try:
        st.page_link(path, label=label, icon=icon)
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
            _page_link(path, f"{title} 열기", icon)


st.markdown(HOME_CSS, unsafe_allow_html=True)
st.markdown(page_header_html(APP_NAME, subtitle=HOME_SUBTITLE), unsafe_allow_html=True)

radar_state = st.session_state.get(NEWS_STATE_KEY)
if not isinstance(radar_state, NewsRadarState):
    radar_state = NewsRadarState()
radar_summary = summarize(radar_state.entries.values())
hospital_count = len(load_hospital_master().hospitals)
naver_ready = get_settings().naver_configured

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

st.markdown(
    '<div class="pc-home-group">오늘의 현황</div>'
    '<div class="pc-home-metrics">'
    + metric_row_html(
        [
            metric_card_html("병원 뉴스 · 새 관심기사", f"{radar_summary.unread}건", news_sub, news_tone),
            metric_card_html(
                "병원 경영 비교 · 비교 가능한 병원",
                f"{hospital_count}개",
                "경영 공시 자료는 아직 연계 전입니다.",
                TONE_INFO,
            ),
            metric_card_html(
                "가격 조사", "제품·견적 검색", "나라장터 거래가격과 식약처 자료로 확인합니다.", TONE_INFO
            ),
        ]
    )
    + "</div>",
    unsafe_allow_html=True,
)

st.markdown('<div class="pc-home-group">구매 업무</div>', unsafe_allow_html=True)
_card_row(PURCHASE_CARDS)

st.markdown('<div class="pc-home-group">병원 경영 정보</div>', unsafe_allow_html=True)
_card_row(MANAGEMENT_CARDS)
