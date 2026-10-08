"""Hospital News Radar: keyword groups, new-article detection and reading status.

Phase 1 keeps everything in memory (the Streamlit session) and in the seed file
``data/news_keywords.json``; the ``news_keyword`` / ``news_item`` tables exist for Phase 2.
The detection layer only records what NAVER returns for display (title, time, links).
Nothing here feeds an AI step.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from purchase_price.clients.naver_news import NaverNewsClientError, NaverNewsItem

DEFAULT_KEYWORD_FILE = Path(__file__).resolve().parents[3] / "data" / "news_keywords.json"

STATUS_NEW = "new"
STATUS_READ = "read"
STATUS_IMPORTANT = "important"
STATUS_IGNORED = "ignored"
STATUS_LABELS: dict[str, str] = {
    STATUS_NEW: "새 기사",
    STATUS_READ: "읽음",
    STATUS_IMPORTANT: "중요",
    STATUS_IGNORED: "관심없음",
}

ALERT_LABELS: dict[str, str] = {
    "immediate": "즉시",
    "daily": "하루 1회 요약",
    "none": "알림 없음",
}

_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid"}


@dataclass(frozen=True)
class Keyword:
    text: str
    group_key: str
    group_name: str
    alert: str = "none"

    @property
    def alert_label(self) -> str:
        return ALERT_LABELS.get(self.alert, ALERT_LABELS["none"])


@dataclass(frozen=True)
class KeywordGroup:
    key: str
    name: str
    enabled: bool
    keywords: tuple[Keyword, ...]


def load_keyword_groups(path: Path = DEFAULT_KEYWORD_FILE) -> tuple[KeywordGroup, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    groups: list[KeywordGroup] = []
    for raw in payload.get("groups") or []:
        key = str(raw.get("key") or "").strip()
        name = str(raw.get("name") or key).strip()
        keywords = tuple(
            Keyword(
                text=str(item.get("text") or "").strip(),
                group_key=key,
                group_name=name,
                alert=str(item.get("alert") or "none"),
            )
            for item in raw.get("keywords") or []
            if str(item.get("text") or "").strip()
        )
        if key and keywords:
            groups.append(
                KeywordGroup(
                    key=key, name=name, enabled=bool(raw.get("enabled", True)), keywords=keywords
                )
            )
    return tuple(groups)


def active_keywords(
    groups: Iterable[KeywordGroup], enabled_overrides: Mapping[str, bool] | None = None
) -> tuple[Keyword, ...]:
    overrides = enabled_overrides or {}
    result: list[Keyword] = []
    for group in groups:
        if overrides.get(group.key, group.enabled):
            result.extend(group.keywords)
    return tuple(result)


def article_id(url: str) -> str:
    """Stable identity for an article: host/path plus non-tracking query, no fragment."""

    parts = urlsplit((url or "").strip())
    host = parts.netloc.casefold()
    if host.startswith("www."):
        host = host[4:]
    query = "&".join(
        pair
        for pair in parts.query.split("&")
        if pair and pair.split("=", 1)[0] not in _TRACKING_PARAMS
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.casefold() or "https", host, path, query, ""))


@dataclass(frozen=True)
class NewsEntry:
    article_id: str
    title: str
    url: str
    naver_link: str
    source_domain: str
    published_at: datetime | None
    keywords: tuple[str, ...]
    detected_at: datetime
    status: str = STATUS_NEW

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, STATUS_LABELS[STATUS_NEW])


@dataclass(frozen=True)
class ScanLog:
    keyword: str
    ok: bool
    result_count: int
    error: str | None
    scanned_at: datetime


@dataclass
class NewsRadarState:
    """Session-held Phase 1 state: known articles and their reading status."""

    entries: dict[str, NewsEntry] = field(default_factory=dict)
    logs: list[ScanLog] = field(default_factory=list)
    last_scan_at: datetime | None = None
    last_new_count: int = 0

    def set_status(self, entry_id: str, status: str) -> None:
        if status not in STATUS_LABELS:
            raise ValueError(f"unknown status: {status}")
        entry = self.entries.get(entry_id)
        if entry is not None:
            self.entries[entry_id] = replace(entry, status=status)


def merge_items(
    state: NewsRadarState,
    keyword: Keyword,
    items: Sequence[NaverNewsItem],
    *,
    now: datetime,
) -> int:
    """Add articles for one keyword; returns how many were new to the radar."""

    new_count = 0
    for item in items:
        url = item.article_url
        entry_id = article_id(url)
        existing = state.entries.get(entry_id)
        if existing is None:
            state.entries[entry_id] = NewsEntry(
                article_id=entry_id,
                title=item.title,
                url=url,
                naver_link=item.link,
                source_domain=item.source_domain,
                published_at=item.published_at,
                keywords=(keyword.text,),
                detected_at=now,
            )
            new_count += 1
        elif keyword.text not in existing.keywords:
            state.entries[entry_id] = replace(
                existing, keywords=(*existing.keywords, keyword.text)
            )
    return new_count


SearchFn = Callable[[str, int], Sequence[NaverNewsItem]]


def scan_keywords(
    state: NewsRadarState,
    keywords: Sequence[Keyword],
    search: SearchFn,
    *,
    now: datetime | None = None,
    display: int = 30,
) -> int:
    """Run one detection pass. ``search(text, display)`` returns NAVER items or raises."""

    scanned_at = now or datetime.now().astimezone()
    total_new = 0
    for keyword in keywords:
        try:
            items = search(keyword.text, display)
        except NaverNewsClientError as exc:
            state.logs.append(ScanLog(keyword.text, False, 0, str(exc), scanned_at))
            continue
        new_count = merge_items(state, keyword, items, now=scanned_at)
        total_new += new_count
        state.logs.append(ScanLog(keyword.text, True, len(items), None, scanned_at))
    state.last_scan_at = scanned_at
    state.last_new_count = total_new
    return total_new


@dataclass(frozen=True)
class RadarSummary:
    today: int
    this_week: int
    important: int
    unread: int


def summarize(entries: Iterable[NewsEntry], *, today: date | None = None) -> RadarSummary:
    today_value = today or date.today()
    week_start = today_value - timedelta(days=today_value.weekday())
    today_count = week_count = important = unread = 0
    for entry in entries:
        if entry.status == STATUS_IGNORED:
            continue
        day = (entry.published_at or entry.detected_at).date()
        if day == today_value:
            today_count += 1
        if week_start <= day <= today_value:
            week_count += 1
        if entry.status == STATUS_IMPORTANT:
            important += 1
        if entry.status == STATUS_NEW:
            unread += 1
    return RadarSummary(today=today_count, this_week=week_count, important=important, unread=unread)


def sorted_entries(
    entries: Iterable[NewsEntry], *, include_ignored: bool = False
) -> list[NewsEntry]:
    def sort_key(entry: NewsEntry) -> datetime:
        value = entry.published_at or entry.detected_at
        return value if value.tzinfo is not None else value.astimezone()

    return sorted(
        (entry for entry in entries if include_ignored or entry.status != STATUS_IGNORED),
        key=sort_key,
        reverse=True,
    )
