from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_quote_review_defaults_to_automatic_market_research() -> None:
    text = (REPO_ROOT / "pages" / "2_견적_검토.py").read_text(encoding="utf-8")

    assert 'options=("자동 시장가격 조사", "정밀 비교검토")' in text
    assert 'if mode == "자동 시장가격 조사"' in text
    assert 'st.button("← 이전 단계"' in text


def test_market_research_pipeline_keeps_procurement_context_outside_direct_prices() -> None:
    text = (REPO_ROOT / "src" / "purchase_price" / "ui" / "market_research.py").read_text(
        encoding="utf-8"
    )

    assert "research_g2b_market(" in text
    assert "enrich_market_bundle_with_bid_items(" in text
    assert "enrich_market_bundle_with_contracts(" in text
    assert "discover_unmapped_g2b_candidates(" in text
    assert "search_all(" in text
    assert "None of those records are passed to `search_all` or `assess_prices`." in text


def test_quick_search_runs_full_procurement_research_without_verified_mapping_gate() -> None:
    text = (REPO_ROOT / "pages" / "3_빠른_검색.py").read_text(encoding="utf-8")

    assert "research_g2b_market(" in text
    assert "enrich_market_bundle_with_bid_items(" in text
    assert "enrich_market_bundle_with_contracts(" in text
    assert "discover_unmapped_g2b_candidates(" in text
    assert "research_needed" not in text


def test_quote_market_surface_persists_procurement_bundle_per_item() -> None:
    text = (
        REPO_ROOT / "src" / "purchase_price" / "ui" / "quote_market_research.py"
    ).read_text(encoding="utf-8")

    assert "run_market_research(" in text
    assert "state.market_bundles[index] = market_bundle" in text
    assert "render_procurement_research(market_bundle)" in text
