from __future__ import annotations

from datetime import date
from pathlib import Path

from streamlit.testing.v1 import AppTest

from purchase_price.services.g2b_contract_evidence import (
    G2B_CONTRACT_BASE_URL,
    G2B_CONTRACT_OPERATION,
    G2BContractEvidenceClient,
    parse_contract_evidence,
)


class _FakeClient:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = payloads
        self.calls: list[tuple[str, str, dict]] = []

    def get_json(self, base_url: str, endpoint: str, **params):
        self.calls.append((base_url, endpoint, params))
        return self.payloads[len(self.calls) - 1]


def _payload(*, page_no: int = 1, total_count: int = 1, items: list[dict] | None = None) -> dict:
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
            "body": {
                "items": items or [],
                "numOfRows": 100,
                "pageNo": page_no,
                "totalCount": total_count,
            },
        }
    }


def test_parse_contract_evidence_keeps_contract_total_out_of_unit_price() -> None:
    item = parse_contract_evidence(
        {
            "dcsnCntrctNo": "2026-001",
            "prdctClsfcNoNm": "심장충격기",
            "cntrctCnclsDate": "20260901",
            "cntrctMthdNm": "일반경쟁",
            "cntrctInsttNm": "테스트기관",
            "cntrctAmt": "12345678",
            "cntrctDtlInfoUrl": "https://example.com/contract",
        },
        source_base_url=G2B_CONTRACT_BASE_URL,
    )

    assert item.decision_contract_number == "2026-001"
    assert item.product_name == "심장충격기"
    assert item.contract_date == date(2026, 9, 1)
    assert item.contract_method_name == "일반경쟁"
    assert item.contract_institution_name == "테스트기관"
    assert item.contract_amount is None
    assert item.detail_url == "https://example.com/contract"
    assert item.provenance is not None


def test_contract_client_uses_official_operation_and_filters() -> None:
    fake = _FakeClient([_payload()])
    client = G2BContractEvidenceClient("unused-in-fake", client=fake)

    client.search_product_contracts(
        product_name="심장충격기",
        begin_date=date(2026, 9, 1),
        end_date=date(2026, 9, 4),
        contract_method_code="01",
    )

    assert len(fake.calls) == 1
    base_url, endpoint, params = fake.calls[0]
    assert base_url == G2B_CONTRACT_BASE_URL
    assert endpoint == G2B_CONTRACT_OPERATION
    assert params["prdctClsfcNoNm"] == "심장충격기"
    assert params["inqryBgnDate"] == "20260901"
    assert params["inqryEndDate"] == "20260904"
    assert params["cntrctMthdCd"] == "01"


def test_contract_client_paginates_all_results() -> None:
    fake = _FakeClient(
        [
            _payload(
                page_no=1,
                total_count=2,
                items=[{"dcsnCntrctNo": "2026-001", "prdctClsfcNoNm": "심장충격기"}],
            ),
            _payload(
                page_no=2,
                total_count=2,
                items=[{"dcsnCntrctNo": "2026-002", "prdctClsfcNoNm": "심장충격기"}],
            ),
        ]
    )
    client = G2BContractEvidenceClient("unused-in-fake", client=fake)

    records = client.search_product_contracts(
        product_name="심장충격기",
        begin_date=date(2026, 9, 1),
        end_date=date(2026, 9, 4),
        num_of_rows=1,
    )

    assert [item.decision_contract_number for item in records] == ["2026-001", "2026-002"]
    assert [call[2]["pageNo"] for call in fake.calls] == [1, 2]


def test_contract_evidence_is_absorbed_into_quick_search_page() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "pages" / "3_빠른_검색.py")

    app.run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "빠른 검색"
