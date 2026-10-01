from __future__ import annotations

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.config import Settings
from purchase_price.services.mfds_identity_live import lookup_mfds_model_identity_live


class FakePortal:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def get_json(self, base_url: str, endpoint: str, **params):
        self.calls.append((base_url, endpoint, params))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _payload(items):
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {
                "pageNo": 1,
                "numOfRows": 100,
                "totalCount": len(items),
                "items": {"item": items},
            },
        }
    }


def test_live_identity_uses_standard_product_api_model_filter() -> None:
    portal = FakePortal(
        [
            _payload(
                [
                    {
                        "UDIDI_CD": "1",
                        "PRDLST_NM": "심장충격기",
                        "PERMIT_NO": "수허 1",
                        "FOML_INFO": "Efficia DFM100",
                        "MNFT_IPRT_ENTP_NM": "Philips",
                    },
                    {
                        "UDIDI_CD": "2",
                        "PRDLST_NM": "심장충격기",
                        "PERMIT_NO": "수허 2",
                        "FOML_INFO": "Efficia DFM100 Plus",
                        "MNFT_IPRT_ENTP_NM": "Philips",
                    },
                ]
            )
        ]
    )

    result = lookup_mfds_model_identity_live(
        "Efficia DFM100",
        settings=Settings(mfds_service_key="key"),
        client=portal,
    )

    assert result.status == "success"
    assert result.match_type == "model"
    assert result.permit_numbers == ("수허 1",)
    assert result.product_names == ("심장충격기",)
    assert portal.calls[0][2]["FOML_INFO"] == "Efficia DFM100"


def test_live_identity_keeps_api_failure_unavailable_not_zero() -> None:
    portal = FakePortal([PublicDataClientError("synthetic failure")])

    result = lookup_mfds_model_identity_live(
        "Efficia DFM100",
        settings=Settings(mfds_service_key="key"),
        client=portal,
    )

    assert result.status == "unavailable"
    assert result.records == ()


def test_live_identity_without_service_key_is_unavailable() -> None:
    result = lookup_mfds_model_identity_live(
        "Efficia DFM100",
        settings=Settings(
            mfds_service_key=None,
            data_go_kr_market_service_key=None,
            data_go_kr_service_key=None,
        ),
    )

    assert result.status == "unavailable"
