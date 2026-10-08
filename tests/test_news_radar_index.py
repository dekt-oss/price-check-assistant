"""News Radar Phase 2: stored article list, 21-day purge, statuses, alerts and digest."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from purchase_price.clients.naver_news import NaverNewsClientError, NaverNewsItem
from purchase_price.services import news_radar as radar
from purchase_price.services import news_radar_index as nri

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 8, 9, 30, tzinfo=KST)
KW_IMMEDIATE = radar.Keyword("부산백병원", "our_hospital", "우리병원", "immediate")
KW_DAILY = radar.Keyword("병원 AI 도입", "ai_digital", "AI·디지털", "daily")


def _item(url: str, title: str = "제목", published: datetime | None = NOW) -> NaverNewsItem:
    return NaverNewsItem(
        title=title,
        link="https://n.news.naver.com/x",
        original_link=url,
        published_at=published,
        source_domain="example.co.kr",
    )


def _groups() -> tuple[radar.KeywordGroup, ...]:
    return (
        radar.KeywordGroup("our_hospital", "우리병원", True, (KW_IMMEDIATE,)),
        radar.KeywordGroup("ai_digital", "AI·디지털", True, (KW_DAILY,)),
    )


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.value = start

    def __call__(self) -> datetime:
        return self.value


def test_merge_dedupes_by_article_id_and_keeps_first_detected_time() -> None:
    index = nri.NewsRadarIndex()
    added = nri.merge_scan(index, KW_IMMEDIATE, [_item("https://a.kr/1?utm_source=x")], now=NOW)
    assert len(added) == 1
    later = NOW + timedelta(hours=2)
    again = nri.merge_scan(index, KW_DAILY, [_item("https://www.a.kr/1/")], now=later)
    assert again == []
    (entry,) = index.items.values()
    assert entry.detected_at == NOW
    assert entry.keywords == ("부산백병원", "병원 AI 도입")


def test_merge_skips_articles_published_before_the_window() -> None:
    index = nri.NewsRadarIndex()
    old = NOW - timedelta(days=nri.RETENTION_DAYS + 1)
    added = nri.merge_scan(index, KW_DAILY, [_item("https://a.kr/old", published=old)], now=NOW)
    assert added == [] and index.items == {}


def test_purge_drops_items_older_than_21_days() -> None:
    index = nri.NewsRadarIndex()
    nri.merge_scan(index, KW_DAILY, [_item("https://a.kr/1")], now=NOW)
    nri.merge_scan(
        index, KW_DAILY, [_item("https://a.kr/2", published=None)], now=NOW + timedelta(days=15)
    )
    purged = nri.purge_expired(index, now=NOW + timedelta(days=nri.RETENTION_DAYS, minutes=1))
    assert purged == 1
    assert list(index.items) == [radar.article_id("https://a.kr/2")]


def test_collect_records_keyword_logs_and_retries_429() -> None:
    calls: list[str] = []
    attempts = {"n": 0}

    def search(text: str, display: int):
        calls.append(text)
        assert display == 100
        if text == KW_IMMEDIATE.text:
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise NaverNewsClientError("HTTP 429", status_code=429)
            return [_item("https://a.kr/1")]
        raise NaverNewsClientError("NAVER 뉴스 검색 오류 HTTP 401", status_code=401)

    sleeps: list[float] = []
    index = nri.NewsRadarIndex()
    result = nri.collect(
        index,
        [KW_IMMEDIATE, KW_DAILY],
        search,
        groups=_groups(),
        clock=_Clock(NOW),
        sleep=sleeps.append,
    )
    assert calls == [KW_IMMEDIATE.text, KW_IMMEDIATE.text, KW_DAILY.text]
    assert 2.0 in sleeps  # 429 backoff
    run = result.run
    assert (run.ok_count, run.failed_count, run.new_count) == (1, 1, 1)
    assert run.failed_keywords == (KW_DAILY.text,)
    assert result.bootstrap is True
    log = run.logs[1].to_payload()
    assert log["source_name"] == "naver_news" and log["query_text"] == KW_DAILY.text
    assert "401" in log["error_message"]
    assert index.keywords_with_alert("immediate") == {KW_IMMEDIATE.text}


def test_429_gives_up_after_retries() -> None:
    def search(text: str, display: int):
        raise NaverNewsClientError("HTTP 429", status_code=429)

    with pytest.raises(NaverNewsClientError):
        nri.search_with_backoff(search, "x", 10, retries=2, sleep=lambda _s: None)


def test_index_round_trip_has_display_fields_only() -> None:
    index = nri.NewsRadarIndex()
    nri.collect(
        index, [KW_IMMEDIATE], lambda t, d: [_item("https://a.kr/1")], groups=_groups(), clock=_Clock(NOW)
    )
    payload = nri.index_to_payload(index)
    assert payload["version"] == nri.INDEX_VERSION and payload["retention_days"] == 21
    assert set(payload["items"][0]) == {
        "article_id",
        "title",
        "url",
        "naver_link",
        "source_domain",
        "published_at",
        "keywords",
        "detected_at",
    }
    assert "description" not in json.dumps(payload)
    restored = nri.index_from_payload(json.loads(json.dumps(payload)))
    assert restored.items == index.items
    assert restored.last_run is not None
    assert restored.last_run.logs[0].keyword == KW_IMMEDIATE.text


def test_unknown_index_version_is_rejected() -> None:
    with pytest.raises(nri.NewsRadarIndexError):
        nri.index_from_payload({"version": 99, "items": []})


def test_status_overlay_prune_and_session_priority() -> None:
    index = nri.NewsRadarIndex()
    nri.merge_scan(index, KW_DAILY, [_item("https://a.kr/1"), _item("https://a.kr/2")], now=NOW)
    id1, id2 = sorted(index.items)
    statuses: dict = {}
    nri.set_status(statuses, id1, radar.STATUS_IMPORTANT, now=NOW)
    nri.set_status(statuses, "gone", radar.STATUS_READ, now=NOW)
    nri.set_status(statuses, id2, radar.STATUS_READ, now=NOW)
    nri.set_status(statuses, id2, radar.STATUS_NEW, now=NOW)  # back to default removes the row
    assert set(statuses) == {id1, "gone"}
    assert set(nri.prune_statuses(statuses, index.items)) == {id1}
    with pytest.raises(ValueError):
        nri.set_status(statuses, id1, "bogus", now=NOW)

    restored = nri.statuses_from_payload(nri.status_payload(statuses, now=NOW))
    overlaid = {e.article_id: e.status for e in nri.overlay_statuses(index.items.values(), restored)}
    assert overlaid == {id1: radar.STATUS_IMPORTANT, id2: radar.STATUS_NEW}

    state = radar.NewsRadarState()
    live = radar.NewsEntry("live", "실시간", "https://b.kr/9", "", "b.kr", NOW, ("x",), NOW)
    state.entries["live"] = live
    nri.seed_state(state, index, restored, session_statuses={id1: radar.STATUS_IGNORED})
    assert state.entries[id1].status == radar.STATUS_IGNORED
    assert state.entries[id2].status == radar.STATUS_NEW
    assert "live" in state.entries


def test_immediate_alert_text_is_title_and_link_only_and_skips_bootstrap() -> None:
    index = nri.NewsRadarIndex()
    first = nri.collect(
        index, [KW_IMMEDIATE], lambda t, d: [_item("https://a.kr/1")], clock=_Clock(NOW)
    )
    assert nri.immediate_alert_text(first, {KW_IMMEDIATE.text}) is None
    second = nri.collect(
        index,
        [KW_IMMEDIATE, KW_DAILY],
        lambda t, d: [_item("https://a.kr/1"), _item(f"https://a.kr/{t}", title="새 소식")],
        clock=_Clock(NOW + timedelta(minutes=30)),
    )
    text = nri.immediate_alert_text(second, {KW_IMMEDIATE.text})
    assert text is not None
    assert text.splitlines() == [
        "병원 News Radar 새 기사 1건",
        "- [부산백병원] 새 소식",
        f"  https://a.kr/{KW_IMMEDIATE.text}",
    ]
    assert nri.immediate_alert_text(second, set()) is None


def test_daily_digest_lists_last_24_hours_of_daily_keywords() -> None:
    index = nri.NewsRadarIndex()
    nri.collect(
        index, [KW_DAILY], lambda t, d: [_item("https://a.kr/old")], groups=_groups(), clock=_Clock(NOW)
    )
    later = NOW + timedelta(days=2)
    nri.collect(
        index,
        [KW_IMMEDIATE, KW_DAILY],
        lambda t, d: [_item(f"https://a.kr/{t}", title="[단독] 새 [AI]", published=later)],
        groups=_groups(),
        clock=_Clock(later),
    )
    text = nri.daily_digest_markdown(index, now=later + timedelta(hours=1))
    assert text.startswith("# 병원 News Radar 하루 요약 2026-10-10")
    assert "## 병원 AI 도입 (1건)" in text
    assert f"- [(단독) 새 (AI)](https://a.kr/{KW_DAILY.text}) · example.co.kr · 10-10 09:30" in text
    assert "부산백병원" not in text  # immediate keyword is not part of the daily digest
    assert "a.kr/old" not in text
    empty = nri.daily_digest_markdown(nri.NewsRadarIndex(), now=NOW)
    assert "새 기사가 없습니다." in empty


def test_local_store_round_trip(tmp_path) -> None:
    store = nri.LocalNewsRadarStore(tmp_path / "news.json.gz")
    assert store.read_index() is None and store.read_statuses() == {}
    index = nri.NewsRadarIndex()
    nri.collect(
        index, [KW_DAILY], lambda t, d: [_item("https://a.kr/1")], groups=_groups(), clock=_Clock(NOW)
    )
    store.write_index(index)
    assert store.read_index().items == index.items
    statuses = nri.set_status({}, next(iter(index.items)), radar.STATUS_READ, now=NOW)
    store.write_statuses(statuses, now=NOW)
    assert store.read_statuses() == statuses
    store.write_digest(date(2026, 9, 1), "old")
    store.write_digest(date(2026, 10, 8), "new")
    assert store.prune_digests(date(2026, 9, 17)) == 1
    assert [p.name for p in store.digest_dir.glob("*.md")] == ["2026-10-08.md"]


class _FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}

    def put_object(self, *, Bucket, Key, Body, Metadata=None, **_kw):  # noqa: N803
        self.objects[Key] = {"Body": Body, "Metadata": dict(Metadata or {})}

    def get_object(self, *, Bucket, Key):  # noqa: N803
        from botocore.exceptions import ClientError

        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        obj = self.objects[Key]
        return {
            "Body": io.BytesIO(obj["Body"]),
            "Metadata": obj["Metadata"],
            "ContentLength": len(obj["Body"]),
        }

    def list_objects_v2(self, *, Bucket, Prefix, **_kw):  # noqa: N803
        return {"Contents": [{"Key": k} for k in sorted(self.objects) if k.startswith(Prefix)]}

    def delete_object(self, *, Bucket, Key):  # noqa: N803
        self.objects.pop(Key, None)


def test_r2_store_streams_verified_index_and_statuses() -> None:
    s3 = _FakeS3()
    store = nri.R2NewsRadarStore(client=s3, bucket="b")
    assert store.read_index() is None and store.read_statuses() == {}
    index = nri.NewsRadarIndex()
    nri.collect(
        index, [KW_DAILY], lambda t, d: [_item("https://a.kr/1")], groups=_groups(), clock=_Clock(NOW)
    )
    assert store.write_index(index) == "news/v1/index.json.gz"
    stored = s3.objects[nri.INDEX_KEY]
    raw = gzip.decompress(stored["Body"])
    assert stored["Metadata"]["sha256"] == hashlib.sha256(raw).hexdigest()
    assert store.read_index().items == index.items

    stored["Metadata"]["sha256"] = "0" * 64
    with pytest.raises(Exception, match="hash mismatch"):
        store.read_index()

    statuses = nri.set_status({}, "x", radar.STATUS_IMPORTANT, now=NOW)
    store.write_statuses(statuses, now=NOW)
    assert store.read_statuses() == statuses
    store.write_digest(date(2026, 9, 1), "old")
    store.write_digest(date(2026, 10, 8), "new")
    assert store.prune_digests(date(2026, 9, 17)) == 1
    assert "news/v1/digest/2026-10-08.md" in s3.objects


def test_resolve_store_prefers_local_path(tmp_path) -> None:
    from purchase_price.config import Settings

    settings = Settings(_env_file=None, news_radar_index_path=str(tmp_path / "i.json"))
    store = nri.resolve_store(settings)
    assert isinstance(store, nri.LocalNewsRadarStore)
    assert store.status_path == tmp_path / "i-status.json"


def test_times_are_shown_in_korean_time_even_on_a_utc_server() -> None:
    from datetime import UTC

    utc_value = datetime(2026, 10, 8, 10, 48, tzinfo=UTC)
    assert radar.seoul_time_text(utc_value) == "10-08 19:48"
    assert radar.seoul_time_text(utc_value, "%H:%M") == "19:48"
    assert radar.seoul_time_text(datetime(2026, 10, 8, 15, 30, tzinfo=UTC)) == "10-09 00:30"
    assert radar.seoul_time_text(None) == "시간 확인 안 됨"
    # An article at 23:30 UTC on 10-07 is "today" (10-08) in Korea.
    entry = radar.NewsEntry(
        "a", "t", "https://a.kr", "", "a.kr", datetime(2026, 10, 7, 23, 30, tzinfo=UTC), ("k",), NOW
    )
    assert radar.summarize([entry], today=date(2026, 10, 8)).today == 1
