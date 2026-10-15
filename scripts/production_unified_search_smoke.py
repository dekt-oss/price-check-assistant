from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from openpyxl import Workbook

PRODUCTION_URL = os.getenv("PRODUCTION_URL", "https://bp-price-research.streamlit.app/")
ARTIFACT_DIR = Path("artifacts/production-browser-smoke")
APP_IFRAME = 'iframe[title="streamlitApp"]'
DEPLOYMENT_MARKER = "#purchase-workspace-runtime-v27"
# Streamlit Cloud has kept serving the previous build 10~25 minutes after a merge (2026-10-09, 10-13).
# `--wait-only` runs first in the workflow and waits this long, so a slow deploy shows up as its own
# "배포 지연" failure instead of a broken search step. Later in-run waits stay short.
DEPLOY_WAIT_SECONDS = float(os.getenv("DEPLOY_WAIT_SECONDS", "1500"))
IN_RUN_WAIT_SECONDS = 240.0
STREAMLIT_SLEEP_MARKER = "This app has gone to sleep due to inactivity."
STREAMLIT_WAKE_TEXT = "Yes, get this app back up!"
# The news and management pages are served from their own files; Production has kept an old copy of
# a page after a deploy before (2026-10-13), so the smoke opens both and checks their new headings.
TRACK_H_PAGES = (
    ("news-radar", "병원 뉴스", "주요 이슈"),
    ("hospital-benchmark", "병원 경영 비교", "경영 브리핑"),
)
# The simplified result screen (2026-10) states counts in plain words on the price card.
WORKSPACE_DIRECT_PATTERN = re.compile(r"같은 제품 거래\s*(\d+)건")
REFERENCE_PATTERN = re.compile(r"비슷한 품목 거래\s*(\d+)건")
RESULT_SECTIONS = ("얼마에 거래됐나", "누가 파는가")
# How long the bottom of the result page may take to arrive after the conclusion is visible.
SECTIONS_RENDER_SECONDS = 45
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


def _wake_if_sleeping(page: Any) -> None:
    """Click Streamlit Cloud's wake button if the idle-sleep screen is showing."""

    try:
        if STREAMLIT_SLEEP_MARKER in page.locator("body").inner_text(timeout=3_000):
            page.get_by_text(STREAMLIT_WAKE_TEXT, exact=True).first.click(timeout=10_000)
            page.wait_for_timeout(10_000)
    except Exception:
        return


def _wait_for_deployed_app(
    page: Any, report: dict[str, object], *, wait_seconds: float = IN_RUN_WAIT_SECONDS
) -> None:
    attempts: list[dict[str, object]] = []
    report["deployment_attempts"] = attempts
    deadline = time.monotonic() + wait_seconds

    while time.monotonic() < deadline:
        attempt = len(attempts) + 1
        try:
            response = page.goto(PRODUCTION_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3_000)
            _wake_if_sleeping(page)
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

    old_builds = sum(1 for item in attempts if item.get("status") == "old_deployment")
    if old_builds:
        raise RuntimeError(
            f"배포 지연: Production이 {wait_seconds / 60:.0f}분 동안 옛 배포를 보여 주었다"
            f"({old_builds}회 확인, {DEPLOYMENT_MARKER[1:]} 없음). Streamlit Cloud에서 Reboot app이 필요할 수 있다"
        )
    raise RuntimeError(f"Production did not expose {DEPLOYMENT_MARKER[1:]} in time")


def _verify_track_h_pages(page: Any, report: dict[str, object]) -> None:
    """Open the 병원 뉴스 and 병원 경영 비교 pages and wait for their current headings and first block."""

    results: dict[str, str] = {}
    report["track_h_pages"] = results
    for url_path, title, block in TRACK_H_PAGES:
        page.goto(PRODUCTION_URL.rstrip("/") + "/" + url_path, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3_000)
        app = _app(page)
        try:
            app.get_by_text(title, exact=True).first.wait_for(state="visible", timeout=60_000)
            app.get_by_text(block).first.wait_for(state="visible", timeout=60_000)
            _assert_no_error_text(_body_text(page))
        except Exception:
            results[url_path] = "fail"
            _save_snapshot(page, report, f"{url_path}-failure")
            raise
        results[url_path] = "pass"


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

    # The page streams in: the conclusion and 얼마에 거래됐나 appear before the same-품목 market and
    # the 입찰·계약 section at the bottom, which Production can draw seconds later.
    body = ""
    sections_deadline = time.monotonic() + SECTIONS_RENDER_SECONDS
    while time.monotonic() < sections_deadline:
        body = _body_text(page)
        _assert_no_error_text(body)
        if "얼마에 거래됐나" in body and "입찰·계약 참고자료" in body:
            break
        page.wait_for_timeout(1_000)
    report["sections_render_seconds"] = round(time.monotonic() - started, 2)
    if "얼마에 거래됐나" not in body or "입찰·계약 참고자료" not in body:
        raise RuntimeError("Default price result did not render after DFM100 search")
    report["price_section_rendered"] = True
    if "누가 파는가" not in body:
        raise RuntimeError("Supplier section did not render after DFM100 search")
    report["supplier_section_rendered"] = True
    # Only shown when MFDS lists the same item; absence is not a failure.
    report["comparison_section_rendered"] = "같은 품목의 다른 모델" in body

    quote_input = app.get_by_label("내 견적 단가", exact=True)
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




# ── UX v1.2 Q4: links, numeric sort and trade-window reopen on the DFM100 result ──
# st.dataframe draws on a canvas; glide-data-grid keeps an accessibility table (role="grid") with
# the raw cell values (a link cell holds its URL, a number cell its plain number), read here.
DATAFRAME_SELECTOR = '[data-testid="stDataFrame"]'
MODEL_LINK_HEADER = "가격 조사"
TRADE_TAB_PATTERN = re.compile(r"^거래 전체")
GRID_ROW_HEIGHT = 35  # Streamlit's default row and header height (px)
_GRID_SNAPSHOT_JS = """
(element) => {
  const table = element.querySelector('table[role="grid"]');
  if (!table) return null;
  const headers = [...table.querySelectorAll('th[role="columnheader"]')].map((cell) => cell.innerText.trim());
  const rows = [...table.querySelectorAll('tbody tr')].map(
    (row) => [...row.querySelectorAll('td[role="gridcell"]')].map((cell) => cell.innerText.trim())
  );
  return {headers, rows};
}
"""


def _grid(table: Any) -> dict[str, Any]:
    try:
        table.scroll_into_view_if_needed(timeout=10_000)
    except Exception:
        pass
    snapshot = table.evaluate(_GRID_SNAPSHOT_JS)
    return snapshot or {"headers": [], "rows": []}


def _find_grid(app: Any, wanted: Callable[[list[str]], bool], *, timeout_seconds: float = 30) -> tuple[Any, dict[str, Any]] | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for table in app.locator(DATAFRAME_SELECTOR).all():
            try:
                if not table.is_visible():
                    continue
                snapshot = _grid(table)
            except Exception:
                continue
            if snapshot["headers"] and wanted(snapshot["headers"]):
                return table, snapshot
        time.sleep(1)
    return None


def _grid_numbers(snapshot: dict[str, Any], header: str) -> list[float]:
    # A sorted header carries a sort mark ("↑ 가운데 값(원)").
    index = next((i for i, name in enumerate(snapshot["headers"]) if header in name), None)
    if index is None:
        return []
    values = []
    for row in snapshot["rows"]:
        text = row[index].replace(",", "") if index < len(row) else ""
        try:
            values.append(float(text))
        except ValueError:
            continue
    return values


def _verify_model_links(page: Any, report: dict[str, object]) -> Any | None:
    """(a) The same-item model table links each model to an absolute ?q= URL, never the inner /~/+/."""

    app = _app(page)
    if "같은 품목의 다른 모델" not in _body_text(page):
        report["model_link_check"] = {"status": "skipped", "note": "DFM100 result has no 같은 품목 section"}
        return None
    found = _find_grid(app, lambda headers: headers[0] == MODEL_LINK_HEADER)
    if found is None:
        raise RuntimeError("Same-item model table with a '가격 조사' link column did not render")
    table, snapshot = found
    hrefs = [row[0] for row in snapshot["rows"] if row and row[0]]
    bad = [href for href in hrefs if "?q=" not in href or "/~/+/" in href or not href.startswith("http")]
    if not hrefs or bad:
        raise RuntimeError(f"Same-item model links are not absolute ?q= URLs: {bad[:3] or 'none'}")
    top_links = app.locator("a.cm-top-link")
    top = [(top_links.nth(i).get_attribute("href") or "", top_links.nth(i).get_attribute("target") or "")
           for i in range(top_links.count())]
    bad_top = [href for href, target in top if "?q=" not in href or "/~/+/" in href or target != "_blank"]
    if bad_top:
        raise RuntimeError(f"Top-model links do not open a ?q= URL in a new tab: {bad_top[:3]}")
    report["model_link_check"] = {
        "status": "pass",
        "table_links_visible": len(hrefs),
        "sample_href": hrefs[0],
        "top_list_links": len(top),
    }
    return table


def _verify_numeric_sort(page: Any, report: dict[str, object], table: Any | None) -> None:
    """(b) A header click on a "(원)" column orders the cells by number, both directions."""

    if table is None:
        report["numeric_sort_check"] = {"status": "skipped", "note": "no same-item model table"}
        return
    app = _app(page)
    snapshot = _grid(table)
    header = next((name for name in snapshot["headers"] if name == "가운데 값(원)"), None) or next(
        (name for name in snapshot["headers"] if name.endswith("(원)")), None
    )
    values = _grid_numbers(snapshot, header) if header else []
    if header is None or len(set(values)) < 2:
        report["numeric_sort_check"] = {"status": "skipped", "note": f"fewer than 2 price values in {header}"}
        return
    # Hide every other column (the grid's own Show/hide menu) so the header to click sits at the left.
    table.hover()
    table.locator('[aria-label="Show/hide columns"]').first.click(timeout=10_000)
    menu = app.locator('[data-testid="stDataFrameColumnVisibilityMenu"]')
    menu.wait_for(state="visible", timeout=10_000)
    boxes = menu.locator('input[type="checkbox"]')
    for index in range(boxes.count()):
        box = boxes.nth(index)
        label = box.get_attribute("aria-label") or ""
        if label in {"Select all", "(index)", header}:
            continue
        if box.is_checked():
            box.locator("xpath=ancestor::label[1]").click(timeout=10_000)  # the input itself is hidden
    page.keyboard.press("Escape")
    page.wait_for_timeout(800)
    grid_box = table.locator('[data-testid="stDataFrameResizable"]').bounding_box()
    if grid_box is None:
        raise RuntimeError("Same-item model table has no size to click its header")
    orders = []
    for _click in range(2):
        page.mouse.click(grid_box["x"] + 70, grid_box["y"] + GRID_ROW_HEIGHT / 2)
        page.wait_for_timeout(1_200)
        sorted_grid = _grid(table)
        shown = _grid_numbers(sorted_grid, header)[:2]
        if len(shown) < 2:
            raise RuntimeError(f"Sorted {header} shows fewer than 2 numbers: {shown} {sorted_grid['headers']}")
        orders.append(shown)
    ascending, descending = orders
    if not (ascending[0] <= ascending[1] and descending[0] >= descending[1] and ascending != descending):
        raise RuntimeError(f"{header} does not sort by number: first click {ascending}, second {descending}")
    report["numeric_sort_check"] = {
        "status": "pass",
        "column": header,
        "ascending_first_two": ascending,
        "descending_first_two": descending,
    }


def _verify_trade_dialog_reopen(page: Any, report: dict[str, object]) -> None:
    """(c) Picking the same 거래 전체 row twice opens the trade window twice."""

    app = _app(page)
    tab = app.get_by_role("tab", name=TRADE_TAB_PATTERN)
    if tab.count() == 0:
        report["trade_dialog_reopen_check"] = {"status": "skipped", "note": "no 거래 전체 tab"}
        return
    tab.first.click(timeout=10_000)
    found = _find_grid(app, lambda headers: "거래 총액(원)" in headers)
    if found is None:
        report["trade_dialog_reopen_check"] = {"status": "skipped", "note": "no selectable trade table"}
        return
    table, _snapshot = found
    grid_box = table.locator('[data-testid="stDataFrameResizable"]').bounding_box()
    if grid_box is None:
        raise RuntimeError("거래 전체 table has no size to pick a row")
    checkbox = (grid_box["x"] + 18, grid_box["y"] + GRID_ROW_HEIGHT * 1.5)
    dialog = app.locator('[role="dialog"]')
    opened = []
    for attempt in range(2):
        page.mouse.click(*checkbox)
        try:
            dialog.first.wait_for(state="visible", timeout=30_000)
        except Exception as exc:
            raise RuntimeError(f"Trade window did not open on pick {attempt + 1} of the same row") from exc
        opened.append(attempt + 1)
        page.keyboard.press("Escape")
        dialog.first.wait_for(state="hidden", timeout=15_000)
        page.wait_for_timeout(1_500)
    report["trade_dialog_reopen_check"] = {"status": "pass", "opened_on_picks": opened}


def _verify_result_interactions(page: Any, report: dict[str, object]) -> None:
    """Q4 checks after the DFM100 flow; each records pass or skipped, a failure raises."""

    table = _verify_model_links(page, report)
    _verify_numeric_sort(page, report, table)
    _verify_trade_dialog_reopen(page, report)
    _save_snapshot(page, report, "unified-search-dfm100-interactions")


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

def wait_only() -> None:
    """Wait for the new deployment marker only (first workflow step after a merge)."""

    from playwright.sync_api import sync_playwright

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {"production_url": PRODUCTION_URL, "status": "failure"}
    started = time.monotonic()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1440, "height": 1200})
                _wait_for_deployed_app(page, report, wait_seconds=DEPLOY_WAIT_SECONDS)
                report["status"] = "pass"
            finally:
                browser.close()
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        output = ARTIFACT_DIR / "deployment-wait-report.json"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))


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
                _verify_result_interactions(page, report)
                _verify_quote_upload_uses_unified_workspace(browser, report)
                _verify_track_h_pages(page, report)
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
    if "--wait-only" in sys.argv[1:]:
        wait_only()
    else:
        main()
