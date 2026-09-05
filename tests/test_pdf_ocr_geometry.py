from purchase_price.services.pdf_ocr import _ocr_words_and_text
from purchase_price.services.pdf_word_geometry import extract_word_geometry_rows_from_words
from purchase_price.services.quote_extraction import _resolve_header_field


def test_tesseract_word_boxes_reconstruct_quote_table() -> None:
    data = {
        "text": ["품", "명", "규", "격", "수량", "단가", "금액", "가스", "마취기", "Flow-C", "1", "66,000,000", "66,000,000"],
        "left": [10, 30, 180, 205, 300, 380, 500, 10, 55, 180, 300, 380, 500],
        "top": [10, 10, 10, 10, 10, 10, 10, 60, 60, 60, 60, 60, 60],
        "width": [15, 15, 15, 15, 35, 35, 35, 35, 55, 50, 10, 85, 85],
        "block_num": [1] * 13,
        "par_num": [1] * 13,
        "line_num": [1] * 7 + [2] * 6,
    }

    words, text = _ocr_words_and_text(data)
    rows = extract_word_geometry_rows_from_words(
        words,
        _resolve_header_field,
        y_tolerance=10,
    )

    assert "품 명 규 격 수량 단가 금액" in text
    assert rows[0] == ("품명", "규격", "수량", "단가", "금액")
    assert rows[1] == ("가스 마취기", "Flow-C", "1", "66,000,000", "66,000,000")
