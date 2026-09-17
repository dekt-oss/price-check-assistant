from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

from playwright.sync_api import sync_playwright

ARTIFACT_DIR = Path("artifacts/production-browser-smoke")
DIAGNOSTIC_RE = re.compile(r"R2_RUNTIME_DIAGNOSTIC code=([a-z0-9_]+)(?: missing=([^\s]+))?")


def _diagnostic_url(base_url: str) -> str:
    parts = urlsplit(base_url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urlencode({"_r2diag": "1"}), ""))


def main() -> None:
    production_url = os.environ.get("PRODUCTION_URL", "https://bp-price-research.streamlit.app/")
    url = _diagnostic_url(production_url)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    report: dict[str, object] = {"url": url, "status": "failure"}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_selector('iframe[title="streamlitApp"]', timeout=90_000)
            frame = page.frame_locator('iframe[title="streamlitApp"]').first
            frame.get_by_text("R2_RUNTIME_DIAGNOSTIC", exact=False).wait_for(timeout=90_000)
            body = frame.locator("body").inner_text(timeout=30_000)
            match = DIAGNOSTIC_RE.search(body)
            if match is None:
                raise RuntimeError("Production R2 diagnostic marker was not rendered")
            report.update(
                {
                    "status": "pass",
                    "code": match.group(1),
                    "missing": match.group(2) or "",
                }
            )
            page.screenshot(
                path=str(ARTIFACT_DIR / "r2-runtime-diagnostic.png"),
                full_page=True,
            )
        except Exception as exc:
            report["error"] = f"{type(exc).__name__}: {exc}"
            page.screenshot(
                path=str(ARTIFACT_DIR / "r2-runtime-diagnostic-failure.png"),
                full_page=True,
            )
        finally:
            browser.close()

    (ARTIFACT_DIR / "r2-runtime-diagnostic.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
