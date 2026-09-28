from purchase_price.services.company_identity import (
    CompanyIdentityStatus,
    compare_company_identity,
)


def test_official_business_identifier_is_required_for_confirmed_same_company() -> None:
    confirmed = compare_company_identity(
        left_name="주식회사 워터맨하우스",
        right_name="(주)워터맨하우스",
        left_business_id="123-45-67890",
        right_business_id="1234567890",
    )
    similar = compare_company_identity(
        left_name="주식회사 워터맨하우스",
        right_name="(주)워터맨하우스",
    )

    assert confirmed.status == CompanyIdentityStatus.CONFIRMED_SAME
    assert confirmed.confirmed_same is True
    assert similar.status == CompanyIdentityStatus.NAME_SIMILAR_UNCONFIRMED
    assert similar.confirmed_same is False


def test_conflicting_official_identifiers_fail_closed_even_when_names_match() -> None:
    result = compare_company_identity(
        left_name="주식회사 워터맨하우스",
        right_name="(주)워터맨하우스",
        left_business_id="1234567890",
        right_business_id="9999999999",
    )

    assert result.status == CompanyIdentityStatus.DIFFERENT
    assert result.confirmed_same is False
