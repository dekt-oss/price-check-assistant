"""News Radar Phase 2: the stored article list, reading statuses and alert texts.

Production has no PostgreSQL, so the scheduled GitHub Actions collector keeps one versioned JSON
object in R2 (``news/v1/index.json.gz``) and the Streamlit app only reads it. Reading statuses
(read / important / ignored) live in a separate small object (``news/v1/status.json``) because the
app is the only writer of statuses and the collector is the only writer of the index.

NAVER search API terms (2026-09-07): results are display-only. The index holds exactly the
display fields of :class:`~purchase_price.services.news_radar.NewsEntry` (title, time, links,
source domain, matched keywords) and never the article summary text. Server-side caching is
limited to 21 days, so every merge drops items older than :data:`RETENTION_DAYS` and items
published before that window are never added. Nothing here feeds an AI step.

For a local review without R2, :class:`LocalNewsRadarStore` keeps the same payloads in files
(``NEWS_RADAR_INDEX_PATH`` / ``NEWS_RADAR_STATUS_PATH``).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from purchase_price.clients.naver_news import NaverNewsClientError, NaverNewsItem
from purchase_price.config import Settings
from purchase_price.services import news_radar as radar

INDEX_VERSION = 1
STATUS_VERSION = 1
RETENTION_DAYS = 21
RUN_HISTORY_LIMIT = 48  # one day of 30-minute runs
NEWS_PREFIX = "news/v1"
INDEX_KEY = f"{NEWS_PREFIX}/index.json.gz"
STATUS_KEY = f"{NEWS_PREFIX}/status.json"
DIGEST_PREFIX = f"{NEWS_PREFIX}/digest"
INDEX_SCHEMA = "news-radar-index-v1"
STATUS_SCHEMA = "news-radar-status-v1"
DATA_CLASSIFICATION = "naver-display-cache-21d"
MAX_INDEX_STORED_BYTES = 64 * 1024 * 1024
SOURCE_NAME = "naver_news"
KST = radar.SEOUL
ALERT_ITEM_LIMIT = 20
_DIGEST_KEY_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\.md$")


class NewsRadarIndexError(RuntimeError):
    """The stored article list is missing required fields or has an unknown version."""


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _iso(value: datetime | None) -> str | None:
    return _aware(value).isoformat() if value is not None else None


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return _aware(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError:
        return None


# --------------------------------------------------------------------------- data model


@dataclass(frozen=True)
class KeywordLog:
    """One keyword search in one run, shaped like a ``data_source_log`` row."""

    keyword: str
    ok: bool
    result_count: int
    new_count: int
    error: str | None
    started_at: datetime
    finished_at: datetime

    def to_payload(self) -> dict[str, Any]:
        return {
            "source_name": SOURCE_NAME,
            "query_text": self.keyword,
            "ok": self.ok,
            "result_count": self.result_count,
            "new_count": self.new_count,
            "error_message": self.error,
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
        }

    @classmethod
    def from_payload(cls, raw: Mapping[str, Any]) -> KeywordLog:
        started = _parse_time(raw.get("started_at")) or datetime.fromtimestamp(0, UTC)
        return cls(
            keyword=str(raw.get("query_text") or ""),
            ok=bool(raw.get("ok")),
            result_count=int(raw.get("result_count") or 0),
            new_count=int(raw.get("new_count") or 0),
            error=(str(raw["error_message"]) if raw.get("error_message") else None),
            started_at=started,
            finished_at=_parse_time(raw.get("finished_at")) or started,
        )


@dataclass(frozen=True)
class CollectionRun:
    started_at: datetime
    finished_at: datetime
    keyword_count: int
    ok_count: int
    failed_count: int
    new_count: int
    purged_count: int
    logs: tuple[KeywordLog, ...] = ()

    @property
    def failed_keywords(self) -> tuple[str, ...]:
        return tuple(log.keyword for log in self.logs if not log.ok)

    def to_payload(self, *, include_logs: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "started_at": _iso(self.started_at),
            "finished_at": _iso(self.finished_at),
            "keyword_count": self.keyword_count,
            "ok_count": self.ok_count,
            "failed_count": self.failed_count,
            "new_count": self.new_count,
            "purged_count": self.purged_count,
            "failed_keywords": list(self.failed_keywords),
        }
        if include_logs:
            payload["logs"] = [log.to_payload() for log in self.logs]
        return payload

    @classmethod
    def from_payload(cls, raw: Mapping[str, Any]) -> CollectionRun:
        started = _parse_time(raw.get("started_at")) or datetime.fromtimestamp(0, UTC)
        logs = tuple(KeywordLog.from_payload(item) for item in raw.get("logs") or [] if isinstance(item, Mapping))
        failed = int(raw.get("failed_count") or 0)
        if not logs and failed:
            # Older runs keep only the failed keyword names; rebuild them as failed logs.
            logs = tuple(
                KeywordLog(str(name), False, 0, 0, None, started, started)
                for name in raw.get("failed_keywords") or []
            )
        return cls(
            started_at=started,
            finished_at=_parse_time(raw.get("finished_at")) or started,
            keyword_count=int(raw.get("keyword_count") or 0),
            ok_count=int(raw.get("ok_count") or 0),
            failed_count=failed,
            new_count=int(raw.get("new_count") or 0),
            purged_count=int(raw.get("purged_count") or 0),
            logs=logs,
        )


@dataclass
class NewsRadarIndex:
    generated_at: datetime | None = None
    keywords: tuple[dict[str, Any], ...] = ()
    items: dict[str, radar.NewsEntry] = field(default_factory=dict)
    runs: list[CollectionRun] = field(default_factory=list)  # oldest first
    version: int = INDEX_VERSION

    @property
    def last_run(self) -> CollectionRun | None:
        return self.runs[-1] if self.runs else None

    def keywords_with_alert(self, alert: str) -> frozenset[str]:
        return frozenset(str(k.get("text")) for k in self.keywords if k.get("alert") == alert)


def keyword_snapshot(
    groups: Iterable[radar.KeywordGroup], keywords: Iterable[radar.Keyword] | None = None
) -> tuple[dict[str, Any], ...]:
    """What was scanned, so the screen and the digest know each keyword's group and alert."""

    scanned = {keyword.text for keyword in keywords} if keywords is not None else None
    return tuple(
        {
            "text": keyword.text,
            "group_key": group.key,
            "group_name": group.name,
            "alert": keyword.alert,
            "enabled": group.enabled,
            "scanned": scanned is None or keyword.text in scanned,
        }
        for group in groups
        for keyword in group.keywords
    )


def entry_to_payload(entry: radar.NewsEntry) -> dict[str, Any]:
    """Display fields only; the reading status is stored separately (status.json)."""

    return {
        "article_id": entry.article_id,
        "title": entry.title,
        "url": entry.url,
        "naver_link": entry.naver_link,
        "source_domain": entry.source_domain,
        "published_at": _iso(entry.published_at),
        "keywords": list(entry.keywords),
        "detected_at": _iso(entry.detected_at),
    }


def entry_from_payload(raw: Mapping[str, Any]) -> radar.NewsEntry:
    article = str(raw.get("article_id") or "").strip()
    url = str(raw.get("url") or "").strip()
    detected = _parse_time(raw.get("detected_at"))
    if not article or not url or detected is None:
        raise NewsRadarIndexError("article entry is missing article_id, url or detected_at")
    return radar.NewsEntry(
        article_id=article,
        title=str(raw.get("title") or ""),
        url=url,
        naver_link=str(raw.get("naver_link") or ""),
        source_domain=str(raw.get("source_domain") or ""),
        published_at=_parse_time(raw.get("published_at")),
        keywords=tuple(str(k) for k in raw.get("keywords") or []),
        detected_at=detected,
    )


def index_to_payload(index: NewsRadarIndex) -> dict[str, Any]:
    runs = index.runs[-RUN_HISTORY_LIMIT:]
    return {
        "version": index.version,
        "generated_at": _iso(index.generated_at),
        "retention_days": RETENTION_DAYS,
        "keywords": [dict(k) for k in index.keywords],
        "items": [
            entry_to_payload(entry)
            for entry in sorted(index.items.values(), key=lambda e: (_aware(e.detected_at), e.article_id))
        ],
        # Per-keyword logs only for the newest run keeps the object small.
        "runs": [run.to_payload(include_logs=i == len(runs) - 1) for i, run in enumerate(runs)],
    }


def index_from_payload(payload: Mapping[str, Any]) -> NewsRadarIndex:
    version = payload.get("version")
    if version != INDEX_VERSION:
        raise NewsRadarIndexError(f"unsupported news index version: {version!r}")
    items: dict[str, radar.NewsEntry] = {}
    for raw in payload.get("items") or []:
        if isinstance(raw, Mapping):
            entry = entry_from_payload(raw)
            items[entry.article_id] = entry
    return NewsRadarIndex(
        generated_at=_parse_time(payload.get("generated_at")),
        keywords=tuple(dict(k) for k in payload.get("keywords") or [] if isinstance(k, Mapping)),
        items=items,
        runs=[CollectionRun.from_payload(r) for r in payload.get("runs") or [] if isinstance(r, Mapping)],
    )


# --------------------------------------------------------------------------- merge / purge


def retention_cutoff(now: datetime) -> datetime:
    return _aware(now) - timedelta(days=RETENTION_DAYS)


def is_expired(entry: radar.NewsEntry, cutoff: datetime) -> bool:
    if _aware(entry.detected_at) < cutoff:
        return True
    return entry.published_at is not None and _aware(entry.published_at) < cutoff


def purge_expired(index: NewsRadarIndex, *, now: datetime) -> int:
    cutoff = retention_cutoff(now)
    expired = [key for key, entry in index.items.items() if is_expired(entry, cutoff)]
    for key in expired:
        del index.items[key]
    return len(expired)


def merge_scan(
    index: NewsRadarIndex,
    keyword: radar.Keyword,
    items: Sequence[NaverNewsItem],
    *,
    now: datetime,
) -> list[radar.NewsEntry]:
    """Fold one keyword's results into the index; returns the entries that were new.

    Dedupes by :func:`news_radar.article_id`, keeps the first-detected time of known articles and
    only adds the keyword to them. Articles published before the 21-day window are skipped so a
    slow keyword does not re-add (and re-alert) old articles that the purge just dropped.
    """

    cutoff = retention_cutoff(now)
    added: list[radar.NewsEntry] = []
    for item in items:
        if item.published_at is not None and _aware(item.published_at) < cutoff:
            continue
        url = item.article_url
        entry_id = radar.article_id(url)
        existing = index.items.get(entry_id)
        if existing is None:
            entry = radar.NewsEntry(
                article_id=entry_id,
                title=item.title,
                url=url,
                naver_link=item.link,
                source_domain=item.source_domain,
                published_at=item.published_at,
                keywords=(keyword.text,),
                detected_at=_aware(now),
            )
            index.items[entry_id] = entry
            added.append(entry)
        elif keyword.text not in existing.keywords:
            index.items[entry_id] = replace(existing, keywords=(*existing.keywords, keyword.text))
    return added


SearchFn = Callable[[str, int], Sequence[NaverNewsItem]]


def search_with_backoff(
    search: SearchFn,
    text: str,
    display: int,
    *,
    retries: int = 3,
    base_delay: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Sequence[NaverNewsItem]:
    """Retry only NAVER 429 (too many requests) with a short exponential backoff."""

    attempt = 0
    while True:
        try:
            return search(text, display)
        except NaverNewsClientError as exc:
            if not exc.rate_limited or attempt >= retries:
                raise
            sleep(base_delay * (2**attempt))
            attempt += 1


@dataclass(frozen=True)
class CollectionResult:
    run: CollectionRun
    new_by_keyword: dict[str, list[radar.NewsEntry]]
    bootstrap: bool  # the index was empty before this run (no alerts for the backlog)

    @property
    def new_entries(self) -> list[radar.NewsEntry]:
        seen: dict[str, radar.NewsEntry] = {}
        for entries in self.new_by_keyword.values():
            for entry in entries:
                seen.setdefault(entry.article_id, entry)
        return list(seen.values())


def collect(
    index: NewsRadarIndex,
    keywords: Sequence[radar.Keyword],
    search: SearchFn,
    *,
    groups: Sequence[radar.KeywordGroup] = (),
    display: int = 100,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
    pause_seconds: float = 0.2,
) -> CollectionResult:
    """One collector pass: search every keyword, merge, purge, append a run record."""

    bootstrap = not index.items and not index.runs
    started = _aware(clock())
    logs: list[KeywordLog] = []
    new_by_keyword: dict[str, list[radar.NewsEntry]] = {}
    for position, keyword in enumerate(keywords):
        if position and pause_seconds:
            sleep(pause_seconds)
        keyword_started = _aware(clock())
        try:
            items = search_with_backoff(search, keyword.text, display, sleep=sleep)
        except NaverNewsClientError as exc:
            logs.append(KeywordLog(keyword.text, False, 0, 0, str(exc), keyword_started, _aware(clock())))
            continue
        added = merge_scan(index, keyword, items, now=started)
        if added:
            new_by_keyword[keyword.text] = added
        logs.append(KeywordLog(keyword.text, True, len(items), len(added), None, keyword_started, _aware(clock())))
    purged = purge_expired(index, now=started)
    finished = _aware(clock())
    run = CollectionRun(
        started_at=started,
        finished_at=finished,
        keyword_count=len(keywords),
        ok_count=sum(1 for log in logs if log.ok),
        failed_count=sum(1 for log in logs if not log.ok),
        new_count=len({e.article_id for entries in new_by_keyword.values() for e in entries}),
        purged_count=purged,
        logs=tuple(logs),
    )
    index.runs = [*index.runs, run][-RUN_HISTORY_LIMIT:]
    index.generated_at = finished
    if groups:
        index.keywords = keyword_snapshot(groups, keywords)
    return CollectionResult(run=run, new_by_keyword=new_by_keyword, bootstrap=bootstrap)


# --------------------------------------------------------------------------- statuses


def status_payload(statuses: Mapping[str, Mapping[str, Any]], *, now: datetime) -> dict[str, Any]:
    return {
        "version": STATUS_VERSION,
        "updated_at": _iso(now),
        "statuses": {key: dict(value) for key, value in sorted(statuses.items())},
    }


def statuses_from_payload(payload: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not payload or payload.get("version") != STATUS_VERSION:
        return {}
    raw = payload.get("statuses")
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for key, value in raw.items():
        if isinstance(value, Mapping) and value.get("status") in radar.STATUS_LABELS:
            result[str(key)] = {"status": value["status"], "updated_at": value.get("updated_at")}
    return result


def set_status(
    statuses: dict[str, dict[str, Any]], entry_id: str, status: str, *, now: datetime
) -> dict[str, dict[str, Any]]:
    if status not in radar.STATUS_LABELS:
        raise ValueError(f"unknown status: {status}")
    if status == radar.STATUS_NEW:
        statuses.pop(entry_id, None)  # "new" is the default; no row needed
    else:
        statuses[entry_id] = {"status": status, "updated_at": _iso(now)}
    return statuses


def prune_statuses(
    statuses: Mapping[str, Mapping[str, Any]], valid_ids: Iterable[str]
) -> dict[str, dict[str, Any]]:
    """Drop statuses of articles that left the 21-day list."""

    keep = set(valid_ids)
    return {key: dict(value) for key, value in statuses.items() if key in keep}


def overlay_statuses(
    entries: Iterable[radar.NewsEntry], statuses: Mapping[str, Mapping[str, Any]]
) -> list[radar.NewsEntry]:
    result: list[radar.NewsEntry] = []
    for entry in entries:
        stored = statuses.get(entry.article_id)
        status = str(stored.get("status")) if stored else radar.STATUS_NEW
        result.append(replace(entry, status=status) if status != entry.status else entry)
    return result


def seed_state(
    state: radar.NewsRadarState,
    index: NewsRadarIndex | None,
    statuses: Mapping[str, Mapping[str, Any]],
    *,
    session_statuses: Mapping[str, str] | None = None,
) -> None:
    """Put stored articles into the page's session state without losing live top-ups.

    A status chosen in this session wins over the stored one (it may not have been saved).
    """

    chosen = session_statuses or {}
    if index is not None:
        for entry in overlay_statuses(index.items.values(), statuses):
            current = state.entries.get(entry.article_id)
            if current is not None:
                merged = tuple(dict.fromkeys((*current.keywords, *entry.keywords)))
                entry = replace(entry, keywords=merged, detected_at=min(
                    _aware(current.detected_at), _aware(entry.detected_at)
                ))
            state.entries[entry.article_id] = entry
    for entry_id, entry in list(state.entries.items()):
        if entry_id in chosen:
            state.entries[entry_id] = replace(entry, status=chosen[entry_id])
        elif entry_id in statuses:
            state.entries[entry_id] = replace(entry, status=str(statuses[entry_id]["status"]))


# --------------------------------------------------------------------------- alerts / digest


def _when(value: datetime | None) -> str:
    return radar.seoul_time_text(value)


def immediate_alert_text(
    result: CollectionResult, immediate_keywords: Iterable[str], *, limit: int = ALERT_ITEM_LIMIT
) -> str | None:
    """Compact title + link message for keywords marked 즉시 alerts; None when nothing to send."""

    if result.bootstrap:
        return None
    wanted = set(immediate_keywords)
    lines: list[str] = []
    seen: set[str] = set()
    for keyword, entries in result.new_by_keyword.items():
        if keyword not in wanted:
            continue
        for entry in entries:
            if entry.article_id in seen:
                continue
            seen.add(entry.article_id)
            lines.append(f"- [{keyword}] {entry.title}\n  {entry.url}")
    if not lines:
        return None
    shown = lines[:limit]
    text = f"병원 News Radar 새 기사 {len(lines)}건\n" + "\n".join(shown)
    if len(lines) > limit:
        text += f"\n외 {len(lines) - limit}건은 News Radar 화면에서 확인하세요."
    return text


DIGEST_PER_KEYWORD_LIMIT = 15


def daily_digest_markdown(
    index: NewsRadarIndex,
    *,
    now: datetime,
    hours: int = 24,
    per_keyword_limit: int = DIGEST_PER_KEYWORD_LIMIT,
) -> str:
    """Markdown digest of the last ``hours`` of articles for keywords marked 하루 1회 요약.

    Each keyword shows its newest ``per_keyword_limit`` articles; the first live run produced a
    1,300-line digest otherwise.
    """

    daily = index.keywords_with_alert("daily")
    since = _aware(now) - timedelta(hours=hours)
    by_keyword: dict[str, list[radar.NewsEntry]] = {}
    for entry in radar.sorted_entries(index.items.values(), include_ignored=True):
        if _aware(entry.detected_at) < since:
            continue
        for keyword in entry.keywords:
            if keyword in daily:
                by_keyword.setdefault(keyword, []).append(entry)
    day = _aware(now).astimezone(KST).date()
    lines = [f"# 병원 News Radar 하루 요약 {day.isoformat()}", ""]
    lines.append(f"최근 {hours}시간 동안 '하루 1회 요약' 키워드로 찾은 기사입니다. 제목과 링크만 모았습니다.")
    lines.append("")
    if not by_keyword:
        lines.append("새 기사가 없습니다.")
        return "\n".join(lines) + "\n"
    ordered = [k.get("text") for k in index.keywords if k.get("text") in by_keyword]
    for keyword in ordered:
        entries = by_keyword[str(keyword)]
        lines.append(f"## {keyword} ({len(entries)}건)")
        lines.append("")
        for entry in entries[:per_keyword_limit]:
            title = entry.title.replace("[", "(").replace("]", ")")
            source = entry.source_domain or "출처 확인 안 됨"
            lines.append(f"- [{title}]({entry.url}) · {source} · {_when(entry.published_at)}")
        if len(entries) > per_keyword_limit:
            lines.append(f"- 외 {len(entries) - per_keyword_limit}건은 News Radar 화면에서 확인하세요.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- stores


class NewsRadarStore(Protocol):
    def describe(self) -> str: ...

    def read_index(self) -> NewsRadarIndex | None: ...

    def write_index(self, index: NewsRadarIndex) -> str: ...

    def read_statuses(self) -> dict[str, dict[str, Any]]: ...

    def write_statuses(self, statuses: Mapping[str, Mapping[str, Any]], *, now: datetime) -> str: ...

    def write_digest(self, day: date, text: str) -> str: ...

    def prune_digests(self, before: date) -> int: ...


def _index_bytes(index: NewsRadarIndex) -> bytes:
    return json.dumps(index_to_payload(index), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


class LocalNewsRadarStore:
    """File-based store for local review: same payloads as R2, no credentials needed."""

    def __init__(self, index_path: Path, status_path: Path | None = None, digest_dir: Path | None = None) -> None:
        self.index_path = Path(index_path)
        stem = self.index_path.name.split(".")[0] or "news-radar"
        self.status_path = Path(status_path) if status_path else self.index_path.with_name(f"{stem}-status.json")
        self.digest_dir = Path(digest_dir) if digest_dir else self.index_path.parent / f"{stem}-digest"

    def describe(self) -> str:
        return f"local:{self.index_path}"

    def read_index(self) -> NewsRadarIndex | None:
        if not self.index_path.exists():
            return None
        opener = gzip.open if self.index_path.suffix == ".gz" else open
        with opener(self.index_path, "rt", encoding="utf-8") as stream:
            return index_from_payload(json.load(stream))

    def write_index(self, index: NewsRadarIndex) -> str:
        data = _index_bytes(index)
        if self.index_path.suffix == ".gz":
            data = gzip.compress(data, mtime=0)
        _atomic_write(self.index_path, data)
        return str(self.index_path)

    def read_statuses(self) -> dict[str, dict[str, Any]]:
        if not self.status_path.exists():
            return {}
        return statuses_from_payload(json.loads(self.status_path.read_text(encoding="utf-8")))

    def write_statuses(self, statuses: Mapping[str, Mapping[str, Any]], *, now: datetime) -> str:
        data = json.dumps(status_payload(statuses, now=now), ensure_ascii=False, indent=1).encode("utf-8")
        _atomic_write(self.status_path, data)
        return str(self.status_path)

    def write_digest(self, day: date, text: str) -> str:
        path = self.digest_dir / f"{day.isoformat()}.md"
        _atomic_write(path, text.encode("utf-8"))
        return str(path)

    def prune_digests(self, before: date) -> int:
        removed = 0
        for path in self.digest_dir.glob("*.md") if self.digest_dir.exists() else ():
            match = _DIGEST_KEY_RE.search(path.name)
            if match and date.fromisoformat(match.group(1)) < before:
                path.unlink(missing_ok=True)
                removed += 1
        return removed


class R2NewsRadarStore:
    """R2 objects under ``news/v1/``. The app's read-only token can read; writes need a writer."""

    def __init__(self, *, client: Any, bucket: str) -> None:
        self._client = client
        self.bucket = bucket

    @classmethod
    def from_settings(cls, settings: Settings) -> R2NewsRadarStore:
        import boto3
        from botocore.config import Config

        if not settings.r2_configured:
            raise NewsRadarIndexError("R2 is not configured")
        client = boto3.client(
            service_name="s3",
            endpoint_url=settings.resolved_r2_endpoint_url,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
            config=Config(connect_timeout=5, read_timeout=30, retries={"max_attempts": 2}),
        )
        bucket = settings.resolved_r2_bucket_name
        assert bucket is not None
        return cls(client=client, bucket=bucket)

    def describe(self) -> str:
        return f"r2:{self.bucket}/{NEWS_PREFIX}"

    def _get(self, key: str) -> dict[str, Any] | None:
        from botocore.exceptions import ClientError

        try:
            return self._client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise

    def read_index(self) -> NewsRadarIndex | None:
        from purchase_price.storage.streaming_gzip import write_verified_gzip_body

        response = self._get(INDEX_KEY)
        if response is None:
            return None
        body = response["Body"]
        try:
            size = int(response.get("ContentLength") or 0)
            if size > MAX_INDEX_STORED_BYTES:
                raise NewsRadarIndexError(f"news index is unexpectedly large: {size} bytes")
            metadata = response.get("Metadata") or {}
            if metadata.get("schema") != INDEX_SCHEMA or not metadata.get("sha256"):
                raise NewsRadarIndexError("news index metadata is invalid")
            with tempfile.TemporaryDirectory(prefix="news-radar-") as folder:
                destination = Path(folder) / "index.json"
                write_verified_gzip_body(
                    body,
                    destination,
                    expected_sha256=str(metadata["sha256"]),
                    invalid_gzip_message="news index is not valid gzip",
                    hash_mismatch_prefix="news index hash mismatch",
                )
                with destination.open("r", encoding="utf-8") as stream:
                    return index_from_payload(json.load(stream))
        finally:
            close = getattr(body, "close", None)
            if callable(close):
                close()

    def write_index(self, index: NewsRadarIndex) -> str:
        data = _index_bytes(index)
        self._client.put_object(
            Bucket=self.bucket,
            Key=INDEX_KEY,
            Body=gzip.compress(data, compresslevel=6, mtime=0),
            ContentType="application/json",
            ContentEncoding="gzip",
            Metadata={
                "schema": INDEX_SCHEMA,
                "sha256": hashlib.sha256(data).hexdigest(),
                "data-classification": DATA_CLASSIFICATION,
                "item-count": str(len(index.items)),
            },
        )
        return INDEX_KEY

    def read_statuses(self) -> dict[str, dict[str, Any]]:
        response = self._get(STATUS_KEY)
        if response is None:
            return {}
        payload = json.loads(response["Body"].read().decode("utf-8"))
        return statuses_from_payload(payload if isinstance(payload, Mapping) else None)

    def write_statuses(self, statuses: Mapping[str, Mapping[str, Any]], *, now: datetime) -> str:
        self._client.put_object(
            Bucket=self.bucket,
            Key=STATUS_KEY,
            Body=json.dumps(status_payload(statuses, now=now), ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
            Metadata={"schema": STATUS_SCHEMA, "data-classification": DATA_CLASSIFICATION},
        )
        return STATUS_KEY

    def write_digest(self, day: date, text: str) -> str:
        key = f"{DIGEST_PREFIX}/{day.isoformat()}.md"
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=text.encode("utf-8"),
            ContentType="text/markdown; charset=utf-8",
            Metadata={"schema": "news-radar-digest-v1", "data-classification": DATA_CLASSIFICATION},
        )
        return key

    def prune_digests(self, before: date) -> int:
        removed = 0
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self.bucket, "Prefix": f"{DIGEST_PREFIX}/", "MaxKeys": 1000}
            if token:
                kwargs["ContinuationToken"] = token
            response = self._client.list_objects_v2(**kwargs)
            for item in response.get("Contents") or []:
                key = str(item.get("Key") or "")
                match = _DIGEST_KEY_RE.search(key)
                if match and date.fromisoformat(match.group(1)) < before:
                    self._client.delete_object(Bucket=self.bucket, Key=key)
                    removed += 1
            if not response.get("IsTruncated"):
                return removed
            token = str(response.get("NextContinuationToken") or "") or None
            if token is None:
                return removed


def resolve_store(settings: Settings) -> NewsRadarStore | None:
    """Local file override first (review without R2), then R2, else None (Phase 1 behaviour)."""

    if settings.news_radar_index_path and settings.news_radar_index_path.strip():
        status = settings.news_radar_status_path
        return LocalNewsRadarStore(
            Path(settings.news_radar_index_path.strip()),
            Path(status.strip()) if status and status.strip() else None,
        )
    if settings.r2_configured:
        return R2NewsRadarStore.from_settings(settings)
    return None
