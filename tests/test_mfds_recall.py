from __future__ import annotations

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.config import Settings
from purchase_price.services import mfds_recall as module
from purchase_price.services.mfds_recall import (
    MFDS_RECALL_BASE_URL,
    MFDS_RECALL_MODEL_OPERATION,
    MFDS_RECALL_PRODUCT_OPERATION,
    MfdsRecallClient,
    lookup_mfds_recall,
    parse_model_recall_record,
)


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


def test_parse_model_recall_record_uses_service04_fields() -> None:
    record = parse_model_recall_record(
        {
            "RECALL_ITEM_SEQ": "R-1",
            "TYPE_NAME": "DFM100",
            "MEA_CLASS_NO": "A12345.01",
            "MEA_CLASS_NAME": "심장충격기",
            "GRADE": "3",
            "MANUF_NAME": "Example Medical",
            "REPORT_STATE_CODE": "20",
            "REPORT_STATE_NAME": "회수중",
            "REPORT_SUBMIT_DATE": "20260920",
            "REPORT_KIND_CODE": "01",
            "REPORT_KIND_NAME": "회수",
            "RTRVL_RESN_CN": "품질 이상",
            "PACK_UNIT": "1 EA",
            "VALID_TERM": "36개월",
        }
    )

    assert record.recall_item_seq == "R-1"
    assert record.model_name == "DFM100"
    assert record.classification_no == "A12345.01"
    assert record.manufacturer_name == "Example Medical"
    assert record.report_state_name == "회수중"
    assert record.report_kind_name == "회수"
    assert record.reason == "품질 이상"


def test_model_lookup_uses_current_service04_contract_and_exact_filter() -> None:
    portal = FakePortal(
        [
            _payload(
                [
                    {"RECALL_ITEM_SEQ": "1", "TYPE_NAME": "DFM100"},
                    {"RECALL_ITEM_SEQ": "2", "TYPE_NAME": "DFM100 Plus"},
                ]
            )
        ]
    )
    client = MfdsRecallClient("test-key", client=portal)

    records = client.search_model("DFM100")

    assert [item.recall_item_seq for item in records] == ["1"]
    assert portal.calls == [
        (
            MFDS_RECALL_BASE_URL,
            MFDS_RECALL_MODEL_OPERATION,
            {"type_name": "DFM100", "pageNo": 1, "numOfRows": 100},
        )
    ]


def test_product_lookup_uses_current_service04_contract_and_exact_filter() -> None:
    portal = FakePortal(
        [
            _payload(
                [
                    {"RECALL_ITEM_SEQ": "1", "ITEM_NAME": "심장충격기"},
                    {"RECALL_ITEM_SEQ": "2", "ITEM_NAME": "심장충격기용전극"},
                ]
            )
        ]
    )
    client = MfdsRecallClient("test-key", client=portal)

    records = client.search_product("심장충격기")

    assert [item.recall_item_seq for item in records] == ["1"]
    assert portal.calls == [
        (
            MFDS_RECALL_BASE_URL,
            MFDS_RECALL_PRODUCT_OPERATION,
            {"item_name": "심장충격기", "pageNo": 1, "numOfRows": 100},
        )
    ]


def test_lookup_without_service_key_is_not_configured() -> None:
    result = lookup_mfds_recall(
        model_name="DFM100",
        settings=Settings(
            mfds_recall_service_key=None,
            mfds_service_key=None,
            data_go_kr_market_service_key=None,
            data_go_kr_service_key=None,
        ),
    )

    assert result.status == "not_configured"
    assert result.checked_at is None


def test_service_key_not_registered_is_not_authorized_not_zero() -> None:
    class UnauthorizedClient:
        def search_model(self, model_name: str):
            raise PublicDataClientError(
                "Public Data Portal request failed: HTTP 403 "
                "error=SERVICE_KEY_IS_NOT_REGISTERED_ERROR code=30"
            )

    result = lookup_mfds_recall(
        model_name="DFM100",
        client=UnauthorizedClient(),  # type: ignore[arg-type]
    )

    assert result.status == "not_authorized"
    assert result.records == ()
    assert result.checked_at
    assert "code=30" in (result.error_message or "")


def test_generic_api_failure_is_failure_not_zero() -> None:
    class BrokenClient:
        def search_model(self, model_name: str):
            raise PublicDataClientError("synthetic failure")

    result = lookup_mfds_recall(
        model_name="DFM100",
        client=BrokenClient(),  # type: ignore[arg-type]
    )

    assert result.status == "failure"
    assert result.records == ()
    assert result.checked_at


def test_successful_empty_query_is_success_zero() -> None:
    class EmptyClient:
        def search_model(self, model_name: str):
            return ()

    result = lookup_mfds_recall(
        model_name="DFM100",
        client=EmptyClient(),  # type: ignore[arg-type]
    )

    assert result.status == "success_0"
    assert result.checked_at


def test_lookup_accepts_legacy_settings_without_new_recall_fields(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class LegacySettings:
        def __init__(self) -> None:
            self.mfds_service_key = "legacy-mfds-key"
            self.data_go_kr_market_service_key = None
            self.data_go_kr_service_key = None
            self.mfds_request_timeout_seconds = 7.0
            self.mfds_max_retries = 1

    class FakeRecallClient:
        def __init__(
            self,
            service_key: str,
            *,
            base_url: str,
            timeout_seconds: float,
            max_retries: int,
        ) -> None:
            captured.update(
                service_key=service_key,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )

        def search_model(self, model_name: str):
            return ()

    monkeypatch.setattr(module, "MfdsRecallClient", FakeRecallClient)

    result = module.lookup_mfds_recall(
        model_name="DFM100",
        settings=LegacySettings(),  # type: ignore[arg-type]
    )

    assert result.status == "success_0"
    assert captured["service_key"] == "legacy-mfds-key"
    assert captured["base_url"] == MFDS_RECALL_BASE_URL
    assert captured["timeout_seconds"] == 7.0
    assert captured["max_retries"] == 1
