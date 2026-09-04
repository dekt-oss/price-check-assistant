from datetime import date
from decimal import Decimal
from pathlib import Path

from streamlit.testing.v1 import AppTest

from purchase_price.domain import ComparisonScope, EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.services.search import search_all


class SuccessfulCollector:
    name = "successful"

    def search(self, query: ProductQuery) -> list[CollectedPrice]:
        assert query.model_name == "M-1"
        return [
            CollectedPrice(
                manufacturer="예시",
                product_name="의료기기",
                model_name="M-1",
                specification=None,
                price=Decimal("1000000"),
                evidence_type=EvidenceType.PUBLIC_SALE_PRICE,
                source_type=SourceType.MANUFACTURER,
                source_name=self.name,
                source_url="https://example.invalid",
                collected_at=date(2026, 9, 4),
                match_grade=MatchGrade.B,
                comparison_scope=ComparisonScope.OBSERVED_ONLY,
            )
        ]


class ZeroCollector:
    name = "zero"

    def search(self, query: ProductQuery) -> list[CollectedPrice]:
        return []


class FailedCollector:
    name = "failed"

    def search(self, query: ProductQuery) -> list[CollectedPrice]:
        raise RuntimeError("upstream unavailable")


def test_search_all_records_per_source_status_without_losing_other_results() -> None:
    run = search_all(
        ProductQuery(model_name="M-1"),
        [SuccessfulCollector(), ZeroCollector(), FailedCollector()],  # type: ignore[list-item]
    )

    assert len(run.results) == 1
    assert [status.status_label for status in run.source_statuses] == [
        "성공 · 1건",
        "성공 · 0건",
        "실패",
    ]
    assert run.source_statuses[2].error == "upstream unavailable"
    assert run.errors == ["failed: upstream unavailable"]


def test_source_status_page_loads() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "pages" / "8_공개가격_수집상태.py")

    app.run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "공개가격 출처별 수집상태"
