from purchase_price.services.runtime_readiness import _run_synthetic_ocr_execution


def test_synthetic_pdf_rasterize_and_tesseract_execution() -> None:
    ready, detail = _run_synthetic_ocr_execution()
    assert ready, detail
