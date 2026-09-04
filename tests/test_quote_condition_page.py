from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_quote_condition_page_loads_without_upload() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "pages" / "9_견적조건_확인.py")

    app.run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "견적서 상업조건 자동추출"
    assert any("견적서를 업로드" in item.value for item in app.info)
