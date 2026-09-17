from pathlib import Path


def test_production_unified_search_smoke_uses_user_visible_result_contract() -> None:
    script = Path("scripts/production_unified_search_smoke.py").read_text(encoding="utf-8")

    assert 'DEPLOYMENT_MARKER = "#unified-search-runtime-v3"' in script
    assert 'fill("DFM100")' in script
    assert "동일성 확인 (\\d+)건 · 검색 참고 (\\d+)건" in script
    assert "strict_count + reference_count < 1" in script
    assert "상세 조사·근거 보기" in script
    assert "상세 조사·근거" in script
    assert 'report["detail_toggle_persisted"] = True' in script
    assert "AttributeError" in script
    assert "This app has encountered an error" in script
    assert 'data-testid="stDataFrame"' not in script


def test_browser_workflow_runs_dedicated_unified_search_smoke_after_merge() -> None:
    workflow = Path(".github/workflows/production-browser-smoke.yml").read_text(encoding="utf-8")

    assert 'EXPECT_UNIFIED_SEARCH: "0"' in workflow
    assert "Run Production DFM100 unified-search smoke" in workflow
    assert "python scripts/production_unified_search_smoke.py" in workflow
    assert "if: github.event_name != 'pull_request'" in workflow
