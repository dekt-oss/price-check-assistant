from decimal import Decimal
from pathlib import Path

from streamlit.testing.v1 import AppTest

from purchase_price.schemas import ProductQuery
from purchase_price.services.purchase_review import (
    PurchaseReviewInput,
    build_purchase_review_input,
)


def test_purchase_review_input_normalizes_identity_fields() -> None:
    review_input = build_purchase_review_input(
        product_name="  심장충격기  ",
        manufacturer=" 예시메디칼 ",
        model_name=" DFM-100 ",
        specification=" biphasic ",
        quote_unit_price=Decimal("1234567"),
    )

    assert review_input == PurchaseReviewInput(
        product_name="심장충격기",
        manufacturer="예시메디칼",
        model_name="DFM-100",
        specification="biphasic",
        quote_unit_price=Decimal("1234567"),
    )


def test_purchase_review_input_rejects_price_without_identity() -> None:
    assert (
        build_purchase_review_input(
            product_name=" ",
            manufacturer=None,
            model_name="<NA>",
            specification="nan",
            quote_unit_price=Decimal("1000"),
        )
        is None
    )


def test_purchase_review_input_converts_to_existing_product_query_contract() -> None:
    review_input = PurchaseReviewInput(
        product_name="약품냉장고",
        manufacturer="GMS",
        model_name="GMSR-182",
        specification="182L",
        quote_unit_price=Decimal("5000000"),
    )

    assert review_input.to_product_query() == ProductQuery(
        product_name="약품냉장고",
        manufacturer="GMS",
        model_name="GMSR-182",
        specification="182L",
    )


def test_direct_and_quote_style_inputs_share_the_same_contract() -> None:
    direct = build_purchase_review_input(
        product_name="약품냉장고",
        manufacturer="GMS",
        model_name="GMSR-182",
        specification="182L",
        quote_unit_price=Decimal("5000000"),
    )
    quote_row = build_purchase_review_input(
        product_name=" 약품냉장고 ",
        manufacturer=" GMS ",
        model_name=" GMSR-182 ",
        specification=" 182L ",
        quote_unit_price=Decimal("5000000"),
    )

    assert direct == quote_row


def test_existing_direct_search_page_loads_with_shared_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "pages" / "1_통합검색.py")

    app.run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "통합검색"


def test_existing_quote_page_loads_with_shared_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "pages" / "2_견적서_분석.py")

    app.run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "견적서 분석"
