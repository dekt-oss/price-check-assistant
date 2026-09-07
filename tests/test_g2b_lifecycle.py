from purchase_price.services.g2b_lifecycle import (
    G2B_LIFECYCLE_BASE_URL,
    G2B_LIFECYCLE_GOODS_OPERATION,
    G2BLifecycleClient,
    G2BLifecycleInquiry,
)


class StubClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str, dict]] = []

    def get_json(self, base_url: str, endpoint: str, **params):
        self.calls.append((base_url, endpoint, params))
        return self.payload


def _payload() -> dict:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {
                "items": {
                    "item": {
                        "orderPlanNo": "1-1-2026-X",
                        "orderPlanUntyNo": "1-1-2026-X-U",
                        "orderBizNm": "장비 구매",
                        "orderInsttNm": "테스트기관",
                        "prcrmntMethdNm": "중앙조달",
                        "cntrctCnclsMthdNm": "일반경쟁",
                        "bfSpecRgstNo": "123456",
                        "bfSpecBizNm": "장비 사전규격",
                        "bidNtceNo": "20260907001",
                        "bidNtceOrd": "00",
                        "prcrmntReqNo": "REQ-1",
                        "bidNtceNm": "장비 구매 입찰",
                        "bidDminsttNm": "테스트기관",
                        "bidMthdNm": "전자입찰",
                        "bidNtceDt": "2026-09-07 10:00:00",
                        "bidwinrInfoList": "[낙찰정보 raw]",
                        "cntrctInfoList": "[계약정보 raw]",
                    }
                }
            },
        }
    }


def test_lifecycle_bid_notice_uses_official_inquiry_div_and_parameter() -> None:
    stub = StubClient(_payload())
    client = G2BLifecycleClient("unused", client=stub)

    result = client.fetch(
        inquiry=G2BLifecycleInquiry.BID_NOTICE,
        identifier="20260907001",
        bid_notice_order="00",
    )

    assert stub.calls == [
        (
            G2B_LIFECYCLE_BASE_URL,
            G2B_LIFECYCLE_GOODS_OPERATION,
            {
                "pageNo": 1,
                "numOfRows": 20,
                "inqryDiv": "1",
                "bidNtceNo": "20260907001",
                "bidNtceOrd": "00",
            },
        )
    ]
    assert len(result.records) == 1
    record = result.records[0]
    assert record.prespec_no == "123456"
    assert record.bid_notice_no == "20260907001"
    assert record.procurement_request_no == "REQ-1"
    # Award/contract list amounts are intentionally retained as opaque research context.
    assert record.award_info_list == "[낙찰정보 raw]"
    assert record.contract_info_list == "[계약정보 raw]"


def test_lifecycle_all_official_inquiry_div_mappings_are_explicit() -> None:
    assert G2BLifecycleInquiry.BID_NOTICE.parameter_name == "bidNtceNo"
    assert G2BLifecycleInquiry.PRESPEC.parameter_name == "bfSpecRgstNo"
    assert G2BLifecycleInquiry.ORDER_PLAN.parameter_name == "orderPlanNo"
    assert G2BLifecycleInquiry.PROCUREMENT_REQUEST.parameter_name == "prcrmntReqNo"
    assert [item.value for item in G2BLifecycleInquiry] == ["1", "2", "3", "4"]
