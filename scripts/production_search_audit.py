from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

PRODUCTION_URL = os.getenv("PRODUCTION_URL", "https://bp-price-research.streamlit.app/")
ARTIFACT_DIR = Path("artifacts/production-search-audit")
APP_IFRAME = 'iframe[title="streamlitApp"]'
DEPLOYMENT_MARKER = "#unified-search-runtime-v3"
RESULT_PATTERN = re.compile(r"동일성 확인\s*(\d+)건\s*·\s*검색 참고\s*(\d+)건")
ERROR_TEXTS = (
    "AttributeError",
    "This app has encountered an error",
    "Error running app",
)

QUERIES = (
    "DFM100",
    "필립스 Efficia DFM100 심장 충격기",
    "ApeosPrint C5570 GK",
    "CX30N",
    "ROTAPRO",
    "MinION Mk1D",
)

KEYWORDS = (
    "거래가격",
    "동일성 확인",
    "검색 참고",
    "직접",
    "Research",
    "타 기관",
    "나라장터",
    "사전규격",
    "입찰",
    "낙찰",
    "동일 모델",
    "동일 제조사",
    "0건",
    "추가 자료 확인 완료",
)


def _app(page: Any) -> Any:
    return page.frame_locator(APP_IFRAME)


def _body(page: Any) -> str:
    return _app(page).locator("body").inner_text(timeout=15_000)


def _slug(text: str) -> str:
    value = re.sub(r"[^0-9A-Za-z가-힣]+", "-", text).strip("-")
    return value[:60] or "query"


def _wait_ready(page: Any) -> None:
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        try:
            page.goto(PRODUCTION_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(3_000)
            app = _app(page)
            app.get_by_label("통합 검색", exact=True).wait_for(state="visible", timeout=15_000)
            app.get_by_role("button", name="검색", exact=True).wait_for(
                state="visible", timeout=15_000
            )
            marker = app.locator(DEPLOYMENT_MARKER)
            if marker.count() > 0:
                page.wait_for_timeout(2_000)
                return
        except Exception:
            pass
        page.wait_for_timeout(5_000)
    raise RuntimeError("Production unified search did not become ready")


def _interesting_lines(body: str) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in body.splitlines():
        line = " ".join(raw.split()).strip()
        if not line or line in seen:
            continue
        if any(keyword.casefold() in line.casefold() for keyword in KEYWORDS):
            seen.add(line)
            output.append(line)
    return output[:100]


def _run_query(page: Any, query: str) -> dict[str, Any]:
    _wait_ready(page)
    app = _app(page)
    before = _body(page)
    search = app.get_by_label("통합 검색", exact=True)
    search.fill(query)
    app.get_by_role("button", name="검색", exact=True).click()

    deadline = time.monotonic() + 100
    body = before
    while time.monotonic() < deadline:
        page.wait_for_timeout(1_000)
        body = _body(page)
        error_text = next((text for text in ERROR_TEXTS if text in body), None)
        if error_text:
            raise RuntimeError(f"rendered error: {error_text}")
        changed = body != before
        has_result_signal = (
            RESULT_PATTERN.search(body) is not None
            or "거래가격" in body
            or "추가 자료 확인 완료" in body
            or "유의미한 Research 결과가 0건" in body
        )
        if changed and has_result_signal:
            break
    else:
        raise RuntimeError(f"query did not render a result signal: {query}")

    match = RESULT_PATTERN.search(body)
    strict_count = int(match.group(1)) if match else None
    reference_count = int(match.group(2)) if match else None

    details_clicked = False
    try:
        toggle = app.get_by_text("상세 조사·근거 보기", exact=True)
        if toggle.count() > 0 and toggle.first.is_visible():
            toggle.first.click()
            page.wait_for_timeout(8_000)
            details_clicked = True
            body = _body(page)
    except Exception:
        pass

    screenshot = ARTIFACT_DIR / f"{_slug(query)}.png"
    page.screenshot(path=str(screenshot), full_page=True)

    return {
        "query": query,
        "status": "pass",
        "strict_count": strict_count,
        "reference_count": reference_count,
        "details_clicked": details_clicked,
        "interesting_lines": _interesting_lines(body),
        "body_prefix": body[:10000],
        "screenshot": str(screenshot),
    }


def main() -> None:
    from playwright.sync_api import sync_playwright

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "production_url": PRODUCTION_URL,
        "queries": list(QUERIES),
        "status": "pass",
        "results": [],
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1600})
        try:
            for query in QUERIES:
                try:
                    result = _run_query(page, query)
                except Exception as exc:
                    result = {
                        "query": query,
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}"[:2000],
                    }
                    report["status"] = "partial"
                report["results"].append(result)
        finally:
            browser.close()

    output = ARTIFACT_DIR / "report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
