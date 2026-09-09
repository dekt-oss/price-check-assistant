from decimal import Decimal
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from purchase_price.services.quote_extraction import extract_quote_file


def _font() -> ImageFont.FreeTypeFont:
    candidates = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), 42)
    raise AssertionError("CI image-OCR E2E requires a standard DejaVu/Liberation font")


def _write_quote_image(path: Path) -> None:
    image = Image.new("RGB", (2100, 900), "white")
    draw = ImageDraw.Draw(image)
    font = _font()
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
    if path.suffix.casefold() in {".jpg", ".jpeg"}:
        image.save(path, format="JPEG", quality=96, subsampling=0)
    else:
        image.save(path, format="PNG")


@pytest.mark.parametrize("suffix", [".png", ".jpg"])
def test_real_image_quote_ocr_e2e(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"synthetic-quote{suffix}"
    _write_quote_image(path)

    result = extract_quote_file(path)

    assert len(result.items) == 1
    item = result.items[0]
    assert item.product_name.casefold() == "synth uat device"
    assert item.model_name.casefold() == "synth-model-1"
    assert item.quantity == Decimal("1")
    assert item.unit.casefold() == "set"
    assert item.unit_price == Decimal("1000000")
    assert item.total_amount == Decimal("1000000")
    assert item.vat_status == "포함"
    assert any("PNG/JPEG" in warning for warning in result.warnings)
