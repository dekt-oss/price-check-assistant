from pathlib import Path


def test_classification_candidate_ui_is_explicitly_research_only() -> None:
    source = Path("src/purchase_price/ui/market_research.py").read_text(encoding="utf-8")

    assert "공식 세부품명 후보 · Research 미검증" in source
    assert "verified mapping 파일을 수정하지" in source
    assert "`assess_prices()`에 승격하지 않습니다" in source
    assert "공식 세부품명 resolver 조회가 실패했습니다. 이는 공식분류 후보 0건과 다릅니다." in source
