from pathlib import Path


def test_production_unified_search_smoke_uses_user_visible_result_contract() -> None:
    script = Path("scripts/production_unified_search_smoke.py").read_text(encoding="utf-8")

    assert 'DEPLOYMENT_MARKER = "#purchase-workspace-quote-v1"' in script
    assert 'fill("DFM100")' in script
    assert "동일성 확인 (\\d+)건 · 검색 참고 (\\d+)건" in script
    assert 'WORKSPACE_DIRECT_PATTERN = re.compile(r"동일제품 거래\\s*(\\d+)건")' in script
    assert "workspace_match = WORKSPACE_DIRECT_PATTERN.search(body)" in script
    assert "strict_count < 1" in script
    assert "DFM100 one-line search did not recover direct A/B evidence" in script
    assert 'get_by_role("tab", name="Research·근거")' in script
    assert 'get_by_role("tab", name="식약처·업체")' in script
    assert 'report["mfds_tab_rendered"] = True' in script
    assert 'get_by_role("tab", name="거래가격")' in script
    assert 'report["workspace_tabs_persisted"] = True' in script
    assert "AttributeError" in script
    assert "This app has encountered an error" in script
    assert 'data-testid="stDataFrame"' not in script


def test_browser_workflow_runs_dedicated_unified_search_smoke_after_merge() -> None:
    workflow = Path(".github/workflows/production-browser-smoke.yml").read_text(encoding="utf-8")

    assert 'EXPECT_UNIFIED_SEARCH: "0"' in workflow
    assert "Run Production DFM100 unified-search smoke" in workflow
    assert "python scripts/production_unified_search_smoke.py" in workflow
    assert "if: github.event_name != 'pull_request'" in workflow
