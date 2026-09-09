from pathlib import Path

import pytest

from purchase_price.services.quote_uat_strategy import (
    default_uat_strategy,
    uat_strategy_options,
)


@pytest.mark.parametrize("kind", ["png", "jpg", "jpeg"])
def test_image_uat_strategy_is_explicit_additional_coverage(kind: str) -> None:
    assert default_uat_strategy(
        file_kind=kind,
        extraction_strategies=("image_local_ocr",),
    ) == "image_ocr"
    assert uat_strategy_options(file_kind=kind) == ("image_ocr",)


def test_main_quote_uploader_accepts_required_file_families() -> None:
    source = Path("src/purchase_price/ui/quote_market_research.py").read_text(encoding="utf-8")
    assert 'type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"]' in source
    assert "PDF · Excel(.xlsx/.xls) · PNG · JPG/JPEG" in source


def test_uat_uploader_accepts_required_file_families() -> None:
    source = Path("pages/13_견적추출_UAT.py").read_text(encoding="utf-8")
    assert 'type=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"]' in source
    assert "PNG/JPG/JPEG" in source
