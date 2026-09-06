from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_evidence_freshness_is_absorbed_into_quote_review_page() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "pages" / "2_견적_검토.py")

    app.run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "견적 검토"
