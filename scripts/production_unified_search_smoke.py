from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from openpyxl import Workbook

PRODUCTION_URL = os.getenv("PRODUCTION_URL", "https://bp-price-research.streamlit.app/")
ARTIFACT_DIR = Path("artifacts/production-browser-smoke")
APP_IFRAME = 'iframe[title="streamlitApp"]'
DEPLOYMENT_MARKER = "#purchase-workspace-runtime-v20"
# The simplified result screen (2026-10) states counts in plain words on the price card.
WORKSPACE_DIRECT_PATTERN = re.compile(r"같은 제품 거래\s*(\d+)건")
REFERENCE_PATTERN = re.compile(r"비슷한 품목 거래\s*(\d+)건")
RESULT_SECTIONS = ("얼마에 거래됐나", "누가 파는가")
ERROR_TEXTS = (
    "AttributeError",
    "This app has encountered an error",
    "Error running app",
)


def _app(page: Any) -> Any:
    return page.frame_locator(APP_IFRAME)


def _body_text(page: Any) -> str:
    return _app(page).locator("body").inner_text(timeout=10_000)


def _float_attributes(page: Any, selector: str, keys: tuple[str, ...]) -> dict[str, float]:
    marker = _app(page).locator(selector).first
    if marker.count() == 0:
        return {}

    values: dict[str, float] = {}
    for key in keys:
        raw = marker.get_attribute(f"data-{key}")
        if raw is None:
            continue
        try:
            values[key] = float(raw)
        except ValueError:
            continue
    return values


def _search_timings(page: Any) -> dict[str, float]:
    return _float_attributes(
        page,
        "#purchase-search-timings-v1",
        ("identity", "track_b", "mfds", "safety", "research", "total"),
    )


def _research_stage_timings(page: Any) -> dict[str, float]:
    return _float_attributes(
        page,
        "#purchase-research-stage-timings-v1",
        (
            "direct_search_all",
            "classification",
            "procurement_research",
            "bid_items",
            "contracts",
            "lifecycle",
            "shopping_discovery",
            "catalog",
            "runner_total",
        ),
    )


def _safety_diagnostic(page: Any) -> dict[str, str]:
    marker = _app(page).locator("#purchase-safety-diagnostic-v1").first
    if marker.count() == 0:
        return {}
    return {
        key: str(marker.get_attribute(f"data-{key}") or "")
        for key in ("status", "error-kind", "error-type")
    }


def _research_status(page: Any) -> str:
    marker = _app(page).locator("#purchase-research-deferred-v1").first
    if marker.count() == 0:
        return ""
    return str(marker.get_attribute("data-status") or "")


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

    raise RuntimeError("Production did not expose purchase-workspace-runtime-v20 in time")


def _wait_for_nonzero_result(page: Any, *, timeout_seconds: float = 75) -> tuple[int, int]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            body = _body_text(page)
        except Exception:
            page.wait_for_timeout(1_000)
            continue
        _assert_no_error_text(body)
        reference_match = REFERENCE_PATTERN.search(body)
        workspace_match = WORKSPACE_DIRECT_PATTERN.search(body)
        if workspace_match is not None and all(section in body for section in RESULT_SECTIONS):
            strict_count = int(workspace_match.group(1))
            reference_count = int(reference_match.group(1)) if reference_match is not None else 0
            if strict_count < 1:
                raise RuntimeError(
                    "DFM100 one-line search did not recover direct A/B evidence: "
                    f"strict={strict_count}, reference={reference_count}"
                )
            return strict_count, reference_count
        page.wait_for_timeout(1_000)
    raise RuntimeError("DFM100 Production unified search did not render a non-zero result summary")


def _verify_workspace_sections_persist_result(page: Any, report: dict[str, object]) -> None:
    """The result is one scrolling page now: check its sections, then change the quote price
    (a Streamlit rerun) and confirm the same result is still shown with the quote position."""

    started = time.monotonic()
    app = _app(page)

    body = _body_text(page)
    _assert_no_error_text(body)
    if "얼마에 거래됐나" not in body or "입찰·계약 참고자료" not in body:
        raise RuntimeError("Default price result did not render after DFM100 search")
    report["price_section_rendered"] = True
    if "누가 파는가" not in body:
        raise RuntimeError("Supplier section did not render after DFM100 search")
    report["supplier_section_rendered"] = True
    # Only shown when MFDS lists the same item; absence is not a failure.
    report["comparison_section_rendered"] = "같은 품목의 다른 모델" in body

    quote_input = app.get_by_label("내 견적가 (원)", exact=True)
    quote_input.wait_for(state="visible", timeout=20_000)
    quote_input.fill("12000000")
    quote_input.press("Enter")
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        body = _body_text(page)
        _assert_no_error_text(body)
        if (
            "내 견적가 12,000,000원은" in body
            and WORKSPACE_DIRECT_PATTERN.search(body) is not None
            and "얼마에 거래됐나" in body
        ):
            report["quote_position_rendered"] = True
            report["direct_workspace_sections_seconds"] = round(
                time.monotonic() - started,
                2,
            )
            _save_snapshot(page, report, "unified-search-dfm100-workspace")
            return
        page.wait_for_timeout(1_000)
    raise RuntimeError("DFM100 result did not survive the quote-price rerun")


def _submit_dfm100(page: Any, report: dict[str, object]) -> None:
    attempts: list[dict[str, object]] = []
    report["search_attempts"] = attempts

    for attempt in range(1, 4):
        try:
            app = _app(page)
            search = app.get_by_label("통합 검색", exact=True)
            search.wait_for(state="visible", timeout=20_000)
            search.fill("DFM100")
            direct_started = time.monotonic()
            app.get_by_role("button", name="검색", exact=True).click()
            strict_count, reference_count = _wait_for_nonzero_result(page)
            report["direct_search_first_result_seconds"] = round(
                time.monotonic() - direct_started,
                2,
            )
            report["direct_server_search_timings_seconds"] = _search_timings(page)
            report["direct_research_stage_timings_seconds"] = _research_stage_timings(page)
            report["direct_safety_diagnostic"] = _safety_diagnostic(page)
            report["direct_research_status"] = _research_status(page)
            if report["direct_research_status"] != "pending":
                raise RuntimeError(
                    "Initial DFM100 workspace did not defer C/Research after A/B result"
                )
            if report["direct_search_first_result_seconds"] > 25:
                raise RuntimeError(
                    "Initial DFM100 A/B workspace exceeded 25 second latency gate"
                )
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
            _verify_workspace_sections_persist_result(page, report)
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

    raise RuntimeError("DFM100 Production unified search did not pass result + workspace-section E2E")




def _build_dfm100_quote(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Quote"
    sheet.append(["품명", "제조사", "모델명", "규격", "수량", "단위", "단가", "금액"])
    sheet.append(
        [
            "심장충격기",
            "Philips",
            "DFM100",
            "",
            1,
            "대",
            12000000,
            12000000,
        ]
    )
    workbook.save(path)


def _verify_quote_upload_uses_unified_workspace(browser: Any, report: dict[str, object]) -> None:
    quote_path = ARTIFACT_DIR / "synthetic-home-dfm100-quote.xlsx"
    _build_dfm100_quote(quote_path)

    page = browser.new_page(viewport={"width": 1440, "height": 1200})
    try:
        _wait_for_deployed_app(page, report)
        app = _app(page)
        uploader = app.get_by_label("견적서 업로드", exact=True).first
        uploader.wait_for(state="visible", timeout=20_000)
        file_input = uploader.locator('input[type="file"]')
        file_input.wait_for(state="attached", timeout=20_000)
        quote_started = time.monotonic()
        file_input.set_input_files(str(quote_path))

        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            body = _body_text(page)
            _assert_no_error_text(body)
            if (
                f"견적서 {quote_path.name}" in body
                and "DFM100" in body
                and all(section in body for section in RESULT_SECTIONS)
            ):
                direct_match = WORKSPACE_DIRECT_PATTERN.search(body)
                if direct_match is None or int(direct_match.group(1)) < 1:
                    raise RuntimeError(
                        "Quote upload reached unified workspace but did not recover DFM100 "
                        "direct A/B evidence"
                    )
                report["quote_upload_unified_workspace"] = True
                report["quote_upload_direct_count"] = int(direct_match.group(1))
                report["quote_upload_workspace_seconds"] = round(
                    time.monotonic() - quote_started,
                    2,
                )
                report["quote_server_search_timings_seconds"] = _search_timings(page)
                report["quote_research_stage_timings_seconds"] = _research_stage_timings(page)
                report["quote_safety_diagnostic"] = _safety_diagnostic(page)
                report["quote_research_status"] = _research_status(page)
                if report["quote_research_status"] != "pending":
                    raise RuntimeError(
                        "Quote DFM100 workspace did not defer C/Research after A/B result"
                    )
                if report["quote_upload_workspace_seconds"] > 35:
                    raise RuntimeError(
                        "Quote DFM100 A/B workspace exceeded 35 second latency gate"
                    )
                _save_snapshot(page, report, "quote-upload-dfm100-unified-workspace")
                return
            page.wait_for_timeout(1_000)

        raise RuntimeError(
            "Home quote upload did not route DFM100 into the same unified purchase workspace"
        )
    finally:
        page.close()

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
                _verify_quote_upload_uses_unified_workspace(browser, report)
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
