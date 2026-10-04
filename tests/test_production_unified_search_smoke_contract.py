from pathlib import Path


def test_production_unified_search_smoke_uses_user_visible_result_contract() -> None:
    script = Path("scripts/production_unified_search_smoke.py").read_text(encoding="utf-8")

    assert 'DEPLOYMENT_MARKER = "#purchase-workspace-runtime-v8"' in script
    assert 'fill("DFM100")' in script
    assert "동일성 확인 (\\d+)건 · 검색 참고 (\\d+)건" in script
    assert 'WORKSPACE_DIRECT_PATTERN = re.compile(r"직접 동일성 확인 거래\\s*(\\d+)건")' in script
    assert "workspace_match = WORKSPACE_DIRECT_PATTERN.search(body)" in script
    assert "strict_count < 1" in script
    assert "DFM100 one-line search did not recover direct A/B evidence" in script
    assert 'get_by_text("업체·조달", exact=True)' in script
    assert 'report["supplier_section_rendered"] = True' in script
    assert 'get_by_text("동일품목 비교", exact=True)' in script
    assert 'report["comparison_section_rendered"] = True' in script
    assert 'report["price_section_rendered"] = True' in script
    assert 'report["direct_research_status"] = _research_status(page)' in script
    assert 'report["quote_research_status"] = _research_status(page)' in script
    assert "Initial DFM100 A/B workspace exceeded 25 second latency gate" in script
    assert "AttributeError" in script
    assert "This app has encountered an error" in script
    assert 'data-testid="stDataFrame"' not in script


def test_browser_workflow_runs_dedicated_unified_search_smoke_after_merge() -> None:
    workflow = Path(".github/workflows/production-browser-smoke.yml").read_text(encoding="utf-8")

    assert 'EXPECT_UNIFIED_SEARCH: "0"' in workflow
    assert "Run Production DFM100 unified-search smoke" in workflow
    assert "python scripts/production_unified_search_smoke.py" in workflow
    assert "if: github.event_name != 'pull_request'" in workflow
