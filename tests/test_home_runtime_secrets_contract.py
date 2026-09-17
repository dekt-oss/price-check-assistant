from pathlib import Path


def test_home_hydrates_runtime_secrets_before_page_routing() -> None:
    source = Path("Home.py").read_text(encoding="utf-8")

    import_marker = "from purchase_price.ui.runtime_secrets import hydrate_streamlit_runtime_secrets"
    hydrate_marker = "hydrate_streamlit_runtime_secrets()"
    navigation_marker = "page = st.navigation("

    assert import_marker in source
    assert hydrate_marker in source
    assert navigation_marker in source
    assert source.index(hydrate_marker) < source.index(navigation_marker)
