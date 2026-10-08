from decimal import Decimal
from types import SimpleNamespace

from purchase_price.ui import result_summary as rs


def _stats(direct=0, low=None, mid=None, high=None, references=0, latest=None):
    return SimpleNamespace(
        direct_count=direct,
        reference_count=references,
        min_price=Decimal(low) if low is not None else None,
        median_price=Decimal(mid) if mid is not None else None,
        max_price=Decimal(high) if high is not None else None,
        latest_transaction_date=latest,
    )


def _all_text(conclusion: rs.Conclusion) -> str:
    return " ".join(
        part for part in (conclusion.headline, conclusion.detail, conclusion.quote_line, conclusion.caveat) if part
    )


def test_many_trades_reports_median_range_and_quote_position():
    stats = _stats(93, "297000", "1980000", "1980000", latest="2026-10-01")
    conclusion = rs.build_conclusion(stats, quote_unit_price=Decimal("2100000"))

    assert "93번 거래" in conclusion.headline
    assert "1,980,000원" in conclusion.headline
    assert conclusion.detail == "거래가 297,000원 ~ 1,980,000원 · 최근 거래 2026-10-01"
    assert "중앙값보다 6.1% 높습니다" in conclusion.quote_line
    assert "가장 높은 값보다도 높습니다" in conclusion.quote_line
    assert conclusion.caveat and "조건이 같은지는 확인하지 않은" in conclusion.caveat
    assert conclusion.band is not None and conclusion.band.quote == Decimal("2100000")


def test_quote_inside_range_and_below_median():
    stats = _stats(10, "1000", "2000", "3000")
    conclusion = rs.build_conclusion(stats, quote_unit_price=Decimal("1500"))
    assert "중앙값보다 25.0% 낮습니다" in conclusion.quote_line
    assert "범위 안" in conclusion.quote_line


def test_no_direct_trades_never_computes_a_position():
    conclusion = rs.build_conclusion(_stats(0, references=12), quote_unit_price=Decimal("5000"))
    assert conclusion.headline == "같은 제품으로 확인된 나라장터 거래가 없습니다."
    assert "12건" in conclusion.detail and "가격 비교에 넣지 않았습니다" in conclusion.detail
    assert conclusion.quote_line == "같은 제품 거래가 없어 견적 위치를 계산하지 않았습니다."
    assert conclusion.band is None
    assert conclusion.caveat is None


def test_unavailable_index_is_a_warning_not_zero():
    conclusion = rs.build_conclusion(_stats(0), quote_unit_price=None, unavailable=True)
    assert conclusion.tone == rs.TONE_WARN
    assert "연결하지 못해" in conclusion.headline
    assert conclusion.quote_line is None


def test_one_trade_lists_the_price_and_says_it_is_not_enough():
    conclusion = rs.build_conclusion(_stats(1, "1000", "1000", "1000"), quote_unit_price=Decimal("1100"))
    assert "1건이고, 1,000원" in conclusion.headline
    assert "10.0% 높습니다" in conclusion.quote_line
    assert "부족합니다" in conclusion.quote_line
    assert conclusion.band is None


def test_two_trades_show_both_prices_without_a_band():
    conclusion = rs.build_conclusion(_stats(2, "1000", "1500", "2000"), quote_unit_price=Decimal("2500"))
    assert "1,000원과 2,000원" in conclusion.headline
    assert conclusion.band is None
    assert "부족합니다" in conclusion.quote_line


def test_identical_prices_do_not_draw_a_band():
    conclusion = rs.build_conclusion(_stats(5, "700", "700", "700"), quote_unit_price=None)
    assert "모두 700원이었습니다" in conclusion.headline
    assert conclusion.band is None


def test_conclusion_never_judges_fairness_or_uses_developer_words():
    cases = [
        rs.build_conclusion(_stats(93, "297000", "1980000", "1980000"), quote_unit_price=Decimal("1")),
        rs.build_conclusion(_stats(1, "1", "1", "1"), quote_unit_price=Decimal("1")),
        rs.build_conclusion(_stats(0, references=3), quote_unit_price=Decimal("1")),
        rs.build_conclusion(_stats(0), quote_unit_price=None, unavailable=True),
    ]
    for conclusion in cases:
        text = _all_text(conclusion)
        assert "적정" not in text
        assert rs.has_banned_term(text) is None


def test_band_html_places_quote_outside_range_on_the_axis():
    band = rs.PriceBand(low=Decimal("100"), high=Decimal("200"), median=Decimal("150"), quote=Decimal("300"))
    markup = rs.render_price_band_html(band)
    assert 'class="pr-mark" style="left:100.00%"' in markup
    assert "내 견적 300원" in markup
    assert "최저 100원" in markup and "최고 200원" in markup


def test_display_rows_relabels_headers_and_statuses_only():
    rows = rs.display_rows([{"품목 책임주체": "A", "식약처 상태": "국내 정상", "모델": "X"}])
    assert rows == [{"제조·수입업체(식약처)": "A", "판매 상태": "판매 가능", "모델": "X"}]


def test_price_group_summary_hides_model_column_for_a_single_model():
    groups = [
        {"모델": "M", "규격": "s", "거래조건": "c", "거래건수": 2, "최저단가": "1원", "중앙값": "1원", "최고단가": "1원", "최근거래일": "d"},
        {"모델": "M", "규격": "t", "거래조건": "c", "거래건수": 9, "최저단가": "2원", "중앙값": "2원", "최고단가": "2원", "최근거래일": "e"},
    ]
    rows = rs.price_group_summary_rows(groups)
    assert "모델" not in rows[0]
    assert rows[0]["건수"] == 9

    groups[1]["모델"] = "N"
    assert "모델" in rs.price_group_summary_rows(groups)[0]


def test_same_item_summary_keeps_searched_model_first_and_fills_company():
    view_rows = [
        {"품목 책임주체": "A사", "모델": "Other", "나라장터 거래": "40건", "가격범위": "", "최근거래": ""},
        {"품목 책임주체": "", "모델": "▶ Mine", "나라장터 거래": "3건", "가격범위": "", "최근거래": ""},
        {"품목 책임주체": "B사", "모델": "Third", "나라장터 거래": "90건", "가격범위": "", "최근거래": ""},
    ]
    rows = rs.same_item_summary_rows(view_rows)
    assert [row["모델"] for row in rows] == ["▶ Mine", "Third", "Other"]
    assert rows[0]["제조·수입업체"] == "A사"


def test_overview_rows_sort_by_trades_and_cap_at_limit():
    crosslinks = [
        {"모델": f"M{i}", "품목 책임주체": "A", "나라장터 직접거래": i, "나라장터 가격범위": "", "최근거래": ""}
        for i in range(15)
    ]
    rows = rs.overview_model_rows(crosslinks)
    assert len(rows) == rs.OVERVIEW_ROW_LIMIT
    assert rows[0]["모델"] == "M14"
    assert rows[0]["같은 제품 거래"] == "14건"


def test_quote_item_rows_mark_unopened_items():
    items = [
        SimpleNamespace(product_name="심장충격기", model_name="DFM100", unit_price=Decimal("12000000")),
        SimpleNamespace(product_name="소모품", model_name=None, unit_price=None),
    ]
    results = {0: {"median_price": Decimal("10000000"), "direct_count": 8}}
    rows = rs.quote_item_rows(items, results)
    assert rows[0]["중앙값 대비"] == "+20.0%"
    assert rows[0]["상태"] == "확인됨"
    assert rows[1]["중앙값 대비"] == "선택하면 조사"
    assert rows[1]["견적 단가"] == "미확인"


def test_short_basis_line():
    line = rs.short_basis_line(
        track_b_data_as_of="2026-09-18",
        live_checked_until="2026-10-06",
        mfds_coverage_percent=53.4,
    )
    assert line == (
        "자료 기준 · 나라장터 2026-09-18 수집분 + 2026-10-06까지 실시간 확인 · "
        "식약처 자료 53% 수집 중이라 빠진 모델이 있을 수 있음"
    )


def _cand(unit, price):
    return SimpleNamespace(unit=unit, price=Decimal(price))


def test_split_by_main_unit_keeps_unknown_units_and_separates_sets():
    candidates = [_cand("대", "4400000")] * 15 + [_cand(None, "4389000"), _cand("set", "36513000"), _cand("SET", "30000000")]
    split = rs.split_by_main_unit(candidates)
    assert split.main_unit == "대"
    assert len(split.kept) == 16 and len(split.other) == 2
    assert split.other_units == ("set",)
    assert "1세트가 몇 대인지는 원문에 없어" in rs.unit_note(split)

    single = rs.split_by_main_unit([_cand("대", "1"), _cand(None, "2")])
    assert not single.mixed and single.main_unit == "대" and rs.unit_note(single) is None


def test_conclusion_names_the_unit():
    stats = _stats(15, "4400000", "4400000", "6585500")
    conclusion = rs.build_conclusion(stats, quote_unit_price=None, unit="대")
    assert "1대당 가운데 값(중앙값)은 4,400,000원" in conclusion.headline
    assert conclusion.detail.startswith("1대당 거래가 4,400,000원 ~ 6,585,500원")
    assert "1 set당 " == rs.per_unit_label("set")


def test_trade_rows_show_total_quantity_then_unit_price():
    rows = [{"거래일": "2026-09-28", "모델": "M40", "가격": "36,513,000원", "총액": "73,026,000원", "수량": "2", "단위": "set", "거래조건": "총액계약", "판매처": "세명", "구매처": "비에스", "규격": "미확인"}]
    table = rs.trade_table_rows(rows)
    assert list(table[0])[:5] == ["거래일", "모델", "거래 총액", "수량", "1단위 가격"]
    assert table[0]["거래 총액"] == "73,026,000원"
    assert table[0]["수량"] == "2 set"
    assert table[0]["1단위 가격"] == "36,513,000원 / set"
    assert rs.trade_amount_line(rows[0]) == "73,026,000원 ÷ 2 set = 1 set당 36,513,000원"


def test_unit_groups_never_mix_units():
    rows = [
        {"모델": "M40", "가격": "4,400,000원", "총액": "8,800,000원", "수량": "2", "단위": "대", "거래조건": "납품요구", "거래일": "2026-09-21"},
        {"모델": "M40", "가격": "4,400,000원", "총액": "4,400,000원", "수량": "1", "단위": "대", "거래조건": "납품요구", "거래일": "2026-09-01"},
        {"모델": "M40", "가격": "36,513,000원", "총액": "73,026,000원", "수량": "2", "단위": "set", "거래조건": "총액계약", "거래일": "2026-09-28"},
    ]
    groups = rs.unit_group_rows(rows)
    assert [g["단위"] for g in groups] == ["대", "set"]
    assert groups[0]["총수량"] == "3 대"
    assert groups[0]["거래 총액 합계"] == "13,200,000원"
    assert groups[0]["1단위 중앙값"] == "4,400,000원"
    assert groups[1]["1단위 최저~최고"] == "36,513,000원"


def test_unit_groups_merge_case_variants_of_one_unit():
    rows = [
        {"모델": "M40", "가격": "4,747,080원", "총액": "37,976,640원", "수량": "8", "단위": "SET", "거래조건": "총액계약", "거래일": "2026-09-28"},
        {"모델": "M40", "가격": "36,513,000원", "총액": "73,026,000원", "수량": "2", "단위": "set", "거래조건": "총액계약", "거래일": "2026-09-28"},
    ]
    groups = rs.unit_group_rows(rows)
    assert len(groups) == 1
    assert groups[0]["단위"] == "SET"
    assert groups[0]["총수량"] == "10 SET"
