"""UX v1.2 Q3: trade windows reopen on the same row; supplier and year rows filter 거래 전체.

Production (2026-10-14): PNB-704 거래 전체 and 도입 기관 opened the trade window only when the picked
row differed from the last applied one, so closing it and picking the same row did nothing. The
supplier, company and year tables had no row action.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from purchase_price.ui import table_actions as ta

FORBIDDEN = (
    "적정", "권장", "싸다", "비싸다", "절감액", "대체 가능", "안전한 제품", "원인 확정", "개선 필요",
    "우수", "부진", "인기", "대표", "추천",
)
DASHBOARD = Path("pages/1_대시보드.py").read_text(encoding="utf-8")
CATEGORY = Path("src/purchase_price/ui/category_market.py").read_text(encoding="utf-8")


def _pick(state: dict, base: str, index: int, callback) -> None:
    """What Streamlit does on a row click: store the selection under the current key, then call back."""

    state[ta.table_key(base, state)] = {"selection": {"rows": [index], "columns": []}}
    callback()


def test_the_same_row_picked_twice_opens_the_window_twice_and_a_rerun_opens_nothing() -> None:
    state: dict = {}
    rows = [{"원천기록": "a"}, {"원천기록": "b"}]
    callback = ta.pick_callback("trades", lambda index: ta.queue_dialog("trades", rows[index], state), state)
    first_key = ta.table_key("trades", state)
    _pick(state, "trades", 1, callback)
    assert ta.table_key("trades", state) != first_key  # the table starts with no selection again
    assert ta.take_dialog("trades", state) == {"원천기록": "b"}
    assert ta.take_dialog("trades", state) is None  # an ordinary rerun (typing a quote) opens nothing
    _pick(state, "trades", 1, callback)  # the same row again
    assert ta.take_dialog("trades", state) == {"원천기록": "b"}


def test_a_selection_state_reads_as_dict_or_attributes() -> None:
    class Selection:
        rows = [3]

    class Event:
        selection = Selection()

    assert ta.selected_row(Event()) == 3
    assert ta.selected_row({"selection": {"rows": []}}) is None
    assert ta.selected_row(None) is None


def test_filters_combine_one_supplier_and_one_year_and_clear() -> None:
    state: dict = {}
    assert not ta.get_filter("PNB-704", state).active
    ta.set_filter("PNB-704", state, supplier="  가  상사 ")
    flt = ta.set_filter("PNB-704", state, year="2025")
    assert flt == ta.TradeFilter(supplier="가 상사", year="2025")
    assert ta.set_filter("PNB-704", state, supplier="나 상사").year == "2025"  # replaces, keeps the year
    rows = [
        {"판매처": "나 상사", "거래일": "2025-03-01"},
        {"판매처": "나  상사", "거래일": "2025-12-31"},
        {"판매처": "나 상사", "거래일": "2024-03-01"},
        {"판매처": "가 상사", "거래일": "2025-03-01"},
    ]
    assert ta.filter_rows(rows, ta.get_filter("PNB-704", state)) == rows[:2]
    assert ta.filter_line(ta.get_filter("PNB-704", state), 2) == "납품업체: 나 상사 · 2025년 거래만 보는 중 (2건)"
    assert ta.filter_rows([{"거래일": ""}], ta.TradeFilter(year=ta.UNDATED_YEAR)) == [{"거래일": ""}]
    assert not ta.get_filter("SJ-DFM100", state).active  # kept per result
    ta.clear_filter("PNB-704", state)
    assert not ta.get_filter("PNB-704", state).active


def test_a_filter_pick_switches_the_tabs_and_a_new_search_resets_everything() -> None:
    state: dict = {}
    assert not ta.stateful_tabs("PNB-704", state)
    ta.remember_tab_target("PNB-704", "tabs::PNB-704", "거래 전체 70건", state)
    ta.set_filter("PNB-704", state, year="2025")
    ta.show_trade_tab("PNB-704", state)
    assert ta.stateful_tabs("PNB-704", state) and state["tabs::PNB-704"] == "거래 전체 70건"
    ta.tabs_state_ready("tabs::PNB-704", ["기간별", "거래 전체 71건"], state)
    assert "tabs::PNB-704" not in state  # a label that no longer exists is dropped
    state["other"] = 1
    ta.clear_all_filters(state)
    assert state == {"other": 1}


def test_dashboard_reopens_trade_windows_and_filters_by_supplier_and_year() -> None:
    assert "workspace_direct_table_applied" not in DASHBOARD and "record_applied_key" not in DASHBOARD
    assert "on_select=_trade_pick_callback(record_base, shown_rows)" in DASHBOARD
    assert "picked_record = table_actions_ui.take_dialog(record_base)" in DASHBOARD
    assert "table_actions_ui.filter_rows(direct_rows, trade_filter)" in DASHBOARD
    assert "trade_rows = result_summary_ui.trade_table_rows(shown_rows)" in DASHBOARD
    assert DASHBOARD.count("_render_supplier_table(supplier_table, quote_key=quote_key)") == 2
    assert '[str(row.get("연도") or "") for row in year_rows], "year"' in DASHBOARD
    assert "table_actions_ui.result_tabs(" in DASHBOARD
    assert DASHBOARD.count("table_actions_ui.clear_all_filters()") == 3
    assert '("purchase_price.ui.category_market", "CATEGORY_MARKET_REOPEN_V1")' in DASHBOARD


def test_category_market_reopens_buyer_windows_and_filters_by_supplier() -> None:
    assert "::applied" not in CATEGORY and "applied_key" not in CATEGORY
    assert "on_select=table_actions.pick_callback(base, picked)" in CATEGORY
    assert "pending = table_actions.take_dialog(base)" in CATEGORY
    assert CATEGORY.count("table_actions.pick_callback(") == 2  # 도입 기관 and 납품업체
    assert "table_actions.result_tabs(" in CATEGORY


def test_category_supplier_filter_keeps_only_that_suppliers_trades() -> None:
    from purchase_price.services import category_market as cm
    from purchase_price.ui import category_market as ui

    def trade(supplier: str) -> cm.ClassifiedTrade:
        return cm.ClassifiedTrade(
            cm.CategoryTrade(
                source_record_id=f"delivery:{supplier}|change:00|line:1", raw_object_key="raw/key.json",
                transaction_date="2026-03-01", institution="병원", manufacturer="나눔", model_name="M1",
                quantity=Decimal("1"), unit="대", unit_price=Decimal("1000"), total_amount=Decimal("1000"),
                supplier=supplier, business_name="구매", product_title="품목", specification="",
                detail_code="4217210101",
            ),
            cm.KIND_EQUIPMENT,
        )

    rows = [trade("가 상사"), trade("나 상사"), trade("가  상사")]
    assert ui.filter_by_supplier(rows, "가 상사") == [rows[0], rows[2]]
    assert ui.filter_result_key("x").startswith("cm::")
    assert ta.filter_key(ui.filter_result_key("x")).startswith("trade_filter::")  # cleared by a new search


def test_new_visible_strings_use_no_judgement_words() -> None:
    texts = [
        ta.CLEAR_LABEL,
        ta.filter_line(ta.TradeFilter(supplier="가 상사", year="2025"), 3),
        "연도 행을 고르면 '거래 전체' 탭이 그 연도 거래만 보여줍니다.",
        "업체 행을 고르면 위 '거래 전체' 탭이 그 업체 거래만 보여줍니다.",
        "이 기간에는 고른 조건의 거래가 없습니다. '전체 보기'로 되돌리거나 기간을 넓히세요.",
    ]
    for text in texts:
        assert text in DASHBOARD or text in CATEGORY or text in (ta.CLEAR_LABEL, texts[1])
        for word in FORBIDDEN:
            assert word not in text, (word, text)


def test_category_block_renders_with_tabs_links_and_selectable_tables() -> None:
    from streamlit.testing.v1 import AppTest

    def app() -> None:
        from decimal import Decimal

        from purchase_price.services import category_market as cm
        from purchase_price.ui import category_market as ui
        from purchase_price.ui import model_links

        trade = cm.CategoryTrade(
            source_record_id="delivery:R1|change:00|line:1", raw_object_key="raw/key.json",
            transaction_date="2026-03-01", institution="병원", manufacturer="나눔", model_name="M1",
            quantity=Decimal("1"), unit="대", unit_price=Decimal("1000000"), total_amount=Decimal("1000000"),
            supplier="가 상사", business_name="구매", product_title="품목", specification="", detail_code="4217210101",
        )
        model = cm.CategoryModel(
            model="M1", company="나눔", permit_number="제허 1", grade="2", status="국내 정상", trade_count=1,
            median=Decimal("1000000"), low=Decimal("1000000"), high=Decimal("1000000"), latest="2026-03-01",
        )
        market = cm.CategoryMarket(
            status="success", product_name="품목", trades=(cm.ClassifiedTrade(trade, cm.KIND_EQUIPMENT),),
            models=(model,), suppliers=(cm.SupplierSummary("가 상사", 1, "2026-03-01", 1, ("M1",)),),
        )
        market = cm.with_status_labels(market, {}) if hasattr(cm, "with_status_labels") else market
        ui.render_category_market(
            market,
            key="probe",
            searched_model="M0",
            model_url=lambda name, reg: model_links.model_search_url(name, base=model_links.PRODUCTION_APP_URL),
            on_open_trade=lambda row: None,
        )

    at = AppTest.from_function(app, default_timeout=30).run()
    assert not at.exception, at.exception
    frames = at.dataframe
    assert len(frames) == 3  # models, 도입 기관, 납품업체
    keys = [frame.key or "" for frame in frames]
    assert any(key.startswith("cm_buyers::probe::0::v") for key in keys)
    assert any(key.startswith("cm_suppliers::probe::v") for key in keys)
    assert "새 탭에서 열리고" in " ".join(caption.value for caption in at.caption)
