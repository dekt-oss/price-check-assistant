from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_production_browser_smoke_gates_r2_before_dfm100() -> None:
    workflow = (REPO_ROOT / ".github/workflows/production-browser-smoke.yml").read_text(
        encoding="utf-8"
    )

    gate = "python scripts/production_r2_runtime_diagnostic.py --require-ready"
    dfm = "python scripts/production_unified_search_smoke.py"
    quote = "python scripts/production_quote_uat_smoke.py"

    assert gate in workflow
    assert dfm in workflow
    assert workflow.index(gate) < workflow.index(dfm)
    assert "Run production quote UAT upload smoke\n        if: always()" in workflow
    assert quote in workflow


def test_r2_diagnostic_has_explicit_readiness_exit_contract() -> None:
    source = (REPO_ROOT / "scripts/production_r2_runtime_diagnostic.py").read_text(
        encoding="utf-8"
    )

    assert '"--require-ready"' in source
    assert 'report.get("code") != "ready"' in source
    assert "return 2" in source
    assert "raise SystemExit(main())" in source


def test_home_surfaces_missing_r2_configuration_to_user() -> None:
    source = (REPO_ROOT / "Home.py").read_text(encoding="utf-8")

    assert "Settings().r2_configured" in source
    assert "나라장터 거래가격 인덱스 연결 설정이 없어" in source
    assert "거래가격 기반 비교·건수·가격범위" in source
