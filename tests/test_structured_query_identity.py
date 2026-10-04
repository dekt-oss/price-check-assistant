from __future__ import annotations

from purchase_price.evidence_domain import IdentityEvidenceStatus
from purchase_price.schemas import ProductQuery
from purchase_price.services.mfds_identity_index import MfdsIdentityLookup, MfdsIdentityRecord
from purchase_price.services.structured_query_identity import canonicalize_product_query


def _record(
    *,
    model: str = "Efficia DFM100",
    product: str = "심장 충격기",
    permit: str = "수허 12-3456",
    company: str = "필립스코리아",
) -> MfdsIdentityRecord:
    return MfdsIdentityRecord(
        udi_di=None,
        product_name=product,
        classification_no=None,
        grade=None,
        permit_number=permit,
        permit_date=None,
        model_name=model,
        trade_name=None,
        registered_company=company,
    )


def test_structured_dfm100_is_canonicalized_to_identity_model() -> None:
    query = ProductQuery(
        product_name="심장충격기",
        manufacturer="Philips",
        model_name="DFM100",
        specification="200J",
    )
    identity = MfdsIdentityLookup(
        status="success",
        query="DFM100",
        match_type="model",
        records=(_record(),),
    )

    result = canonicalize_product_query(query, identity)

    assert result.canonicalized is True
    assert result.ambiguous is False
    assert result.query.product_name == "심장 충격기"
    assert result.query.model_name == "Efficia DFM100"
    assert result.query.manufacturer == "Philips"
    assert result.query.specification == "200J"


def test_registered_company_never_replaces_quote_manufacturer() -> None:
    query = ProductQuery(
        product_name="심장충격기",
        manufacturer="Philips",
        model_name="DFM100",
    )
    identity = MfdsIdentityLookup(
        status="success",
        query="DFM100",
        match_type="model",
        records=(_record(company="식약처 책임주체"),),
    )

    result = canonicalize_product_query(query, identity)

    assert result.query.manufacturer == "Philips"
    assert result.query.manufacturer != "식약처 책임주체"


def test_ambiguous_identity_does_not_auto_select_canonical_model() -> None:
    query = ProductQuery(product_name="심장충격기", model_name="DFM100")
    identity = MfdsIdentityLookup(
        status="success",
        query="DFM100",
        match_type="model",
        records=(
            _record(permit="수허 1", company="회사A"),
            _record(permit="수허 2", company="회사B"),
        ),
    )
    assert identity.identity_status == IdentityEvidenceStatus.AMBIGUOUS

    result = canonicalize_product_query(query, identity)

    assert result.ambiguous is True
    assert result.canonicalized is False
    assert result.query == query


def test_zero_or_unavailable_identity_preserves_structured_query() -> None:
    query = ProductQuery(product_name="장비", manufacturer="Maker", model_name="MODEL-X")

    for status in ("success_0", "unavailable", "not_ingested"):
        identity = MfdsIdentityLookup(
            status=status,
            query="MODEL-X",
            match_type=None,
            records=(),
        )
        result = canonicalize_product_query(query, identity)
        assert result.query == query
        assert result.canonicalized is False
        assert result.ambiguous is False
