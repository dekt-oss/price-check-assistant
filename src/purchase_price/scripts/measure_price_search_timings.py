"""Measure how long a price search takes in the running app (UX v1.1 Phase P2a).

Opens ``<url>?q=<query>`` for each query in a headless browser, waits for the conclusion card
(or the empty state), and records:

* ``wall``: seconds from navigation to the card, as the reader waits (browser clock)
* the server stages from the hidden ``#purchase-search-timings-v2`` marker (start-up index wait,
  cold flag, identity, same-model trades, category market, live check, safety, total)
* ``render_card`` from ``#purchase-render-timings-v1``
* ``wall_done``: seconds until ``#purchase-deferred-timings-v1``, written once the same-품목
  models below the card are built (review D-02), with where they ran (``same_item_when``) and
  their ``same_item_models`` / ``category_market`` seconds

Samples go to a JSON file and, with ``--r2``, into a rolling R2 state object
(``state/v1/perf/price-search-timings.json``, newest ``MAX_SAMPLES``) so a week of scheduled runs
gives the baseline in ``docs/performance/UX_V11_PRICE_BASELINE.md``. ``--summary`` prints median
and 90th percentile per model and stage, split by cold and warm searches. A stage the page did not
report is counted as missing, never as 0 seconds.

Playwright is imported lazily: the CI workflow installs it, the app venv does not need it.

    python -m purchase_price.scripts.measure_price_search_timings --output timings.json --summary
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any
from urllib.parse import quote

DEFAULT_URL = "https://bp-price-research.streamlit.app/"
# A dense model, a model without trades, a model with entry errors and outliers, a PC.
DEFAULT_QUERIES = ("PNB-704", "SJ-DFM100", "HeartOn A16-DS", "NT960XJG-K72AG")
APP_IFRAME = 'iframe[title="streamlitApp"]'
TIMING_KEYS = (
    "warmup-wait",
    "cold",
    "identity",
    "track-b",
    "track-b-lookup",
    "same-item-models",
    "category-market",
    "overview-probe",
    "track-b-live",
    "mfds",
    "safety",
    "total",
)
SUMMARY_STAGES = (
    "wall",
    "wall_done",
    "warmup_wait",
    "identity",
    "track_b",
    "track_b_lookup",
    "same_item_models",
    "category_market",
    "overview_probe",
    "track_b_live",
    "safety",
    "total",
    "render_card",
)
RESULT_SELECTORS = ("#purchase-conclusion-v1", "#purchase-not-found-v1", "#category-market-status-v1")
STATE_NAME = "perf/price-search-timings"
MAX_SAMPLES = 600
PAGE_TIMEOUT_SECONDS = 300
DEFERRED_MARKER = "#purchase-deferred-timings-v1"
DEFERRED_TIMEOUT_SECONDS = 120
# Streamlit Community Cloud puts an idle app to sleep and shows this screen instead of the app.
# Without clicking the wake button every query waits out its full timeout (2026-10-14 04:55Z).
STREAMLIT_SLEEP_MARKER = "This app has gone to sleep due to inactivity."
STREAMLIT_WAKE_TEXT = "Yes, get this app back up!"


# ── Pure parts (unit-tested) ──


def sample_from_markers(
    *,
    query: str,
    wall: float,
    timings: Mapping[str, str | None],
    render: Mapping[str, str | None],
    status: str,
    at: datetime,
    deferred: Mapping[str, str | None] | None = None,
    wall_done: float | None = None,
) -> dict[str, Any]:
    """One sample: marker attribute names (track-b) become stage names (track_b).

    ``deferred`` (the after-card marker) adds the same-품목 stages when they ran after the card."""

    stages: dict[str, float] = {}
    for key, raw in {**timings, **{k: v for k, v in (deferred or {}).items() if k != "when"}}.items():
        if key == "done":
            continue
        if raw is None:
            # Not reported by the page: a measurement gap, not a 0-second stage.
            continue
        try:
            stages[key.replace("-", "_")] = float(raw)
        except ValueError:
            continue
    try:
        render_card = float(render.get("card")) if render.get("card") is not None else None
    except ValueError:
        render_card = None
    return {
        "at": at.astimezone(UTC).isoformat(timespec="seconds"),
        "query": query,
        "status": status,
        "wall": round(wall, 3),
        "cold": bool(stages.pop("cold", 0.0)),
        "stages": stages,
        "render_card": render_card,
        "wall_done": round(wall_done, 3) if wall_done is not None else None,
        "same_item_when": (deferred or {}).get("when"),
    }


def merge_samples(existing: Sequence[Mapping[str, Any]], new: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    merged = [dict(sample) for sample in existing] + [dict(sample) for sample in new]
    merged.sort(key=lambda sample: str(sample.get("at") or ""))
    return merged[-MAX_SAMPLES:]


def _percentile(values: Sequence[float], share: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(share * (len(ordered) - 1))))
    return ordered[index]


def _stage_value(sample: Mapping[str, Any], stage: str) -> float | None:
    if stage in {"wall", "wall_done", "render_card"}:
        value = sample.get(stage)
    else:
        value = (sample.get("stages") or {}).get(stage)
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _queries(samples: Sequence[Mapping[str, Any]]) -> list[str]:
    return list(dict.fromkeys(str(s.get("query") or "") for s in samples))


def summarize(samples: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Median and 90th percentile per model, warm/cold and stage (successful samples only).

    Models are kept apart so a slow model is not hidden by fast ones; ``missing`` counts
    successful samples in which the page did not report that stage."""

    rows: list[dict[str, Any]] = []
    for query in _queries(samples):
        for label, cold in (("따뜻한 상태", False), ("차가운 상태", True)):
            group = [
                s
                for s in samples
                if str(s.get("query") or "") == query
                and s.get("status") == "ok"
                and bool(s.get("cold")) is cold
            ]
            for stage in SUMMARY_STAGES:
                values = [v for s in group if (v := _stage_value(s, stage)) is not None]
                if not values:
                    continue
                rows.append(
                    {
                        "query": query,
                        "state": label,
                        "stage": stage,
                        "n": len(values),
                        "missing": len(group) - len(values),
                        "median": round(median(values), 2),
                        "p90": round(_percentile(values, 0.9), 2),
                    }
                )
    return rows


def summary_markdown(samples: Sequence[Mapping[str, Any]]) -> str:
    rows = summarize(samples)
    failed = sum(1 for s in samples if s.get("status") != "ok")
    lines = [f"표본 {len(samples)}개 (실패·시간 초과 {failed}개)", ""]
    for query in _queries(samples):
        mine = [s for s in samples if str(s.get("query") or "") == query]
        mine_failed = sum(1 for s in mine if s.get("status") != "ok")
        lines.append(f"- {query}: 표본 {len(mine)}개, 실패·시간 초과 {mine_failed}개")
    lines += [
        "",
        "| 모델 | 상태 | 단계 | 표본 | 누락 | 중앙값(초) | 90%(초) |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    lines += [
        f"| {r['query']} | {r['state']} | {r['stage']} | {r['n']} | {r['missing']} "
        f"| {r['median']} | {r['p90']} |"
        for r in rows
    ]
    return "\n".join(lines) + "\n"


# ── Browser ──


def _root(page: Any) -> Any:
    if page.locator(APP_IFRAME).count() > 0:
        return page.frame_locator(APP_IFRAME)
    return page


def _attributes(root: Any, selector: str, keys: Sequence[str]) -> dict[str, str | None]:
    marker = root.locator(selector).first
    if marker.count() == 0:
        return {}
    return {key: marker.get_attribute(f"data-{key}") for key in keys}


def measure_query(page: Any, url: str, query: str) -> dict[str, Any]:
    started = time.monotonic()
    status = "timeout"
    page.goto(f"{url.rstrip('/')}/?q={quote(query)}", wait_until="domcontentloaded", timeout=120_000)
    deadline = started + PAGE_TIMEOUT_SECONDS
    root = page
    woke = False
    while time.monotonic() < deadline:
        if not woke:
            woke = _wake_if_sleeping(page)
        root = _root(page)
        if any(root.locator(selector).count() > 0 for selector in RESULT_SELECTORS):
            status = "ok"
            break
        page.wait_for_timeout(500)
    wall = time.monotonic() - started
    timings = _attributes(root, "#purchase-search-timings-v2", TIMING_KEYS) if status == "ok" else {}
    render = _attributes(root, "#purchase-render-timings-v1", ("card",)) if status == "ok" else {}
    deferred: dict[str, str | None] = {}
    wall_done: float | None = None
    if status == "ok":
        done_deadline = time.monotonic() + DEFERRED_TIMEOUT_SECONDS
        while time.monotonic() < done_deadline:
            root = _root(page)
            if root.locator(DEFERRED_MARKER).count() > 0:
                wall_done = time.monotonic() - started
                deferred = _attributes(
                    root, DEFERRED_MARKER, ("when", "done", "same-item-models", "category-market")
                )
                break
            page.wait_for_timeout(500)
    sample = sample_from_markers(
        query=query,
        wall=wall,
        timings=timings,
        render=render,
        status=status,
        at=datetime.now(UTC),
        deferred=deferred,
        wall_done=wall_done,
    )
    if woke:
        sample["woke"] = True
    return sample


def _wake_if_sleeping(page: Any) -> bool:
    """Click Streamlit Cloud's wake button when the sleep screen is showing; True when clicked."""

    try:
        if STREAMLIT_SLEEP_MARKER not in page.locator("body").inner_text(timeout=2_000):
            return False
        page.get_by_text(STREAMLIT_WAKE_TEXT, exact=True).first.click(timeout=10_000)
    except Exception:
        return False
    return True


def run(url: str, queries: Sequence[str]) -> list[dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    samples: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for query in queries:
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            try:
                samples.append(measure_query(page, url, query))
            except Exception as exc:  # one broken query must not lose the others
                samples.append(
                    {
                        "at": datetime.now(UTC).isoformat(timespec="seconds"),
                        "query": query,
                        "status": f"error: {type(exc).__name__}",
                    }
                )
            finally:
                page.close()
        browser.close()
    return samples


def _store() -> Any:
    from purchase_price.config import get_settings
    from purchase_price.storage.r2_state import R2OperationalStateStore

    return R2OperationalStateStore.from_settings(get_settings())


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=os.getenv("PRODUCTION_URL", DEFAULT_URL))
    parser.add_argument("--queries", default=",".join(DEFAULT_QUERIES))
    parser.add_argument("--output", type=Path, default=Path("artifacts/price-search-timings.json"))
    parser.add_argument("--r2", action="store_true", help="append to the rolling R2 state object")
    parser.add_argument("--summary", action="store_true", help="print the stage summary (all stored samples with --r2)")
    args = parser.parse_args(argv)

    queries = [q.strip() for q in args.queries.split(",") if q.strip()]
    samples = run(args.url, queries)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(samples, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    stored = samples
    if args.r2:
        store = _store()
        previous = (store.read_json(STATE_NAME) or {}).get("samples") or []
        stored = merge_samples(previous, samples)
        store.write_json(STATE_NAME, {"version": 1, "samples": stored})
    if args.summary:
        text = summary_markdown(stored)
        print(text)
        step_summary = os.getenv("GITHUB_STEP_SUMMARY")
        if step_summary:
            with open(step_summary, "a", encoding="utf-8") as handle:
                handle.write("## 가격 검색 시간\n\n" + text)
    return 0 if any(s.get("status") == "ok" for s in samples) else 1


if __name__ == "__main__":
    raise SystemExit(main())
