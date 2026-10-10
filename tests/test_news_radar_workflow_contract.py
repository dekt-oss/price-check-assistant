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
    assert 'cron: "*/30 * * * *"' in TEXT
    assert 'cron: "30 23 * * *"' in TEXT  # 08:30 KST
    assert "workflow_dispatch:" in TEXT
    assert "github.event.schedule == '*/30 * * * *'" in _job("collect")
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


def test_collect_job_loops_and_starts_its_own_next_run() -> None:
    job = _job("collect")
    assert "--loop-minutes 59" in job and "--interval-minutes 30" in job
    assert "timeout-minutes: 80" in job  # the loop plus setup fits inside the job timeout
    assert "actions: write" in job and "contents: read" in job
    assert "GH_TOKEN: ${{ github.token }}" in job
    assert "NEWS_RADAR_CHAIN: ${{ vars.NEWS_RADAR_CHAIN }}" in job  # kill switch
    assert "NEWS_RADAR_DAILY_CALL_CAP: ${{ vars.NEWS_RADAR_DAILY_CALL_CAP || '5000' }}" in job
    from purchase_price.services.news_radar_budget import DEFAULT_DAILY_CAP

    assert DEFAULT_DAILY_CAP == 5_000  # the workflow fallback and the Python default agree
    step = job.split("- name: Start the next collect run", 1)[1].split("- name:", 1)[0]
    assert "!cancelled() && github.ref == 'refs/heads/main'" in step
    assert "gh run list" in step and "--json databaseId,status,displayTitle" in step
    assert "purchase_price.scripts.next_news_radar_run" in step and '--run-id "$GITHUB_RUN_ID"' in step
    assert "--loop-summary artifacts/news-radar/collect.json" in step
    assert 'if [ "$next_run" = dispatch ]; then' in step
    assert "gh workflow run news-radar-collect.yml" in step and "--ref main -f mode=collect" in step
    # The collect step writes the summary the chain step reads, and the summary upload comes last.
    chain_step = job.index("- name: Start the next collect run")
    assert job.index("--summary-json artifacts/news-radar/collect.json") < chain_step
    assert chain_step < job.index("- name: Upload run summary")


def test_run_titles_separate_collect_from_digest_runs() -> None:
    from purchase_price.scripts.next_news_radar_run import COLLECT_RUN_TITLE

    head = TEXT.split("\non:", 1)[0]
    assert "run-name:" in head
    assert f"'{COLLECT_RUN_TITLE}'" in head and "'News Radar digest'" in head
    assert "github.event.schedule == '30 23 * * *' || inputs.mode == 'digest'" in head


def test_digest_job_cannot_start_runs() -> None:
    job = _job("daily-digest")
    assert "actions: write" not in job and "gh workflow run" not in job


def test_workflow_never_echoes_secrets_or_calls_ai() -> None:
    lowered = TEXT.casefold()
    for forbidden in ("anthropic", "openai", "deepseek", "echo $naver", "echo ${{ secrets"):
        assert forbidden not in lowered
    assert "permissions:\n  contents: read" in TEXT
