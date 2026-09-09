from purchase_price.services.pdf_word_geometry import extract_word_geometry_rows_from_words
from purchase_price.services.quote_extraction_core import _resolve_header_field


def _word(text: str, x0: float, x1: float, top: float) -> dict[str, object]:
    return {"text": text, "x0": x0, "x1": x1, "top": top}


def test_spaced_unit_and_price_are_independent_columns() -> None:
    words = [
        _word("Description", 80, 310, 100),
        _word("Model", 650, 770, 100),
        _word("Qty", 1080, 1150, 100),
        _word("Unit", 1220, 1300, 100),
        _word("Price", 1420, 1520, 100),
        _word("Amount", 1750, 1910, 100),
        _word("SYNTH", 80, 215, 230),
        _word("UAT", 235, 315, 230),
        _word("DEVICE", 335, 485, 230),
        _word("SYNTH-MODEL-1", 650, 995, 230),
        _word("1", 1080, 1100, 230),
        _word("set", 1220, 1285, 230),
        _word("1,000,000", 1420, 1630, 230),
        _word("1,000,000", 1750, 1960, 230),
    ]

    rows = extract_word_geometry_rows_from_words(words, _resolve_header_field, y_tolerance=10)

    assert rows[0] == ("품명", "모델명", "수량", "단위", "단가", "금액")
    assert rows[1] == (
        "SYNTH UAT DEVICE",
        "SYNTH-MODEL-1",
        "1",
        "set",
        "1,000,000",
        "1,000,000",
    )


def test_close_unit_price_remains_compound_unit_price_header() -> None:
    words = [
        _word("Description", 80, 310, 100),
        _word("Unit", 650, 730, 100),
        _word("Price", 740, 840, 100),
        _word("Amount", 1050, 1210, 100),
        _word("DEVICE", 80, 240, 230),
        _word("1,000,000", 660, 860, 230),
        _word("1,000,000", 1050, 1250, 230),
    ]

    rows = extract_word_geometry_rows_from_words(words, _resolve_header_field, y_tolerance=10)

    assert rows[0] == ("품명", "단가", "금액")
    assert rows[1] == ("DEVICE", "1,000,000", "1,000,000")
