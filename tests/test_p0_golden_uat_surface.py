from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_golden_uat_workflow_and_probe_exist() -> None:
    assert (REPO_ROOT / ".github/workflows/p0-golden-apc-flow-uat.yml").exists()
    assert (REPO_ROOT / "src/purchase_price/scripts/probe_p0_golden_uat.py").exists()


def test_integrated_market_research_keeps_research_outside_assessment() -> None:
    text = (REPO_ROOT / "src/purchase_price/ui/market_research.py").read_text(
        encoding="utf-8"
    )
    assert "None of those records" in text
    assert "or candidates are passed to `search_all` or `assess_prices`." in text
    assert "verified mapping 파일을 수정하지" in text
    assert "세부품명번호 표적 Shopping Research 실행" in text


def test_golden_uat_documents_non_promotion_contract() -> None:
    text = (REPO_ROOT / "docs/P0_GOLDEN_UAT_INTEGRATION.md").read_text(encoding="utf-8")
    assert "FLOW-C20" in text
    assert "Water Jacket" in text
    assert "동일모델 가격 band로 승격하지 않는다" in text
    assert "외부 API 인증/transport 실패" in text
