"""AI Hospital Intelligence 통합 홈 (Phase 1).

세 모듈(구매가격 조사 · 병원 News Radar · 병원 경영 Benchmark)로 들어가는 한 화면.
숫자는 모두 이 세션에서 실제로 확인된 것만 보여 주고, 아직 연계되지 않은 자료는 그렇게 말한다.
"""

from __future__ import annotations

import streamlit as st
from streamlit.errors import StreamlitPageNotFoundError

from purchase_price.config import get_settings
from purchase_price.services.hospital_master import load_hospital_master
from purchase_price.services.news_radar import NewsRadarState, summarize
from purchase_price.ui.runtime_secrets import hydrate_streamlit_runtime_secrets

hydrate_streamlit_runtime_secrets()

NEWS_STATE_KEY = "news_radar_state"


def _page_link(path: str, label: str, icon: str) -> None:
    """Link to a sibling page; when this file runs on its own (startup smoke) just say so."""

    try:
        st.page_link(path, label=label, icon=icon)
    except StreamlitPageNotFoundError:
        st.caption(f"{label} (홈 화면에서 열 수 있습니다)")


st.title("AI Hospital Intelligence")
st.caption("병원 관리·경영 업무에 필요한 외부 정보를 한곳에서 확인합니다.")

st.subheader("오늘의 현황")

radar_state = st.session_state.get(NEWS_STATE_KEY)
if not isinstance(radar_state, NewsRadarState):
    radar_state = NewsRadarState()
radar_summary = summarize(radar_state.entries.values())
hospital_count = len(load_hospital_master().hospitals)
naver_ready = get_settings().naver_configured

col_news, col_bench, col_price = st.columns(3)
with col_news:
    st.metric("새 관심기사", f"{radar_summary.unread}건")
    if radar_state.last_scan_at is None:
        st.caption(
            "이 세션에서 아직 기사를 확인하지 않았습니다."
            if naver_ready
            else "뉴스 검색 연결 설정이 아직 없습니다."
        )
    else:
        st.caption(f"마지막 확인 {radar_state.last_scan_at:%m-%d %H:%M}")
with col_bench:
    st.metric("비교 가능한 병원", f"{hospital_count}개")
    st.caption("경영 공시 자료는 아직 연계 전입니다.")
with col_price:
    st.metric("구매가격 조사", "제품·견적 검색")
    st.caption("나라장터 거래가격과 식약처 자료로 확인합니다.")

st.divider()

menu_price, menu_news, menu_bench = st.columns(3)
with menu_price:
    st.markdown("#### 구매가격 조사")
    st.write("제품명·모델명으로 공개 거래가격과 공급업체를 찾고 견적을 검토합니다.")
    _page_link("pages/1_대시보드.py", "구매가격 조사 열기", "🔎")
with menu_news:
    st.markdown("#### 병원 News Radar")
    st.write("등록한 키워드로 병원·정책·경쟁기관 기사를 자동으로 확인합니다.")
    _page_link("pages/20_병원_News_Radar.py", "병원 News Radar 열기", "📰")
with menu_bench:
    st.markdown("#### 병원 경영 Benchmark")
    st.write("공개 회계·병상 자료로 병원을 같은 기준에서 비교합니다.")
    _page_link("pages/21_병원_경영_Benchmark.py", "병원 경영 Benchmark 열기", "📈")
