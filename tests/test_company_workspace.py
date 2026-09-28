from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from purchase_price.domain import MatchGrade
from purchase_price.evidence_domain import PriceEvidenceStatus
from purchase_price.services.company_workspace import build_company_procurement_rows
from purchase_price.services.mfds_identity_index import parse_mfds_product_info_record


def _record(model: str, permit: str):
    return parse_mfds_product_info_record(
        {
            "UDIDI_CD": f"UDI-{model}",
            "PRDLST_NM": "채혈기",
            "MDEQ_CLSF_NO": "A66020.01",
            "CLSF_NO_GRAD_CD": "1",
            "PERMIT_NO": permit,
            "PRMSN_YMD": "20220101",
            "FOML_INFO": model,
            "PRDT_NM_INFO": model,
            "MNFT_IPRT_ENTP_NM": "책임주체A",
        }
    )


def _comparison(*, supplier: str | None, price: str | None, status=PriceEvidenceStatus.FOUND):
    candidates = ()
    if supplier and price:
        candidates = (
            SimpleNamespace(
                match_grade=MatchGrade.A,
                price=Decimal(price),
                supplier=supplier,
                transaction_date="2026-09-01",
            ),
        )
    return SimpleNamespace(
        candidates=candidates,
        evidence_status=status,
        status=status.value,
        data_as_of="2026-09-28T06:30:00Z",
    )


class Snapshot:
    def __init__(self, comparisons):
        self.comparisons = tuple(comparisons)
        self.queries = ()

    def lookup_model_summaries(self, queries):
        self.queries = tuple(queries)
        return self.comparisons


def test_company_workspace_batches_models_and_keeps_supplier_role_separate() -> None:
    snapshot = Snapshot(
        [
            _comparison(supplier="조달업체A", price="450"),
            _comparison(supplier="조달업체B", price="510"),
        ]
    )

    rows = build_company_procurement_rows(
        [_record("C101", "수신 22-2177호"), _record("C102", "수신 22-2177호")],
        track_b_snapshot=snapshot,
    )

    assert [query.model_name for query in snapshot.queries] == ["C101", "C102"]
    assert len(rows) == 2
    assert rows[0]["품목 책임주체"] == "책임주체A"
    assert rows[0]["실제 조달 납품업체"] == "조달업체A"
    assert rows[0]["A/B 직접거래"] == 1
    assert rows[0]["가격범위"] == "450 ~ 450원"
    assert rows[0]["data_as_of"] == "2026-09-28T06:30:00Z"


def test_company_workspace_fails_closed_when_procurement_index_is_unavailable() -> None:
    snapshot = Snapshot(
        [
            _comparison(
                supplier=None,
                price=None,
                status=PriceEvidenceStatus.UNAVAILABLE,
            )
        ]
    )

    rows = build_company_procurement_rows(
        [_record("C101", "수신 22-2177호")],
        track_b_snapshot=snapshot,
    )

    assert rows[0]["조달 상태"] == "UNAVAILABLE"
    assert rows[0]["A/B 직접거래"] is None
    assert rows[0]["가격범위"] == "조회 불가"
    assert rows[0]["실제 조달 납품업체"] == "미확인"


def test_company_workspace_deduplicates_same_identity_before_batch_lookup() -> None:
    record = _record("C101", "수신 22-2177호")
    snapshot = Snapshot([_comparison(supplier="조달업체A", price="450")])

    rows = build_company_procurement_rows(
        [record, record],
        track_b_snapshot=snapshot,
    )

    assert len(snapshot.queries) == 1
    assert len(rows) == 1
