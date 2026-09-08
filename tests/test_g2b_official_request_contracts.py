from __future__ import annotations

from datetime import date
from decimal import Decimal

from purchase_price.services.g2b_contract_research import G2BContractResearchClient
from purchase_price.services.g2b_market_models import ResearchAmountType
from purchase_price.services.g2b_market_sources import G2BPrespecResearchClient


class RecordingPortal:
    def __init__(self, items: list[dict] | None = None) -> None:
        self.items = list(items or [])
        self.calls: list[tuple[str, str, dict]] = []

    def get_json(self, base_url: str, endpoint: str, **params):
        self.calls.append((base_url, endpoint, params))
        return {
            "response": {
                "header": {"resultCode": "00", "resultMsg": "OK"},
                "body": {
                    "items": self.items,
                    "totalCount": len(self.items),
                    "pageNo": 1,
                    "numOfRows": 100,
                },
            }
        }


def test_prespec_search_uses_official_product_name_field() -> None:
    portal = RecordingPortal()
    client = G2BPrespecResearchClient("key", client=portal)  # type: ignore[arg-type]

    client.fetch_page(
        keyword="이산화탄소배양기",
        begin=date(2026, 8, 1),
        end=date(2026, 8, 30),
    )

    params = portal.calls[0][2]
    assert params["prdctClsfcNoNm"] == "이산화탄소배양기"
    assert "bfSpecNm" not in params


def test_contract_search_uses_official_notice_field_and_preserves_link() -> None:
    portal = RecordingPortal(
        [
            {
                "dcsnCntrctNo": "C-2026-001",
                "ntceNo": "R26BK01516675",
                "cntrctNm": "이산화탄소배양기 구매",
                "totCntrctAmt": "50000000",
            }
        ]
    )
    client = G2BContractResearchClient("key", client=portal)  # type: ignore[arg-type]

    records, request_count = client.search_by_bid_notice(
        bid_notice_no="R26BK01516675",
        max_pages=1,
    )

    params = portal.calls[0][2]
    assert params["ntceNo"] == "R26BK01516675"
    assert "bidNtceNo" not in params
    assert request_count == 1
    assert len(records) == 1
    assert records[0].bid_notice_no == "R26BK01516675"
    assert "R26BK01516675" in records[0].source_record_id
    assert records[0].amount == Decimal("50000000")
    assert records[0].amount_type == ResearchAmountType.CONTRACT_TOTAL
    assert not records[0].is_direct_unit_price


def test_contract_parser_keeps_legacy_notice_alias_for_old_evidence_fixtures() -> None:
    portal = RecordingPortal(
        [
            {
                "dcsnCntrctNo": "C-LEGACY",
                "bidNtceNo": "R25BK00000001",
                "totCntrctAmt": "1000000",
            }
        ]
    )
    client = G2BContractResearchClient("key", client=portal)  # type: ignore[arg-type]

    records, _ = client.search_by_bid_notice(
        bid_notice_no="R25BK00000001",
        max_pages=1,
    )

    assert records[0].bid_notice_no == "R25BK00000001"
    assert records[0].amount_type == ResearchAmountType.CONTRACT_TOTAL
    assert not records[0].is_direct_unit_price
