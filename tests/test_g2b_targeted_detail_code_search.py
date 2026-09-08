from datetime import date

import pytest

from purchase_price.collectors.g2b_shopping import G2BShoppingCollector


class RecordingPortal:
    def __init__(self) -> None:
        self.call = None

    def get_json(self, base_url, endpoint, **params):
        self.call = (base_url, endpoint, params)
        return {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "OK"},
                "body": {
                    "items": [],
                    "totalCount": 0,
                    "pageNo": 1,
                    "numOfRows": 100,
                },
            }
        }


def test_detail_product_code_uses_server_side_code_filter() -> None:
    portal = RecordingPortal()
    collector = G2BShoppingCollector("unused", client=portal)  # type: ignore[arg-type]

    collector.fetch_specific_item_page(
        detail_product_code="4110449801",
        begin_date=date(2025, 9, 8),
        end_date=date(2026, 9, 7),
    )

    assert portal.call is not None
    _, endpoint, params = portal.call
    assert endpoint == "getSpcifyPrdlstPrcureInfoList"
    assert params["inqryPrdctDiv"] == "2"
    assert params["dtilPrdctClsfcNo"] == "4110449801"
    assert "dtilPrdctClsfcNoNm" not in params


def test_name_search_contract_remains_backward_compatible() -> None:
    portal = RecordingPortal()
    collector = G2BShoppingCollector("unused", client=portal)  # type: ignore[arg-type]

    collector.fetch_specific_item_page(
        detail_product_name="제습기",
        begin_date=date(2026, 7, 14),
        end_date=date(2026, 8, 13),
    )

    assert portal.call is not None
    params = portal.call[2]
    assert params["dtilPrdctClsfcNoNm"] == "제습기"
    assert "dtilPrdctClsfcNo" not in params


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"detail_product_name": "배양기", "detail_product_code": "4110449801"},
        {"detail_product_code": "ABC"},
        {"detail_product_code": "411044980"},
    ],
)
def test_targeted_selector_fails_closed_on_ambiguous_or_invalid_input(kwargs) -> None:
    collector = G2BShoppingCollector("unused", client=RecordingPortal())  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        collector.fetch_specific_item_page(
            begin_date=date(2026, 8, 1),
            end_date=date(2026, 8, 30),
            **kwargs,
        )
