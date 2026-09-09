from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from openpyxl import Workbook

PRODUCTION_URL = os.getenv("PRODUCTION_URL", "https://bp-price-research.streamlit.app/")
UAT_URL = PRODUCTION_URL.rstrip("/") + "/quote-extraction-uat"
ARTIFACT_DIR = Path("artifacts/production-browser-smoke")
APP_IFRAME = 'iframe[title="streamlitApp"]'
COMMERCIAL_GUIDANCE = "배송·설치·옵션·보증·유지보수·기타조건도 원문에 명시된 경우"


def _app_frame(page: Any) -> Any:
    return page.frame_locator(APP_IFRAME)


def _build_synthetic_quote(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Quote"
    sheet.append(
        [
            "품명",
            "제조사",
            "모델명",
            "규격",
            "수량",
            "단위",
            "단가",
            "금액",
            "부가세",
            "배송조건",
            "설치조건",
            "옵션조건",
            "보증기간",
            "유지보수조건",
            "기타조건",
        ]
    )
    sheet.append(
        [
            "SYNTH-UAT-DEVICE",
            "SYNTH-MAKER",
            "SYNTH-MODEL-1",
            "SYNTH-SPEC-1",
            1,
            "set",
            1000000,
            1000000,
            "포함",
            "SYNTH-DELIVERY-INCLUDED",
            "SYNTH-INSTALLATION-INCLUDED",
            "SYNTH-OPTION-NONE",
            "SYNTH-WARRANTY-3Y",
            "SYNTH-MAINTENANCE-1Y",
            "SYNTH-OTHER-CONDITION",
        ]
    )
    workbook.save(path)


def main() -> None:
    from playwright.sync_api import sync_playwright

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    quote_path = ARTIFACT_DIR / "synthetic-quote-uat.xlsx"
    report_path = ARTIFACT_DIR / "quote-uat-upload-report.json"
    screenshot_path = ARTIFACT_DIR / "quote-uat-upload.png"
    _build_synthetic_quote(quote_path)

    report: dict[str, object] = {
        "production_url": PRODUCTION_URL,
        "uat_url": UAT_URL,
        "status": "failure",
        "checks": [],
        "synthetic_only": True,
        "grid_note": (
            "Streamlit dataframes virtualize off-screen columns, so this browser smoke verifies the "
            "real Production upload/extraction path and deployed commercial-review guidance rather "
            "than scraping virtualized cell values. Commercial field extraction/scoring remains "
            "covered by deterministic CI tests."
        ),
    }
    started = time.monotonic()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1400})
            try:
                page.goto(UAT_URL, wait_until="domcontentloaded", timeout=60_000)
                app = _app_frame(page)
                app.get_by_role("heading", name="견적추출 UAT", exact=True).wait_for(
                    state="visible", timeout=60_000
                )
                report["checks"].append("uat_page_rendered")

                uploader = app.get_by_label("UAT 견적 파일", exact=True)
                uploader.wait_for(state="visible", timeout=30_000)
                file_input = uploader.locator('input[type="file"]')
                file_input.wait_for(state="attached", timeout=30_000)
                file_input.set_input_files(str(quote_path))
                app.get_by_text("UAT-001", exact=False).first.wait_for(state="visible", timeout=45_000)
                report["checks"].append("synthetic_xlsx_uploaded")

                app.get_by_text("자동 추출 품목", exact=True).wait_for(state="visible", timeout=30_000)
                body = app.locator("body").inner_text(timeout=10_000)
                if "자동 추출 품목\n1" not in body and "자동 추출 품목 1" not in body:
                    raise RuntimeError("Synthetic quote did not render exactly one extracted item")
                report["checks"].append("synthetic_item_extracted")

                if COMMERCIAL_GUIDANCE not in body:
                    raise RuntimeError("Commercial-condition UAT guidance is missing from Production")
                report["checks"].append("commercial_review_guidance_rendered")

                report["body_text_prefix"] = body[:6000]
                report["final_url"] = page.url
                page.screenshot(path=str(screenshot_path), full_page=True)
                report["screenshot"] = str(screenshot_path)
                report["status"] = "pass"
            except Exception as exc:
                report["error_type"] = type(exc).__name__
                report["error_message"] = str(exc)[:3000]
                try:
                    page.screenshot(path=str(screenshot_path), full_page=True)
                    report["screenshot"] = str(screenshot_path)
                except Exception:
                    pass
                raise
            finally:
                browser.close()
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
