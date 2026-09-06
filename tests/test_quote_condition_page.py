from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_quote_condition_review_is_absorbed_into_quote_review_page() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "pages" / "2_견적_검토.py")

    app.run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "견적 검토"
    assert any("업로드" in item.value for item in app.info)


def test_external_condition_comparison_is_absorbed_into_quote_review_page() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "pages" / "2_견적_검토.py")

    app.run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "견적 검토"
