from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_quote_comparability_is_absorbed_into_quote_review_page() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "pages" / "2_견적_검토.py")

    app.run(timeout=10)

    assert not app.exception
    assert any("견적서 검토" in item.value for item in app.markdown)
    assert any("견적서 파일을 올리면" in item.value for item in app.markdown)
