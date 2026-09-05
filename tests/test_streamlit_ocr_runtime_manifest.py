from pathlib import Path


def test_streamlit_runtime_declares_local_ocr_dependencies() -> None:
    requirements = Path("requirements.txt").read_text(encoding="utf-8")
    packages = Path("packages.txt").read_text(encoding="utf-8")

    assert "pytesseract>=0.3.13,<1" in requirements
    assert "pypdfium2>=5.9,<6" in requirements
    assert "tesseract-ocr" in packages.splitlines()
    assert "tesseract-ocr-kor" in packages.splitlines()
    assert "tesseract-ocr-eng" in packages.splitlines()
