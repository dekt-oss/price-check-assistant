from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_targeted_shopping_uses_only_verified_or_explicit_session_candidate_code() -> None:
    text = (REPO_ROOT / "src" / "purchase_price" / "ui" / "market_research.py").read_text(
        encoding="utf-8"
    )

    assert "def _targeted_detail_codes(" in text
    assert "basis.is_verified_official" in text
    assert "st.session_state.get(_classification_session_key(query)" in text
    assert "return (selected,) if selected in allowed else ()" in text
    assert "target_detail_product_codes=targeted_codes" in text


def test_targeted_shopping_ui_keeps_research_selection_out_of_price_promotion() -> None:
    text = (REPO_ROOT / "src" / "purchase_price" / "ui" / "market_research.py").read_text(
        encoding="utf-8"
    )

    assert "세부품명번호 표적 Shopping Research 실행" in text
    assert "표적조회 자체는 동일제품 판정이 아닙니다" in text
    assert "verified mapping" in text
    assert "`assess_prices()`에 승격하지 않습니다" in text
