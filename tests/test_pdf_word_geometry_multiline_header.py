from purchase_price.services.pdf_word_geometry import extract_word_geometry_rows_from_words


def _resolve_header(value: str) -> str | None:
    normalized = "".join(value.split()).casefold()
    return {
        "품명": "product_name",
        "규격": "specification",
        "수량": "quantity",
        "단가": "unit_price",
        "금액": "total_amount",
    }.get(normalized)


def _word(text: str, x0: float, x1: float, top: float) -> dict[str, object]:
    return {"text": text, "x0": x0, "x1": x1, "top": top}


def test_reconstructs_table_when_ocr_header_is_split_across_lines() -> None:
    words = [
        _word("품명", 0, 40, 10),
        _word("규격", 100, 140, 10),
        _word("수량", 200, 240, 10),
        _word("단가", 300, 340, 25),
        _word("금액", 400, 440, 25),
        _word("극초단파치료시스템", 0, 60, 45),
        _word("MW-1000", 100, 145, 45),
        _word("1", 205, 215, 45),
        _word("12,000,000", 300, 350, 45),
        _word("12,000,000", 400, 450, 45),
    ]

    rows = extract_word_geometry_rows_from_words(words, _resolve_header, y_tolerance=3)

    assert rows == (
        ("품명", "규격", "수량", "단가", "금액"),
        ("극초단파치료시스템", "MW-1000", "1", "12,000,000", "12,000,000"),
    )
