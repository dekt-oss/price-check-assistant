from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_quote_comparability_gate_page_loads_without_upload() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "pages" / "11_견적_비교가능성_게이트.py")

    app.run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "견적가격 비교가능성 안전게이트"
    assert any("견적서를 업로드" in item.value for item in app.info)
