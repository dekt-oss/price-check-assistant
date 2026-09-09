from __future__ import annotations

from pathlib import Path

from purchase_price.services.image_ocr import ImageOcrUnavailableError, ocr_pil_image_text
from purchase_price.services.quote_extraction_core import QuoteItem
from purchase_price.services.quote_ruled_table_ocr import (
    _remove_long_grid_lines,
    recover_sparse_single_item_from_text,
)


def recover_sparse_ruled_table_image_quote(
    path: Path,
    *,
    languages: str = "kor+eng",
) -> QuoteItem | None:
    """Recover a single ruled-table quote directly from PNG/JPEG input.

    This mirrors the scanned-PDF ruled-table fallback but skips PDF rasterization. It preserves the
    same fail-closed row synthesis requirements in `recover_sparse_single_item_from_text`.
    """

    try:
        from PIL import Image, ImageOps
    except ImportError:
        return None

    try:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            original_text = ocr_pil_image_text(
                image,
                languages=languages,
                psm=11,
            )
            cleaned = _remove_long_grid_lines(image)
            sparse_text = ocr_pil_image_text(
                cleaned,
                languages=languages,
                psm=11,
            )
    except (OSError, ImageOcrUnavailableError):
        return None

    return recover_sparse_single_item_from_text(
        sparse_text,
        context_text=original_text,
        page_number=1,
    )
