from decimal import Decimal
from pathlib import Path

from purchase_price.services.purchase_workspace_handoff import (
    build_purchase_workspace_handoff,
    parse_purchase_workspace_handoff,
)


def test_quote_item_handoff_keeps_identity_and_quote_price_only() -> None:
    handoff = build_purchase_workspace_handoff(
        product_name=" 심장충격기 ",
        manufacturer=" Philips ",
        model_name=" Efficia DFM100 ",
        specification=" 200J ",
        quote_unit_price="12,500,000",
    )

    assert handoff is not None
    assert handoff.product_name == "심장충격기"
    assert handoff.manufacturer == "Philips"
    assert handoff.model_name == "Efficia DFM100"
    assert handoff.specification == "200J"
    assert handoff.quote_unit_price == Decimal("12500000")
    assert handoff.to_session_payload() == {
        "product_name": "심장충격기",
        "manufacturer": "Philips",
        "model_name": "Efficia DFM100",
        "specification": "200J",
        "quote_unit_price": "12500000",
    }


def test_handoff_rejects_price_without_identity() -> None:
    assert build_purchase_workspace_handoff(quote_unit_price="1000") is None


def test_handoff_parser_fail_closes_on_unrelated_payload() -> None:
    assert parse_purchase_workspace_handoff({"file_name": "private.pdf", "total": "1000"}) is None


def test_quote_and_home_pages_share_purchase_workspace_handoff_contract() -> None:
    quote_source = Path("src/purchase_price/ui/quote_market_research.py").read_text(
        encoding="utf-8"
    )
    home_source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "가격 조사에서 이 품목 자세히 보기" in quote_source
    assert "PURCHASE_WORKSPACE_HANDOFF_SESSION_KEY" in quote_source
    assert 'st.switch_page("pages/1_대시보드.py")' in quote_source

    assert "PURCHASE_WORKSPACE_HANDOFF_SESSION_KEY" in home_source
    assert "parse_purchase_workspace_handoff" in home_source
    # Opened from 견적서 검토: a strip naming the item and a link back, not a second item table.
    assert 'search_state["origin"] = "quote_review"' in home_source
    assert "_render_quote_review_strip(search_state)" in home_source
    assert 'search_text=(handoff.model_name or handoff.product_name)' in home_source
    assert "_render_quote_items(search_state)" in home_source


def test_home_quote_upload_auto_routes_first_item_through_unified_search() -> None:
    home_source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "QUOTE_AUTO_ROUTE_FILE_SESSION_KEY" in home_source
    assert "1번 품목을 조사하고 있습니다" in home_source
    assert "quote_result = _execute_search(" in home_source
    assert 'search_text=(item.model_name or item.product_name or "")' in home_source
    assert 'product_name=""' in home_source
    assert 'manufacturer=""' in home_source
    assert 'model_name=""' in home_source
    assert 'specification=""' in home_source
    assert 'quote_result["origin"] = "quote"' in home_source
    assert 'quote_result["quote_item_index"] = 0' in home_source
    assert 'st.session_state[HOME_SEARCH_STATE_KEY] = quote_result' in home_source
    assert 'st.page_link("pages/2_견적_검토.py", label="견적 상세 검증 열기"' in home_source
    assert 'st.switch_page("pages/2_견적_검토.py")' not in home_source


def test_quote_batch_page_is_explicitly_summary_not_second_search_engine() -> None:
    quote_source = Path("src/purchase_price/ui/quote_market_research.py").read_text(
        encoding="utf-8"
    )

    assert "each item's full research opens in the 가격 조사" in quote_source
    assert "the same search as a typed model name" in quote_source


def test_home_structured_quote_fields_use_identity_canonicalization() -> None:
    home_source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "lookup_key = raw_search or model_name.strip() or product_name.strip()" in home_source
    assert "canonicalize_product_query(base_query, identity)" in home_source
    assert "canonical.query.model_name" in home_source


def test_handoff_remembers_where_it_came_from() -> None:
    device = parse_purchase_workspace_handoff({"model_name": "HeartOn A16-DS", "source": "device"})
    assert device is not None and device.source == "device"
    assert device.to_session_payload()["source"] == "device"
    unknown = parse_purchase_workspace_handoff({"model_name": "M40", "source": "somewhere"})
    assert unknown is not None and unknown.source == "" and "source" not in unknown.to_session_payload()


def test_only_a_real_quote_review_handoff_shows_the_quote_strip() -> None:
    home = Path("pages/1_대시보드.py").read_text(encoding="utf-8")
    device_page = Path("pages/4_의료기기_조회.py").read_text(encoding="utf-8")
    quote = Path("src/purchase_price/ui/quote_market_research.py").read_text(encoding="utf-8")
    assert '"source": "device"' in device_page
    assert '"source": "quote_review"' in quote
    branch = home[home.index('if handoff_source == "device":') :]
    # Device: its own back link; the quote strip only with a loaded quote (file and items).
    assert (
        branch.index('search_state["origin"] = "device"')
        < branch.index("elif isinstance(review_state, QuoteReviewState) and review_state.items:")
        < branch.index('search_state["origin"] = "quote_review"')
    )
    assert '"의료기기 허가·안전에서 연 제품입니다", "pages/4_의료기기_조회.py"' in home
