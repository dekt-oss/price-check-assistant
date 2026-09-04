from datetime import date
from pathlib import Path
from typing import Any

from streamlit.testing.v1 import AppTest

from purchase_price.services.g2b_contract_evidence import (
    G2B_CONTRACT_BASE_URL,
    G2B_CONTRACT_PRODUCT_SEARCH_OPERATION,
    G2BContractEvidence,
    G2BContractEvidenceClient,
    parse_contract_evidence,
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


def test_parse_contract_evidence_does_not_create_price() -> None:
    record = parse_contract_evidence(
        {
            "dcsnCntrctNo": "2026-001",
            "cntrctCnclsMthdNm": "일반경쟁",
            "cntrctInsttNm": "예시병원",
            "prdctClsfcNoNm": "심장충격기",
            "cntrctCnclsDate": "20260901",
            "cntrctDtlInfoUrl": "https://example.invalid/contract/2026-001",
            "totCntrctAmt": "999999999",
        }
    )

    assert record == G2BContractEvidence(
        decision_contract_number="2026-001",
        contract_method_name="일반경쟁",
        contract_institution_name="예시병원",
        product_name="심장충격기",
        contract_date=date(2026, 9, 1),
        detail_url="https://example.invalid/contract/2026-001",
    )
    assert not hasattr(record, "price")


def test_search_product_contracts_uses_product_date_contract() -> None:
    fake = FakeClient(
        _payload(
            {
                "dcsnCntrctNo": "2026-001",
                "cntrctCnclsMthdNm": "수의계약",
                "cntrctInsttNm": "예시기관",
                "prdctClsfcNoNm": "심장충격기",
                "cntrctDtlInfoUrl": "https://example.invalid/contract/2026-001",
            }
        )
    )
    client = G2BContractEvidenceClient("unused-in-fake", client=fake)

    records = client.search_product_contracts(
        product_name=" 심장충격기 ",
        begin_date=date(2026, 8, 1),
        end_date=date(2026, 9, 4),
        contract_method_code="4",
    )

    assert len(records) == 1
    assert fake.calls == [
        (
            G2B_CONTRACT_BASE_URL,
            G2B_CONTRACT_PRODUCT_SEARCH_OPERATION,
            {
                "inqryDiv": "1",
                "inqryBgnDate": "20260801",
                "inqryEndDate": "20260904",
                "pageNo": 1,
                "numOfRows": 100,
                "prdctClsfcNoNm": "심장충격기",
                "cntrctMthdCd": "4",
            },
        )
    ]


def test_contract_method_filter_is_omitted_when_blank() -> None:
    fake = FakeClient(_payload())
    client = G2BContractEvidenceClient("unused-in-fake", client=fake)

    client.search_product_contracts(
        product_name="의료용냉장고",
        begin_date=date(2026, 9, 1),
        end_date=date(2026, 9, 4),
    )

    assert "cntrctMthdCd" not in fake.calls[0][2]


def test_contract_evidence_page_loads() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "pages" / "7_나라장터_계약근거.py")

    app.run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "나라장터 물품 계약근거"
