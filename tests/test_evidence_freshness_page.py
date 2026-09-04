from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_evidence_freshness_page_loads() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "pages" / "12_가격근거_최신성.py")

    app.run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "공개가격 근거 최신성 확인"
