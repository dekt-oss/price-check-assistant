"""Collector CLI: local store, status pruning, webhook alert and digest (no network)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx

from purchase_price.clients.naver_news import NaverNewsClientError, NaverNewsItem
from purchase_price.config import Settings
from purchase_price.scripts import collect_news_radar as cli
from purchase_price.services import news_alerts
from purchase_price.services import news_radar as radar
from purchase_price.services import news_radar_budget as budget
from purchase_price.services import news_radar_index as nri


def _keywords_file(tmp_path):
    path = tmp_path / "keywords.json"
    path.write_text(
        json.dumps(
            {
                "groups": [
                    {
                        "key": "g",
                        "name": "우리병원",
                        "keywords": [
                            {"text": "부산백병원", "alert": "immediate"},
                            {"text": "병원 AI 도입", "alert": "daily"},
                        ],
                    },
                    {"key": "off", "name": "꺼진 그룹", "enabled": False, "keywords": [{"text": "꺼짐"}]},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _search_factory(urls_by_keyword):
    calls: list[str] = []

    def search(text: str, display: int):
        calls.append(text)
        now = datetime.now(UTC)
        return [
            NaverNewsItem(f"{text} 기사", "https://n.news.naver.com/x", url, now, "a.kr")
            for url in urls_by_keyword.get(text, [])
        ]

    return search, calls


def test_collect_writes_local_index_alerts_only_after_bootstrap(tmp_path, monkeypatch) -> None:
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))
    monkeypatch.setenv(cli.WEBHOOK_ENV, "https://hooks.example/abc")
    sent: list[dict] = []
    monkeypatch.setattr(
        news_alerts,
        "send_webhook",
        lambda text, env, transport=None: sent.append({"text": text}) or news_alerts.SendResult("webhook", "sent"),
    )
    args = cli._parse_args(["--output", str(tmp_path / "news.json.gz"), "--keywords-file", str(_keywords_file(tmp_path))])
    store = cli._store(args, Settings(_env_file=None))

    search, calls = _search_factory({"부산백병원": ["https://a.kr/1"]})
    first = cli.run_collect(args, Settings(_env_file=None), store, search=search)
    assert calls == ["부산백병원", "병원 AI 도입"]  # disabled group is not searched
    assert first["alert"] == "skipped (first run backlog)" and sent == []
    assert first["item_count"] == 1 and first["ok_count"] == 2

    article = next(iter(store.read_index().items))
    store.write_statuses({article: {"status": "read"}, "gone": {"status": "read"}}, now=datetime.now(UTC))

    search, _ = _search_factory({"부산백병원": ["https://a.kr/1", "https://a.kr/2"], "병원 AI 도입": ["https://a.kr/3"]})
    second = cli.run_collect(args, Settings(_env_file=None), store, search=search)
    assert second["new_count"] == 2 and second["alert"] == "1건 → webhook sent"
    (message,) = sent
    assert "https://a.kr/2" in message["text"] and "https://a.kr/3" not in message["text"]
    assert set(store.read_statuses()) == {article}  # statuses of vanished articles are pruned
    assert "새 기사 2건" in summary_path.read_text(encoding="utf-8")


def test_collect_without_webhook_skips_silently(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(cli.WEBHOOK_ENV, raising=False)
    args = cli._parse_args(["--output", str(tmp_path / "n.json"), "--keywords-file", str(_keywords_file(tmp_path))])
    store = cli._store(args, Settings(_env_file=None))
    cli.run_collect(args, Settings(_env_file=None), store, search=_search_factory({})[0])
    search, _ = _search_factory({"부산백병원": ["https://a.kr/9"]})
    assert cli.run_collect(args, Settings(_env_file=None), store, search=search)["alert"] == (
        "1건 → webhook skipped (not configured)"
    )


def test_post_webhook_sends_text_json_and_hides_url() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(500 if b"fail" in request.content else 200)

    transport = httpx.MockTransport(handler)
    assert cli.post_webhook("https://hooks.example/secret", "안녕", transport=transport) == "sent"
    assert json.loads(seen[0].content) == {"text": "안녕"}
    status = cli.post_webhook("https://hooks.example/secret", "fail", transport=transport)
    assert status == "failed (HTTP 500)" and "secret" not in status


def test_digest_mode_writes_markdown_and_prunes_old_files(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    store = nri.LocalNewsRadarStore(tmp_path / "news.json")
    index = nri.NewsRadarIndex()
    groups = radar.load_keyword_groups(_keywords_file(tmp_path))
    now = datetime(2026, 10, 7, 23, 30, tzinfo=UTC)  # 08:30 KST on 10-08
    keyword = radar.active_keywords(groups)[1]
    nri.collect(
        index,
        [keyword],
        lambda t, d: [NaverNewsItem("병원 AI 도입 기사", "", "https://a.kr/ai", now - timedelta(hours=1), "a.kr")],
        groups=groups,
        clock=lambda: now - timedelta(hours=1),
    )
    store.write_index(index)
    store.write_digest(datetime(2026, 9, 1).date(), "old")
    args = cli._parse_args(["--mode", "digest", "--output", str(tmp_path / "news.json")])
    result = cli.run_digest(args, store, now=now)
    assert result["day"] == "2026-10-08" and result["removed_old_digests"] == 1
    text = (store.digest_dir / "2026-10-08.md").read_text(encoding="utf-8")
    assert "[병원 AI 도입 기사](https://a.kr/ai) · a.kr · 10-08 07:30" in text


class _FakeClock:
    """Clock + sleep pair: sleeping moves the clock; each search takes ``search_seconds``."""

    def __init__(self, search_seconds: float = 15.0) -> None:
        self.now = datetime(2026, 10, 10, 3, 0, tzinfo=UTC)
        self.search_seconds = search_seconds
        self.sleeps: list[float] = []

    def __call__(self) -> datetime:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += timedelta(seconds=seconds)


def _loop_args(tmp_path, *extra: str):
    return cli._parse_args(
        [
            "--output",
            str(tmp_path / "news.json.gz"),
            "--keywords-file",
            str(_keywords_file(tmp_path)),
            "--no-alert",
            *extra,
        ]
    )


def _timed_search(clock: _FakeClock, *, fail: bool = False):
    calls: list[str] = []

    def search(text: str, display: int):
        calls.append(text)
        clock.now += timedelta(seconds=clock.search_seconds)
        if fail:
            raise NaverNewsClientError("NAVER 뉴스 검색 오류 HTTP 500", status_code=500)
        return [NaverNewsItem(f"{text} 기사", "", f"https://a.kr/{len(calls)}", clock.now, "a.kr")]

    return search, calls


def _loop(args, state, clock, search):
    settings = Settings(_env_file=None)
    store = cli._store(args, settings)
    summary = cli.run_loop(args, settings, store, state, search=search, clock=clock, sleep=clock.sleep)
    return summary, store


def test_loop_runs_a_pass_every_ten_minutes_and_counts_naver_calls(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(budget.CHAIN_ENV, raising=False)
    monkeypatch.delenv(budget.CAP_ENV, raising=False)
    args = _loop_args(tmp_path, "--loop-minutes", "49", "--interval-minutes", "10")
    state = cli.usage_state(args, Settings(_env_file=None))
    clock = _FakeClock()
    search, calls = _timed_search(clock)

    summary, store = _loop(args, state, clock, search)

    assert [p["started_at"][11:16] for p in summary["passes"]] == ["03:00", "03:10", "03:20", "03:30", "03:40"]
    assert summary["finished_at"] == "2026-10-10T03:49:00+00:00"  # waits out the window
    assert summary["ok_passes"] == 5 and summary["failed_passes"] == 0 and summary["chain"] is True
    assert len(calls) == 10 and summary["naver_calls"] == 10 and summary["naver_calls_today"] == 10
    assert budget.used_today(state) == 10
    assert len(store.read_index().runs) == 5


def test_loop_is_a_single_pass_when_the_chain_is_off(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(budget.CHAIN_ENV, "off")
    args = _loop_args(tmp_path, "--loop-minutes", "49")
    clock = _FakeClock()
    search, _ = _timed_search(clock)
    summary, _ = _loop(args, None, clock, search)
    assert summary["chain"] is False and len(summary["passes"]) == 1 and clock.sleeps == []
    assert summary["naver_calls_today"] is None  # no counter: unknown, not zero


def test_loop_skips_passes_that_would_cross_the_daily_cap(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(budget.CHAIN_ENV, raising=False)
    monkeypatch.setenv(budget.CAP_ENV, "5")
    args = _loop_args(tmp_path, "--loop-minutes", "29")
    state = cli.usage_state(args, Settings(_env_file=None))
    clock = _FakeClock()
    search, calls = _timed_search(clock)
    summary, _ = _loop(args, state, clock, search)
    # 2 keywords a pass, cap 5: passes 1 and 2 run (2, then 4 calls), pass 3 would make 6.
    assert [p["status"] for p in summary["passes"]] == ["ok", "ok", "skipped"]
    assert "하루 호출 상한 5건" in summary["passes"][2]["reason"]
    assert len(calls) == 4 and summary["skipped_passes"] == 1


def test_loop_keeps_going_after_failed_passes_and_main_marks_all_failed(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(budget.CHAIN_ENV, raising=False)
    monkeypatch.delenv(budget.CAP_ENV, raising=False)
    args = _loop_args(tmp_path, "--loop-minutes", "19")
    clock = _FakeClock()
    search, _ = _timed_search(clock, fail=True)
    summary, _ = _loop(args, None, clock, search)
    assert [p["status"] for p in summary["passes"]] == ["failed", "failed"]
    assert summary["naver_calls"] == 4  # 2 passes x 2 keywords; HTTP 500 is not retried


def test_loop_drops_a_slot_that_a_slow_pass_pushed_past_the_window(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(budget.CHAIN_ENV, raising=False)
    args = _loop_args(tmp_path, "--loop-minutes", "19")
    clock = _FakeClock(search_seconds=10 * 60)  # a pass takes 20 minutes
    search, _ = _timed_search(clock)
    summary, _ = _loop(args, None, clock, search)
    assert len(summary["passes"]) == 1 and clock.sleeps == []
