from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

PRODUCTION_URL = os.getenv("PRODUCTION_URL", "https://bp-price-research.streamlit.app/")
ARTIFACT_DIR = Path("artifacts/production-browser-smoke")
KNOWN_PLATFORM_ERRORS = (
    "Error installing requirements",
    "Error running app",
)
APP_IFRAME = 'iframe[title="streamlitApp"]'
OCR_READINESS_LABELS = (
    "OCR Python 모듈",
    "Tesseract 실행파일",
    "Tesseract 상태",
    "OCR 언어팩",
    "OCR 실행 검증",
)


def _app_frame(page: Any) -> Any:
    return page.frame_locator(APP_IFRAME)


def _wait_heading(context: Any, name: str, *, timeout: int = 30_000) -> None:
    context.get_by_role("heading", name=name, exact=True).wait_for(state="visible", timeout=timeout)


def _navigate(page: Any, name: str) -> None:
    app = _app_frame(page)
    app.get_by_role("link", name=name, exact=True).click()
    _wait_heading(app, name)


def _navigate_direct(page: Any, route: str, heading: str) -> None:
    url = f"{PRODUCTION_URL.rstrip('/')}/{route}"
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    app = _app_frame(page)
    _wait_heading(app, heading, timeout=30_000)


def _read_readiness_status(body_text: str, label: str) -> dict[str, str]:
    lines = [line.strip() for line in body_text.splitlines() if line.strip()]
    try:
        index = lines.index(label)
    except ValueError:
        return {"status": "MISSING", "detail": "label not found"}

    window = lines[index + 1 : index + 5]
    status = next((line for line in window if line in {"READY", "UNAVAILABLE"}), "UNKNOWN")
    detail_lines = [line for line in window if line not in {"READY", "UNAVAILABLE"}]
    return {
        "status": status,
        "detail": " | ".join(detail_lines)[:1000],
    }


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
    expected = "구매가격 검색·검토 보조시스템"

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
            _wait_heading(app, expected, timeout=30_000)
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

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1200})
            _install_browser_diagnostics(page, report)
            try:
                _wake_and_wait_dashboard(page, report)
                report["checks"].append("dashboard_rendered")

                _navigate(page, "빠른 검색")
                app = _app_frame(page)
                app.get_by_label("제품명", exact=True).wait_for(state="visible")
                app.get_by_label("제조사", exact=True).wait_for(state="visible")
                app.get_by_label("모델명", exact=True).wait_for(state="visible")
                app.get_by_role("button", name="시장가격 조사", exact=True).wait_for(
                    state="visible"
                )
                report["checks"].append("quick_search_form_rendered")

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

                _navigate_direct(page, "운영환경_진단", "운영환경 진단")
                app = _app_frame(page)
                app.get_by_role("heading", name="OCR Python 모듈", exact=True).wait_for(
                    state="visible"
                )
                runtime_body = app.locator("body").inner_text(timeout=10_000)
                report["ocr_runtime_readiness"] = {
                    label: _read_readiness_status(runtime_body, label)
                    for label in OCR_READINESS_LABELS
                }
                report["checks"].append("runtime_diagnostics_rendered")

                report["final_snapshot"] = _diagnostic_snapshot(
                    page, label="runtime-diagnostics-page"
                )
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
