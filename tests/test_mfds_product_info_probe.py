from __future__ import annotations

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.scripts.probe_mfds_product_info import (
    MFDS_PRODUCT_INFO_BASE_URL,
    MFDS_PRODUCT_INFO_OPERATION,
    _is_source_not_authorized,
    _source_not_authorized_report,
    probe_product_info,
)


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def get_json(self, base_url: str, endpoint: str, **params):
        self.calls.append((base_url, endpoint, params))
        return {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
                "body": {
                    "pageNo": 1,
                    "numOfRows": 20,
                    "totalCount": 1,
                    "items": [
                        {
                            "UDIDI_CD": "08800186600030",
                            "PRDLST_NM": "치과 주조용 귀금속 합금",
                            "MDEQ_CLSF_NO": "C02010.01",
                            "CLSF_NO_GRAD_CD": "2",
                            "PERMIT_NO": "제인 26-4861 호",
                            "PRMSN_YMD": "20260901",
                            "FOML_INFO": "DAVINCI 83",
                            "PRDT_NM_INFO": "DAVINCI 83",
                            "MNFT_IPRT_ENTP_NM": "업체A",
                            "UNRELATED": "drop-me",
                        }
                    ],
                },
            }
        }


def test_probe_product_info_uses_candidate_model_filter_and_safe_fields() -> None:
    fake = FakeClient()

    report = probe_product_info(fake, model_name=" DAVINCI 83 ")

    assert report["exact_model_count"] == 1
    assert report["records"] == [
        {
            "UDIDI_CD": "08800186600030",
            "PRDLST_NM": "치과 주조용 귀금속 합금",
            "MDEQ_CLSF_NO": "C02010.01",
            "CLSF_NO_GRAD_CD": "2",
            "PERMIT_NO": "제인 26-4861 호",
            "PRMSN_YMD": "20260901",
            "FOML_INFO": "DAVINCI 83",
            "PRDT_NM_INFO": "DAVINCI 83",
            "MNFT_IPRT_ENTP_NM": "업체A",
        }
    ]
    assert fake.calls == [
        (
            MFDS_PRODUCT_INFO_BASE_URL,
            MFDS_PRODUCT_INFO_OPERATION,
            {"FOML_INFO": "DAVINCI 83", "pageNo": 1, "numOfRows": 20},
        )
    ]


def test_probe_product_info_exact_match_is_whitespace_case_normalized() -> None:
    fake = FakeClient()

    report = probe_product_info(fake, model_name="davinci83")

    assert report["exact_model_count"] == 1


def test_source_not_authorized_detection_matches_data_portal_code_30() -> None:
    error = PublicDataClientError(
        "Public Data Portal request failed: HTTP 403 "
        "error=SERVICE_KEY_IS_NOT_REGISTERED_ERROR "
        "auth=등록되지 않은 서비스키 code=30"
    )

    assert _is_source_not_authorized(error) is True


def test_source_not_authorized_report_is_explicit_and_fail_closed() -> None:
    report = _source_not_authorized_report(model_name=" DFM100 ")

    assert report["status"] == "SOURCE_NOT_AUTHORIZED"
    assert report["query_model"] == "DFM100"
    assert report["exact_model_count"] is None
    assert report["records"] == []
    assert report["writes_performed"] == 0
