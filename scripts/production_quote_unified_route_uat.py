from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from openpyxl import Workbook

PRODUCTION_URL = os.getenv("PRODUCTION_URL", "https://bp-price-research.streamlit.app/")
ARTIFACT_DIR = Path("artifacts/quote-unified-route-uat")
APP_IFRAME = 'iframe[title="streamlitApp"]'
ROUTE_CAPTION = "견적서에서 추출한 품목을 일반 통합검색과 동일한 구매조사 파이프라인으로 조사했습니다."
DIRECT_PATTERN = re.compile(r"직접 동일성 확인 거래\s*(\d+)건")
ERROR_TEXTS = ("ImportError", "This app has encountered an error", "Error running app")


def _build_quote(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Quote"
    ws.append(["품명", "제조사", "모델명", "규격", "수량", "단위", "단가", "금액", "부가세"])
    ws.append(["심장충격기", "Philips", "DFM100", "", 1, "대", 12500000, 12500000, "포함"])
    wb.save(path)


def _app(page: Any) -> Any:
    return page.frame_locator(APP_IFRAME)


def _body(page: Any) -> str:
    return _app(page).locator("body").inner_text(timeout=10_000)


def _wake_if_needed(page: Any) -> None:
    try:
        body = page.locator("body").inner_text(timeout=4_000)
    except Exception:
        return
    if "This app has gone to sleep due to inactivity." not in body:
        return
    wake = page.get_by_text("Yes, get this app back up!", exact=True)
    if wake.count():
        wake.first.click()
        page.locator(APP_IFRAME).wait_for(state="attached", timeout=60_000)


def _attempt(page: Any, quote_path: Path, report: dict[str, object]) -> bool:
    page.goto(PRODUCTION_URL, wait_until="domcontentloaded", timeout=60_000)
    _wake_if_needed(page)
    app = _app(page)
    uploader = app.get_by_label("견적서 업로드", exact=True)
    uploader.wait_for(state="visible", timeout=30_000)
    uploader.locator('input[type="file"]').set_input_files(str(quote_path))

    deadline = time.monotonic() + 150
    last_body = ""
    while time.monotonic() < deadline:
        try:
            last_body = _body(page)
        except Exception:
            page.wait_for_timeout(1_500)
            continue
        if any(text in last_body for text in ERROR_TEXTS):
            report["last_body_prefix"] = last_body[:5000]
            return False
        if ROUTE_CAPTION in last_body and "구매조사 워크스페이스" in last_body and "DFM100" in last_body:
            match = DIRECT_PATTERN.search(last_body)
            if match is None:
                page.wait_for_timeout(1_500)
                continue
            direct_count = int(match.group(1))
            report["direct_count"] = direct_count
            report["last_body_prefix"] = last_body[:12000]
            if direct_count < 1:
                raise RuntimeError(f"quote unified route rendered but direct evidence was {direct_count}")
            return True
        page.wait_for_timeout(1_500)

    report["last_body_prefix"] = last_body[:12000]
    return False


def main() -> None:
    from playwright.sync_api import sync_playwright

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    quote_path = ARTIFACT_DIR / "dfm100-unified-route-uat.xlsx"
    screenshot = ARTIFACT_DIR / "quote-unified-route.png"
    report_path = ARTIFACT_DIR / "report.json"
    _build_quote(quote_path)

    report: dict[str, object] = {
        "production_url": PRODUCTION_URL,
        "status": "failure",
        "query_model": "DFM100",
        "checks": [],
        "expected_main_sha": "8d40f82b0f26e47d1a50eaf27b190728543bd513",
    }
    started = time.monotonic()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1400})
            try:
                for attempt in range(1, 7):
                    report["attempt"] = attempt
                    try:
                        if _attempt(page, quote_path, report):
                            report["checks"] = [
                                "root_quote_uploaded",
                                "one_item_extracted",
                                "same_unified_workspace_route",
                                "dfm100_direct_evidence",
                            ]
                            report["status"] = "pass"
                            break
                    except Exception as exc:
                        report[f"attempt_{attempt}_error"] = f"{type(exc).__name__}: {exc}"[:2000]
                    if attempt < 6:
                        page.wait_for_timeout(20_000)
                if report["status"] != "pass":
                    raise RuntimeError("Production quote upload did not reach unified DFM100 workspace")
                page.screenshot(path=str(screenshot), full_page=True)
                report["screenshot"] = str(screenshot)
                report["final_url"] = page.url
            finally:
                browser.close()
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
