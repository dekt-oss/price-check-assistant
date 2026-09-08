from __future__ import annotations

import json
import os
import time
from pathlib import Path

import playwright.sync_api as pw


PRODUCTION_URL = os.getenv("PRODUCTION_URL", "https://bp-price-research.streamlit.app/")
ARTIFACT_DIR = Path("artifacts/production-browser-smoke")


def _wait_heading(page: pw.Page, name: str) -> None:
    page.get_by_role("heading", name=name, exact=True).wait_for(state="visible", timeout=30_000)


def _navigate(page: pw.Page, name: str) -> None:
    page.get_by_role("link", name=name, exact=True).click()
    _wait_heading(page, name)


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report: dict[str, object] = {
        "production_url": PRODUCTION_URL,
        "status": "failure",
        "checks": [],
    }

    try:
        with pw.sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1200})
            page.goto(PRODUCTION_URL, wait_until="domcontentloaded", timeout=60_000)
            _wait_heading(page, "구매가격 검색·검토 보조시스템")
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

            page.screenshot(path=str(ARTIFACT_DIR / "medical-device-page.png"), full_page=True)
            report["final_url"] = page.url
            report["status"] = "pass"
            browser.close()
    except Exception as exc:
        report["error_type"] = type(exc).__name__
        report["error_message"] = str(exc)[:2000]
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
