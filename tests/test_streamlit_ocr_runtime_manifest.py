from pathlib import Path


def test_streamlit_runtime_bypasses_broken_apt_without_losing_ocr_contract() -> None:
    requirements = Path("requirements.txt").read_text(encoding="utf-8")
    deferred_packages = Path("packages.ocr.txt").read_text(encoding="utf-8")

    assert "pytesseract>=0.3.13,<1" in requirements
    assert "pypdfium2>=5.9,<6" in requirements
    assert not Path("packages.txt").exists()
    assert "tesseract-ocr" in deferred_packages.splitlines()
    assert "tesseract-ocr-kor" in deferred_packages.splitlines()
    assert "tesseract-ocr-eng" in deferred_packages.splitlines()
