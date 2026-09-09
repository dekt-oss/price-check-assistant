from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

PRODUCTION_URL = os.getenv("PRODUCTION_URL", "https://bp-price-research.streamlit.app/")
ARTIFACT_DIR = Path("artifacts/production-scan-ocr-smoke")
APP_IFRAME = 'iframe[title="streamlitApp"]'
SUCCESS_STRATEGY = "추출 경로: PDF 로컬 OCR(Tesseract kor+eng)"
OCR_FAILURE_MARKERS = (
    "스캔 PDF로 감지했지만 로컬 OCR을 실행할 수 없습니다",
    "스캔 PDF에 로컬 OCR을 실행했지만 인식 가능한 텍스트를 찾지 못했습니다",
    "로컬 Tesseract OCR 실행에 실패했습니다",
    "Error installing requirements",
    "Error running app",
)


def _app_frame(page: Any) -> Any:
    return page.frame_locator(APP_IFRAME)


def _snapshot(page: Any, label: str) -> dict[str, object]:
    result: dict[str, object] = {"label": label, "url": page.url}
    try:
        app = _app_frame(page)
        result["app_body_text_prefix"] = app.locator("body").inner_text(timeout=5_000)[:8000]
    except Exception as exc:
        result["app_body_error"] = f"{type(exc).__name__}: {exc}"[:1000]
    try:
        screenshot = ARTIFACT_DIR / f"{label}.png"
        page.screenshot(path=str(screenshot), full_page=True)
        result["screenshot"] = str(screenshot)
    except Exception as exc:
        result["screenshot_error"] = f"{type(exc).__name__}: {exc}"[:1000]
    return result


def _build_image_only_quote_pdf(path: Path) -> None:
    import pypdfium2 as pdfium
    from pypdf import PdfReader
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen.canvas import Canvas

    text_pdf = path.with_name("synthetic-source-text.pdf")
    canvas = Canvas(str(text_pdf), pagesize=letter)
    canvas.setFont("Helvetica-Bold", 14)
    headers = (
        ("Description", 30),
        ("Specification", 220),
        ("Quantity", 355),
        ("Unit Price", 420),
        ("Amount", 520),
    )
    for label, x in headers:
        canvas.drawString(x, 700, label)

    canvas.setFont("Helvetica", 14)
    row = (
        ("Infusion Pump", 30),
        ("IP-200", 220),
        ("2", 365),
        ("1250000", 420),
        ("2500000", 520),
    )
    for value, x in row:
        canvas.drawString(x, 660, value)
    canvas.save()

    document = pdfium.PdfDocument(str(text_pdf))
    page = bitmap = None
    try:
        page = document[0]
        bitmap = page.render(scale=220 / 72)
        bitmap.to_pil().convert("RGB").save(path, format="PDF", resolution=220.0)
    finally:
        if bitmap is not None:
            bitmap.close()
        if page is not None:
            page.close()
        document.close()
        text_pdf.unlink(missing_ok=True)

    reader = PdfReader(str(path))
    if any((pdf_page.extract_text() or "").strip() for pdf_page in reader.pages):
        raise RuntimeError("Synthetic Production OCR fixture unexpectedly contains a text layer")


def _wait_for_extraction_result(page: Any, *, timeout_seconds: float = 120.0) -> None:
    app = _app_frame(page)
    deadline = time.monotonic() + timeout_seconds
    last_body = ""
    while time.monotonic() < deadline:
        try:
            last_body = app.locator("body").inner_text(timeout=5_000)
        except Exception:
            page.wait_for_timeout(1_000)
            continue
        if SUCCESS_STRATEGY in last_body:
            return
        failure = next((marker for marker in OCR_FAILURE_MARKERS if marker in last_body), "")
        if failure:
            raise RuntimeError(f"Production scan OCR reported failure: {failure}")
        page.wait_for_timeout(1_000)
    raise RuntimeError(
        "Production scan OCR did not reach the OCR extraction strategy within the bounded wait; "
        f"last body prefix={last_body[:1000]!r}"
    )


def _verify_extracted_fields(page: Any) -> dict[str, str]:
    app = _app_frame(page)
    app.get_by_text(SUCCESS_STRATEGY, exact=True).wait_for(state="visible", timeout=10_000)
    app.get_by_text("추출 품목", exact=True).wait_for(state="visible", timeout=10_000)
    app.get_by_text("1건", exact=True).first.wait_for(state="visible", timeout=10_000)

    app.get_by_text("추출 품목 수정", exact=True).click(timeout=10_000)
    fields = {
        "product_name": app.get_by_label("품명", exact=True).input_value(timeout=10_000),
        "specification": app.get_by_label("규격", exact=True).input_value(timeout=10_000),
        "unit_price": app.get_by_label("견적 단가", exact=True).input_value(timeout=10_000),
        "quantity": app.get_by_label("수량", exact=True).input_value(timeout=10_000),
    }
    expected = {
        "product_name": "Infusion Pump",
        "specification": "IP-200",
        "unit_price": "1250000",
        "quantity": "2",
    }
    if fields != expected:
        raise RuntimeError(f"Production OCR extracted unexpected synthetic fields: {fields!r}")
    return fields


def _run_attempt(page: Any, pdf_path: Path, attempt: int) -> dict[str, object]:
    response = page.goto(PRODUCTION_URL, wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(3_000)
    app = _app_frame(page)
    app.get_by_role(
        "heading", name="구매가격 검색·검토 보조시스템", exact=True
    ).wait_for(state="visible", timeout=30_000)
    app.get_by_role("link", name="견적 검토", exact=True).click()
    app.get_by_role("heading", name="견적 검토", exact=True).wait_for(
        state="visible", timeout=30_000
    )

    uploader = app.locator(
        'section[aria-label="견적서 파일"] input[type="file"]'
    )
    uploader.set_input_files(str(pdf_path), timeout=15_000)
    _wait_for_extraction_result(page)
    fields = _verify_extracted_fields(page)

    result = _snapshot(page, f"success-attempt-{attempt}")
    result.update(
        {
            "attempt": attempt,
            "status": "pass",
            "root_http_status": response.status if response is not None else None,
            "extracted_fields": fields,
            "strategy": SUCCESS_STRATEGY,
        }
    )
    return result


def main() -> None:
    from playwright.sync_api import sync_playwright

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = ARTIFACT_DIR / "synthetic-image-only-quote.pdf"
    _build_image_only_quote_pdf(pdf_path)

    report: dict[str, object] = {
        "production_url": PRODUCTION_URL,
        "status": "failure",
        "fixture": {
            "kind": "synthetic image-only PDF",
            "contains_real_quote_data": False,
            "expected_product_name": "Infusion Pump",
            "expected_specification": "IP-200",
        },
        "attempts": [],
    }
    started = time.monotonic()
    final_error: Exception | None = None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for attempt in range(1, 4):
                    page = browser.new_page(viewport={"width": 1440, "height": 1200})
                    try:
                        attempt_result = _run_attempt(page, pdf_path, attempt)
                        attempts = report["attempts"]
                        assert isinstance(attempts, list)
                        attempts.append(attempt_result)
                        report["status"] = "pass"
                        final_error = None
                        break
                    except Exception as exc:
                        final_error = exc
                        attempt_result = _snapshot(page, f"failure-attempt-{attempt}")
                        attempt_result.update(
                            {
                                "attempt": attempt,
                                "status": "failure",
                                "error_type": type(exc).__name__,
                                "error_message": str(exc)[:3000],
                            }
                        )
                        attempts = report["attempts"]
                        assert isinstance(attempts, list)
                        attempts.append(attempt_result)
                        if attempt < 3:
                            page.close()
                            time.sleep(20)
                            continue
                        break
                    finally:
                        if not page.is_closed():
                            page.close()
            finally:
                browser.close()
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        if final_error is not None:
            report["error_type"] = type(final_error).__name__
            report["error_message"] = str(final_error)[:3000]
        report_path = ARTIFACT_DIR / "report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))

    if report["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
