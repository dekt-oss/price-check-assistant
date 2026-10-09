"""Contract for the scheduled News Radar workflow (text checks; CI has no YAML parser pinned)."""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "news-radar-collect.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")


def _job(name: str) -> str:
    match = re.search(rf"^  {name}:\n(.*?)(?=^  [a-z-]+:\n|\Z)", TEXT, flags=re.M | re.S)
    assert match, name
    return match.group(1)


def test_schedules_and_manual_trigger() -> None:
    assert 'cron: "*/10 * * * *"' in TEXT
    assert 'cron: "30 23 * * *"' in TEXT  # 08:30 KST
    assert "workflow_dispatch:" in TEXT
    assert "github.event.schedule == '*/10 * * * *'" in _job("collect")
    assert "github.event.schedule == '30 23 * * *'" in _job("daily-digest")


def test_collect_job_secrets_concurrency_and_python() -> None:
    job = _job("collect")
    for secret in (
        "NAVER_CLIENT_ID",
        "NAVER_CLIENT_SECRET",
        "R2_ACCOUNT_ID",
        "R2_BUCKET",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "NEWS_ALERT_WEBHOOK_URL",
    ):
        assert f"{secret}: ${{{{ secrets.{secret} }}}}" in job, secret
    assert "group: news-radar-collect" in job
    assert "cancel-in-progress: false" in job
    assert 'python-version: "3.11"' in job
    assert "purchase_price.scripts.collect_news_radar" in job and "--mode collect" in job


def test_digest_job_uses_r2_only_and_its_own_group() -> None:
    job = _job("daily-digest")
    assert "NAVER_CLIENT" not in job  # the digest never calls NAVER
    assert "secrets.R2_ACCESS_KEY_ID" in job
    assert "group: news-radar-digest" in job and "cancel-in-progress: false" in job
    assert "--mode digest" in job


def test_workflow_never_echoes_secrets_or_calls_ai() -> None:
    lowered = TEXT.casefold()
    for forbidden in ("anthropic", "openai", "deepseek", "echo $naver", "echo ${{ secrets"):
        assert forbidden not in lowered
    assert "permissions:\n  contents: read" in TEXT
