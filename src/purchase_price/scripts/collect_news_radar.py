"""Scheduled News Radar collector (GitHub Actions, every 30 minutes) and daily digest.

    python -m purchase_price.scripts.collect_news_radar                    # R2 (writer secrets)
    python -m purchase_price.scripts.collect_news_radar --output news.json # local file, no R2
    python -m purchase_price.scripts.collect_news_radar --mode digest      # 08:30 KST digest

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
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from purchase_price.clients.naver_news import MAX_DISPLAY, NaverNewsClient
from purchase_price.config import Settings
from purchase_price.services import news_alerts
from purchase_price.services import news_radar as radar
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


def run_collect(
    args: argparse.Namespace,
    settings: Settings,
    store: nri.NewsRadarStore,
    *,
    search: nri.SearchFn | None = None,
) -> dict[str, Any]:
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
                lambda text, display: client.search(text, display=display, sort="date"),
                groups=groups,
                display=args.display,
            )
        finally:
            client.close()
    else:
        result = nri.collect(index, keywords, search, groups=groups, display=args.display, pause_seconds=0)

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
    summary = run_collect(args, settings, store) if args.mode == "collect" else run_digest(args, store)
    rendered = json.dumps(summary, ensure_ascii=False, indent=2)
    print(rendered)
    if args.summary_json is not None:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(rendered + "\n", encoding="utf-8")
    if args.mode == "collect" and summary["keyword_count"] and summary["ok_count"] == 0:
        return 1  # every keyword failed: surface it as a failed job
    return 0


if __name__ == "__main__":
    sys.exit(main())
