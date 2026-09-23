from __future__ import annotations

from types import SimpleNamespace

from purchase_price.domain import MatchGrade
from purchase_price.schemas import ProductQuery
from purchase_price.services.mfds_device_intelligence import (
    parse_business_record,
    parse_model_record,
)
from purchase_price.services.mfds_workspace import (
    research_mfds_for_workspace,
    should_query_mfds,
)


def _track_b(*, detail_code: str = "4217210101"):
    candidate = SimpleNamespace(
        detail_code=detail_code,
        match_grade=MatchGrade.A,
    )
    return SimpleNamespace(candidates=(candidate,), reference_candidates=())


def test_medical_g2b_class_enables_mfds_lookup() -> None:
    assert should_query_mfds(
        ProductQuery(product_name="심장충격기", model_name="MODEL-1"),
        _track_b(),
    ) is True


def test_non_medical_g2b_class_does_not_call_mfds() -> None:
    assert should_query_mfds(
        ProductQuery(product_name="레이저프린터", model_name="MODEL-1"),
        _track_b(detail_code="4321210501"),
    ) is False


def test_workspace_resolves_exact_model_and_active_competitors() -> None:
    records = (
        parse_model_record(
            {
                "PRDLST_NM": "심장충격기",
                "TYPE_INFO": "MODEL-1",
                "MEDDEV_ITEM_NO": "수허 1",
                "INDT_NM": "수입업",
                "EXPORT_YN": "아니오",
            }
        ),
        parse_model_record(
            {
                "PRDLST_NM": "심장충격기",
                "TYPE_INFO": "MODEL-2",
                "MEDDEV_ITEM_NO": "수허 2",
                "INDT_NM": "제조업",
                "EXPORT_YN": "아니오",
            }
        ),
        parse_model_record(
            {
                "PRDLST_NM": "심장충격기",
                "TYPE_INFO": "MODEL-X",
                "MEDDEV_ITEM_NO": "수허 3",
                "INDT_NM": "수입업",
                "RTRCN_DSCTN_DIVS_CD": "취하",
                "EXPORT_YN": "아니오",
            }
        ),
    )

    class ModelClient:
        def search_models(self, product_name: str, *, max_pages: int):
            assert product_name == "심장충격기"
            assert max_pages == 5
            return records

    result = research_mfds_for_workspace(
        ProductQuery(product_name="심장충격기", model_name="MODEL 1"),
        _track_b(),
        model_client=ModelClient(),
    )

    assert result.status == "success"
    assert result.exact_confirmed is True
    assert result.exact_ambiguous is False
    assert result.permit_numbers == ("수허 1",)
    assert len(result.active_records) == 2
    assert [item.model_name for item in result.active_competitor_records] == ["MODEL-2"]
    assert result.industry_types == ("수입업", "제조업")
    assert result.registered_company_status == "company_source_not_connected"


def test_workspace_business_lookup_is_only_a_company_hint_cross_check() -> None:
    model = parse_model_record(
        {
            "PRDLST_NM": "심장충격기",
            "TYPE_INFO": "MODEL-1",
            "MEDDEV_ITEM_NO": "수허 1",
            "EXPORT_YN": "아니오",
        }
    )
    business = parse_business_record(
        {
            "ENTRPS": "예시메디칼",
            "INDUTY_TYPE": "판매업",
            "BIZ_STTUS": "영업",
            "MEDDEV_ENTP_NO": "123",
        }
    )

    class ModelClient:
        def search_models(self, product_name: str, *, max_pages: int):
            return (model,)

    class BusinessClient:
        def search_company(self, company_name: str):
            assert company_name == "예시메디칼"
            return (business,)

    result = research_mfds_for_workspace(
        ProductQuery(
            product_name="심장충격기",
            manufacturer="예시메디칼",
            model_name="MODEL-1",
        ),
        _track_b(),
        model_client=ModelClient(),
        business_client=BusinessClient(),
    )

    assert result.business_query == "예시메디칼"
    assert result.business_records == (business,)
    assert result.registered_company_status == "company_source_not_connected"
