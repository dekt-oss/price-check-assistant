from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from purchase_price.clients.naver_news import NaverNewsClientError, NaverNewsItem
from purchase_price.services import news_radar as radar

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 8, 9, 30, tzinfo=KST)


def _item(url: str, title: str = "제목", published: datetime | None = NOW) -> NaverNewsItem:
    return NaverNewsItem(
        title=title,
        link="https://n.news.naver.com/x",
        original_link=url,
        published_at=published,
        source_domain="example.co.kr",
    )


def _entry(
    article: str,
    title: str,
    *,
    hours: int = 0,
    domain: str = "example.co.kr",
    keywords: tuple[str, ...] = ("부산백병원",),
) -> radar.NewsEntry:
    published = NOW + timedelta(hours=hours)
    return radar.NewsEntry(
        article_id=article,
        title=title,
        url=f"https://{domain}/{article}",
        naver_link="",
        source_domain=domain,
        published_at=published,
        keywords=keywords,
        detected_at=published,
    )


def test_seed_keyword_groups_match_the_plan() -> None:
    groups = radar.load_keyword_groups()
    assert [group.name for group in groups] == [
        "우리병원",
        "같은 의료원 병원",
        "경쟁·Benchmark 병원",
        "병원경영",
        "AI·디지털",
        "구매·관리",
    ]
    assert all(group.enabled for group in groups)
    our = groups[0]
    assert [keyword.text for keyword in our.keywords] == [
        "부산백병원",
        "인제대 백병원",
        "백중앙의료원",
    ]
    assert our.keywords[0].alert_label == "즉시"
    all_texts = [keyword.text for group in groups for keyword in group.keywords]
    assert "부산 상급종합병원" in all_texts
    # Stand-alone generic words pulled in unrelated articles (2026-10-08 scan); keep them qualified.
    for generic in ("의료수가", "병상", "의료인력", "의료기기", "의료장비", "필수의료"):
        assert generic not in all_texts


def test_group_toggle_filters_active_keywords() -> None:
    groups = radar.load_keyword_groups()
    active = radar.active_keywords(groups, {"management": False, "procurement": False})
    assert {keyword.group_key for keyword in active} == {"our_hospital", "paik_network", "peer_hospitals", "ai_digital"}


def test_article_id_ignores_tracking_params_fragment_and_www() -> None:
    a = radar.article_id("https://www.example.co.kr/news/1?utm_source=naver&id=9#top")
    b = radar.article_id("https://example.co.kr/news/1/?id=9")
    assert a == b == "https://example.co.kr/news/1?id=9"


def test_scan_detects_only_new_articles_and_merges_keywords() -> None:
    state = radar.NewsRadarState()
    keywords = (
        radar.Keyword("부산백병원", "our_hospital", "우리병원", "immediate"),
        radar.Keyword("의료수가", "management", "병원경영", "daily"),
    )
    responses = {
        "부산백병원": [_item("https://example.co.kr/a"), _item("https://example.co.kr/b")],
        "의료수가": [_item("https://example.co.kr/b?utm_source=x"), _item("https://example.co.kr/c")],
    }

    def search(text: str, display: int) -> list[NaverNewsItem]:
        return responses[text]

    assert radar.scan_keywords(state, keywords, search, now=NOW) == 3
    assert state.entries[radar.article_id("https://example.co.kr/b")].keywords == (
        "부산백병원",
        "의료수가",
    )
    # A second pass finds nothing new and keeps the status that was set in between.
    state.set_status(radar.article_id("https://example.co.kr/a"), radar.STATUS_IMPORTANT)
    assert radar.scan_keywords(state, keywords, search, now=NOW + timedelta(minutes=30)) == 0
    assert state.entries[radar.article_id("https://example.co.kr/a")].status == "important"
    assert state.last_new_count == 0
    assert all(log.ok for log in state.logs)


def test_scan_records_failed_keywords_and_continues() -> None:
    state = radar.NewsRadarState()
    keywords = (
        radar.Keyword("부산백병원", "our_hospital", "우리병원"),
        radar.Keyword("의료수가", "management", "병원경영"),
    )

    def search(text: str, display: int) -> list[NaverNewsItem]:
        if text == "부산백병원":
            raise NaverNewsClientError("HTTP 429")
        return [_item("https://example.co.kr/z")]

    assert radar.scan_keywords(state, keywords, search, now=NOW) == 1
    failed = [log for log in state.logs if not log.ok]
    assert [(log.keyword, log.error) for log in failed] == [("부산백병원", "HTTP 429")]


def test_summary_counts_today_week_important_and_skips_ignored() -> None:
    state = radar.NewsRadarState()
    keyword = radar.Keyword("병상", "management", "병원경영")
    items = [
        _item("https://e.kr/today", published=NOW),
        _item("https://e.kr/monday", published=datetime(2026, 10, 5, 8, 0, tzinfo=KST)),
        _item("https://e.kr/lastweek", published=datetime(2026, 10, 1, 8, 0, tzinfo=KST)),
        _item("https://e.kr/ignored", published=NOW),
    ]
    radar.merge_items(state, keyword, items, now=NOW)
    state.set_status(radar.article_id("https://e.kr/monday"), radar.STATUS_IMPORTANT)
    state.set_status(radar.article_id("https://e.kr/ignored"), radar.STATUS_IGNORED)
    summary = radar.summarize(state.entries.values(), today=date(2026, 10, 8))
    assert (summary.today, summary.this_week, summary.important, summary.unread) == (1, 2, 1, 2)
    ordered = radar.sorted_entries(state.entries.values())
    assert [entry.url for entry in ordered] == [
        "https://e.kr/today",
        "https://e.kr/monday",
        "https://e.kr/lastweek",
    ]


def test_unknown_status_is_rejected() -> None:
    state = radar.NewsRadarState()
    with pytest.raises(ValueError):
        state.set_status("x", "starred")


def test_cluster_news_issues_groups_title_variants_but_not_other_hospital_events() -> None:
    keywords = (radar.Keyword("부산백병원", "our_hospital", "우리병원", "immediate"),)
    entries = [
        _entry("a", "부산백병원, 조제약 카카오 알림 서비스 시행", domain="one.kr"),
        _entry("b", "부산백병원 약제부 카카오톡 복약 안내 서비스", hours=20, domain="two.kr"),
        _entry("c", "부산백병원 모자의료센터 개소 10주년", hours=22, domain="three.kr"),
    ]

    issues = radar.cluster_news_issues(entries, keywords, now=NOW + timedelta(hours=24))

    assert sorted(issue.article_count for issue in issues) == [1, 2]
    grouped = next(issue for issue in issues if issue.article_count == 2)
    assert grouped.article_ids == ("a", "b")
    assert grouped.source_count == 2
    assert grouped.group_names == ("우리병원",)


def test_cluster_news_issues_respects_time_window_and_keeps_roundups_separate() -> None:
    keyword = radar.Keyword("부산백병원", "our_hospital", "우리병원", "immediate")
    entries = [
        _entry("a", "부산백병원 카카오 복약 알림 서비스", hours=0),
        _entry("b", "부산백병원 카카오 복약 안내 서비스", hours=97),
        _entry("c", "[병원계 이모저모] 부산백병원 외", hours=1),
        _entry("d", "[병원계 이모저모] 부산백병원 소식", hours=2),
    ]

    issues = radar.cluster_news_issues(entries, (keyword,), now=NOW + timedelta(hours=100))

    assert len(issues) == 4


def test_cluster_news_issues_does_not_bridge_beyond_the_total_time_window() -> None:
    keyword = radar.Keyword("부산백병원", "our_hospital", "우리병원", "immediate")
    entries = [
        _entry("a", "부산백병원 카카오 복약 알림 서비스", hours=0),
        _entry("b", "부산백병원 카카오 복약 안내 서비스", hours=90),
        _entry("c", "부산백병원 카카오 복약 알림 서비스", hours=180),
    ]

    issues = radar.cluster_news_issues(entries, (keyword,), now=NOW + timedelta(hours=180))

    assert sorted(issue.article_count for issue in issues) == [1, 2]


def test_issue_priority_is_not_article_count_alone() -> None:
    keywords = (
        radar.Keyword("부산백병원", "our_hospital", "우리병원", "immediate"),
        radar.Keyword("병원 AI 도입", "ai_digital", "AI·디지털", "daily"),
    )
    many_old = [
        _entry(
            f"old-{i}",
            f"병원 AI 도입 공동 연구 발표 {i}",
            hours=-70 + i,
            domain=f"old{i}.kr",
            keywords=("병원 AI 도입",),
        )
        for i in range(4)
    ]
    recent_ours = _entry("ours", "부산백병원 새 의료센터 개소", hours=-1, domain="recent.kr")

    issues = radar.cluster_news_issues([*many_old, recent_ours], keywords, now=NOW)

    assert issues[0].representative_article_id == "ours"


def test_issue_priority_boosts_recall_and_safety_keywords() -> None:
    keywords = (
        radar.Keyword("병원 AI 도입", "ai_digital", "AI·디지털", "daily"),
        radar.Keyword("의료기기 회수", "procurement", "구매·관리", "daily"),
    )
    ordinary = _entry(
        "ordinary",
        "병원 AI 도입 현황 발표",
        keywords=("병원 AI 도입",),
    )
    recall = _entry(
        "recall",
        "의료기기 회수 대상 공개",
        hours=-10,
        keywords=("의료기기 회수",),
    )

    issues = radar.cluster_news_issues([ordinary, recall], keywords, now=NOW)

    assert issues[0].representative_article_id == "recall"
