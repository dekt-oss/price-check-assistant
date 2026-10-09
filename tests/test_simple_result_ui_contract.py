"""Contract for the simplified purchasing-team screen (docs/UI_SIMPLIFICATION_WORK_SPEC_20261006.md)."""

from __future__ import annotations

import ast
from pathlib import Path

from purchase_price.ui import result_summary as rs

ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "pages" / "1_대시보드.py"
HOME = ROOT / "Home.py"

# Streamlit calls whose string arguments reach the screen.
_DISPLAY_CALLS = {
    "caption",
    "info",
    "warning",
    "success",
    "error",
    "subheader",
    "title",
    "button",
    "form_submit_button",
    "download_button",
    "link_button",
    "page_link",
    "expander",
    "status",
    "update",
    "checkbox",
    "selectbox",
    "text_input",
    "metric",
    "spinner",
    "toggle",
    "TextColumn",
    "NumberColumn",
}


def _screen_strings(source: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in _DISPLAY_CALLS:
            continue
        for arg in [*node.args, *(keyword.value for keyword in node.keywords)]:
            for inner in ast.walk(arg):
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                    if any("가" <= char <= "힣" for char in inner.value):
                        found.append((inner.lineno, inner.value))
    return found


def test_dashboard_screen_text_has_no_developer_terms() -> None:
    offenders = [
        (line, text)
        for line, text in _screen_strings(DASHBOARD.read_text(encoding="utf-8"))
        if rs.has_banned_term(text)
    ]
    assert offenders == []


def test_markdown_headings_on_the_result_screen_are_plain() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    for heading in ("#### 얼마에 거래됐나", "#### 누가 파는가", "#### 같은 품목의 다른 모델"):
        assert heading in source
    for removed in ("구매조사 워크스페이스", "WORKSPACE_VIEWS[", "st.segmented_control("):
        assert removed not in source


def test_result_screen_keeps_deployment_and_diagnostic_markers() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    for marker in (
        'id="purchase-workspace-runtime-v16"',
        'id="purchase-workspace-runtime-v21"',
        'id="purchase-search-timings-v1"',
        'id="purchase-research-stage-timings-v1"',
        'id="purchase-safety-diagnostic-v1"',
        'id="purchase-research-deferred-v1"',
        'id="purchase-simple-result-v1"',
    ):
        assert marker in source


def test_slow_lookups_are_not_primary_buttons_on_the_first_screen() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    mfds_button = source.index('key=f"workspace_header_mfds_model_info::{quote_key}"')
    assert 'type="tertiary"' in source[mfds_button : mfds_button + 120]
    # The procurement research loads only below the detail section.
    assert source.index('"상세 자료 · 견적 조건') < source.index("입찰·계약 참고자료 불러오기")


def test_full_tables_are_one_expander_away() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    # The full list is the third tab of 얼마에 거래됐나 (design step 3, 2026-10-09).
    assert '["연도별", "단위·조건별", f"거래 전체 {strict_count}건"]' in source
    assert "result_summary_ui.unit_group_rows(direct_rows" in source
    assert "result_summary_ui.trade_table_rows(direct_rows)" in source
    assert "supplier_summary_rows(" in source
    assert "same_item_summary_rows(" in source


def test_quote_upload_opens_items_in_place() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    assert "_render_quote_items(search_state)" in source
    assert 'selection_mode="single-row"' in source
    assert 'st.switch_page("pages/2_견적_검토.py")' not in source


def test_sidebar_groups_business_pages_and_hides_validation_tools() -> None:
    source = HOME.read_text(encoding="utf-8")
    assert 'position="hidden"' in source
    assert 'title="가격 조사"' in source
    assert 'title="의료기기 허가·안전"' in source
    assert 'sidebar_group_html("구매 업무")' in source
    assert 'sidebar_group_html("병원 경영 정보")' in source
    # Validation pages stay reachable by URL (production OCR smoke) but are listed only for admins.
    assert 'url_path="quote-extraction-uat"' in source
    assert "if _admin_mode():" in source


def test_dashboard_reloads_retained_pre_simplification_ui_modules() -> None:
    import importlib

    source = DASHBOARD.read_text(encoding="utf-8")
    assert "_refresh_ui_modules()\nst.set_page_config(" in source
    for name, marker in (
        ("purchase_price.ui.widgets", "PLAIN_WORDING_2026_10"),
        ("purchase_price.ui.g2b_market_research", "PLAIN_WORDING_2026_10"),
        ("purchase_price.ui.market_research", "PLAIN_WORDING_2026_10"),
        ("purchase_price.ui.same_item_compare", "PLAIN_WORDING_2026_10"),
        ("purchase_price.ui.workspace_header", "PLAIN_WORDING_2026_10C"),
        ("purchase_price.ui.result_summary", "RESULT_SUMMARY_V3"),
        ("purchase_price.ui.search_overviews", "OVERVIEW_V2"),
        ("purchase_price.ui.result_layout", "RESULT_LAYOUT_V3"),
    ):
        assert f'("{name}", "{marker}")' in source
        assert getattr(importlib.import_module(name), marker) is True


def test_zero_trade_rows_do_not_put_words_in_the_price_column() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    assert "직접 동일성 확인 거래 0건" not in source
    rows = rs.overview_model_rows(
        [{"모델": "A", "품목 책임주체": "X", "나라장터 직접거래": 0, "나라장터 가격범위": "같은 제품 거래 0건"}]
    )
    assert rows[0]["가격범위"] == ""
    assert rows[0]["같은 제품 거래(수집분)"] == "0건"


def test_company_overview_offers_similarly_named_companies_instead_of_guessing() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    assert '"similar_companies": similar_companies' in source
    assert "overview_ui.company_name_variants(raw_search)" in source
    assert "이름이 비슷한 다른 업체도 있습니다" in source
