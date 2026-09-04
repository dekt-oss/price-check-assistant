from decimal import Decimal

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
