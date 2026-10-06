from pathlib import Path


def test_quote_uat_workspace_is_registered_separately_from_business_pages() -> None:
    home = Path("Home.py").read_text(encoding="utf-8")

    assert '"pages/13_견적추출_UAT.py"' in home
    assert 'title="견적추출 UAT"' in home
    assert 'url_path="quote-extraction-uat"' in home
    assert "*validation_pages" in home

    # The team's sidebar lists only the business pages; validation tools are admin-only links.
    sidebar = home.split("with st.sidebar:", 1)[1]
    business_links, admin_links = sidebar.split("if admin_pages:", 1)
    assert "validation_pages" not in business_links
    assert "validation_pages" in admin_links
