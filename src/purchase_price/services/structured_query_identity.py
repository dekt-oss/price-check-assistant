from __future__ import annotations

from dataclasses import dataclass

from purchase_price.evidence_domain import IdentityEvidenceStatus
from purchase_price.schemas import ProductQuery
from purchase_price.services.mfds_identity_corroboration import identity_needs_review
from purchase_price.services.mfds_identity_index import MfdsIdentityLookup


@dataclass(frozen=True)
class CanonicalQueryIdentity:
    query: ProductQuery
    identity: MfdsIdentityLookup | None
    canonicalized: bool
    ambiguous: bool


def canonicalize_product_query(
    query: ProductQuery,
    identity: MfdsIdentityLookup | None,
) -> CanonicalQueryIdentity:
    """Apply a single unambiguous MFDS identity to a structured query.

    Only product/model identity fields are canonicalized. Manufacturer remains the user's or
    quote's manufacturer hint because MFDS registered company is a different relationship.
    Specification is preserved exactly because the identity index does not prove configuration
    equivalence.
    """

    if (
        identity is None
        or identity.status != "success"
        or not identity.records
        or identity.match_type not in {"model", "permit", "udi"}
    ):
        return CanonicalQueryIdentity(query, identity, False, False)

    if identity.identity_status == IdentityEvidenceStatus.AMBIGUOUS:
        return CanonicalQueryIdentity(query, identity, False, True)

    # A short or numeric model key that neither the manufacturer nor the product name
    # corroborates is not allowed to rewrite the query; it is surfaced as a candidate.
    if identity_needs_review(
        identity,
        manufacturer=query.manufacturer,
        product_name=query.product_name,
    ):
        return CanonicalQueryIdentity(query, identity, False, True)

    models = identity.model_names
    products = identity.product_names
    canonical_model = models[0] if len(models) == 1 else query.model_name
    canonical_product = products[0] if len(products) == 1 else query.product_name

    normalized = ProductQuery(
        product_name=canonical_product,
        manufacturer=query.manufacturer,
        model_name=canonical_model,
        specification=query.specification,
    )
    return CanonicalQueryIdentity(
        normalized,
        identity,
        normalized != query,
        False,
    )
