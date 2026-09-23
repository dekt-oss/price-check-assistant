from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

PURCHASE_WORKSPACE_HANDOFF_SESSION_KEY = "purchase_workspace_handoff_v1"
_MAX_TEXT = 500


@dataclass(frozen=True)
class PurchaseWorkspaceHandoff:
    product_name: str = ""
    manufacturer: str = ""
    model_name: str = ""
    specification: str = ""
    quote_unit_price: Decimal | None = None

    @property
    def has_identity(self) -> bool:
        return any(
            (
                self.product_name,
                self.manufacturer,
                self.model_name,
                self.specification,
            )
        )

    def to_session_payload(self) -> dict[str, str | None]:
        return {
            "product_name": self.product_name,
            "manufacturer": self.manufacturer,
            "model_name": self.model_name,
            "specification": self.specification,
            "quote_unit_price": (
                str(self.quote_unit_price) if self.quote_unit_price is not None else None
            ),
        }


def _text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "<na>", "none"}:
        return ""
    return text[:_MAX_TEXT]


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def build_purchase_workspace_handoff(
    *,
    product_name: Any = "",
    manufacturer: Any = "",
    model_name: Any = "",
    specification: Any = "",
    quote_unit_price: Any = None,
) -> PurchaseWorkspaceHandoff | None:
    handoff = PurchaseWorkspaceHandoff(
        product_name=_text(product_name),
        manufacturer=_text(manufacturer),
        model_name=_text(model_name),
        specification=_text(specification),
        quote_unit_price=_decimal(quote_unit_price),
    )
    return handoff if handoff.has_identity else None


def parse_purchase_workspace_handoff(payload: object) -> PurchaseWorkspaceHandoff | None:
    if not isinstance(payload, Mapping):
        return None
    return build_purchase_workspace_handoff(
        product_name=payload.get("product_name"),
        manufacturer=payload.get("manufacturer"),
        model_name=payload.get("model_name"),
        specification=payload.get("specification"),
        quote_unit_price=payload.get("quote_unit_price"),
    )
