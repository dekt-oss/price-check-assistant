from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_market_research_wires_independent_contract_terms_and_requested_lookback() -> None:
    text = (REPO_ROOT / "src" / "purchase_price" / "ui" / "market_research.py").read_text(
        encoding="utf-8"
    )

    assert "enrich_market_bundle_with_contracts(" in text
    assert "research_terms = research_terms_with_basis(query) + resolver_terms" in text
    assert "independent_terms=research_terms" in text
    assert "requested_lookback_days=lookback_days" in text
    assert "max_independent_terms=1" in text
    assert "max_pages_per_window=1" in text


def test_procurement_ui_exposes_actual_contract_coverage_and_not_run_state() -> None:
    text = (
        REPO_ROOT / "src" / "purchase_price" / "ui" / "g2b_market_research.py"
    ).read_text(encoding="utf-8")

    assert "def _coverage_caption(" in text
    assert "실제 조회범위/전략" in text
    assert "source.coverage_start" in text
    assert "source.coverage_end" in text
    assert "source.requested_lookback_days" in text
    assert "ResearchSourceStatus.NOT_RUN" in text
    assert 'column.metric(label, "미조회")' in text
    assert "0건 검색 결과가 아니라 **미조회** 상태" in text


def test_contract_research_does_not_assume_undocumented_31_day_window() -> None:
    text = (
        REPO_ROOT / "src" / "purchase_price" / "services" / "g2b_contract_research.py"
    ).read_text(encoding="utf-8")

    assert "max_window_days: int | None = None" in text
    assert "if max_window_days is None:" in text
    assert "return ((begin, end),)" in text
