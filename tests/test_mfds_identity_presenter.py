from types import SimpleNamespace

from purchase_price.evidence_domain import (
    IdentityEvidenceStatus,
    MfdsItemAuthorizationType,
)
from purchase_price.services.mfds_identity_presenter import (
    MFDS_PRODUCT_INFO_DATASET_URL,
    mfds_identity_status,
    mfds_item_authorization_type,
)


def _legacy_record(
    *,
    permit_number: str,
    model_name: str = "C101",
    registered_company: str = "책임주체A",
    product_name: str = "채혈기",
):
    return SimpleNamespace(
        permit_number=permit_number,
        model_name=model_name,
        registered_company=registered_company,
        product_name=product_name,
    )


def test_presenter_classifies_legacy_record_without_new_property() -> None:
    record = _legacy_record(permit_number="수신 22-2177호")

    assert not hasattr(record, "item_authorization_type")
    assert mfds_item_authorization_type(record) == MfdsItemAuthorizationType.NOTIFICATION
    assert MFDS_PRODUCT_INFO_DATASET_URL.endswith("15073875/openapi.do")


def test_presenter_computes_ambiguity_without_new_lookup_property() -> None:
    lookup = SimpleNamespace(
        status="success",
        match_type="model",
        records=(
            _legacy_record(permit_number="수신 22-2177호", registered_company="책임주체A"),
            _legacy_record(permit_number="수신 24-9999호", registered_company="책임주체B"),
        ),
    )

    assert not hasattr(lookup, "identity_status")
    assert mfds_identity_status(lookup) == IdentityEvidenceStatus.AMBIGUOUS


def test_presenter_preserves_coverage_miss_and_unavailable() -> None:
    missing = SimpleNamespace(status="success_0", match_type=None, records=())
    unavailable = SimpleNamespace(status="unavailable", match_type=None, records=())

    assert mfds_identity_status(missing) == IdentityEvidenceStatus.NOT_FOUND_IN_COVERAGE
    assert mfds_identity_status(unavailable) == IdentityEvidenceStatus.UNAVAILABLE
