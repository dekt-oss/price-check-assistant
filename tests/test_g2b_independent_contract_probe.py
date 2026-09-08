from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from purchase_price.scripts import probe_g2b_independent_contract as probe
from purchase_price.services.g2b_market_models import (
    G2BResearchRecord,
    G2BResearchSource,
    ResearchAmountType,
)


class FakeContractClient:
    def __init__(self, service_key: str, *args, **kwargs) -> None:
        del args, kwargs
        assert service_key == "contract-key"

    def search_by_product_name(self, **kwargs):
        assert kwargs["product_name"] == "레이저프린터"
        assert kwargs["begin_date"] == date(2025, 9, 9)
        assert kwargs["end_date"] == date(2026, 9, 8)
        assert kwargs["max_pages_per_window"] == 1
        return (
            (
                G2BResearchRecord(
                    source_type=G2BResearchSource.CONTRACT,
                    source_record_id="contract:C-1:R26BK1:1",
                    contract_no="C-1",
                    bid_notice_no="R26BK1",
                    title="레이저프린터 구매 계약",
                    product_name="레이저프린터",
                    amount=Decimal("5000000"),
                    amount_type=ResearchAmountType.CONTRACT_TOTAL,
                    search_term="레이저프린터",
                ),
            ),
            1,
        )


def _settings(key: str | None = "contract-key") -> SimpleNamespace:
    return SimpleNamespace(
        resolved_g2b_contract_service_key=key,
        g2b_contract_key_source=("G2B_CONTRACT_SERVICE_KEY" if key else "미설정"),
        g2b_contract_base_url=None,
    )


def test_probe_reports_contract_total_as_research_only(monkeypatch) -> None:
    monkeypatch.setattr(probe, "get_settings", lambda: _settings())
    monkeypatch.setattr(probe, "G2BContractResearchClient", FakeContractClient)

    report = probe.build_report(
        product_name="레이저프린터",
        lookback_days=365,
        timeout_seconds=15,
        max_retries=1,
        today=date(2026, 9, 8),
    )

    assert report["validation_status"] == "pass"
    assert report["source_status"] == "success"
    assert report["key_source"] == "G2B_CONTRACT_SERVICE_KEY"
    assert report["coverage_start"] == "2025-09-09"
    assert report["coverage_end"] == "2026-09-08"
    assert report["record_count"] == 1
    assert report["sample_records"][0]["amount_type"] == "contract_total"
    assert report["safety_contract"]["direct_price_promotion_performed"] is False
    assert report["safety_contract"]["contract_total_is_unit_price"] is False


def test_probe_missing_key_is_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(probe, "get_settings", lambda: _settings(None))

    report = probe.build_report(
        product_name="레이저프린터",
        lookback_days=365,
        timeout_seconds=15,
        max_retries=1,
        today=date(2026, 9, 8),
    )

    assert report["validation_status"] == "not_configured"
    assert report["key_source"] == "미설정"
