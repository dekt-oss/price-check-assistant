"""병원 News Radar.

NAVER 뉴스 검색 결과는 '새 기사가 있는지'를 확인하고 제목·시간·링크를 그대로 보여 주는 데만 쓴다.
검색 결과를 AI 요약·분석에 넘기지 않는다 (2026-09-07 네이버 검색 API 이용약관).

Phase 2: a GitHub Actions job collects every 30 minutes into R2 (news/v1/index.json.gz) and this
page reads it (cached 5 minutes). NEWS_RADAR_INDEX_PATH points the page at a local file instead.
Reading statuses are saved to news/v1/status.json when the credentials allow writing; otherwise
they stay in this session. Without R2 or a local file the page behaves as in Phase 1.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from purchase_price.clients.naver_news import NaverNewsClient, NaverNewsClientError
from purchase_price.config import get_settings
from purchase_price.services import news_radar as radar
from purchase_price.services import news_radar_index as nri
from purchase_price.services import news_subscriptions as subs
from purchase_price.ui.runtime_secrets import hydrate_streamlit_runtime_secrets

hydrate_streamlit_runtime_secrets()


def _reload_retained_modules() -> None:
    """Streamlit Cloud keeps imported modules across a redeploy; reload the news services when the
    retained copy predates title relevance (2026-10-09) so the page never runs on an old object."""

    import importlib
    import sys

    if hasattr(radar, "rank_entries") and hasattr(radar.Keyword, "exclude_terms"):
        return
    for name in (
        "purchase_price.clients.naver_news",
        "purchase_price.services.news_radar",
        "purchase_price.services.news_radar_index",
        "purchase_price.services.news_alerts",
    ):
        module = sys.modules.get(name)
        if module is not None:
            importlib.reload(module)


_reload_retained_modules()

NEWS_STATE_KEY = "news_radar_state"
GROUP_TOGGLE_PREFIX = "news_radar_group::"
STATUS_WIDGET_PREFIX = "news_radar_status::"
STATUS_OPTIONS = tuple(radar.STATUS_LABELS)
PAGE_SIZE = 50
SESSION_STATUSES_KEY = "news_radar_session_statuses"
SAVED_STATUSES_KEY = "news_radar_saved_statuses"
STATUS_SESSION_ONLY_KEY = "news_radar_status_session_only"
INDEX_CACHE_SECONDS = 300
STALE_AFTER = timedelta(hours=1)


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


SUBSCRIBER_ENV_NAMES = (
    "SUBSCRIBER_R2_BUCKET",
    "SUBSCRIBER_R2_ACCESS_KEY_ID",
    "SUBSCRIBER_R2_SECRET_ACCESS_KEY",
    "R2_ENDPOINT_URL",
    "R2_ACCOUNT_ID",
)


def _subscriber_store() -> subs.SubscriberStore | None:
    local = _secret("SUBSCRIBER_STORE_PATH")
    if local:
        return subs.LocalSubscriberStore(local)
    env = {name: value for name in SUBSCRIBER_ENV_NAMES if (value := _secret(name))}
    try:
        return subs.R2SubscriberStore.from_env(env)
    except Exception:  # noqa: BLE001 - a broken store must not break the news page
        return None


def _handle_subscription_links(store: subs.SubscriberStore | None) -> None:
    """``?confirm=`` and ``?unsubscribe=`` links from the emails."""

    params = st.query_params
    for name in ("confirm", "unsubscribe"):
        token = params.get(name)
        if not token:
            continue
        if store is None:
            st.warning("이메일 알림 저장소가 아직 연결되지 않아 처리하지 못했습니다. 관리자에게 알려 주세요.")
        else:
            try:
                if name == "confirm":
                    person = subs.confirm(store, token)
                    chosen = ", ".join(subs.PREF_LABELS[p] for p in person.prefs)
                    st.success(f"{person.email} 주소로 알림을 보내 드립니다: {chosen}")
                else:
                    st.success(subs.unsubscribe(store, token))
            except subs.SubscriptionError as exc:
                st.warning(str(exc))
        del st.query_params[name]


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


def _store() -> nri.NewsRadarStore | None:
    try:
        return nri.resolve_store(get_settings())
    except Exception:  # broken settings must not take the page down
        return None


@st.cache_data(ttl=INDEX_CACHE_SECONDS, show_spinner=False)
def _load_index(source: str) -> tuple[nri.NewsRadarIndex | None, bool]:
    """(stored list or None, read failed). ``source`` only keys the cache."""

    del source
    store = _store()
    if store is None:
        return None, False
    try:
        return store.read_index(), False
    except Exception:
        return None, True


def _saved_statuses(store: nri.NewsRadarStore | None) -> dict[str, dict]:
    if SAVED_STATUSES_KEY not in st.session_state:
        loaded: dict[str, dict] = {}
        if store is not None:
            try:
                loaded = store.read_statuses()
            except Exception:
                loaded = {}
        st.session_state[SAVED_STATUSES_KEY] = loaded
    return st.session_state[SAVED_STATUSES_KEY]


def _session_statuses() -> dict[str, str]:
    return st.session_state.setdefault(SESSION_STATUSES_KEY, {})


def _save_status(entry_id: str, status: str) -> None:
    """Read-modify-write the small status object; any failure means statuses stay in this session."""

    store = _store()
    if store is None or st.session_state.get(STATUS_SESSION_ONLY_KEY):
        return
    index, _ = _load_index(store.describe())
    valid = {entry_id, *(index.items if index is not None else ())}
    now = datetime.now(UTC)
    try:
        statuses = nri.prune_statuses(store.read_statuses(), valid)
        nri.set_status(statuses, entry_id, status, now=now)
        store.write_statuses(statuses, now=now)
    except Exception:
        st.session_state[STATUS_SESSION_ONLY_KEY] = True
        return
    st.session_state[SAVED_STATUSES_KEY] = statuses


def _group_enabled(group: radar.KeywordGroup) -> bool:
    return bool(st.session_state.get(GROUP_TOGGLE_PREFIX + group.key, group.enabled))


def _apply_status(entry_id: str) -> None:
    status = st.session_state[STATUS_WIDGET_PREFIX + entry_id]
    _state().set_status(entry_id, status)
    _session_statuses()[entry_id] = status
    _save_status(entry_id, status)


def _time_text(value: datetime | None) -> str:
    return radar.seoul_time_text(value)


groups = radar.load_keyword_groups()
state = _state()
credentials = _naver_credentials()
store = _store()
stored_index, index_failed = _load_index(store.describe()) if store is not None else (None, False)
nri.seed_state(
    state, stored_index, _saved_statuses(store), session_statuses=_session_statuses()
)

subscriber_store = _subscriber_store()
_handle_subscription_links(subscriber_store)

st.title("병원 News Radar")
st.caption("등록한 키워드로 새 기사를 자동 확인합니다. 기사 제목·시간·링크를 그대로 보여 주고 요약하지 않습니다.")

# Counts cover articles whose title matches a keyword; body-only mentions are not counted.
_all_keywords = [k for g in groups for k in g.keywords]
summary = radar.summarize(
    r.entry for r in radar.rank_entries(state.entries.values(), _all_keywords, include_ignored=True) if r.relevant
)
m1, m2, m3, m4 = st.columns(4)
m1.metric("오늘", f"{summary.today}건")
m2.metric("이번 주", f"{summary.this_week}건")
m3.metric("중요 표시", f"{summary.important}건")
m4.metric("아직 안 읽음", f"{summary.unread}건")

if store is not None:
    last_run = stored_index.last_run if stored_index is not None else None
    if index_failed:
        st.warning("자동으로 모아 둔 기사를 불러오지 못했습니다. 잠시 뒤 다시 열거나 새 기사 확인 버튼을 눌러 주세요.")
    elif last_run is None:
        st.caption("자동 수집 상태: 아직 자동으로 모은 기사가 없습니다. 첫 자동 확인이 끝나면 여기에 쌓입니다.")
    else:
        same_day = radar.to_seoul(last_run.finished_at).date() == radar.to_seoul(datetime.now(UTC)).date()
        last_text = radar.seoul_time_text(last_run.finished_at, "%H:%M" if same_day else "%m-%d %H:%M")
        status_text = (
            f"자동 수집 상태: 마지막 자동 확인 {last_text} · 키워드 {last_run.keyword_count}개 중 "
            f"{last_run.ok_count}개 확인 · 새 기사 {last_run.new_count}건 · 10분마다 자동 확인"
        )
        if last_run.failed_keywords:
            status_text += " · 확인 못 한 키워드: " + ", ".join(last_run.failed_keywords)
        st.caption(status_text)
        if datetime.now(UTC) - last_run.finished_at > STALE_AFTER:
            st.warning("자동 확인이 1시간 넘게 멈춰 있습니다. 새 기사 확인 버튼으로 직접 확인할 수 있습니다.")
    if st.session_state.get(STATUS_SESSION_ONLY_KEY):
        st.caption("읽음·중요 표시는 이 화면을 연 동안만 유지됩니다 (저장 권한이 없는 연결).")
    else:
        st.caption("읽음·중요 표시는 저장되어 다음에 열어도 그대로 보입니다.")
else:
    st.caption("읽음·중요 표시는 이 화면을 연 동안만 유지됩니다.")

with st.expander("관심 키워드 관리", expanded=not state.entries):
    st.caption(
        "그룹 단위로 켜고 끌 수 있습니다(이 화면에만 적용). 즉시 알림 키워드는 새 기사가 나오면 알림 채널로 "
        "보내고, 하루 1회 요약 키워드는 매일 오전 8시 30분에 모아 정리합니다."
    )
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
                f"마지막 직접 확인 {_time_text(state.last_scan_at)} · 새로 찾은 기사 {state.last_new_count}건"
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
filter_col, sort_col = st.columns([2, 1])
with filter_col:
    keyword_filter = st.multiselect(
        "키워드로 좁혀 보기", [keyword.text for keyword in keywords], placeholder="전체 키워드"
    )
with sort_col:
    sort_mode = st.radio("정렬", ["중요도순", "최신순"], horizontal=True)
body_col_opt, ignored_col = st.columns(2)
with body_col_opt:
    show_body_only = st.checkbox(
        "본문에서만 언급된 기사도 보기",
        value=False,
        help="제목에 키워드가 없고 본문 어딘가에만 단어가 있는 기사입니다. 대부분 관련 없는 기사라 기본으로 숨깁니다.",
    )
with ignored_col:
    show_ignored = st.checkbox("관심없음으로 표시한 기사도 보기", value=False)

tiers = radar.load_source_tiers()
ranked = radar.rank_entries(state.entries.values(), keywords, tiers, include_ignored=show_ignored)
hidden_body_only = sum(1 for r in ranked if not r.relevant)
if not show_body_only:
    ranked = [r for r in ranked if r.relevant]
if keyword_filter:
    wanted = set(keyword_filter)
    ranked = [r for r in ranked if wanted & set(r.matched_keywords or r.entry.keywords)]
if sort_mode == "중요도순":
    ranked = radar.by_priority(ranked)
st.caption(
    "중요도순: 제목에 키워드가 있는 기사, 우리병원·경쟁병원 기사, 의학·병원 전문지 기사를 앞에 둡니다."
    + (f" 본문에서만 언급된 {hidden_body_only}건은 숨겼습니다." if not show_body_only and hidden_body_only else "")
)
entries = [r.entry for r in ranked]
rank_by_id = {r.entry.article_id: r for r in ranked}

if not entries:
    st.write("아직 확인된 기사가 없습니다. 위의 새 기사 확인 버튼을 누르면 여기에 쌓입니다.")

# Hundreds of cards make the page sluggish; show the first batch and let the reader extend it.
page_size = st.session_state.setdefault("news_radar_page_size", PAGE_SIZE)
visible_entries = entries[:page_size]
if len(entries) > len(visible_entries):
    st.caption(f"{len(visible_entries)}건을 보여 줍니다 (전체 {len(entries)}건).")

for entry in visible_entries:
    with st.container(border=True):
        head_col, body_col, status_col = st.columns([1, 4, 1.2])
        with head_col:
            if entry.status == radar.STATUS_NEW:
                st.markdown(f"**NEW** {_time_text(entry.published_at)}")
            else:
                st.markdown(_time_text(entry.published_at))
            info = rank_by_id.get(entry.article_id)
            st.caption(" · ".join(info.matched_keywords if info and info.matched_keywords else entry.keywords))
        with body_col:
            st.markdown(f"**{entry.title}**")
            badges = []
            if info and info.tier:
                badges.append(info.tier.label)
            if info and not info.relevant:
                badges.append("본문에서만 언급")
            st.caption(
                f"{entry.source_domain or '출처 확인 안 됨'} | {_time_text(entry.published_at)}"
                + (" | " + " · ".join(badges) if badges else "")
            )
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

st.divider()
st.subheader("이메일 알림 받기")
st.caption(
    "우리병원(부산백병원·인제대 백병원·백중앙의료원) 기사가 제목에 나오면 좋은 기사든 나쁜 기사든 약 10분 안에 "
    "메일로 보내 드립니다. 매일 아침 8시 30분에는 병원 전체 동향 요약을 보내 드립니다."
)
if subscriber_store is None:
    st.info("이메일 알림 신청은 관리자 설정이 끝나면 열립니다.")
else:
    with st.form("news_subscribe", clear_on_submit=True):
        email = st.text_input("이메일 주소", placeholder="name@example.com")
        want_immediate = st.checkbox(subs.PREF_LABELS[subs.PREF_IMMEDIATE], value=True)
        want_daily = st.checkbox(subs.PREF_LABELS[subs.PREF_DAILY], value=False)
        st.caption(
            "입력한 주소로 확인 메일을 먼저 보내고, 메일 속 링크를 눌러야 알림이 시작됩니다. 주소는 알림 발송에만 "
            "쓰고, 확인하지 않은 신청은 7일 뒤, 수신 거부하면 즉시 지웁니다. 모든 알림 메일에 수신 거부 링크가 있습니다."
        )
        submitted = st.form_submit_button("알림 신청")
    if submitted:
        prefs = [p for p, on in ((subs.PREF_IMMEDIATE, want_immediate), (subs.PREF_DAILY, want_daily)) if on]
        try:
            subs.request_subscription(subscriber_store, email, prefs)
        except subs.SubscriptionError as exc:
            st.warning(str(exc))
        else:
            st.success("신청을 받았습니다. 10분 안에 확인 메일이 갑니다. 메일 속 링크를 눌러 주세요.")
