from __future__ import annotations

from collections.abc import Sequence

UAT_STRATEGY_LABELS: dict[str, str] = {
    "xlsx": "Excel(.xlsx) 표본",
    "xls": "Excel(.xls) 표본",
    "pdf_text": "PDF 텍스트 표본",
    "pdf_ocr": "PDF 스캔/OCR 표본",
    "pdf_commercial": "PDF 상업조건 표본",
}

PDF_UAT_STRATEGIES = ("pdf_text", "pdf_ocr", "pdf_commercial")


def default_uat_strategy(*, file_kind: str, extraction_strategies: Sequence[str]) -> str:
    """Return the canonical release-gate key suggested by the actual extraction path.

    `pdf_commercial` is intentionally never inferred. It is a UAT coverage designation that means
    the reviewer selected a PDF whose commercial terms are part of the ground-truth review; the
    operator must choose it explicitly in the workspace.
    """

    kind = file_kind.strip().casefold().lstrip(".")
    if kind == "xlsx":
        return "xlsx"
    if kind == "xls":
        return "xls"
    if kind != "pdf":
        raise ValueError(f"지원하지 않는 UAT 파일 형식: {file_kind}")

    strategies = {value.strip().casefold() for value in extraction_strategies}
    if strategies & {"pdf_local_ocr", "pdf_scan_no_text", "pdf_ocr_unavailable"}:
        return "pdf_ocr"
    return "pdf_text"


def uat_strategy_options(*, file_kind: str) -> tuple[str, ...]:
    kind = file_kind.strip().casefold().lstrip(".")
    if kind == "xlsx":
        return ("xlsx",)
    if kind == "xls":
        return ("xls",)
    if kind == "pdf":
        return PDF_UAT_STRATEGIES
    raise ValueError(f"지원하지 않는 UAT 파일 형식: {file_kind}")
