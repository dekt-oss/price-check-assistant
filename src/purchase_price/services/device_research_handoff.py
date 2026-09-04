from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

DEVICE_RESEARCH_HANDOFF_SESSION_KEY = "device_research_prefill_v1"
QUOTE_REVIEW_ROWS_SESSION_KEY = "quote_review_rows_v1"
_MAX_FIELD_LENGTH = 500


@dataclass(frozen=True)
class DeviceResearchPrefill:
    """Non-sensitive identity hints passed from quote review to medical-device research.

    The payload intentionally excludes quote price, quantity, totals, file metadata, and uploaded
    file contents. Values are only user/quote-provided hints; they are not official MFDS identity
    until the target page verifies them against an official source.
    """

    product_name: str = ""
    manufacturer: str = ""
    model_name: str = ""
    specification: str = ""

    @property
    def has_identity_hint(self) -> bool:
        return any(
            (self.product_name, self.manufacturer, self.model_name, self.specification)
        )

    def to_session_payload(self) -> dict[str, str]:
        return asdict(self)


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text or text.casefold() in {"nan", "<na>", "none"}:
        return ""
    return text[:_MAX_FIELD_LENGTH]


def build_device_research_prefill(
    *,
    product_name: Any = "",
    manufacturer: Any = "",
    model_name: Any = "",
    specification: Any = "",
) -> DeviceResearchPrefill | None:
    """Build a bounded, identity-only handoff payload from an edited quote row."""

    prefill = DeviceResearchPrefill(
        product_name=_clean_text(product_name),
        manufacturer=_clean_text(manufacturer),
        model_name=_clean_text(model_name),
        specification=_clean_text(specification),
    )
    return prefill if prefill.has_identity_hint else None


def parse_device_research_prefill(payload: object) -> DeviceResearchPrefill | None:
    """Parse only the allow-listed identity fields from Streamlit session state."""

    if not isinstance(payload, Mapping):
        return None
    return build_device_research_prefill(
        product_name=payload.get("product_name", ""),
        manufacturer=payload.get("manufacturer", ""),
        model_name=payload.get("model_name", ""),
        specification=payload.get("specification", ""),
    )
