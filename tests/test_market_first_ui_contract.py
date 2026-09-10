from __future__ import annotations

from pathlib import Path

from purchase_price.ui.quote_market_research import _filename_product_candidate

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_quote_review_uses_one_upload_first_workflow() -> None:
    text = (REPO_ROOT / "pages" / "2_견적_검토.py").read_text(encoding="utf-8")

    assert "render_quote_market_research(state)" in text
    assert "상세 검증·최종 판정" in text
    assert "원문 확인 · 제품 식별 · 조건 대조 · 승인" in text
    assert 'options=("자동 시장가격 조사", "정밀 비교검토")' not in text
    assert 'key="quote_review_mode"' not in text


def test_market_research_pipeline_keeps_procurement_context_outside_direct_prices() -> None:
    text = (REPO_ROOT / "src" / "purchase_price" / "ui" / "market_research.py").read_text(
        encoding="utf-8"
    )

    assert "research_g2b_market(" in text
    assert "enrich_market_bundle_with_bid_items(" in text
    assert "enrich_market_bundle_with_contracts(" in text
    assert "discover_unmapped_g2b_candidates(" in text
    assert "search_all(" in text
    assert "None of those records or candidates are passed to `search_all`" in text
    assert "or candidates are passed to `search_all` or `assess_prices`." in text


def test_quick_search_uses_full_market_research_pipeline_without_verified_mapping_gate() -> None:
    text = (REPO_ROOT / "pages" / "3_빠른_검색.py").read_text(encoding="utf-8")

    assert "run_market_research(" in text
    assert "render_procurement_research(market_bundle)" in text
    assert "render_market_reference_summary(" in text
    assert "research_needed" not in text
    assert "verified mapping" in text


def test_quote_market_surface_persists_procurement_bundle_per_item() -> None:
    text = (
        REPO_ROOT / "src" / "purchase_price" / "ui" / "quote_market_research.py"
    ).read_text(encoding="utf-8")

    assert "run_market_research(" in text
    assert "state.market_bundles[index] = market_bundle" in text
    assert "render_procurement_research(market_bundle)" in text


def test_quote_market_surface_handles_zero_extraction_without_mode_switch() -> None:
    text = (
        REPO_ROOT / "src" / "purchase_price" / "ui" / "quote_market_research.py"
    ).read_text(encoding="utf-8")

    assert "def _render_inline_manual_item_form" in text
    assert "build_manual_quote_item(" in text
    assert "품목 저장 후 시장조사" in text
    assert "다른 검토 모드로 이동할 필요 없이" in text
    assert "_render_inline_manual_item_form(state)" in text
    assert "파일명 기반 후보이며 OCR 확정값이나 공식 제품식별값은 아닙니다" in text


def test_filename_product_candidate_recovers_user_quote_name() -> None:
    assert _filename_product_candidate("극초단파치료시스템 견적1.pdf") == "극초단파치료시스템"
    assert _filename_product_candidate("02_환자감시장치_견적서_v2.png") == "환자감시장치"


def test_filename_product_candidate_does_not_invent_identity_from_generic_filename() -> None:
    assert _filename_product_candidate("견적1.pdf") == ""
    assert _filename_product_candidate("2026-09-10.pdf") == ""


def test_quote_item_edit_invalidates_stale_identity_and_research() -> None:
    text = (
        REPO_ROOT / "src" / "purchase_price" / "ui" / "quote_market_research.py"
    ).read_text(encoding="utf-8")

    assert "def _invalidate_item_review" in text
    assert "state.identity.pop(index, None)" in text
    assert "state.item_confirmed[index] = False" in text
    assert "_clear_research(state)" in text