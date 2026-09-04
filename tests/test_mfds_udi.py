from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from purchase_price.services.mfds_udi import (
    MFDS_UDI_CODE_BASE_URL,
    MFDS_UDI_CODE_OPERATION,
    MedicalDeviceUdiCodeRecord,
    MfdsUdiCodeClient,
    parse_udi_code_record,
)


class FakeClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def get_json(self, base_url: str, endpoint: str, **params: Any) -> dict[str, Any]:
        self.calls.append((base_url, endpoint, params))
        return self.payload


def _payload(*items: dict[str, Any]) -> dict[str, Any]:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {
                "items": list(items),
                "totalCount": len(items),
                "pageNo": 1,
                "numOfRows": 100,
            },
        }
    }


def test_parse_udi_code_record_uses_official_fields() -> None:
    record = parse_udi_code_record(
        {
            "UDIDI_CD": "08801234567890",
            "CD_STRCT_DIVS_CD": "GS1",
            "CODE_SYSTEM_NAME": "GS1",
            "BSSH_NM": "예시메디칼",
            "INDT_DIVS_NM": "수입업",
        }
    )

    assert record == MedicalDeviceUdiCodeRecord(
        udi_di="08801234567890",
        code_structure_code="GS1",
        code_system_name="GS1",
        company_name="예시메디칼",
        company_type="수입업",
    )


def test_lookup_udi_uses_documented_udidi_cd_filter_and_exact_result() -> None:
    fake = FakeClient(
        _payload(
            {
                "UDIDI_CD": "08801234567890",
                "CD_STRCT_DIVS_CD": "GS1",
                "CODE_SYSTEM_NAME": "GS1",
                "BSSH_NM": "예시메디칼",
                "INDT_DIVS_NM": "수입업",
            },
            {
                "UDIDI_CD": "DIFFERENT",
                "BSSH_NM": "다른업체",
            },
        )
    )
    client = MfdsUdiCodeClient("unused-in-fake", client=fake)

    records = client.lookup_udi(" 08801234567890 ")

    assert [item.udi_di for item in records] == ["08801234567890"]
    assert fake.calls == [
        (
            MFDS_UDI_CODE_BASE_URL,
            MFDS_UDI_CODE_OPERATION,
            {"UDIDI_CD": "08801234567890", "pageNo": 1, "numOfRows": 100},
        )
    ]


def test_lookup_udi_rejects_empty_identifier() -> None:
    client = MfdsUdiCodeClient("unused-in-fake", client=FakeClient(_payload()))

    with pytest.raises(ValueError, match="udi_di is required"):
        client.lookup_udi("  ")


def test_udi_page_loads_without_live_request() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "pages" / "6_의료기기_UDI.py")

    app.run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "의료기기 UDI-DI 공식조회"
    assert any("UDIDI_CD" in item.value for item in app.caption)
