"""Hand the identified product from the purchase workspace to the 의료기기 조회 page.

Only identity fields cross pages: MFDS product name, model, registered company, item numbers
and UDI-DI. Quote prices, quantities, file names and procurement rows never do (#201: "가격/
수량/파일원문 등 민감·불필요 필드는 전달하지 않음").

The handoff carries a token so the receiving page fills its inputs once per new search and
does not overwrite what the user typed afterwards.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

MEDICAL_LOOKUP_HANDOFF_KEY = "medical_lookup_handoff_v1"
MEDICAL_LOOKUP_APPLIED_KEY = "medical_lookup_handoff_applied_v1"

# Widget keys on pages/4_의료기기_조회.py, filled from the handoff.
WIDGET_PRODUCT = "medical_market_product"
WIDGET_MODEL = "medical_market_model"
WIDGET_MANUFACTURER = "medical_market_manufacturer"
WIDGET_SAFETY_MODEL = "medical_safety_model"
WIDGET_SAFETY_PERMITS = "medical_safety_permits"
WIDGET_SAFETY_COMPANY = "medical_safety_company"
WIDGET_UDI = "medical_udi_di"


@dataclass(frozen=True)
class MedicalLookupHandoff:
    product_name: str = ""
    model_name: str = ""
    company: str = ""
    permit_numbers: tuple[str, ...] = ()
    udi_di: str = ""
    source: str = ""

    @property
    def token(self) -> str:
        payload = "|".join(
            (self.product_name, self.model_name, self.company, ",".join(self.permit_numbers), self.udi_di)
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @property
    def is_empty(self) -> bool:
        return not (self.product_name or self.model_name or self.permit_numbers or self.udi_di)

    def to_state(self) -> dict[str, Any]:
        state = asdict(self)
        state["permit_numbers"] = list(self.permit_numbers)
        state["token"] = self.token
        return state


def _text(value: Any) -> str:
    return str(value or "").strip()


def _unique(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(text for text in (_text(v) for v in values) if text))


def build_medical_lookup_handoff(
    *,
    identity_records: Iterable[Any] = (),
    model_info_records: Iterable[Any] = (),
    query_product_name: str = "",
    query_model_name: str = "",
) -> MedicalLookupHandoff:
    """Best confirmed identity first: product-info index, then exact 형명 rows, then the query."""

    identity = list(identity_records)
    if identity:
        first = identity[0]
        return MedicalLookupHandoff(
            product_name=_text(getattr(first, "product_name", None)) or _text(query_product_name),
            model_name=_text(getattr(first, "model_name", None)) or _text(query_model_name),
            company=_text(getattr(first, "registered_company", None)),
            permit_numbers=_unique(getattr(item, "permit_number", None) for item in identity),
            udi_di=_text(getattr(first, "udi_di", None)),
            source="식약처 제품정보",
        )
    exact = list(model_info_records)
    if exact:
        first = exact[0]
        return MedicalLookupHandoff(
            product_name=_text(getattr(first, "product_name", None)) or _text(query_product_name),
            model_name=_text(getattr(first, "model_name", None)) or _text(query_model_name),
            permit_numbers=_unique(getattr(item, "permit_number", None) for item in exact),
            source="식약처 형명정보",
        )
    return MedicalLookupHandoff(
        product_name=_text(query_product_name),
        model_name=_text(query_model_name),
        source="검색어",
    )


def handoff_widget_values(handoff: Mapping[str, Any]) -> dict[str, str]:
    """Widget key -> value for the 의료기기 조회 page; empty fields are left untouched."""

    permits = ", ".join(_text(p) for p in handoff.get("permit_numbers") or () if _text(p))
    values = {
        WIDGET_PRODUCT: _text(handoff.get("product_name")),
        WIDGET_MODEL: _text(handoff.get("model_name")),
        WIDGET_MANUFACTURER: _text(handoff.get("company")),
        WIDGET_SAFETY_MODEL: _text(handoff.get("model_name")),
        WIDGET_SAFETY_PERMITS: permits,
        WIDGET_SAFETY_COMPANY: _text(handoff.get("company")),
        WIDGET_UDI: _text(handoff.get("udi_di")),
    }
    return {key: value for key, value in values.items() if value}


def apply_handoff(session_state: Any) -> Mapping[str, Any] | None:
    """Fill widget state once per new handoff token; returns the applied handoff or None."""

    handoff = session_state.get(MEDICAL_LOOKUP_HANDOFF_KEY)
    if not isinstance(handoff, Mapping):
        return None
    token = _text(handoff.get("token"))
    if not token:
        return None
    if session_state.get(MEDICAL_LOOKUP_APPLIED_KEY) != token:
        for key, value in handoff_widget_values(handoff).items():
            session_state[key] = value
        session_state[MEDICAL_LOOKUP_APPLIED_KEY] = token
    return handoff
