from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

PRODUCTION_URL = os.getenv("PRODUCTION_URL", "https://bp-price-research.streamlit.app/")
EXPECT_QUOTE_UAT = os.getenv("EXPECT_QUOTE_UAT", "").strip().casefold() in {
    "1",
    "true",
    "yes",
    "on",
}
EXPECT_UNIFIED_SEARCH = os.getenv("EXPECT_UNIFIED_SEARCH", "").strip().casefold() in {
    "1",
    "true",
    "yes",
    "on",
}
ARTIFACT_DIR = Path("artifacts/production-browser-smoke")
KNOWN_PLATFORM_ERRORS = (
    "Error installing requirements",
    "Error running app",
)
APP_IFRAME = 'iframe[title="streamlitApp"]'
DEPLOYMENT_MARKER = "#unified-search-runtime-v2"


def _app_frame(page: Any) -> Any:
    return page.frame_locator(APP_IFRAME)


def _wait_heading(context: Any, name: str, *, timeout: int = 30_000) -> None:
    context.get_by_role("heading", name=name, exact=True).wait_for(state="visible", timeout=timeout)


def _navigate(page: Any, name: str) -> None:
    """Navigate by sidebar label; destination-specific controls prove page readiness.

    Streamlit navigation titles are allowed to differ from a page's internal H1/page title, so
    coupling those strings made the smoke test fail on healthy pages. Callers always wait for a
    destination-specific control immediately after navigation.
    """

    app = _app_frame(page)
    app.get_by_role("link", name=name, exact=True).click()


def _wait_for_navigation_link(
    page: Any,
    name: str,
    *,
    timeout_seconds: float = 180.0,
) -> None:
    """Wait for a newly deployed navigation target without treating rollout lag as app failure."""

    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            app = _app_frame(page)
            link = app.get_by_role("link", name=name, exact=True)
            if link.count() > 0:
                link.first.wait_for(state="visible", timeout=5_000)
                return
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"[:1000]

        try:
            page.goto(PRODUCTION_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(5_000)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"[:1000]
        page.wait_for_timeout(5_000)

    detail = f"; last_error={last_error}" if last_error else ""
    raise RuntimeError(f"Production navigation link did not appear: {name}{detail}")


def _diagnostic_snapshot(page: Any, *, label: str) -> dict[str, object]:
    snapshot: dict[str, object] = {"label": label, "url": page.url}
    try:
        snapshot["title"] = page.title()
    except Exception as exc:
        snapshot["title_error"] = f"{type(exc).__name__}: {exc}"[:500]
    try:
        snapshot["outer_body_text_prefix"] = page.locator("body").inner_text(timeout=5_000)[:3000]
    except Exception as exc:
        snapshot["outer_body_error"] = f"{type(exc).__name__}: {exc}"[:500]
    try:
        app = _app_frame(page)
        snapshot["app_body_text_prefix"] = app.locator("body").inner_text(timeout=5_000)[:5000]
        snapshot["streamlit_app_count"] = app.locator('[data-testid="stApp"]').count()
    except Exception as exc:
        snapshot["app_body_error"] = f"{type(exc).__name__}: {exc}"[:500]
    try:
        snapshot["html_prefix"] = page.content()[:12000]
        snapshot["outer_root_count"] = page.locator("#root").count()
        snapshot["iframe_count"] = page.locator("iframe").count()
    except Exception as exc:
        snapshot["dom_probe_error"] = f"{type(exc).__name__}: {exc}"[:500]
    try:
        screenshot_path = ARTIFACT_DIR / f"{label}.png"
        page.screenshot(path=str(screenshot_path), full_page=True)
        snapshot["screenshot"] = str(screenshot_path)
    except Exception as exc:
        snapshot["screenshot_error"] = f"{type(exc).__name__}: {exc}"[:500]
    return snapshot


def _install_browser_diagnostics(page: Any, report: dict[str, object]) -> None:
    console_messages: list[dict[str, str]] = []
    page_errors: list[str] = []
    failed_requests: list[dict[str, str]] = []
    stcore_responses: list[dict[str, object]] = []
    websockets: list[dict[str, object]] = []

    report["console_messages"] = console_messages
    report["page_errors"] = page_errors
    report["failed_requests"] = failed_requests
    report["stcore_responses"] = stcore_responses
    report["websockets"] = websockets

    def on_console(message: Any) -> None:
        if len(console_messages) < 100:
            console_messages.append(
                {
                    "type": str(message.type),
                    "text": str(message.text)[:2000],
                }
            )

    def on_page_error(error: Any) -> None:
        page_errors.append(str(error)[:4000])

    def on_request_failed(request: Any) -> None:
        failure = request.failure or "unknown"
        failed_requests.append(
            {
                "method": request.method,
                "url": request.url[:2000],
                "failure": str(failure)[:2000],
            }
        )

    def on_response(response: Any) -> None:
        if "_stcore" not in response.url:
            return
        stcore_responses.append(
            {
                "url": response.url[:2000],
                "status": response.status,
                "status_text": response.status_text,
            }
        )

    def on_websocket(socket: Any) -> None:
        record: dict[str, object] = {
            "url": socket.url[:2000],
            "events": ["open"],
        }
        websockets.append(record)

        def append_event(name: str, detail: object = "") -> None:
            events = record.setdefault("events", [])
            if isinstance(events, list) and len(events) < 30:
                events.append(f"{name}: {str(detail)[:500]}" if detail else name)

        socket.on("framesent", lambda payload: append_event("frame_sent", type(payload).__name__))
        socket.on(
            "framereceived", lambda payload: append_event("frame_received", type(payload).__name__)
        )
        socket.on("socketerror", lambda error: append_event("socket_error", error))
        socket.on("close", lambda: append_event("close"))

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("requestfailed", on_request_failed)
    page.on("response", on_response)
    page.on("websocket", on_websocket)


def _wake_and_wait_dashboard(page: Any, report: dict[str, object]) -> None:
    attempts: list[dict[str, object]] = []
    report["dashboard_attempts"] = attempts

    for attempt in range(1, 4):
        response = page.goto(PRODUCTION_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3_000)
        outer_body = page.locator("body").inner_text(timeout=5_000)
        platform_error = next((text for text in KNOWN_PLATFORM_ERRORS if text in outer_body), "")
        if platform_error:
            snapshot = _diagnostic_snapshot(page, label=f"dashboard-attempt-{attempt}")
            snapshot.update(
                {
                    "attempt": attempt,
                    "status": "platform_error",
                    "platform_error": platform_error,
                    "root_http_status": response.status if response is not None else None,
                }
            )
            attempts.append(snapshot)
            if attempt < 3:
                page.wait_for_timeout(10_000)
                continue
            break

        try:
            app = _app_frame(page)
            app.get_by_label("통합 검색", exact=True).wait_for(state="visible", timeout=30_000)
            app.get_by_role("button", name="검색", exact=True).wait_for(
                state="visible", timeout=30_000
            )
            attempts.append(
                {
                    "attempt": attempt,
                    "status": "pass",
                    "url": page.url,
                    "root_http_status": response.status if response is not None else None,
                }
            )
            return
        except Exception as exc:
            snapshot = _diagnostic_snapshot(page, label=f"dashboard-attempt-{attempt}")
            snapshot.update(
                {
                    "attempt": attempt,
                    "status": "timeout",
                    "root_http_status": response.status if response is not None else None,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc)[:1000],
                }
            )
            attempts.append(snapshot)
            if attempt < 3:
                page.wait_for_timeout(10_000)

    raise RuntimeError("Production unified-search dashboard did not render after 3 bounded attempts")


def _wait_for_hotfix_deployment(
    page: Any,
    report: dict[str, object],
    *,
    timeout_seconds: float = 240.0,
) -> None:
    """Poll until Streamlit is serving the code version that contains this hotfix."""

    attempts: list[dict[str, object]] = []
    report["hotfix_deployment_attempts"] = attempts
    deadline = time.monotonic() + timeout_seconds
    last_error = ""
    attempt = 0

    while time.monotonic() < deadline:
        attempt += 1
        try:
            response = page.goto(PRODUCTION_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3_000)
            app = _app_frame(page)
            app.get_by_label("통합 검색", exact=True).wait_for(state="visible", timeout=15_000)
            marker = app.locator(DEPLOYMENT_MARKER)
            if marker.count() > 0:
                marker.first.wait_for(state="attached", timeout=5_000)
                attempts.append(
                    {
                        "attempt": attempt,
                        "status": "pass",
                        "root_http_status": response.status if response is not None else None,
                    }
                )
                report["checks"].append("hotfix_deployment_marker_seen")
                return
            attempts.append(
                {
                    "attempt": attempt,
                    "status": "old_deployment",
                    "root_http_status": response.status if response is not None else None,
                }
            )
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"[:1000]
            attempts.append(
                {
                    "attempt": attempt,
                    "status": "retry",
                    "error": last_error,
                }
            )
        page.wait_for_timeout(7_000)

    detail = f"; last_error={last_error}" if last_error else ""
    raise RuntimeError(f"Production did not expose the unified-search hotfix marker{detail}")


def _exercise_unified_search(page: Any, report: dict[str, object]) -> None:
    app = _app_frame(page)
    app.get_by_label("통합 검색", exact=True).fill("DFM100")
    app.get_by_role("button", name="검색", exact=True).click()
    _wait_heading(app, "DFM100 거래가격", timeout=90_000)
    app.get_by_text("나라장터 거래가격", exact=True).wait_for(state="visible", timeout=90_000)
    app.locator('[data-testid="stDataFrame"]').first.wait_for(state="visible", timeout=90_000)

    summary_locator = app.get_by_text(
        re.compile(r"동일성 확인 \d+건 · 검색 참고 \d+건"),
        exact=False,
    ).first
    summary_locator.wait_for(state="visible", timeout=90_000)
    summary_text = summary_locator.inner_text()
    count_match = re.search(r"동일성 확인 (\d+)건 · 검색 참고 (\d+)건", summary_text)
    if count_match is None:
        raise RuntimeError(f"Could not parse DFM100 result counts: {summary_text!r}")
    strict_count, reference_count = (int(value) for value in count_match.groups())
    if strict_count + reference_count < 1:
        raise RuntimeError(f"DFM100 rendered no Track B transactions: {summary_text}")

    body_text = app.locator("body").inner_text(timeout=10_000)
    if "AttributeError" in body_text or "This app has encountered an error" in body_text:
        raise RuntimeError("DFM100 unified search rendered a Streamlit exception")

    report["unified_search_counts"] = {
        "strict": strict_count,
        "reference": reference_count,
    }
    report["checks"].append("unified_search_dfm100_rendered")
    report["unified_search_snapshot"] = _diagnostic_snapshot(page, label="unified-search-dfm100")


def main() -> None:
    from playwright.sync_api import sync_playwright

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report: dict[str, object] = {
        "production_url": PRODUCTION_URL,
        "expect_quote_uat": EXPECT_QUOTE_UAT,
        "expect_unified_search": EXPECT_UNIFIED_SEARCH,
        "status": "failure",
        "checks": [],
    }

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1200})
            _install_browser_diagnostics(page, report)
            try:
                _wake_and_wait_dashboard(page, report)
                report["checks"].append("dashboard_rendered")
                report["checks"].append("unified_search_form_rendered")

                if EXPECT_UNIFIED_SEARCH:
                    _wait_for_hotfix_deployment(page, report)
                    _exercise_unified_search(page, report)

                _navigate(page, "상세 검색")
                app = _app_frame(page)
                app.get_by_label("제품명", exact=True).wait_for(state="visible")
                app.get_by_label("제조사", exact=True).wait_for(state="visible")
                app.get_by_label("모델명", exact=True).wait_for(state="visible")
                app.get_by_role("button", name="시장가격 조사", exact=True).wait_for(
                    state="visible"
                )
                report["checks"].append("detailed_search_form_rendered")

                app.get_by_role("tab", name="나라장터 계약근거", exact=True).click()
                app.get_by_label("계약 품명", exact=True).wait_for(state="visible")
                app.get_by_role("button", name="계약근거 조회", exact=True).wait_for(
                    state="visible"
                )
                report["checks"].append("contract_tab_rendered")

                _navigate(page, "견적 검토")
                app = _app_frame(page)
                app.get_by_label("견적서 파일", exact=True).wait_for(state="visible")
                report["checks"].append("quote_review_rendered")

                _navigate(page, "의료기기 조회")
                app = _app_frame(page)
                app.get_by_role("tab", name="등록·시장조사", exact=True).wait_for(
                    state="visible"
                )
                app.get_by_role("tab", name="Safety·공급사", exact=True).wait_for(
                    state="visible"
                )
                app.get_by_role("tab", name="UDI-DI", exact=True).wait_for(state="visible")
                report["checks"].append("medical_device_tabs_rendered")

                final_label = "medical-device-page"
                if EXPECT_QUOTE_UAT:
                    _wait_for_navigation_link(page, "견적추출 UAT")
                    _navigate(page, "견적추출 UAT")
                    app = _app_frame(page)
                    app.get_by_label("UAT 견적 파일", exact=True).wait_for(
                        state="visible", timeout=30_000
                    )
                    _wait_heading(app, "UAT 집계", timeout=30_000)
                    if "quote-extraction-uat" not in page.url:
                        raise RuntimeError(
                            "Quote UAT workspace rendered without the expected stable URL path: "
                            f"{page.url}"
                        )
                    report["checks"].append("quote_uat_workspace_rendered")
                    final_label = "quote-uat-workspace"

                report["final_snapshot"] = _diagnostic_snapshot(page, label=final_label)
                report["final_url"] = page.url
                report["status"] = "pass"
            except Exception as exc:
                report["error_type"] = type(exc).__name__
                report["error_message"] = str(exc)[:2000]
                report["failure_snapshot"] = _diagnostic_snapshot(page, label="failure-final")
                raise
            finally:
                browser.close()
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        (ARTIFACT_DIR / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
