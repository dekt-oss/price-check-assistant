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

    assert "일반 검색과 동일한 상세결과 열기" in quote_source
    assert "PURCHASE_WORKSPACE_HANDOFF_SESSION_KEY" in quote_source
    assert 'st.switch_page("pages/1_대시보드.py")' in quote_source

    assert "PURCHASE_WORKSPACE_HANDOFF_SESSION_KEY" in home_source
    assert "parse_purchase_workspace_handoff" in home_source
    assert 'search_state["origin"] = "quote"' in home_source
    assert "일반 통합검색과 동일한 구매조사 파이프라인" in home_source


def test_home_quote_upload_auto_routes_first_item_through_unified_search() -> None:
    home_source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert 'QUOTE_AUTO_ROUTE_FILE_KEY = "quote_auto_route_file_v1"' in home_source
    assert "견적 첫 품목을 일반 통합검색과 동일하게 조사하고 있습니다" in home_source
    assert "quote_result = _execute_search(" in home_source
    assert 'quote_result["origin"] = "quote"' in home_source
    assert 'quote_result["quote_item_index"] = 0' in home_source
    assert 'st.session_state[HOME_SEARCH_STATE_KEY] = quote_result' in home_source
    assert 'st.switch_page("pages/2_견적_검토.py")' in home_source


def test_quote_batch_page_is_explicitly_summary_not_second_search_engine() -> None:
    quote_source = Path("src/purchase_price/ui/quote_market_research.py").read_text(
        encoding="utf-8"
    )

    assert "다품목 견적의 빠른 요약·검증 화면" in quote_source
    assert "일반 통합검색과 동일한 구매조사 Workspace" in quote_source
