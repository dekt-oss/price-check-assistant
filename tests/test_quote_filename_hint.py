import inspect

from purchase_price.ui import quote_market_research


def test_filename_product_candidate_recovers_korean_quote_name() -> None:
    assert (
        quote_market_research._filename_product_candidate("극초단파치료시스템 견적1.pdf")
        == "극초단파치료시스템"
    )
    assert (
        quote_market_research._filename_product_candidate("02_환자감시장치_견적서_v2.png")
        == "환자감시장치"
    )


def test_filename_product_candidate_rejects_generic_or_date_only_names() -> None:
    assert quote_market_research._filename_product_candidate("견적1.pdf") == ""
    assert quote_market_research._filename_product_candidate("2026-09-10.pdf") == ""


def test_filename_hint_is_explicitly_unverified() -> None:
    source = inspect.getsource(quote_market_research._render_inline_manual_item_form)

    assert "파일명 기반 후보이며 OCR 확정값이나 공식 제품식별값은 아닙니다" in source
    assert "value=product_candidate" in source
