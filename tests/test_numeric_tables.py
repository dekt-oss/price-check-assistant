"""UX v1.2 Q1: price, count and quantity cells are numbers, so a header click sorts by value.

Production (2026-10-14): PNB-704 거래 총액 descending put 147,000,000원 after 63,000,000원, and
SJ-DFM100 가운데 값 ascending listed 298 blank rows first, because every cell was a formatted
string. Here every converted column holds int/float/None, sorts numerically with None last, and
every st.dataframe call site formats it with a NumberColumn.
"""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from purchase_price.services import price_metrics as pm
from purchase_price.services.category_market import KIND_EQUIPMENT
from purchase_price.ui import category_market as cm
from purchase_price.ui import number_columns as nc
from purchase_price.ui import price_trend as pt
from purchase_price.ui import result_layout as rl
from purchase_price.ui import result_summary as rs
from purchase_price.ui import same_item_compare as same

BIG, SMALL, MID = 147_000_000, 63_000_000, 99_000_000
FORBIDDEN = ("적정", "권장", "싸다", "비싸다", "절감액", "대체 가능", "안전한 제품", "원인 확정", "개선 필요", "우수", "부진", "인기", "대표", "추천")


def _assert_numeric(rows: list[dict[str, object]], columns: list[str]) -> None:
    assert rows
    for row in rows:
        for column in columns:
            value = row[column]
            assert value is None or (isinstance(value, int | float) and not isinstance(value, bool)), (column, value)
    assert set(columns) <= set(nc.numeric_columns(rows))


def _sorted_desc(rows: list[dict[str, object]], column: str) -> list[object]:
    frame = pd.DataFrame(rows)
    assert pd.api.types.is_numeric_dtype(frame[column]), column
    return [None if pd.isna(v) else v for v in frame.sort_values(column, ascending=False)[column]]


def _trade(total: int | None, price: int, quantity: str = "1", unit: str = "대", day: str = "2026-09-01") -> dict[str, object]:
    return {
        "거래일": day,
        "모델": "PNB-704",
        "가격": f"{price:,}원",
        "총액": f"{total:,}원" if total is not None else "미확인",
        "수량": quantity,
        "단위": unit,
        "거래조건": "납품요구",
        "원천기록": "delivery:R26TB02199340|change:00|line:1",
    }


TRADES = [_trade(SMALL, SMALL), _trade(BIG, BIG // 2, "2"), _trade(None, MID, "", "미확인"), _trade(MID, MID)]


def test_number_parses_money_text_and_keeps_missing_values_empty() -> None:
    assert nc.number("147,000,000원") == BIG
    assert nc.number(Decimal("5492750.0")) == 5492750 and isinstance(nc.number(Decimal("2.0")), int)
    assert nc.number(Decimal("1.5")) == 1.5
    for missing in (None, "", "미확인", "확인 안 됨", "—", True, Decimal("NaN")):
        assert nc.number(missing) is None


def test_trade_table_sorts_the_total_by_value() -> None:
    rows = rs.trade_table_rows(TRADES)
    _assert_numeric(rows, ["거래 총액(원)", "수량", "1단위 가격(원)"])
    assert _sorted_desc(rows, "거래 총액(원)") == [BIG, MID, SMALL, None]
    assert _sorted_desc(rows, "1단위 가격(원)")[0] == MID
    assert [row["단위"] for row in rows] == ["대", "대", "확인 안 됨", "대"]


def test_year_and_unit_group_tables_are_numeric() -> None:
    trades = [_trade(SMALL, SMALL, day="2025-03-01"), _trade(BIG, BIG, day="2026-03-01"), _trade(None, 10, "", "set", "2024-01-01")]
    years = rs.year_summary_rows(trades, main_unit="대")
    _assert_numeric(years, ["거래 건수", "총수량(대)", "1대당 중앙값(원)", "1대당 최저(원)", "1대당 최고(원)", "다른 단위 거래(건)"])
    assert _sorted_desc(years, "1대당 중앙값(원)") == [BIG, SMALL, None]
    assert years[-1]["다른 단위 거래(건)"] == 1

    groups = rs.unit_group_rows(
        [_trade(SMALL, SMALL), _trade(BIG, BIG), _trade(None, MID, ""), _trade(SMALL, SMALL, unit="set")], limit=10
    )
    numeric = ["건수", "총수량", "거래 총액 합계(원)", "1단위 중앙값(원)", "1단위 최저(원)", "1단위 최고(원)"]
    _assert_numeric(groups, numeric)
    main, sets = groups
    # One 대 trade has no quantity and no total: the sums stay empty and the status says why.
    assert main["총수량"] is None and main["거래 총액 합계(원)"] is None
    assert main["상태"] == "총수량·거래 총액 일부 확인 안 됨"
    assert (main["1단위 최저(원)"], main["1단위 최고(원)"]) == (SMALL, BIG)
    assert sets["총수량"] == 1 and sets["거래 총액 합계(원)"] == SMALL and sets["상태"] == ""
    assert _sorted_desc(groups, "1단위 중앙값(원)") == [MID, SMALL]


def test_trend_rows_are_numeric() -> None:
    bucket = SimpleNamespace(label="2026", ongoing=False, count=3, median=Decimal(SMALL), low=Decimal(SMALL), high=Decimal(BIG), enough=True)
    empty = SimpleNamespace(label="2025", ongoing=False, count=0, median=None, low=None, high=None, enough=False)
    other = SimpleNamespace(label="2024", ongoing=False, count=12, median=Decimal(MID), low=Decimal(MID), high=Decimal(MID), enough=True)
    rows = pt.trend_rows(SimpleNamespace(buckets=[other, empty, bucket]), unit="대")
    _assert_numeric(rows, ["거래 건수", "1대당 가운데 값(원)", "최저(원)", "최고(원)"])
    assert _sorted_desc(rows, "1대당 가운데 값(원)") == [MID, SMALL, None]
    assert _sorted_desc(rows, "거래 건수") == [12, 3, 0]


def test_supplier_summary_is_numeric() -> None:
    suppliers = [
        {"공급업체": "A", "직접거래건수": 2, "수요기관수": 1, "최저단가": Decimal(SMALL), "최고단가": Decimal(SMALL)},
        {"공급업체": "B", "직접거래건수": 12, "수요기관수": 4, "최저단가": Decimal(BIG), "최고단가": Decimal(BIG)},
        {"공급업체": "C", "직접거래건수": 1, "수요기관수": 1, "최저단가": None, "최고단가": None},
    ]
    rows = rs.supplier_summary_rows(suppliers, limit=None)
    _assert_numeric(rows, ["거래 건수", "납품 기관 수", "최저(원)", "최고(원)"])
    assert _sorted_desc(rows, "최고(원)") == [BIG, SMALL, None]


LINKS = [
    {"모델": "SJ-DFM100", "식약처 품목번호": "제허 1", "품목 책임주체": "A사", "나라장터 직접거래": 70, "나라장터 가격범위": "63,000,000 ~ 147,000,000원", "현재 모델": True},
    {"모델": "B2", "식약처 품목번호": "제허 2", "품목 책임주체": "A사", "나라장터 직접거래": 5, "나라장터 가격범위": "99,000,000원"},
    {"모델": "C3", "식약처 품목번호": "제허 3", "품목 책임주체": "B사", "나라장터 직접거래": None, "나라장터 가격범위": ""},
    {"모델": "D4", "식약처 품목번호": "제허 4", "품목 책임주체": "B사", "나라장터 직접거래": 0, "나라장터 가격범위": ""},
]


def test_same_item_rows_split_the_range_and_keep_the_status_words() -> None:
    view = same.build_same_item_rows(LINKS, None, include_unpriced=True)
    full = rs.display_rows(view.rows)
    _assert_numeric(full, ["같은 제품 거래", "최저(원)", "최고(원)"])
    by_model = {row["모델"].removeprefix("▶ "): row for row in full}
    assert by_model["SJ-DFM100"]["최저(원)"] == SMALL and by_model["SJ-DFM100"]["최고(원)"] == BIG
    assert by_model["C3"]["같은 제품 거래"] is None and by_model["C3"]["거래 자료 상태"] == "조회 불가"
    assert _sorted_desc(full, "최고(원)") == [BIG, MID, None, None]

    summary = rs.same_item_summary_rows(view.rows, limit=10)
    _assert_numeric(summary, [rs.COLLECTED_TRADES_LABEL, "최저(원)", "최고(원)"])
    assert summary[0]["모델"] == "▶ SJ-DFM100"
    assert _sorted_desc(summary, rs.COLLECTED_TRADES_LABEL)[:2] == [70, 5]


def _model(name: str, count: int | None, median: int | None, *, current: bool = False) -> SimpleNamespace:
    value = Decimal(median) if median is not None else None
    return SimpleNamespace(
        model=name, current=current, company="A사", trade_count=count, median=value, low=value, high=value,
        latest="2026-09-01", veterinary_count=0, parts_count=0, permit_number="제허 1", status="국내 정상", grade="2",
    )


def test_category_model_table_sorts_the_median_with_blanks_last() -> None:
    models = [_model("SJ-DFM100", 70, SMALL, current=True), _model("B2", 3, BIG), _model("C3", 0, None), _model("D4", None, None)]
    rows = cm.model_rows(models)
    _assert_numeric(rows, ["같은 제품 거래", "가운데 값(원)", "최저(원)", "최고(원)"])
    assert _sorted_desc(rows, "가운데 값(원)") == [BIG, SMALL, None, None]
    ascending = pd.DataFrame(rows).sort_values("가운데 값(원)")["가운데 값(원)"].tolist()
    assert ascending[:2] == [SMALL, BIG]  # blanks go last, not first
    assert [row["거래 자료 상태"] for row in rows] == ["", "", "나라장터 거래 없음", "조회 불가"]
    assert rows[0]["모델"] == "▶ SJ-DFM100"


def test_category_buyer_supplier_and_company_tables_are_numeric() -> None:
    def classified(price: int, quantity: str | None) -> SimpleNamespace:
        trade = SimpleNamespace(
            transaction_date="2026-09-01", institution="병원", model_label="M", quantity=Decimal(quantity) if quantity else None,
            unit="대", unit_price=Decimal(price), supplier="S", business_name="사업", source_record_id="delivery:R1|change:00|line:1",
        )
        return SimpleNamespace(trade=trade, kind=KIND_EQUIPMENT, is_equipment=True, reason="")

    rows, _picked = cm.buyer_rows([classified(SMALL, "2"), classified(BIG, "1.5"), classified(MID, None)])
    _assert_numeric(rows, ["수량", "1단위 가격(원)"])
    assert _sorted_desc(rows, "1단위 가격(원)") == [BIG, MID, SMALL]
    assert rows[1]["수량"] == 1.5 and rows[2]["수량"] is None and rows[0]["단위"] == "대"

    market = SimpleNamespace(
        suppliers=[
            SimpleNamespace(name="A", count=9, latest="2026-09-01", institutions=2, models=("M",)),
            SimpleNamespace(name="B", count=120, latest="2026-08-01", institutions=30, models=("M",)),
        ],
        companies=[
            SimpleNamespace(name="A사", model_count=9, traded_model_count=1, models=("M",), latest_permit="2020-01-01"),
            SimpleNamespace(name="B사", model_count=12, traded_model_count=10, models=("M",), latest_permit="2021-01-01"),
        ],
    )
    suppliers = cm.supplier_rows(market)
    _assert_numeric(suppliers, ["납품 건수", "구매 기관 수"])
    assert _sorted_desc(suppliers, "납품 건수") == [120, 9]
    companies = cm.company_rows(market)
    _assert_numeric(companies, ["등록 모델 수", "나라장터 거래가 있는 모델 수"])
    assert _sorted_desc(companies, "등록 모델 수") == [12, 9]


def test_reference_table_keeps_the_price_and_total_as_numbers() -> None:
    rows = rs.reference_table_rows([{**_trade(BIG, BIG), "수량": "1,000"}, _trade(None, SMALL, "")])
    _assert_numeric(rows, ["대당 단가", "총액", "수량"])
    assert rows[0]["수량"] == 1000 and rows[1]["총액"] is None


def test_number_column_config_formats_numbers_and_lets_overrides_win() -> None:
    rows = rs.trade_table_rows(TRADES)
    link = {"type_config": {"type": "link"}}
    config = nc.number_column_config(rows, {"나라장터": link})
    for column in ("거래 총액(원)", "수량", "1단위 가격(원)"):
        assert config[column]["type_config"]["type"] == "number"
        assert config[column]["type_config"]["format"] == "localized"
    assert config["나라장터"] is link
    assert "모델" not in config and "단위" not in config


# The st.dataframe call sites of the converted tables, each with a NumberColumn config.
DASHBOARD_TABLES = (
    "price_trend_ui.trend_rows(trend, unit=unit)",
    "result_summary_ui.year_summary_rows(direct_rows",
    "shown_groups = all_groups[",
    "result_summary_ui.trade_table_rows(direct_rows)",
    "result_summary_ui.reference_table_rows(reference_rows)",
    "supplier_table = result_summary_ui.supplier_summary_rows(procurement_suppliers)",
    "result_summary_ui.same_item_summary_rows(summary_view.rows)",
    "result_summary_ui.display_rows(full_view.rows)",
    "result_summary_ui.display_rows(view.rows)",
)


def _dataframe_calls(source: str) -> list[str]:
    calls = []
    for match in re.finditer(r"st\.dataframe\(", source):
        depth, end = 0, match.end() - 1
        for end in range(match.end() - 1, len(source)):
            depth += {"(": 1, ")": -1}.get(source[end], 0)
            if depth == 0:
                break
        calls.append(source[match.start() : end + 1])
    return calls


def test_every_converted_dashboard_table_passes_a_number_column_config() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")
    calls = _dataframe_calls(source)
    starts = [match.start() for match in re.finditer(r"st\.dataframe\(", source)]
    for anchor in DASHBOARD_TABLES:
        found = [match.start() for match in re.finditer(re.escape(anchor), source)]
        assert found, anchor
        for start in found:
            variable = re.match(r"\s*(\w+)\s*=", source[source.rindex("\n", 0, start) :])
            call = calls[next(i for i, at in enumerate(starts) if at > start)]
            assert "number_columns_ui.number_column_config(" in call, anchor
            if variable:
                assert variable.group(1) in call, (anchor, variable.group(1))
    assert source.count("supplier_table = result_summary_ui.supplier_summary_rows") == 2
    assert 'TextColumn("표기 금액' not in source and 'TextColumn("거래총액")' not in source


def test_category_market_tables_pass_a_number_column_config() -> None:
    source = Path("src/purchase_price/ui/category_market.py").read_text(encoding="utf-8")
    calls = _dataframe_calls(source)
    assert len(calls) == 4
    assert all("number_column_config(" in call for call in calls)
    assert 'TextColumn("가운데 값"' not in source and "거래 범위" not in source


def test_runtime_markers_reload_the_converted_modules() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")
    for name in ("same_item_compare", "result_summary", "price_trend", "category_market"):
        assert f'("purchase_price.ui.{name}", "NUMERIC_TABLES_V1")' in source
    assert '("purchase_price.ui.result_layout", "RESULT_LAYOUT_QUOTE_RULE_V1")' in source
    assert rs.NUMERIC_TABLES_V1 and same.NUMERIC_TABLES_V1 and pt.NUMERIC_TABLES_V1 and cm.NUMERIC_TABLES_V1
    assert rl.RESULT_LAYOUT_QUOTE_RULE_V1


# ── The three small fixes from the v1.1 closing test ──

FIXTURES = Path(__file__).parent / "fixtures" / "price"


def _result(name: str, quote: str) -> pm.PriceResult:
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    trades = [pm.PriceTrade.from_mapping(row) for row in data["trades"]]
    valid = [t for t in trades if t.entry_error_reason is None]
    return pm.build_price_result(
        trades,
        quote_unit_price=Decimal(quote),
        identity_confirmed=True,
        identity_exact=True,
        period_label="최근 3년",
        cutoff=date(2023, 10, 13),
        preferred_unit=pm.main_unit(valid),
        data_as_of="2026-10-10",
        today=date(2026, 10, 12),
    )


def test_quote_above_the_highest_trade_but_in_range_explains_both_rules() -> None:
    # 12,000,000원 against median 11,880,000 = highest trade: +1% is 거래 범위 안, the bar says 최고보다 높음.
    quote = Decimal("12000000")
    result = _result("many_single_unit", "12000000")
    assert result.comparison.status == pm.STATUS_IN_RANGE and quote > result.summary.high
    note = rl.quote_rule_note(result, quote=quote)
    assert "가운데 값 ±20% 기준" in note and "'최고보다 높음'" in note
    html = rl.comparison_status_html(result, quote_entered=True, quote=quote)
    assert '<span class="rl-status-note">' in html and "거래 범위 안 (조건 미확인)" in html
    rail = rl.price_rail_html(low=result.summary.low, high=result.summary.high, median=result.summary.median, quote=quote)
    assert "(최고보다 높음)" in rail
    # Inside the range there is nothing to explain; without a quote neither.
    assert rl.quote_rule_note(_result("many_single_unit", "11000000"), quote=Decimal("11000000")) == ""
    assert "rl-status-note" not in rl.comparison_status_html(result, quote_entered=False)


def test_quote_far_below_the_median_gets_the_unit_and_configuration_check() -> None:
    result = _result("many_single_unit", "5000000")
    assert result.comparison.status == pm.STATUS_CHECK
    note = rl.quote_rule_note(result, quote=Decimal("5000000"))
    # The same guidance as the 견적 검토 page (quote_review_layout / price_metrics.compare_quote).
    assert "단위·수량·구성(설치·옵션 포함 여부)이 거래와 같은지 확인하세요." in note
    assert note.startswith("가운데 값보다 20% 넘게 낮아 확인 필요로 표시했습니다.")
    html = rl.comparison_status_html(result, quote_entered=True, quote=Decimal("5000000"))
    assert "단위·수량·구성" in html
    high = _result("many_mixed_units", "6500000")
    assert high.comparison.status == pm.STATUS_CHECK and rl.quote_rule_note(high, quote=Decimal("6500000")) == ""


@pytest.mark.parametrize(
    "text",
    [
        rl.quote_rule_note(_result("many_single_unit", "12000000"), quote=Decimal("12000000")),
        rl.quote_rule_note(_result("many_single_unit", "5000000"), quote=Decimal("5000000")),
    ],
)
def test_new_sentences_use_no_judgement_words(text: str) -> None:
    assert text and not any(word in text for word in FORBIDDEN)
