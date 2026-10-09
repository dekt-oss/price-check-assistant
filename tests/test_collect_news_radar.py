"""Collector CLI: local store, status pruning, webhook alert and digest (no network)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx

from purchase_price.clients.naver_news import NaverNewsItem
from purchase_price.config import Settings
from purchase_price.scripts import collect_news_radar as cli
from purchase_price.services import news_alerts
from purchase_price.services import news_radar as radar
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
