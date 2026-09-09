from pathlib import Path


def test_quote_uat_workspace_is_registered_separately_from_business_pages() -> None:
    home = Path("Home.py").read_text(encoding="utf-8")

    assert '"검증": validation_pages' in home
    assert '"pages/13_견적추출_UAT.py"' in home
    assert 'title="견적추출 UAT"' in home
    assert 'url_path="quote-extraction-uat"' in home

    business_section = home.split("business_pages = [", 1)[1].split("]", 1)[0]
    assert "pages/13_견적추출_UAT.py" not in business_section
