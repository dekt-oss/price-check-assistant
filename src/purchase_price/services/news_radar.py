"""Hospital News Radar: keyword groups, new-article detection and reading status.

Phase 1 keeps everything in memory (the Streamlit session) and in the seed file
``data/news_keywords.json``; the ``news_keyword`` / ``news_item`` tables exist for Phase 2.
The detection layer only records what NAVER returns for display (title, time, links).
Nothing here feeds an AI step.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from purchase_price.clients.naver_news import NaverNewsClientError, NaverNewsItem

DEFAULT_KEYWORD_FILE = Path(__file__).resolve().parents[3] / "data" / "news_keywords.json"
MODULES_REVISION = "2026-10-13-h1-review"
ISSUE_WINDOW = timedelta(hours=96)
ISSUE_RECENT_WINDOW = timedelta(hours=72)
ISSUE_SIMILARITY_THRESHOLD = 0.18
ISSUE_REGULATORY_TERMS = ("회수", "판매중지", "리콜", "안전성")
DEFAULT_ISSUE_ROUNDUP_TERMS = ("이모저모",)

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

try:
    SEOUL = ZoneInfo("Asia/Seoul")
except ZoneInfoNotFoundError:  # no tz database (bare Windows); Korea has no DST
    SEOUL = timezone(timedelta(hours=9), name="KST")
UNKNOWN_TIME_TEXT = "시간 확인 안 됨"


def to_seoul(value: datetime) -> datetime:
    """Streamlit Cloud runs in UTC; every time shown to people is Korean time."""

    return (value if value.tzinfo is not None else value.replace(tzinfo=UTC)).astimezone(SEOUL)


def seoul_time_text(value: datetime | None, fmt: str = "%m-%d %H:%M") -> str:
    return to_seoul(value).strftime(fmt) if value is not None else UNKNOWN_TIME_TEXT


_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid"}


@dataclass(frozen=True)
class Keyword:
    text: str
    group_key: str
    group_name: str
    alert: str = "none"
    # Words that must appear in the article *title* for it to count as relevant. Each inner tuple
    # is a set of alternatives (any one is enough); every inner tuple must be satisfied. Empty means
    # "every word of the keyword text". NAVER returns articles that mention the words anywhere in
    # the body, so without this most results are unrelated (measured 2026-10-09: 40 of 1,624).
    title_terms: tuple[tuple[str, ...], ...] = ()
    # Words that disqualify a title even when the required words are there (e.g. "부산백화점").
    exclude_terms: tuple[str, ...] = ()

    @property
    def required_terms(self) -> tuple[tuple[str, ...], ...]:
        return self.title_terms or tuple((word,) for word in self.text.split() if word)

    @property
    def alert_label(self) -> str:
        return ALERT_LABELS.get(self.alert, ALERT_LABELS["none"])


@dataclass(frozen=True)
class KeywordGroup:
    key: str
    name: str
    enabled: bool
    keywords: tuple[Keyword, ...]
    notify: tuple[str, ...] = ()  # channels for 즉시 alerts: kakao, email, sms, webhook


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
                title_terms=tuple(
                    tuple(str(t) for t in (group if isinstance(group, list) else [group]))
                    for group in item.get("title_terms") or []
                ),
                exclude_terms=tuple(str(t) for t in item.get("exclude_terms") or []),
            )
            for item in raw.get("keywords") or []
            if str(item.get("text") or "").strip()
        )
        if key and keywords:
            groups.append(
                KeywordGroup(
                    key=key,
                    name=name,
                    enabled=bool(raw.get("enabled", True)),
                    keywords=keywords,
                    notify=tuple(str(c) for c in raw.get("notify") or ("webhook",)),
                )
            )
    return tuple(groups)


def load_issue_roundup_terms(path: Path = DEFAULT_KEYWORD_FILE) -> tuple[str, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    configured = tuple(
        str(term).strip() for term in payload.get("issue_roundup_terms") or [] if str(term).strip()
    )
    return configured or DEFAULT_ISSUE_ROUNDUP_TERMS


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text or "").casefold()


def title_matches(title: str, keyword: Keyword) -> bool:
    """True when the title contains the keyword's required words (spaces and case ignored)."""

    squashed = _squash(title)
    if any(_squash(term) in squashed for term in keyword.exclude_terms):
        return False
    return all(any(_squash(term) in squashed for term in group) for group in keyword.required_terms)


DEFAULT_SOURCE_FILE = Path(__file__).resolve().parents[3] / "data" / "news_sources.json"


@dataclass(frozen=True)
class SourceTier:
    key: str
    label: str
    weight: int
    domains: tuple[str, ...]


def load_source_tiers(path: Path = DEFAULT_SOURCE_FILE) -> tuple[SourceTier, ...]:
    if not path.exists():
        return ()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        SourceTier(
            key=str(raw["key"]),
            label=str(raw.get("label") or raw["key"]),
            weight=int(raw.get("weight") or 0),
            domains=tuple(str(d).casefold() for d in raw.get("domains") or []),
        )
        for raw in payload.get("tiers") or []
    )


def source_tier(domain: str, tiers: Iterable[SourceTier]) -> SourceTier | None:
    host = (domain or "").casefold()
    for tier in tiers:
        if any(host == d or host.endswith("." + d) for d in tier.domains):
            return tier
    return None


GROUP_WEIGHTS = {"our_hospital": 4, "peer_hospitals": 2}
RELEVANT_WEIGHT = 3


@dataclass(frozen=True)
class RankedEntry:
    entry: NewsEntry
    relevant: bool
    matched_keywords: tuple[str, ...]
    tier: SourceTier | None
    score: int


def rank_entries(
    entries: Iterable[NewsEntry],
    keywords: Iterable[Keyword],
    tiers: Iterable[SourceTier] = (),
    *,
    include_ignored: bool = False,
) -> list[RankedEntry]:
    """Score each article: title relevance, 우리병원/경쟁병원 group, medical trade press.

    Returned newest first; callers sort by ``score`` for the 중요도순 view.
    """

    by_text = {k.text: k for k in keywords}
    tier_list = tuple(tiers)
    ranked: list[RankedEntry] = []
    for entry in sorted_entries(entries, include_ignored=include_ignored):
        matched = tuple(
            text for text in entry.keywords if (k := by_text.get(text)) is not None and title_matches(entry.title, k)
        )
        tier = source_tier(entry.source_domain, tier_list)
        group_weight = max(
            (GROUP_WEIGHTS.get(by_text[t].group_key, 0) for t in matched if t in by_text), default=0
        )
        score = (RELEVANT_WEIGHT if matched else 0) + group_weight + (tier.weight if tier else 0)
        ranked.append(RankedEntry(entry, bool(matched), matched, tier, score))
    return ranked


def by_priority(ranked: Iterable[RankedEntry]) -> list[RankedEntry]:
    """중요도순: higher score first, newer first within the same score (input is newest first)."""

    return sorted(ranked, key=lambda r: -r.score)


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
class NewsIssue:
    issue_id: str
    title: str
    article_ids: tuple[str, ...]
    group_keys: tuple[str, ...]
    group_names: tuple[str, ...]
    source_count: int
    article_count: int
    first_published_at: datetime
    latest_published_at: datetime
    representative_article_id: str
    score: int


_TITLE_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")
_TITLE_ALIASES = {
    "카카오톡": "카카오",
    "인제대학교": "인제대",
    "영아": "아기",
    "건전지꿀꺽": "건전지 삼킨",
    "권역모자의료센터": "모자 의료 센터",
    "모자의료센터": "모자 의료 센터",
    "10주년": "10년",
    "원내약": "약",
    "조제현황": "조제",
}
_TITLE_STOPWORDS = {"ai", "기사", "뉴스", "병원", "의료", "의료기기"}
_TITLE_SUFFIXES = ("으로", "에서", "에게", "까지", "부터", "처럼", "의", "이", "가", "은", "는", "을", "를", "과", "와", "도", "에", "로")


def _issue_title_parts(title: str) -> tuple[set[str], set[str]]:
    normalized = title.casefold()
    for source, target in _TITLE_ALIASES.items():
        normalized = normalized.replace(source.casefold(), target.casefold())
    tokens: set[str] = set()
    for raw_token in _TITLE_TOKEN_RE.findall(normalized):
        token = raw_token
        for suffix in _TITLE_SUFFIXES:
            if len(token) - len(suffix) >= 2 and token.endswith(suffix):
                token = token[: -len(suffix)]
                break
        if (len(token) >= 2 or token == "약") and token not in _TITLE_STOPWORDS and "병원" not in token:
            tokens.add(token)
    compact = "".join(_TITLE_TOKEN_RE.findall(normalized))
    bigrams = {compact[i : i + 2] for i in range(max(0, len(compact) - 1))}
    return tokens, bigrams


def _issue_title_similarity(left: str, right: str) -> tuple[int, float]:
    return _issue_parts_similarity(_issue_title_parts(left), _issue_title_parts(right))


def _issue_parts_similarity(
    left: tuple[set[str], set[str]], right: tuple[set[str], set[str]]
) -> tuple[int, float]:
    left_tokens, left_bigrams = left
    right_tokens, right_bigrams = right
    shared_tokens = len(left_tokens & right_tokens)
    denominator = len(left_bigrams) + len(right_bigrams)
    dice = 0.0 if not denominator else 2 * len(left_bigrams & right_bigrams) / denominator
    return shared_tokens, dice


def cluster_news_issues(
    entries: Iterable[NewsEntry],
    keywords: Iterable[Keyword],
    tiers: Iterable[SourceTier] = (),
    *,
    now: datetime | None = None,
    roundup_terms: Sequence[str] = DEFAULT_ISSUE_ROUNDUP_TERMS,
) -> tuple[NewsIssue, ...]:
    """Deterministically group title-matching articles that report the same event."""

    current = now or datetime.now(UTC)
    keyword_list = tuple(keywords)
    by_text = {keyword.text: keyword for keyword in keyword_list}
    ranked = [item for item in rank_entries(entries, keyword_list, tiers) if item.relevant]
    ordered = sorted(
        ranked,
        key=lambda item: (
            _aware_issue_time(item.entry.published_at or item.entry.detected_at),
            item.entry.article_id,
        ),
    )
    parents = list(range(len(ordered)))
    component_first = [
        _aware_issue_time(item.entry.published_at or item.entry.detected_at) for item in ordered
    ]
    component_latest = list(component_first)
    title_parts = [_issue_title_parts(item.entry.title) for item in ordered]
    roundup_list = tuple(term.casefold() for term in roundup_terms if term)

    def root(position: int) -> int:
        while parents[position] != position:
            parents[position] = parents[parents[position]]
            position = parents[position]
        return position

    def union(left: int, right: int) -> bool:
        left_root, right_root = root(left), root(right)
        if left_root == right_root:
            return True
        first = min(component_first[left_root], component_first[right_root])
        latest = max(component_latest[left_root], component_latest[right_root])
        if latest - first > ISSUE_WINDOW:
            return False
        parents[right_root] = left_root
        component_first[left_root] = first
        component_latest[left_root] = latest
        return True

    for left_position, left in enumerate(ordered):
        left_entry = left.entry
        if any(term in left_entry.title.casefold() for term in roundup_list):
            continue
        left_time = _aware_issue_time(left_entry.published_at or left_entry.detected_at)
        left_groups = {by_text[text].group_key for text in left.matched_keywords if text in by_text}
        for right_position in range(left_position + 1, len(ordered)):
            right = ordered[right_position]
            right_entry = right.entry
            if any(term in right_entry.title.casefold() for term in roundup_list):
                continue
            right_time = _aware_issue_time(right_entry.published_at or right_entry.detected_at)
            if right_time - left_time > ISSUE_WINDOW:
                break
            right_groups = {by_text[text].group_key for text in right.matched_keywords if text in by_text}
            if not left_groups.intersection(right_groups):
                continue
            shared, similarity = _issue_parts_similarity(
                title_parts[left_position], title_parts[right_position]
            )
            same_event = shared >= 2 and similarity >= ISSUE_SIMILARITY_THRESHOLD
            if same_event:
                union(left_position, right_position)

    grouped: dict[int, list[RankedEntry]] = {}
    for position, item in enumerate(ordered):
        grouped.setdefault(root(position), []).append(item)
    clusters = list(grouped.values())

    issues: list[NewsIssue] = []
    for cluster in clusters:
        cluster_entries = [item.entry for item in cluster]
        representative = max(
            cluster,
            key=lambda item: (
                item.score,
                _aware_issue_time(item.entry.published_at or item.entry.detected_at),
                item.entry.article_id,
            ),
        )
        times = [_aware_issue_time(entry.published_at or entry.detected_at) for entry in cluster_entries]
        group_keys = sorted(
            {
                by_text[text].group_key
                for item in cluster
                for text in item.matched_keywords
                if text in by_text
            }
        )
        group_names = tuple(
            dict.fromkeys(
                by_text[text].group_name
                for item in cluster
                for text in item.matched_keywords
                if text in by_text
            )
        )
        unique_sources = len({entry.source_domain for entry in cluster_entries if entry.source_domain})
        age = _aware_issue_time(current) - max(times)
        recency = 2 if age <= timedelta(hours=24) else 1 if age <= timedelta(hours=72) else 0
        regulatory = (
            3
            if any(
                term in item.entry.title.casefold()
                or any(term in text.casefold() for text in item.matched_keywords)
                for item in cluster
                for term in ISSUE_REGULATORY_TERMS
            )
            else 0
        )
        score = representative.score + regulatory + min(max(unique_sources - 1, 0), 3) + recency
        article_ids = tuple(entry.article_id for entry in cluster_entries)
        digest = hashlib.sha256("\n".join(article_ids).encode("utf-8")).hexdigest()[:16]
        issues.append(
            NewsIssue(
                issue_id=f"issue-{digest}",
                title=representative.entry.title,
                article_ids=article_ids,
                group_keys=tuple(group_keys),
                group_names=group_names,
                source_count=unique_sources,
                article_count=len(cluster_entries),
                first_published_at=min(times),
                latest_published_at=max(times),
                representative_article_id=representative.entry.article_id,
                score=score,
            )
        )
    return tuple(
        sorted(
            issues,
            key=lambda issue: (-issue.score, -issue.latest_published_at.timestamp(), issue.issue_id),
        )
    )


def recent_news_issues(
    issues: Iterable[NewsIssue],
    *,
    now: datetime | None = None,
    max_age: timedelta = ISSUE_RECENT_WINDOW,
) -> tuple[NewsIssue, ...]:
    """Keep issues whose latest article is recent enough for the top-of-page block."""

    cutoff = _aware_issue_time(now or datetime.now(UTC)) - max_age
    return tuple(issue for issue in issues if _aware_issue_time(issue.latest_published_at) >= cutoff)


def markdown_link_title(title: str) -> str:
    """Keep an original title readable without letting brackets break a Markdown link."""

    return title.replace("[", "(").replace("]", ")")


def _aware_issue_time(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.astimezone()


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
    today_value = today or datetime.now(SEOUL).date()
    week_start = today_value - timedelta(days=today_value.weekday())
    today_count = week_count = important = unread = 0
    for entry in entries:
        if entry.status == STATUS_IGNORED:
            continue
        day = to_seoul(entry.published_at or entry.detected_at).date()
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
