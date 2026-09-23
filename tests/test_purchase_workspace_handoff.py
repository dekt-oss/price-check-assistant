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

    assert "통합 구매조사 열기" in quote_source
    assert "PURCHASE_WORKSPACE_HANDOFF_SESSION_KEY" in quote_source
    assert 'st.switch_page("pages/1_대시보드.py")' in quote_source

    assert "PURCHASE_WORKSPACE_HANDOFF_SESSION_KEY" in home_source
    assert "parse_purchase_workspace_handoff" in home_source
    assert 'search_state["origin"] = "quote"' in home_source
    assert "견적서 품목에서 이어진 조사" in home_source
