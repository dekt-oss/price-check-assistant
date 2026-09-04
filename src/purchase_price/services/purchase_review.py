from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from purchase_price.schemas import ProductQuery


@dataclass(frozen=True)
class PurchaseReviewInput:
    """Canonical input shared by direct search and quote-row review.

    This contract contains only the fields needed to identify one purchasable item and the
    optional quote unit price used for comparison. File metadata, quote totals, source rows,
    and other document context intentionally stay outside this object.
    """

    product_name: str = ""
    manufacturer: str = ""
    model_name: str = ""
    specification: str = ""
    quote_unit_price: Decimal | None = None

    @property
    def has_identity_hint(self) -> bool:
        return any(
            (
                self.product_name,
                self.manufacturer,
                self.model_name,
                self.specification,
            )
        )

    def to_product_query(self) -> ProductQuery:
        return ProductQuery(
            product_name=self.product_name,
            manufacturer=self.manufacturer,
            model_name=self.model_name,
            specification=self.specification,
        )


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "<na>", "none"}:
        return ""
    return text


def build_purchase_review_input(
    *,
    product_name: Any = "",
    manufacturer: Any = "",
    model_name: Any = "",
    specification: Any = "",
    quote_unit_price: Decimal | None = None,
) -> PurchaseReviewInput | None:
    """Normalize one direct-search input or edited quote row into the shared contract.

    A quote price by itself is not enough to identify a product, so an identity-free input is
    rejected. The caller remains responsible for parsing/validating user-entered money strings.
    """

    review_input = PurchaseReviewInput(
        product_name=_clean_text(product_name),
        manufacturer=_clean_text(manufacturer),
        model_name=_clean_text(model_name),
        specification=_clean_text(specification),
        quote_unit_price=quote_unit_price,
    )
    return review_input if review_input.has_identity_hint else None
