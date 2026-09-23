from pathlib import Path

from scripts.production_unified_search_smoke import _price_tab_direct_count


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
    assert "direct_count = _price_tab_direct_count(body)" in script
    assert 'report["price_tab_direct_count"] = direct_count' in script
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


def test_price_tab_contract_accepts_observed_production_body() -> None:
    body = (
        "구매조사 워크스페이스\nEfficia DFM100\n거래가격\n"
        "나라장터 실제 거래\n동일성 확인 2건 · 검색 참고 0건\n"
        "모델·규격·조건별 직접가격"
    )

    assert _price_tab_direct_count(body) == 2


def test_price_tab_contract_rejects_summary_only_or_zero_direct_results() -> None:
    assert _price_tab_direct_count("동일제품 거래\n2건") is None
    assert _price_tab_direct_count(
        "나라장터 실제 거래\n동일성 확인 0건 · 검색 참고 3건"
    ) is None
