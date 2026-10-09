from pathlib import Path

from purchase_price.services.purchase_workspace_handoff import (
    PURCHASE_WORKSPACE_HANDOFF_SESSION_KEY,
)


def test_quote_review_upload_stays_on_the_item_table_and_hands_off_per_item() -> None:
    """견적서 검토 (design step 4) shows every item side by side, so an upload here no longer
    jumps to 가격 조사 with item 1; each item opens there from its own button instead."""

    source = Path("src/purchase_price/ui/quote_market_research.py").read_text(
        encoding="utf-8"
    )

    assert "newly_extracted" in source
    assert "QUOTE_AUTO_ROUTE_FILE_SESSION_KEY" in source
    assert "first_item = state.items[0]" not in source
    render_detail = source.split("def _render_detail_card", 1)[1].split("\ndef ", 1)[0]
    assert "PURCHASE_WORKSPACE_HANDOFF_SESSION_KEY" in render_detail
    assert 'st.switch_page("pages/1_대시보드.py")' in render_detail
    upload_flow = source.split("def render_quote_market_research", 1)[1]
    assert upload_flow.count("st.switch_page(") == 0


def test_home_and_quote_review_share_the_same_auto_route_guard() -> None:
    dashboard = Path("pages/1_대시보드.py").read_text(encoding="utf-8")
    quote = Path("src/purchase_price/ui/quote_market_research.py").read_text(
        encoding="utf-8"
    )

    assert "QUOTE_AUTO_ROUTE_FILE_SESSION_KEY" in dashboard
    assert "QUOTE_AUTO_ROUTE_FILE_SESSION_KEY" in quote
    assert 'QUOTE_AUTO_ROUTE_FILE_SESSION_KEY = "quote_auto_route_file_v1"' in dashboard
    assert 'QUOTE_AUTO_ROUTE_FILE_SESSION_KEY = "quote_auto_route_file_v1"' in quote
    assert "QUOTE_AUTO_ROUTE_FILE_SESSION_KEY," not in dashboard.split(
        "from purchase_price.services.purchase_workspace_handoff import (", 1
    )[1].split(")", 1)[0]
    assert "QUOTE_AUTO_ROUTE_FILE_SESSION_KEY," not in quote.split(
        "from purchase_price.services.purchase_workspace_handoff import (", 1
    )[1].split(")", 1)[0]
    assert PURCHASE_WORKSPACE_HANDOFF_SESSION_KEY == "purchase_workspace_handoff_v1"
