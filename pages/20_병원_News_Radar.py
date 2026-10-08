"""병원 News Radar (Phase 1 기본 화면).

NAVER 뉴스 검색 결과는 '새 기사가 있는지'를 확인하고 제목·시간·링크를 그대로 보여 주는 데만 쓴다.
검색 결과를 AI 요약·분석에 넘기지 않는다 (2026-09-07 네이버 검색 API 이용약관).
키워드 그룹과 읽음 상태는 이 세션 안에서만 유지된다.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import datetime

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from purchase_price.clients.naver_news import NaverNewsClient, NaverNewsClientError
from purchase_price.config import get_settings
from purchase_price.services import news_radar as radar
from purchase_price.ui.runtime_secrets import hydrate_streamlit_runtime_secrets

hydrate_streamlit_runtime_secrets()

NEWS_STATE_KEY = "news_radar_state"
GROUP_TOGGLE_PREFIX = "news_radar_group::"
STATUS_WIDGET_PREFIX = "news_radar_status::"
STATUS_OPTIONS = tuple(radar.STATUS_LABELS)
PAGE_SIZE = 50


def _secret(name: str) -> str | None:
    value = os.getenv(name)
    if value and value.strip():
        return value.strip()
    try:
        root: Mapping[str, object] = st.secrets
        candidate = root.get(name)
        if candidate is None:
            table = root.get("naver")
            if isinstance(table, Mapping):
                candidate = table.get(name.removeprefix("NAVER_").lower())
    except (FileNotFoundError, KeyError, StreamlitSecretNotFoundError):
        return None
    return str(candidate).strip() if candidate else None


def _naver_credentials() -> tuple[str, str] | None:
    settings = get_settings()
    client_id = settings.naver_client_id or _secret("NAVER_CLIENT_ID")
    client_secret = settings.naver_client_secret or _secret("NAVER_CLIENT_SECRET")
    if client_id and client_secret:
        return client_id, client_secret
    return None


def _state() -> radar.NewsRadarState:
    state = st.session_state.get(NEWS_STATE_KEY)
    if not isinstance(state, radar.NewsRadarState):
        state = radar.NewsRadarState()
        st.session_state[NEWS_STATE_KEY] = state
    return state


def _group_enabled(group: radar.KeywordGroup) -> bool:
    return bool(st.session_state.get(GROUP_TOGGLE_PREFIX + group.key, group.enabled))


def _apply_status(entry_id: str) -> None:
    _state().set_status(entry_id, st.session_state[STATUS_WIDGET_PREFIX + entry_id])


def _time_text(value: datetime | None) -> str:
    return value.astimezone().strftime("%m-%d %H:%M") if value else "시간 확인 안 됨"


groups = radar.load_keyword_groups()
state = _state()
credentials = _naver_credentials()

st.title("병원 News Radar")
st.caption("등록한 키워드로 새 기사를 자동 확인합니다. 기사 제목·시간·링크를 그대로 보여 주고 요약하지 않습니다.")

summary = radar.summarize(state.entries.values())
m1, m2, m3, m4 = st.columns(4)
m1.metric("오늘", f"{summary.today}건")
m2.metric("이번 주", f"{summary.this_week}건")
m3.metric("중요 표시", f"{summary.important}건")
m4.metric("아직 안 읽음", f"{summary.unread}건")

with st.expander("관심 키워드 관리", expanded=not state.entries):
    st.caption("그룹 단위로 켜고 끌 수 있습니다. 알림 방식은 다음 단계에서 메일·메신저와 연결합니다.")
    for group in groups:
        toggle_col, list_col = st.columns([1, 3])
        with toggle_col:
            st.toggle(group.name, value=group.enabled, key=GROUP_TOGGLE_PREFIX + group.key)
        with list_col:
            st.write(
                " · ".join(f"{keyword.text} ({keyword.alert_label})" for keyword in group.keywords)
            )

enabled_overrides = {group.key: _group_enabled(group) for group in groups}
keywords = radar.active_keywords(groups, enabled_overrides)

if credentials is None:
    st.info(
        "뉴스 검색 연결 설정이 없습니다. NAVER API HUB에서 뉴스 검색 API를 켠 Application의 "
        "NAVER_CLIENT_ID 와 NAVER_CLIENT_SECRET 을 운영 설정에 넣으면 바로 새 기사 확인을 "
        "시작할 수 있습니다. 키워드 관리는 지금도 가능합니다."
    )
else:
    action_col, note_col = st.columns([1, 3])
    with action_col:
        run_scan = st.button(
            f"새 기사 확인 ({len(keywords)}개 키워드)", type="primary", disabled=not keywords
        )
    with note_col:
        if state.last_scan_at is not None:
            st.caption(
                f"마지막 확인 {state.last_scan_at:%m-%d %H:%M} · 새로 찾은 기사 {state.last_new_count}건"
            )
    if run_scan:
        client_id, client_secret = credentials
        settings = get_settings()
        with st.spinner("키워드별로 새 기사를 확인하는 중입니다."):
            try:
                with NaverNewsClient(
                    client_id,
                    client_secret,
                    api_style=settings.naver_api_style,
                    base_url=settings.naver_news_base_url,
                    timeout_seconds=settings.naver_request_timeout_seconds,
                ) as client:
                    new_count = radar.scan_keywords(
                        state,
                        keywords,
                        lambda text, display: client.search(text, display=display),
                    )
            except NaverNewsClientError as exc:
                st.error(f"뉴스 검색에 실패했습니다: {exc}")
            else:
                st.success(f"새 기사 {new_count}건을 찾았습니다.")
                st.rerun()

failed_logs = [log for log in state.logs if not log.ok and log.scanned_at == state.last_scan_at]
if failed_logs:
    st.warning(
        "일부 키워드는 확인하지 못했습니다: "
        + ", ".join(f"{log.keyword} ({log.error})" for log in failed_logs)
    )

st.subheader("오늘의 병원동향")
filter_col, ignored_col = st.columns([2, 1])
with filter_col:
    keyword_filter = st.multiselect(
        "키워드로 좁혀 보기", [keyword.text for keyword in keywords], placeholder="전체 키워드"
    )
with ignored_col:
    show_ignored = st.checkbox("관심없음으로 표시한 기사도 보기", value=False)
entries = radar.sorted_entries(state.entries.values(), include_ignored=show_ignored)
if keyword_filter:
    entries = [entry for entry in entries if set(entry.keywords) & set(keyword_filter)]

if not entries:
    st.write("아직 확인된 기사가 없습니다. 위의 새 기사 확인 버튼을 누르면 여기에 쌓입니다.")

# Hundreds of cards make the page sluggish; show the newest batch and let the reader extend it.
page_size = st.session_state.setdefault("news_radar_page_size", PAGE_SIZE)
visible_entries = entries[:page_size]
if len(entries) > len(visible_entries):
    st.caption(f"최신 {len(visible_entries)}건을 보여 줍니다 (전체 {len(entries)}건).")

for entry in visible_entries:
    with st.container(border=True):
        head_col, body_col, status_col = st.columns([1, 4, 1.2])
        with head_col:
            if entry.status == radar.STATUS_NEW:
                st.markdown(f"**NEW** {_time_text(entry.published_at)}")
            else:
                st.markdown(_time_text(entry.published_at))
            st.caption(" · ".join(entry.keywords))
        with body_col:
            st.markdown(f"**{entry.title}**")
            st.caption(f"{entry.source_domain or '출처 확인 안 됨'} | {_time_text(entry.published_at)}")
            link_col, naver_col = st.columns(2)
            with link_col:
                st.link_button("원문보기", entry.url)
            with naver_col:
                if entry.naver_link and entry.naver_link != entry.url:
                    st.link_button("네이버에서 보기", entry.naver_link)
        with status_col:
            widget_key = STATUS_WIDGET_PREFIX + entry.article_id
            if widget_key not in st.session_state:
                st.session_state[widget_key] = entry.status
            st.selectbox(
                "상태",
                STATUS_OPTIONS,
                key=widget_key,
                format_func=lambda value: radar.STATUS_LABELS[value],
                on_change=_apply_status,
                args=(entry.article_id,),
            )

if len(entries) > len(visible_entries):
    if st.button(f"기사 {PAGE_SIZE}건 더 보기"):
        st.session_state["news_radar_page_size"] = page_size + PAGE_SIZE
        st.rerun()
