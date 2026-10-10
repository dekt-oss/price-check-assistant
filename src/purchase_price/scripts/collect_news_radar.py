"""Scheduled News Radar collector (GitHub Actions, every 30 minutes) and daily digest.

    python -m purchase_price.scripts.collect_news_radar                    # R2 (writer secrets)
    python -m purchase_price.scripts.collect_news_radar --output news.json # local file, no R2
    python -m purchase_price.scripts.collect_news_radar --loop-minutes 59 --interval-minutes 30  # a pass every 30 min
    python -m purchase_price.scripts.collect_news_radar --mode digest      # 08:30 KST digest

GitHub's schedule ran the "*/10" collector only five times on 2026-10-09, so one workflow run
now loops: a pass every ``--interval-minutes`` for ``--loop-minutes``, then the workflow starts
its own next run (``next_news_radar_run``). Every NAVER call is counted per KST day and a pass
that would cross the daily cap is skipped (``services/news_radar_budget.py``).

Collect mode searches every enabled keyword on NAVER (sort=date, up to 100 per keyword), folds
the results into the stored article list, purges anything older than 21 days and writes it back.
Keywords marked "immediate" post a title + link message to ``NEWS_ALERT_WEBHOOK_URL`` when new
articles appear (skipped when the variable is unset). Digest mode writes the last 24 hours of
"daily" keyword articles as markdown to ``news/v1/digest/YYYY-MM-DD.md`` and the GitHub step
summary, and removes digests older than 21 days.

NAVER results are display-only: nothing here sends them to an AI step, and the article summary
text is never read. Keys and the webhook address are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from purchase_price.clients.naver_news import MAX_DISPLAY, NaverNewsClient
from purchase_price.config import Settings
from purchase_price.services import news_alerts
from purchase_price.services import news_radar as radar
from purchase_price.services import news_radar_budget as budget
from purchase_price.services import news_radar_index as nri
from purchase_price.services import news_subscriptions as subs

WEBHOOK_ENV = "NEWS_ALERT_WEBHOOK_URL"


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=("collect", "digest"), default="collect")
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the article list to this local file instead of R2 (.gz suffix = gzip).",
    )
    parser.add_argument("--status-path", type=Path, help="Local status file (default: next to --output).")
    parser.add_argument("--keywords-file", type=Path, default=radar.DEFAULT_KEYWORD_FILE)
    parser.add_argument("--display", type=int, default=MAX_DISPLAY)
    parser.add_argument("--no-alert", action="store_true", help="Never post to the alert webhook.")
    parser.add_argument("--summary-json", type=Path, help="Also write the run summary to this file.")
    parser.add_argument(
        "--loop-minutes",
        type=float,
        default=0,
        help="Collect mode: keep running passes for this long (0 = one pass; NEWS_RADAR_CHAIN=off forces 0).",
    )
    parser.add_argument("--interval-minutes", type=float, default=10, help="Minutes between pass starts.")
    parser.add_argument(
        "--subscribers-dir",
        type=Path,
        help="Local subscriber records (default: the SUBSCRIBER_R2_* bucket when configured).",
    )
    return parser.parse_args(argv)


def _store(args: argparse.Namespace, settings: Settings) -> nri.NewsRadarStore:
    if args.output is not None:
        return nri.LocalNewsRadarStore(args.output, args.status_path)
    if not settings.r2_configured:
        raise SystemExit("R2 is not configured; pass --output PATH for a local run")
    return nri.R2NewsRadarStore.from_settings(settings)


def _append_step_summary(text: str) -> None:
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text.rstrip() + "\n")


KAKAO_TOKEN_KEY = "private/v1/kakao_refresh_token.json"


def _kakao_token_io(store: nri.NewsRadarStore):
    """Keep the refresh token Kakao re-issues (about monthly) in R2, so the GitHub secret only has
    to be set once. Local stores keep using the secret."""

    if not isinstance(store, nri.R2NewsRadarStore):
        return (lambda: None), None
    client, bucket = store._client, store.bucket

    def load() -> str | None:
        try:
            body = client.get_object(Bucket=bucket, Key=KAKAO_TOKEN_KEY)["Body"].read()
            return str(json.loads(body.decode("utf-8")).get("refresh_token") or "") or None
        except Exception:  # noqa: BLE001 - missing object or no access: fall back to the secret
            return None

    def save(token: str) -> None:
        client.put_object(
            Bucket=bucket,
            Key=KAKAO_TOKEN_KEY,
            Body=json.dumps({"refresh_token": token, "saved_at": datetime.now(UTC).isoformat()}).encode("utf-8"),
            ContentType="application/json",
        )

    return load, save


def _subscriber_store(args: argparse.Namespace) -> subs.SubscriberStore | None:
    if getattr(args, "subscribers_dir", None) is not None:
        return subs.LocalSubscriberStore(args.subscribers_dir)
    return subs.R2SubscriberStore.from_env(os.environ)


def _page_url() -> str:
    return (os.getenv(news_alerts.PAGE_URL_ENV) or news_alerts.DEFAULT_PAGE_URL).strip()


def run_subscriber_upkeep(store: subs.SubscriberStore | None, *, now: datetime | None = None) -> str:
    """Send confirmation mails for new requests and drop week-old unconfirmed ones."""

    if store is None:
        return "not configured"
    now = now or datetime.now(UTC)
    sent = failed = 0
    for subscriber in store.all():
        if not subscriber.needs_confirmation_mail:
            continue
        subject, body = subs.confirmation_mail(subscriber, _page_url())
        result = news_alerts.send_email(subject, body, os.environ, to=[subscriber.email])
        if result.status == "sent":
            store.put(replace(subscriber, confirm_sent_at=now))
            sent += 1
        else:
            failed += 1
    purged = subs.purge_stale(store, now=now)
    return f"확인 메일 {sent}건 발송, 실패 {failed}건, 만료 삭제 {purged}건"


def send_to_subscribers(
    store: subs.SubscriberStore | None, pref: str, subject: str, body: str
) -> str:
    """One message per confirmed subscriber (no shared To list), each with its unsubscribe link."""

    if store is None:
        return "구독 저장소 없음"
    people = subs.recipients(store, pref)
    results = [
        news_alerts.send_email(subject, body + subs.unsubscribe_footer(p, _page_url()), os.environ, to=[p.email])
        for p in people
    ]
    ok = sum(1 for r in results if r.status == "sent")
    return f"구독자 {len(people)}명 중 {ok}명 발송"


def post_webhook(url: str, text: str, *, transport: httpx.BaseTransport | None = None) -> str:
    """Teams/Slack-compatible ``{"text": ...}``; returns a status word, never raises or echoes the URL."""

    try:
        with httpx.Client(timeout=10.0, transport=transport) as client:
            response = client.post(url, json={"text": text})
    except httpx.HTTPError as exc:
        return f"failed ({type(exc).__name__})"
    return "sent" if 200 <= response.status_code < 300 else f"failed (HTTP {response.status_code})"


class CallCounter:
    """Counts NAVER search calls (a 429 retry is another call)."""

    def __init__(self) -> None:
        self.calls = 0

    def wrap(self, search: nri.SearchFn) -> nri.SearchFn:
        def counted(text: str, display: int) -> Sequence[Any]:
            self.calls += 1
            return search(text, display)

        return counted


def run_collect(
    args: argparse.Namespace,
    settings: Settings,
    store: nri.NewsRadarStore,
    *,
    search: nri.SearchFn | None = None,
    counter: CallCounter | None = None,
) -> dict[str, Any]:
    counter = counter or CallCounter()
    groups = radar.load_keyword_groups(args.keywords_file)
    keywords = radar.active_keywords(groups)
    index = store.read_index() or nri.NewsRadarIndex()

    if search is None:
        if not settings.naver_configured:
            raise SystemExit("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET are not configured")
        assert settings.naver_client_id is not None and settings.naver_client_secret is not None
        client = NaverNewsClient(
            settings.naver_client_id,
            settings.naver_client_secret,
            api_style=settings.naver_api_style,
            base_url=settings.naver_news_base_url,
            timeout_seconds=settings.naver_request_timeout_seconds,
        )
        try:
            result = nri.collect(
                index,
                keywords,
                counter.wrap(lambda text, display: client.search(text, display=display, sort="date")),
                groups=groups,
                display=args.display,
            )
        finally:
            client.close()
    else:
        result = nri.collect(
            index, keywords, counter.wrap(search), groups=groups, display=args.display, pause_seconds=0
        )

    written = store.write_index(index)

    statuses = store.read_statuses()
    pruned = nri.prune_statuses(statuses, index.items)
    if len(pruned) != len(statuses):
        store.write_statuses(pruned, now=datetime.now(UTC))

    alert = "not needed"
    tiers = radar.load_source_tiers()
    items = news_alerts.immediate_items(result.new_by_keyword, groups, tiers)
    if result.bootstrap and result.run.new_count:
        alert = "skipped (first run backlog)"
    elif items and args.no_alert:
        alert = "skipped (--no-alert)"
    elif items:
        load_token, save_token = _kakao_token_io(store)
        sent = news_alerts.dispatch(
            news_alerts.route(items, groups),
            kakao_refresh_token=load_token(),
            save_kakao_refresh_token=save_token,
        )
        alert = f"{len(items)}건 → " + ", ".join(f"{r.channel} {r.status}" for r in sent)
        ours = [i for i in items if "email" in {c for g in groups if g.key == i.group_key for c in g.notify}]
        if ours:
            subject = f"[병원 News Radar] {ours[0].keyword} 등 새 기사 {len(ours)}건"
            alert += ", " + send_to_subscribers(
                _subscriber_store(args),
                subs.PREF_IMMEDIATE,
                subject,
                news_alerts.long_text(ours, _page_url()),
            )
    upkeep = "skipped (--no-alert)" if args.no_alert else run_subscriber_upkeep(_subscriber_store(args))

    run = result.run
    summary = {
        "mode": "collect",
        "store": store.describe(),
        "written": written,
        "item_count": len(index.items),
        "status_count": len(pruned),
        "alert": alert,
        "subscribers": upkeep,
        "naver_calls": counter.calls,
        **run.to_payload(include_logs=True),
    }
    lines = [
        "### 병원 News Radar 수집",
        "",
        f"- 키워드 {run.keyword_count}개 중 {run.ok_count}개 확인, 실패 {run.failed_count}개",
        f"- 새 기사 {run.new_count}건, 21일 지나 지운 기사 {run.purged_count}건, 보관 중 {len(index.items)}건",
        f"- 즉시 알림: {alert}",
        f"- 이메일 구독: {upkeep}",
    ]
    if run.failed_keywords:
        lines.append("- 실패 키워드: " + ", ".join(run.failed_keywords))
    _append_step_summary("\n".join(lines))
    return summary


def usage_state(args: argparse.Namespace, settings: Settings) -> budget.JsonState | None:
    """Where the daily NAVER call count lives: next to --output locally, R2 operational state otherwise."""

    if args.output is not None:
        return budget.LocalJsonState(args.output.parent)
    try:
        from purchase_price.storage.r2_state import R2OperationalStateStore

        return R2OperationalStateStore.from_settings(settings)
    except Exception as exc:  # noqa: BLE001 - counting must never stop the news collection
        print(f"NAVER call counter unavailable: {type(exc).__name__}", file=sys.stderr)
        return None


def _used_today(state: budget.JsonState | None) -> int | None:
    if state is None:
        return None
    try:
        return budget.used_today(state)
    except Exception as exc:  # noqa: BLE001
        print(f"NAVER call count unreadable: {type(exc).__name__}", file=sys.stderr)
        return None


def _record(state: budget.JsonState | None, calls: int) -> int | None:
    if state is None:
        return None
    try:
        return budget.record_calls(state, calls)
    except Exception as exc:  # noqa: BLE001
        print(f"NAVER call count not saved: {type(exc).__name__}", file=sys.stderr)
        return None


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


def run_loop(
    args: argparse.Namespace,
    settings: Settings,
    store: nri.NewsRadarStore,
    state: budget.JsonState | None,
    *,
    search: nri.SearchFn | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Collect passes every ``--interval-minutes`` until ``--loop-minutes`` have passed.

    The run then waits out the window, so the next chained run's first pass lands about one
    interval after this run's last one. A failed pass never stops the loop; a pass that would
    cross the daily NAVER call cap is skipped.
    """

    chain = budget.chain_enabled()
    loop_seconds = max(0.0, float(args.loop_minutes) * 60) if chain else 0.0
    interval_seconds = max(60.0, float(args.interval_minutes) * 60)
    cap = budget.daily_cap()
    keyword_count = len(radar.active_keywords(radar.load_keyword_groups(args.keywords_file)))
    started = clock()
    offsets = [0.0]
    while offsets[-1] + interval_seconds < loop_seconds:
        offsets.append(offsets[-1] + interval_seconds)

    passes: list[dict[str, Any]] = []
    calls_today = _used_today(state)
    for offset in offsets:
        wait = (started + timedelta(seconds=offset) - clock()).total_seconds()
        if wait > 0:
            sleep(wait)
        if offset and (clock() - started).total_seconds() >= loop_seconds:
            break  # a slow pass pushed this slot past the window; the next run takes it
        entry: dict[str, Any] = {"started_at": _utc_text(clock())}
        used = _used_today(state)
        if used is not None:
            calls_today = used
            if used + keyword_count > cap:
                entry.update(status="skipped", reason=f"하루 호출 상한 {cap:,}건 도달 (오늘 {used:,}건)")
                passes.append(entry)
                continue
        counter = CallCounter()
        try:
            summary = run_collect(args, settings, store, search=search, counter=counter)
        except Exception as exc:  # noqa: BLE001 - keep looping; the next pass may work
            entry.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:300])
        else:
            all_failed = bool(summary["keyword_count"]) and summary["ok_count"] == 0
            entry.update(status="failed" if all_failed else "ok", summary=summary)
        entry["naver_calls"] = counter.calls
        recorded = _record(state, counter.calls)
        if recorded is not None:
            calls_today = recorded
        elif calls_today is not None:
            calls_today += counter.calls
        passes.append(entry)

    if loop_seconds:
        wait = (started + timedelta(seconds=loop_seconds) - clock()).total_seconds()
        if wait > 0:
            sleep(wait)
    return {
        "mode": "collect",
        "chain": chain,
        "started_at": _utc_text(started),
        "finished_at": _utc_text(clock()),
        "loop_seconds": loop_seconds,
        "interval_seconds": interval_seconds,
        "keyword_count": keyword_count,
        "daily_call_cap": cap,
        "naver_calls": sum(int(p.get("naver_calls") or 0) for p in passes),
        "naver_calls_today": calls_today,
        "ok_passes": sum(1 for p in passes if p["status"] == "ok"),
        "failed_passes": sum(1 for p in passes if p["status"] == "failed"),
        "skipped_passes": sum(1 for p in passes if p["status"] == "skipped"),
        "passes": passes,
    }


def run_digest(args: argparse.Namespace, store: nri.NewsRadarStore, *, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    index = store.read_index() or nri.NewsRadarIndex()
    digest_keywords = [k for g in radar.load_keyword_groups(args.keywords_file) for k in g.keywords]
    text = nri.daily_digest_markdown(
        index, now=current, keywords=digest_keywords, tiers=radar.load_source_tiers())
    day = current.astimezone(nri.KST).date()
    written = store.write_digest(day, text)
    removed = store.prune_digests(day - timedelta(days=nri.RETENTION_DAYS))
    _append_step_summary(text)
    mailed = send_to_subscribers(
        _subscriber_store(args),
        subs.PREF_DAILY,
        f"[병원 News Radar] {day.isoformat()} 병원 동향 요약",
        text,
    )
    return {
        "mode": "digest",
        "mailed": mailed,
        "store": store.describe(),
        "written": written,
        "day": day.isoformat(),
        "removed_old_digests": removed,
        "line_count": len(text.splitlines()),
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    settings = Settings()
    store = _store(args, settings)
    if args.mode == "collect":
        summary = run_loop(args, settings, store, usage_state(args, settings))
    else:
        summary = run_digest(args, store)
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    print(rendered)
    if args.summary_json is not None:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(rendered + "\n", encoding="utf-8")
    if args.mode == "collect" and summary["failed_passes"] and not summary["ok_passes"]:
        return 1  # every pass failed: surface it as a failed job
    return 0


if __name__ == "__main__":
    sys.exit(main())
