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
DEPLOYMENT_MARKER = "#purchase-workspace-quote-v1"
RESULT_PATTERN = re.compile(r"동일성 확인 (\d+)건 · 검색 참고 (\d+)건")
WORKSPACE_DIRECT_PATTERN = re.compile(r"동일제품 거래\s*(\d+)건")
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


def _assert_no_error_text(body: str) -> None:
    error_text = next((text for text in ERROR_TEXTS if text in body), "")
    if error_text:
        raise RuntimeError(f"Production search rendered error text: {error_text}")


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

    raise RuntimeError("Production did not expose purchase-workspace-quote-v1 in time")


def _wait_for_nonzero_result(page: Any, *, timeout_seconds: float = 75) -> tuple[int, int]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            body = _body_text(page)
        except Exception:
            page.wait_for_timeout(1_000)
            continue
        _assert_no_error_text(body)
        legacy_match = RESULT_PATTERN.search(body)
        workspace_match = WORKSPACE_DIRECT_PATTERN.search(body)
        if (
            workspace_match is not None
            and "구매조사 워크스페이스" in body
            and "동일제품 거래" in body
        ):
            strict_count = int(workspace_match.group(1))
            reference_count = int(legacy_match.group(2)) if legacy_match is not None else 0
            if strict_count < 1:
                raise RuntimeError(
                    "DFM100 one-line search did not recover direct A/B evidence: "
                    f"strict={strict_count}, reference={reference_count}"
                )
            return strict_count, reference_count
        page.wait_for_timeout(1_000)
    raise RuntimeError("DFM100 Production unified search did not render a non-zero result summary")


def _verify_workspace_tabs_persist_result(page: Any, report: dict[str, object]) -> None:
    app = _app(page)

    research_tab = app.get_by_role("tab", name="Research·근거")
    research_tab.wait_for(state="visible", timeout=20_000)
    research_tab.click()

    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        body = _body_text(page)
        _assert_no_error_text(body)
        if (
            "구매조사 워크스페이스" in body
            and "공개조달 Research·근거" in body
            and "동일제품 거래" in body
        ):
            break
        page.wait_for_timeout(1_000)
    else:
        raise RuntimeError("Research workspace tab did not preserve DFM100 search result")

    mfds_tab = app.get_by_role("tab", name="식약처·업체")
    mfds_tab.click()
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        body = _body_text(page)
        _assert_no_error_text(body)
        if "식약처 등록정보" in body:
            report["mfds_tab_rendered"] = True
            break
        page.wait_for_timeout(1_000)
    else:
        raise RuntimeError("MFDS workspace tab did not render after DFM100 search")

    price_tab = app.get_by_role("tab", name="거래가격")
    price_tab.click()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        body = _body_text(page)
        _assert_no_error_text(body)
        price_match = RESULT_PATTERN.search(body)
        if (
            "나라장터 실제 거래" in body
            and price_match is not None
            and int(price_match.group(1)) >= 1
        ):
            report["workspace_tabs_persisted"] = True
            report["price_tab_direct_count"] = int(price_match.group(1))
            _save_snapshot(page, report, "unified-search-dfm100-workspace")
            return
        page.wait_for_timeout(1_000)
    raise RuntimeError("Price workspace tab did not preserve DFM100 transaction results")


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
            strict_count, reference_count = _wait_for_nonzero_result(page)
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
            report["total_track_b_results"] = strict_count + reference_count
            _save_snapshot(page, report, "unified-search-dfm100-success")
            _verify_workspace_tabs_persist_result(page, report)
            return
        except Exception as exc:
            attempts.append(
                {
                    "attempt": attempt,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}"[:1500],
                    "body_prefix": _body_text(page)[:2500] if page else "",
                }
            )
            if any(text in str(exc) for text in ERROR_TEXTS):
                raise

        if attempt < 3:
            _wait_for_deployed_app(page, report)

    raise RuntimeError("DFM100 Production unified search did not pass result + workspace-tab E2E")


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
