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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from purchase_price.clients.naver_news import MAX_DISPLAY, NaverNewsClient
from purchase_price.config import Settings
from purchase_price.services import news_radar as radar
from purchase_price.services import news_radar_index as nri

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
    text = nri.immediate_alert_text(result, index.keywords_with_alert("immediate"))
    if result.bootstrap and result.run.new_count:
        alert = "skipped (first run backlog)"
    elif text is not None:
        url = (os.getenv(WEBHOOK_ENV) or "").strip()
        if args.no_alert:
            alert = "skipped (--no-alert)"
        elif not url:
            alert = "skipped (no webhook configured)"
        else:
            alert = post_webhook(url, text)

    run = result.run
    summary = {
        "mode": "collect",
        "store": store.describe(),
        "written": written,
        "item_count": len(index.items),
        "status_count": len(pruned),
        "alert": alert,
        **run.to_payload(include_logs=True),
    }
    lines = [
        "### 병원 News Radar 수집",
        "",
        f"- 키워드 {run.keyword_count}개 중 {run.ok_count}개 확인, 실패 {run.failed_count}개",
        f"- 새 기사 {run.new_count}건, 21일 지나 지운 기사 {run.purged_count}건, 보관 중 {len(index.items)}건",
        f"- 즉시 알림: {alert}",
    ]
    if run.failed_keywords:
        lines.append("- 실패 키워드: " + ", ".join(run.failed_keywords))
    _append_step_summary("\n".join(lines))
    return summary


def run_digest(args: argparse.Namespace, store: nri.NewsRadarStore, *, now: datetime | None = None) -> dict[str, Any]:
    current = now or datetime.now(UTC)
    index = store.read_index() or nri.NewsRadarIndex()
    text = nri.daily_digest_markdown(index, now=current)
    day = current.astimezone(nri.KST).date()
    written = store.write_digest(day, text)
    removed = store.prune_digests(day - timedelta(days=nri.RETENTION_DAYS))
    _append_step_summary(text)
    return {
        "mode": "digest",
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
