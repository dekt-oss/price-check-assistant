from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from openpyxl import Workbook

PRODUCTION_URL = os.getenv("PRODUCTION_URL", "https://bp-price-research.streamlit.app/")
UAT_URL = PRODUCTION_URL.rstrip("/") + "/quote-extraction-uat"
EXPECT_QUOTE_IMAGES = os.getenv("EXPECT_QUOTE_IMAGES", "").strip().casefold() in {
    "1",
    "true",
    "yes",
    "on",
}
ARTIFACT_DIR = Path("artifacts/production-browser-smoke")
APP_IFRAME = 'iframe[title="streamlitApp"]'
COMMERCIAL_GUIDANCE_PATTERN = re.compile(
    r"배송·설치·옵션·보증·유지보수·기타조건도\s+원문에\s+명시된\s+경우"
)


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


def _build_synthetic_quote_image(path: Path) -> None:
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (2100, 900), "white")
    draw = ImageDraw.Draw(image)
    font_candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    )
    font = None
    for candidate in font_candidates:
        if Path(candidate).is_file():
            font = ImageFont.truetype(candidate, 42)
            break
    if font is None:
        font = ImageFont.load_default()

    draw.text((80, 60), "QUOTATION", fill="black", font=font)
    draw.text((80, 140), "Manufacturer: SYNTH-MAKER", fill="black", font=font)

    columns = (
        (80, "Description", "SYNTH UAT DEVICE"),
        (650, "Model", "SYNTH-MODEL-1"),
        (1080, "Qty", "1"),
        (1220, "Unit", "set"),
        (1420, "Price", "1,000,000"),
        (1750, "Amount", "1,000,000"),
    )
    for x, header, value in columns:
        draw.text((x, 300), header, fill="black", font=font)
        draw.text((x, 430), value, fill="black", font=font)
    draw.text((80, 590), "VAT Included", fill="black", font=font)
    draw.text((80, 680), "Warranty: 3 years", fill="black", font=font)

    suffix = path.suffix.casefold()
    if suffix in {".jpg", ".jpeg"}:
        image.save(path, format="JPEG", quality=96, subsampling=0)
    else:
        image.save(path, format="PNG")


def _open_uat(page: Any) -> Any:
    page.goto(UAT_URL, wait_until="domcontentloaded", timeout=60_000)
    app = _app_frame(page)
    app.get_by_role("heading", name="견적추출 UAT", exact=True).wait_for(
        state="visible", timeout=60_000
    )
    return app


def _upload_one(page: Any, path: Path, *, timeout: int = 60_000) -> str:
    app = _open_uat(page)
    uploader = app.get_by_label("UAT 견적 파일", exact=True)
    uploader.wait_for(state="visible", timeout=30_000)
    file_input = uploader.locator('input[type="file"]')
    file_input.wait_for(state="attached", timeout=30_000)
    file_input.set_input_files(str(path))
    app.get_by_text("UAT-001", exact=False).first.wait_for(state="visible", timeout=timeout)

    metric = app.locator('[data-testid="stMetric"]').filter(has_text="자동 추출 품목").first
    metric.wait_for(state="visible", timeout=timeout)
    metric_text = metric.inner_text(timeout=10_000)
    if not re.search(r"자동 추출 품목\s*1(?:\D|$)", metric_text):
        raise RuntimeError(
            f"Synthetic {path.suffix} quote did not render exactly one extracted item; "
            f"metric={metric_text!r}"
        )
    return metric_text


def main() -> None:
    from playwright.sync_api import sync_playwright

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    quote_path = ARTIFACT_DIR / "synthetic-quote-uat.xlsx"
    png_path = ARTIFACT_DIR / "synthetic-quote-uat.png"
    jpeg_path = ARTIFACT_DIR / "synthetic-quote-uat.jpg"
    report_path = ARTIFACT_DIR / "quote-uat-upload-report.json"
    screenshot_path = ARTIFACT_DIR / "quote-uat-upload.png"
    _build_synthetic_quote(quote_path)
    if EXPECT_QUOTE_IMAGES:
        _build_synthetic_quote_image(png_path)
        _build_synthetic_quote_image(jpeg_path)

    report: dict[str, object] = {
        "production_url": PRODUCTION_URL,
        "uat_url": UAT_URL,
        "expect_quote_images": EXPECT_QUOTE_IMAGES,
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
                xlsx_metric = _upload_one(page, quote_path)
                report["checks"].extend(
                    ["uat_page_rendered", "synthetic_xlsx_uploaded", "synthetic_xlsx_item_extracted"]
                )
                report["xlsx_metric_text"] = xlsx_metric

                app = _app_frame(page)
                guidance = app.get_by_text(COMMERCIAL_GUIDANCE_PATTERN).first
                guidance.wait_for(state="visible", timeout=30_000)
                report["commercial_guidance_text"] = guidance.inner_text(timeout=10_000)
                report["checks"].append("commercial_review_guidance_rendered")

                if EXPECT_QUOTE_IMAGES:
                    png_metric = _upload_one(page, png_path, timeout=90_000)
                    report["png_metric_text"] = png_metric
                    report["checks"].extend(
                        ["synthetic_png_uploaded", "synthetic_png_item_extracted"]
                    )

                    jpeg_metric = _upload_one(page, jpeg_path, timeout=90_000)
                    report["jpeg_metric_text"] = jpeg_metric
                    report["checks"].extend(
                        ["synthetic_jpeg_uploaded", "synthetic_jpeg_item_extracted"]
                    )

                app = _app_frame(page)
                body = app.locator("body").inner_text(timeout=10_000)
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
