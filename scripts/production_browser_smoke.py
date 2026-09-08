from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


PRODUCTION_URL = os.getenv("PRODUCTION_URL", "https://bp-price-research.streamlit.app/")
ARTIFACT_DIR = Path("artifacts/production-browser-smoke")


def _wait_heading(page: Any, name: str, *, timeout: int = 30_000) -> None:
    page.get_by_role("heading", name=name, exact=True).wait_for(state="visible", timeout=timeout)


def _navigate(page: Any, name: str) -> None:
    page.get_by_role("link", name=name, exact=True).click()
    _wait_heading(page, name)


def _diagnostic_snapshot(page: Any, *, label: str) -> dict[str, object]:
    snapshot: dict[str, object] = {"label": label, "url": page.url}
    try:
        snapshot["title"] = page.title()
    except Exception as exc:
        snapshot["title_error"] = f"{type(exc).__name__}: {exc}"[:500]
    try:
        snapshot["body_text_prefix"] = page.locator("body").inner_text(timeout=5_000)[:3000]
    except Exception as exc:
        snapshot["body_error"] = f"{type(exc).__name__}: {exc}"[:500]
    try:
        screenshot_path = ARTIFACT_DIR / f"{label}.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        snapshot["screenshot"] = str(screenshot_path)
    except Exception as exc:
        snapshot["screenshot_error"] = f"{type(exc).__name__}: {exc}"[:500]
    return snapshot


def _wake_and_wait_dashboard(page: Any, report: dict[str, object]) -> None:
    attempts: list[dict[str, object]] = []
    report["dashboard_attempts"] = attempts
    expected = "구매가격 검색·검토 보조시스템"

    for attempt in range(1, 4):
        page.goto(PRODUCTION_URL, wait_until="domcontentloaded", timeout=60_000)
        try:
            _wait_heading(page, expected, timeout=30_000)
            attempts.append(
                {
                    "attempt": attempt,
                    "status": "pass",
                    "url": page.url,
                    "elapsed_since_start_seconds": round(time.monotonic(), 2),
                }
            )
            return
        except Exception as exc:
            snapshot = _diagnostic_snapshot(page, label=f"dashboard-attempt-{attempt}")
            snapshot.update(
                {
                    "attempt": attempt,
                    "status": "timeout",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:1000],
                }
            )
            attempts.append(snapshot)
            if attempt < 3:
                page.wait_for_timeout(5_000)

    raise RuntimeError("Production dashboard did not render after 3 bounded attempts")


def main() -> None:
    from playwright.sync_api import sync_playwright

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report: dict[str, object] = {
        "production_url": PRODUCTION_URL,
        "status": "failure",
        "checks": [],
    }
    page: Any | None = None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1200})
            _wake_and_wait_dashboard(page, report)
            report["checks"].append("dashboard_rendered")

            _navigate(page, "빠른 검색")
            page.get_by_label("제품명", exact=True).wait_for(state="visible")
            page.get_by_label("제조사", exact=True).wait_for(state="visible")
            page.get_by_label("모델명", exact=True).wait_for(state="visible")
            page.get_by_role("button", name="시장가격 조사", exact=True).wait_for(state="visible")
            report["checks"].append("quick_search_form_rendered")

            page.get_by_role("tab", name="나라장터 계약근거", exact=True).click()
            page.get_by_label("계약 품명", exact=True).wait_for(state="visible")
            page.get_by_role("button", name="계약근거 조회", exact=True).wait_for(state="visible")
            report["checks"].append("contract_tab_rendered")

            _navigate(page, "견적 검토")
            report["checks"].append("quote_review_rendered")

            _navigate(page, "의료기기 조회")
            page.get_by_role("tab", name="등록·시장조사", exact=True).wait_for(state="visible")
            page.get_by_role("tab", name="Safety·공급사", exact=True).wait_for(state="visible")
            page.get_by_role("tab", name="UDI-DI", exact=True).wait_for(state="visible")
            report["checks"].append("medical_device_tabs_rendered")

            report["final_snapshot"] = _diagnostic_snapshot(page, label="medical-device-page")
            report["final_url"] = page.url
            report["status"] = "pass"
            browser.close()
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        report["error_message"] = str(exc)[:2000]
        if page is not None:
            report["failure_snapshot"] = _diagnostic_snapshot(page, label="failure-final")
        raise
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        (ARTIFACT_DIR / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
