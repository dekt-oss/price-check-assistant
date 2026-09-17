from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

PRODUCTION_URL = os.getenv("PRODUCTION_URL", "https://bp-price-research.streamlit.app/")
ARTIFACT_DIR = Path("artifacts/production-browser-smoke")
APP_IFRAME = 'iframe[title="streamlitApp"]'
DEPLOYMENT_MARKER = "#unified-search-runtime-v2"
RESULT_PATTERN = re.compile(r"동일성 확인 (\d+)건 · 검색 참고 (\d+)건")
ERROR_TEXTS = (
    "AttributeError",
    "This app has encountered an error",
    "Error running app",
)


def _app(page: Any) -> Any:
    return page.frame_locator(APP_IFRAME)


def _body_text(page: Any) -> str:
    return _app(page).locator("body").inner_text(timeout=10_000)


def _save_snapshot(page: Any, report: dict[str, object], label: str) -> None:
    try:
        report[f"{label}_body"] = _body_text(page)[:12000]
    except Exception as exc:
        report[f"{label}_body_error"] = f"{type(exc).__name__}: {exc}"[:1000]
    try:
        path = ARTIFACT_DIR / f"{label}.png"
        page.screenshot(path=str(path), full_page=True)
        report[f"{label}_screenshot"] = str(path)
    except Exception as exc:
        report[f"{label}_screenshot_error"] = f"{type(exc).__name__}: {exc}"[:1000]


def _wait_for_deployed_app(page: Any, report: dict[str, object]) -> None:
    attempts: list[dict[str, object]] = []
    report["deployment_attempts"] = attempts
    deadline = time.monotonic() + 240

    while time.monotonic() < deadline:
        attempt = len(attempts) + 1
        try:
            response = page.goto(PRODUCTION_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3_000)
            app = _app(page)
            app.get_by_label("통합 검색", exact=True).wait_for(state="visible", timeout=15_000)
            app.get_by_role("button", name="검색", exact=True).wait_for(
                state="visible", timeout=15_000
            )
            marker = app.locator(DEPLOYMENT_MARKER)
            if marker.count() > 0:
                marker.first.wait_for(state="attached", timeout=5_000)
                attempts.append(
                    {
                        "attempt": attempt,
                        "status": "pass",
                        "http_status": response.status if response is not None else None,
                    }
                )
                # Give Streamlit Cloud a short quiet period after a rolling reload before submitting.
                page.wait_for_timeout(4_000)
                return
            attempts.append(
                {
                    "attempt": attempt,
                    "status": "old_deployment",
                    "http_status": response.status if response is not None else None,
                }
            )
        except Exception as exc:
            attempts.append(
                {
                    "attempt": attempt,
                    "status": "retry",
                    "error": f"{type(exc).__name__}: {exc}"[:1000],
                }
            )
        page.wait_for_timeout(6_000)

    raise RuntimeError("Production did not expose unified-search-runtime-v2 in time")


def _submit_dfm100(page: Any, report: dict[str, object]) -> None:
    attempts: list[dict[str, object]] = []
    report["search_attempts"] = attempts

    for attempt in range(1, 4):
        try:
            app = _app(page)
            search = app.get_by_label("통합 검색", exact=True)
            search.wait_for(state="visible", timeout=20_000)
            search.fill("DFM100")
            app.get_by_role("button", name="검색", exact=True).click()

            deadline = time.monotonic() + 75
            last_body = ""
            saw_heading = False
            while time.monotonic() < deadline:
                try:
                    body = _body_text(page)
                except Exception:
                    page.wait_for_timeout(1_000)
                    continue
                last_body = body

                error_text = next((text for text in ERROR_TEXTS if text in body), "")
                if error_text:
                    raise RuntimeError(f"Production search rendered error text: {error_text}")

                if "DFM100 거래가격" in body and "나라장터 거래가격" in body:
                    saw_heading = True

                match = RESULT_PATTERN.search(body)
                if match is not None:
                    strict_count, reference_count = (int(value) for value in match.groups())
                    total = strict_count + reference_count
                    if total < 1:
                        raise RuntimeError(
                            "DFM100 result summary rendered zero Track B transactions: "
                            f"strict={strict_count}, reference={reference_count}"
                        )
                    if not saw_heading:
                        raise RuntimeError("DFM100 result counts appeared without the result section")

                    attempts.append(
                        {
                            "attempt": attempt,
                            "status": "pass",
                            "strict_count": strict_count,
                            "reference_count": reference_count,
                        }
                    )
                    report["strict_count"] = strict_count
                    report["reference_count"] = reference_count
                    report["total_track_b_results"] = total
                    _save_snapshot(page, report, "unified-search-dfm100-success")
                    return

                page.wait_for_timeout(1_000)

            attempts.append(
                {
                    "attempt": attempt,
                    "status": "timeout",
                    "saw_result_heading": saw_heading,
                    "body_prefix": last_body[:2500],
                }
            )
        except Exception as exc:
            attempts.append(
                {
                    "attempt": attempt,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}"[:1500],
                }
            )
            if any(text in str(exc) for text in ERROR_TEXTS):
                raise

        if attempt < 3:
            # A Streamlit Cloud rolling reload can clear a submitted form. Re-open the deployed
            # app and retry rather than mistaking that transient reload for a search failure.
            _wait_for_deployed_app(page, report)

    raise RuntimeError("DFM100 Production unified search did not render a non-zero result summary")


def main() -> None:
    from playwright.sync_api import sync_playwright

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "production_url": PRODUCTION_URL,
        "query": "DFM100",
        "status": "failure",
    }
    started = time.monotonic()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1200})
            try:
                _wait_for_deployed_app(page, report)
                _submit_dfm100(page, report)
                report["status"] = "pass"
            except Exception:
                _save_snapshot(page, report, "unified-search-dfm100-failure")
                raise
            finally:
                browser.close()
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        output = ARTIFACT_DIR / "unified-search-report.json"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
