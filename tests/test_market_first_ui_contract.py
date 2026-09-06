from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_quote_review_defaults_to_automatic_market_research() -> None:
    text = (REPO_ROOT / "pages" / "2_견적_검토.py").read_text(encoding="utf-8")

    assert 'options=("자동 시장가격 조사", "정밀 비교검토")' in text
    assert 'if mode == "자동 시장가격 조사"' in text
    assert 'st.button("← 이전 단계"' in text


def test_quick_search_runs_market_research_without_verified_mapping_gate() -> None:
    text = (REPO_ROOT / "pages" / "3_빠른_검색.py").read_text(encoding="utf-8")

    assert "run_market_research(" in text
    assert "제품명 키워드만으로 나라장터 Research" in text
    assert "research_needed" not in text
