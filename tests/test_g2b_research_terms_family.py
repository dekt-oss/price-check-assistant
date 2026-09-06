from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_research_terms import research_terms_for_query
from purchase_price.services.market_research import build_market_research_terms


def test_anesthesia_family_terms_expand_plain_keyword() -> None:
    terms = build_market_research_terms(ProductQuery(product_name="마취"))

    assert terms[:5] == ("마취", "마취기", "가스마취기", "전신가스마취기", "마취기시스템")


def test_anesthesia_family_terms_expand_descriptive_quote_label_without_identity_promotion() -> None:
    query = ProductQuery(product_name="마취기(Anesthesia Machine)", model_name="FLOW-C")

    assert research_terms_for_query(query) == (
        "마취기",
        "가스마취기",
        "전신가스마취기",
        "마취기시스템",
    )
    terms = build_market_research_terms(query)
    assert terms[0] == "FLOW-C"
    assert "가스마취기" in terms
