from __future__ import annotations

from types import SimpleNamespace

from purchase_price.scripts import probe_g2b_contract_notice as probe
from purchase_price.services.g2b_market_models import G2BResearchRecord, G2BResearchSource


class FakeContractClient:
    def __init__(self, service_key: str, **kwargs) -> None:
        del kwargs
        assert service_key == "contract-key"

    def search_by_bid_notice(self, *, bid_notice_no: str, max_pages: int = 1):
        assert bid_notice_no == "20160234982"
        assert max_pages == 1
        return (
            (
                G2BResearchRecord(
                    source_type=G2BResearchSource.CONTRACT,
                    source_record_id="contract:C-1:20160234982:1",
                    contract_no="C-1",
                    bid_notice_no="20160234982",
                ),
            ),
            1,
        )


def _settings(key: str | None = "contract-key") -> SimpleNamespace:
    return SimpleNamespace(
        resolved_g2b_contract_service_key=key,
        g2b_contract_key_source=("G2B_CONTRACT_SERVICE_KEY" if key else "미설정"),
    )


def test_known_positive_probe_uses_contract_specific_key(monkeypatch) -> None:
    monkeypatch.setattr(probe, "get_settings", lambda: _settings())
    monkeypatch.setattr(probe, "G2BContractResearchClient", FakeContractClient)

    report = probe.build_report(
        bid_notice_no="20160234982",
        timeout_seconds=15,
        max_retries=1,
    )

    assert report["validation_status"] == "pass"
    assert report["key_source"] == "G2B_CONTRACT_SERVICE_KEY"
    assert report["matching_notice_count"] == 1
    assert report["safety_contract"]["contract_totals_are_research_only"] is True
    assert report["safety_contract"]["direct_unit_price_promotion_performed"] is False


def test_known_positive_probe_reports_missing_contract_key(monkeypatch) -> None:
    monkeypatch.setattr(probe, "get_settings", lambda: _settings(None))

    report = probe.build_report(
        bid_notice_no="20160234982",
        timeout_seconds=15,
        max_retries=1,
    )

    assert report["validation_status"] == "not_configured"
    assert report["key_source"] == "미설정"
