from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


BUSINESS_PAGES = (
    "pages/1_대시보드.py",
    "pages/2_견적_검토.py",
    "pages/3_빠른_검색.py",
    "pages/4_의료기기_조회.py",
)
ADMIN_PAGE = "pages/9_관리.py"
REMOVED_PAGES = (
    "pages/1_통합검색.py",
    "pages/2_견적서_분석.py",
    "pages/7_나라장터_계약근거.py",
    "pages/9_견적조건_확인.py",
    "pages/10_견적_외부조건_대조.py",
    "pages/11_견적_비교가능성_게이트.py",
    "pages/12_가격근거_최신성.py",
)


def test_home_registers_four_business_pages_and_admin_page() -> None:
    text = (ROOT / "Home.py").read_text(encoding="utf-8")
    assert "st.navigation" in text
    for path in BUSINESS_PAGES:
        assert path in text
        assert (ROOT / path).exists()
    assert ADMIN_PAGE in text
    assert (ROOT / ADMIN_PAGE).exists()
    assert "ADMIN_MODE" in text


def test_absorbed_legacy_pages_are_removed() -> None:
    for path in REMOVED_PAGES:
        assert not (ROOT / path).exists(), path


def test_runtime_python_does_not_link_to_removed_pages() -> None:
    forbidden = tuple(path.removeprefix("pages/") for path in REMOVED_PAGES)
    runtime_files = [ROOT / "Home.py", *(ROOT / "pages").glob("*.py")]
    for file_path in runtime_files:
        text = file_path.read_text(encoding="utf-8")
        for filename in forbidden:
            assert filename not in text, f"{file_path.relative_to(ROOT)} still references {filename}"
