from pathlib import Path

from purchase_price.services.purchase_workspace_handoff import (
    PURCHASE_WORKSPACE_HANDOFF_SESSION_KEY,
    QUOTE_AUTO_ROUTE_FILE_SESSION_KEY,
)


def test_quote_review_upload_routes_first_extracted_item_to_unified_workspace() -> None:
    source = Path("src/purchase_price/ui/quote_market_research.py").read_text(
        encoding="utf-8"
    )

    assert "newly_extracted" in source
    assert "QUOTE_AUTO_ROUTE_FILE_SESSION_KEY" in source
    assert "PURCHASE_WORKSPACE_HANDOFF_SESSION_KEY" in source
    assert 'st.switch_page("pages/1_대시보드.py")' in source
    assert "first_item = state.items[0]" in source


def test_home_and_quote_review_share_the_same_auto_route_guard() -> None:
    dashboard = Path("pages/1_대시보드.py").read_text(encoding="utf-8")
    quote = Path("src/purchase_price/ui/quote_market_research.py").read_text(
        encoding="utf-8"
    )

    assert "QUOTE_AUTO_ROUTE_FILE_SESSION_KEY" in dashboard
    assert "QUOTE_AUTO_ROUTE_FILE_SESSION_KEY" in quote
    assert "quote_auto_route_file_v1" not in dashboard
    assert QUOTE_AUTO_ROUTE_FILE_SESSION_KEY == "quote_auto_route_file_v1"
    assert PURCHASE_WORKSPACE_HANDOFF_SESSION_KEY == "purchase_workspace_handoff_v1"
