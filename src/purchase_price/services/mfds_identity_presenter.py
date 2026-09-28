from __future__ import annotations

from typing import Any

from purchase_price.evidence_domain import IdentityEvidenceStatus, MfdsItemAuthorizationType
from purchase_price.services.matching import normalize_text

MFDS_PRODUCT_INFO_DATASET_URL = "https://www.data.go.kr/data/15073875/openapi.do"


def mfds_item_authorization_type(value: Any) -> MfdsItemAuthorizationType:
    """Classify an MFDS item number without requiring new properties on cached record classes."""
    permit_number = getattr(value, "permit_number", value)
    text = str(permit_number or "").strip().replace(" ", "")
    if text.startswith(("제허", "수허")):
        return MfdsItemAuthorizationType.PERMIT
    if text.startswith(("제인", "수인")):
        return MfdsItemAuthorizationType.CERTIFICATION
    if text.startswith(("제신", "수신")):
        return MfdsItemAuthorizationType.NOTIFICATION
    return MfdsItemAuthorizationType.UNKNOWN


def mfds_identity_status(lookup: Any) -> IdentityEvidenceStatus:
    """Compute V3 identity state from old or new lookup objects.

    Streamlit Community Cloud can retain an older imported module while reloading a page.
    This helper therefore relies only on fields that existed before Workspace V3.
    """
    status = str(getattr(lookup, "status", "") or "")
    if status in {"unavailable", "not_ingested"}:
        return IdentityEvidenceStatus.UNAVAILABLE
    if status == "success_0":
        return IdentityEvidenceStatus.NOT_FOUND_IN_COVERAGE
    if status != "success":
        return IdentityEvidenceStatus.UNAVAILABLE

    match_type = str(getattr(lookup, "match_type", "") or "")
    if match_type in {"model", "udi"}:
        identity_keys = {
            (
                normalize_text(getattr(item, "permit_number", None)),
                normalize_text(getattr(item, "registered_company", None)),
                normalize_text(getattr(item, "product_name", None)),
            )
            for item in tuple(getattr(lookup, "records", ()) or ())
            if any(
                (
                    normalize_text(getattr(item, "permit_number", None)),
                    normalize_text(getattr(item, "registered_company", None)),
                    normalize_text(getattr(item, "product_name", None)),
                )
            )
        }
        if len(identity_keys) > 1:
            return IdentityEvidenceStatus.AMBIGUOUS
    return IdentityEvidenceStatus.FOUND
