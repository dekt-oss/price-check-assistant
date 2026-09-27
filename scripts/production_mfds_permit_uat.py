from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

PRODUCTION_URL = os.getenv("PRODUCTION_URL", "https://bp-price-research.streamlit.app/")
ARTIFACT_DIR = Path("artifacts/mfds-permit-uat")
PERMIT_PATH = ARTIFACT_DIR / "production-permit.txt"
REPORT_PATH = ARTIFACT_DIR / "production-uat.json"
APP_IFRAME = 'iframe[title="streamlitApp"]'
DEPLOYMENT_MARKER = "#purchase-workspace-mfds-v2"
ERROR_TEXTS = (
    "AttributeError",
    "ImportError",
    "This app has encountered an error",
    "Error running app",
)


def _app(page: Any) -> Any:
    return page.frame_locator(APP_IFRAME)


def _body(page: Any) -> str:
    return _app(page).locator("body").inner_text(timeout=15_000)


def _save(page: Any, report: dict[str, object], label: str) -> None:
    try:
        report[f"{label}_body"] = _body(page)[:18000]
    except Exception as exc:
        report[f"{label}_body_error"] = f"{type(exc).__name__}: {exc}"[:1000]
    try:
        path = ARTIFACT_DIR / f"{label}.png"
        page.screenshot(path=str(path), full_page=True)
        report[f"{label}_screenshot"] = str(path)
    except Exception as exc:
        report[f"{label}_screenshot_error"] = f"{type(exc).__name__}: {exc}"[:1000]


def _assert_no_app_error(body: str) -> None:
    hit = next((text for text in ERROR_TEXTS if text in body), None)
    if hit:
        raise RuntimeError(f"Production app error text detected: {hit}")


def _wait_for_deployment(page: Any) -> None:
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        try:
            page.goto(PRODUCTION_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3_000)
            app = _app(page)
            app.get_by_label("통합 검색", exact=True).wait_for(state="visible", timeout=15_000)
            marker = app.locator(DEPLOYMENT_MARKER)
            if marker.count() > 0:
                marker.first.wait_for(state="attached", timeout=5_000)
                return
        except Exception:
            pass
        page.wait_for_timeout(6_000)
    raise RuntimeError("Production did not expose purchase-workspace-mfds-v2 in time")


def _wait_for_permit_result(page: Any, permit: str, report: dict[str, object]) -> None:
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        body = _body(page)
        _assert_no_app_error(body)
        if (
            permit in body
            and "허가번호 exact 일치" in body
            and "구매조사 워크스페이스" in body
            and "식약처 누적 인덱스에서 검색어 확인" in body
        ):
            report["exact_permit_rendered"] = True
            return
        page.wait_for_timeout(1_500)
    raise RuntimeError("Production permit search did not render exact MFDS identity")


def _verify_summary_crosslink(page: Any, report: dict[str, object]) -> None:
    body = _body(page)
    _assert_no_app_error(body)
    if "허가번호 기준 모델·조달가격 연결" not in body:
        raise RuntimeError("Permit-specific procurement crosslink section did not render")
    if "나라장터 가격범위" not in body:
        raise RuntimeError("Permit-specific crosslink table did not render G2B price column")
    if "식약처 등록업체" not in body:
        raise RuntimeError("Permit-specific crosslink table did not render registered company")
    report["summary_crosslink_rendered"] = True


def _verify_tabs(page: Any, report: dict[str, object]) -> None:
    app = _app(page)

    mfds_tab = app.get_by_role("tab", name="식약처·허가")
    mfds_tab.click()
    page.wait_for_timeout(1_500)
    body = _body(page)
    _assert_no_app_error(body)
    if "누적 Identity Index" not in body:
        raise RuntimeError("MFDS tab did not preserve indexed permit identity")
    report["mfds_tab_preserved"] = True

    supplier_tab = app.get_by_role("tab", name="공급사")
    supplier_tab.click()
    page.wait_for_timeout(1_500)
    body = _body(page)
    _assert_no_app_error(body)
    if "식약처 제품 등록업체" not in body:
        raise RuntimeError("Supplier tab did not render MFDS registered-company evidence")
    if "실제 조달 공급업체" not in body:
        raise RuntimeError("Supplier tab did not keep procurement suppliers separate")
    report["supplier_evidence_separated"] = True

    competitor_tab = app.get_by_role("tab", name="경쟁장비")
    competitor_tab.click()
    page.wait_for_timeout(1_500)
    body = _body(page)
    _assert_no_app_error(body)
    if "검색한 허가번호 → 등록모델 → 나라장터 가격" not in body:
        raise RuntimeError("Competitor tab did not render permit-model-price crosslink")
    report["competitor_crosslink_preserved"] = True


def main() -> None:
    from playwright.sync_api import sync_playwright

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    permit = PERMIT_PATH.read_text(encoding="utf-8").strip()
    if not permit:
        raise RuntimeError("UAT permit candidate is empty")

    report: dict[str, object] = {
        "status": "failure",
        "permit": permit,
        "production_url": PRODUCTION_URL,
    }
    started = time.monotonic()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1500, "height": 1300})
            try:
                _wait_for_deployment(page)
                app = _app(page)
                search = app.get_by_label("통합 검색", exact=True)
                search.fill(permit)
                app.get_by_role("button", name="검색", exact=True).click()
                _wait_for_permit_result(page, permit, report)
                _save(page, report, "permit-summary")
                _verify_summary_crosslink(page, report)
                _verify_tabs(page, report)
                _save(page, report, "permit-tabs")
                report["status"] = "pass"
            except Exception:
                _save(page, report, "permit-failure")
                raise
            finally:
                browser.close()
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        REPORT_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
