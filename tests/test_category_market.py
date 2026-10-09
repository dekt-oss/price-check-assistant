from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from purchase_price.services import category_market as cm
from purchase_price.ui import category_market as ui


def _trade(
    price: str,
    *,
    business: str = "전신마취기 구매",
    institution: str = "가 병원",
    unit: str = "대",
    model: str = "수요기관규격",
    maker: str = "기타물품포함",
    date: str = "2026-03-01",
    supplier: str = "가 상사",
    spec: str = "",
    number: str = "R1",
) -> cm.CategoryTrade:
    return cm.CategoryTrade(
        source_record_id=f"delivery:{number}|change:00|line:1",
        raw_object_key="raw/key.json",
        transaction_date=date,
        institution=institution,
        manufacturer=maker,
        model_name=model,
        quantity=Decimal("1"),
        unit=unit,
        unit_price=Decimal(price),
        total_amount=Decimal(price),
        supplier=supplier,
        business_name=business,
        product_title="가스마취기, 기타물품포함, 수요기관규격",
        specification=spec,
        detail_code="4227250101",
    )


# ── Exclusion rules (the real 가스마취기 / 저출력심장충격기 wording) ──


def test_parts_and_repairs_are_not_equipment() -> None:
    for business in (
        "마취통증의학과 전신마취기의 New Flow Sensor 구입",
        "마취통증의학과 전신마취기의 예방점검(소모성 부품) 교체",
        "전신마취기의 pba Pressure/flow 교체수리",
        "자동심장충격기 소모품 구매",
    ):
        assert cm.classify_trade(_trade("486090", business=business)).kind == cm.KIND_PARTS, business
    # 나라장터 marks accessory lines "(부품)" in the specification.
    assert cm.classify_trade(_trade("396000", spec="(부품)스탠드형보관함")).kind == cm.KIND_PARTS


def test_exclusion_example_shows_the_text_that_matched() -> None:
    cabinet = _trade("396000", business="미래창업원 자동심장충격기(AED) 구매", spec="(부품)스탠드형보관함")
    market = cm.build_category_market([cabinet], product_name="저출력심장충격기")
    assert market.exclusions[0].examples == ("(부품)스탠드형보관함",)
    sensor = _trade("486090", business="New Flow Sensor 구입")
    assert cm.build_category_market([sensor], product_name="가스 마취기").exclusions[0].examples == (
        "New Flow Sensor 구입",
    )


def test_replacing_old_equipment_is_still_a_purchase() -> None:
    assert cm.classify_trade(_trade("90000000", business="노후 마취기 교체 구매")).kind == cm.KIND_EQUIPMENT


def test_veterinary_uses_are_not_hospital_prices() -> None:
    cases = (
        {"business": "의료기술시험연수원 동물용 마취기 구매"},
        {"business": "2026년 사육곰보호센터 대동물 마취기 구매"},
        {"business": "실험동물센터 장비 구매(호흡마취기)"},
        {"institution": "제주대학교 수의과대학"},
        {"institution": "전남대학교 동물병원"},
        {"business": "가스마취기 WATO EX-20Vet AG Module 구입"},
        {"business": "동물용 마취시스템(Veterinary anesthesia workstation)"},
    )
    for case in cases:
        assert cm.classify_trade(_trade("9700000", **case)).kind == cm.KIND_VETERINARY, case


def test_words_that_only_contain_animal_syllables_are_not_veterinary() -> None:
    # Real 사업명/기관 that a bare "동물"/"수의" match flagged by mistake.
    for case in (
        {"business": "2026년 주민지원사업 마을공동물품(심장충격기,보관함) 조달 구입"},
        {"business": "(소액수의) 서부정비창 운용장비(의료기기) 구매"},
        {"institution": "의료법인 성수의료재단(비에스종합병원)"},
        {"business": "velvet 커버 구입"},
    ):
        assert cm.classify_trade(_trade("1980000", **case)).kind != cm.KIND_VETERINARY, case


def test_machine_units_count_as_one_unit_and_other_units_stay_out_of_the_price() -> None:
    trades = [
        _trade("90000000", unit="대", number="A"),
        _trade("93000000", unit="SET", number="B"),
        _trade("95000000", unit="세트", number="C"),
        _trade("97000000", unit="식", number="D"),
        _trade("1000", unit="box", number="E"),
    ]
    rows, unit = cm.classify_trades(trades)
    assert unit == cm.MACHINE_UNIT
    kinds = {row.trade.source_record_id[9]: row.kind for row in rows}
    assert kinds == {"A": "equipment", "B": "equipment", "C": "equipment", "D": "equipment", "E": "other_unit"}


def test_prices_three_times_away_from_the_middle_leave_only_the_price_level() -> None:
    trades = [_trade(price, number=str(index)) for index, price in enumerate(("90000000", "94000000", "97500000", "100000000"))]
    trades.append(_trade("310800000", business="3모터 전동침대 등 6종 (3분류)", number="X"))
    market = cm.build_category_market(trades, product_name="가스 마취기")
    gap = [row for row in market.trades if row.kind == cm.KIND_PRICE_GAP]
    assert [row.trade.business_name for row in gap] == ["3모터 전동침대 등 6종 (3분류)"]
    assert market.level.count == 4 and market.level.high == Decimal("100000000")
    # Still an equipment purchase: listed as 도입 기관 and counted for its supplier.
    assert len(market.equipment) == 5


def test_price_rule_needs_enough_rows() -> None:
    rows, _unit = cm.classify_trades([_trade("1000000", number="1"), _trade("90000000", number="2")])
    assert all(row.kind == cm.KIND_EQUIPMENT for row in rows)


# ── Stats and ordering ──


def test_price_level_and_years_use_counted_equipment_only() -> None:
    trades = [
        _trade("90000000", date="2025-10-21", number="1"),
        _trade("100000000", date="2026-03-04", number="2"),
        _trade("110000000", date="2026-06-16", number="3"),
        _trade("486090", business="New Flow Sensor 구입", date="2026-07-01", number="4"),
        _trade("9700000", business="동물용 마취기 구매", date="2026-08-03", number="5"),
    ]
    market = cm.build_category_market(trades, product_name="가스 마취기")
    assert market.level.count == 3
    assert market.level.median == Decimal("100000000")
    assert (market.level.first_date, market.level.latest_date) == ("2025-10-21", "2026-06-16")
    assert [(year.year, year.count, year.median) for year in market.years] == [
        ("2026", 2, Decimal("105000000")),
        ("2025", 1, Decimal("90000000")),
    ]
    assert {item.kind: item.count for item in market.exclusions} == {"parts": 1, "veterinary": 1}
    # Newest first.
    assert [row.trade.transaction_date for row in market.trades][0] == "2026-08-03"


def test_unstated_models_are_labelled_and_named_models_keep_the_maker() -> None:
    assert _trade("1").model_label == cm.UNSTATED_MODEL_LABEL
    assert _trade("1", maker="Datex-ohmeda", model="Carestation 750").model_label == "Datex-ohmeda Carestation 750"


def test_suppliers_are_ordered_by_deliveries_then_latest() -> None:
    trades = [
        _trade("90000000", supplier="동부의료기", date="2026-02-20", number="1"),
        _trade("91000000", supplier="동부의료기", date="2025-10-28", number="2"),
        _trade("92000000", supplier="수도헬스케어", maker="Datex-ohmeda", model="Carestation 750", date="2025-11-14", number="3"),
        _trade("93000000", supplier="조은메디칼", date="2026-08-06", number="4"),
        _trade("486090", supplier="부품상사", business="센서 구입", number="5"),
    ]
    market = cm.build_category_market(trades, product_name="가스 마취기")
    assert [item.name for item in market.suppliers] == ["동부의료기", "조은메디칼", "수도헬스케어"]
    assert market.suppliers[0].models == ("모델 미기재 2건",)
    assert market.suppliers[2].models == ("Datex-ohmeda Carestation 750",)


@dataclass(frozen=True)
class _Record:
    permit_number: str
    model_name: str
    registered_company: str
    grade: str = "3"
    permit_date: str = "2021-08-02"
    product_name: str = "가스 마취기"


def _link(model: str, permit: str, company: str, count: int | None, price: str = "", latest: str = "", current: bool = False):
    return {
        "모델": model,
        "식약처 품목번호": permit,
        "품목 책임주체": company,
        "나라장터 직접거래": count,
        "나라장터 가격범위": price,
        "최근거래": latest,
        "현재 모델": "현재 모델" if current else "",
    }


def test_models_with_trades_come_first_and_every_registered_model_is_listed() -> None:
    links = [
        _link("Flow-c", "수허 21-193 호", "(주)게팅게메디칼코리아", 0, current=True),
        _link("Aisys CS2", "수허 06-1203 호", "지이헬스케어코리아(주)", 0),
        _link("Carestation 750", "수허 21-125 호", "지이헬스케어코리아(주)", 1, "43,500,000 ~ 43,500,000원", "2025-11-14"),
        _link("9100c NXT", "수허 17-398 호", "지이헬스케어코리아(주)", 1, "108,300,000 ~ 108,300,000원", "2026-07-31"),
        _link("Broken", "수허 1", "X사", None),
    ]
    records = [_Record("수허 21-193 호", "Flow-c", "(주)게팅게메디칼코리아", grade="3")]
    vet = _trade(
        "108300000",
        business="수의과대학 실험실습기자재(가스마취기 등 5종) 구매",
        maker="GE medical systems",
        model="9100cNXT",
        number="V",
    )
    market = cm.build_category_market(
        [vet],
        product_name="가스 마취기",
        crosslinks=links,
        identity_records=records,
        model_medians={("수허21-193호", "flowc"): Decimal("1")},
        status_labels={"수허21-193호": "국내 정상(품목)"},
    )
    names = [model.model for model in market.models]
    assert names[:2] == ["9100c NXT", "Carestation 750"]
    assert set(names) == {"Flow-c", "Aisys CS2", "Carestation 750", "9100c NXT", "Broken"}
    nine = market.models[0]
    assert nine.veterinary_count == 1 and nine.low == Decimal("108300000")
    flow = next(model for model in market.models if model.model == "Flow-c")
    # No trade: no price even if a median was passed, but grade and status are kept.
    assert flow.current and flow.median is None and flow.grade == "3" and flow.status == "국내 정상(품목)"
    rows = ui.model_rows(market.models)
    assert rows[0]["참고"] == "동물용 구매 1건 포함"
    by_model = {row["모델"]: row for row in rows}
    assert by_model["▶ Flow-c"]["같은 제품 거래"] == "나라장터 거래 없음"
    assert by_model["▶ Flow-c"]["허가 상태"] == "판매 가능(허가 기준)"
    assert by_model["Broken"]["같은 제품 거래"] == "조회 불가"
    assert market.traded_models == 2
    assert [company.name for company in market.companies][0] == "지이헬스케어코리아(주)"


def test_model_detail_codes_ignore_a_code_used_once() -> None:
    assert cm.model_detail_codes({"4227250101": 9, "4214250201": 1}) == ("4227250101",)
    assert cm.model_detail_codes({}) == ()
    assert cm.is_veterinary_class("동물용가스마취기")


def test_identity_from_same_product_needs_exactly_one_registration() -> None:
    one = [_Record("수허 21-193 호", "Flow-c", "G사"), _Record("수허 21-193 호", "Flow-c", "G사")]
    assert len(cm.identity_from_same_product(one, "FLOW-C")) == 2
    two = [_Record("수허 1", "M40", "A사"), _Record("제허 2", "M40", "B사")]
    assert cm.identity_from_same_product(two, "M40") == ()
    assert cm.identity_from_same_product(one, "") == ()


# ── Screen ──


def _market() -> cm.CategoryMarket:
    trades = [
        _trade("90000000", number="1", date="2026-02-01"),
        _trade("100000000", number="2", date="2026-03-04"),
        _trade("110000000", number="3", date="2026-06-16"),
        _trade("486090", business="New Flow Sensor 구입", number="4"),
    ]
    codes = (cm.DetailCode("4227250101", "가스마취기"),)
    return cm.build_category_market(trades, product_name="가스 마취기", codes=codes, data_as_of="2026-10-05")


def test_headline_names_the_searched_model_and_the_category() -> None:
    market = _market()
    assert ui.headline_text(market, searched_model="Flow-c") == (
        "Flow-c의 나라장터 거래는 없지만, 같은 품목(가스 마취기) 장비 구매가 3건 있습니다"
    )
    assert "다른 모델까지" in ui.headline_text(market, searched_model="Carestation 750", has_direct=True)
    assert ui.headline_text(market) == "가스 마취기 장비 구매가 나라장터에 3건 있습니다"
    basis = ui.basis_text(market)
    assert "가스마취기(4227250101) 거래 4건 중 부품·수리·동물용 1건을 뺀 수" in basis
    assert "2026-10-05 수집분" in basis


def test_summary_shows_price_level_rules_and_exclusions() -> None:
    html = ui.summary_html(_market(), searched_model="Flow-c")
    assert "1대 가운데 값 (참고 시세)" in html and "100,000,000원" in html
    assert "계산에서 뺀 거래" in html and "부품·수리 1건" in html
    assert cm.RULE_NOTE.split("'")[0] in html
    assert "연도별 시세" in html and "최근 장비 구매" in html
    assert 'id="category-market-v1"' in html
    # Hidden-marker CSS collapses rows with ids starting "purchase-"; this block must not use them.
    assert 'id="purchase-' not in html


def test_empty_category_says_so_instead_of_inventing_a_price() -> None:
    market = cm.build_category_market([], product_name="가스 마취기", crosslinks=[_link("Flow-c", "수허 1", "G사", 0)])
    assert "아직 없습니다" in ui.headline_text(market, searched_model="Flow-c")
    assert "계산 안 됨" in ui.metric_cards_html(market)


def test_buyer_rows_show_unstated_models_and_open_the_original() -> None:
    market = _market()
    rows, trades = ui.buyer_rows(market.trades)
    assert len(rows) == 3 and rows[0]["모델"] == "모델 미기재"
    assert rows[0]["나라장터"].startswith("https://")
    all_rows, _ = ui.buyer_rows(market.trades, include_excluded=True)
    assert any(row["구분"].startswith("부품·수리") for row in all_rows)
    dialog = ui.trade_dialog_row(trades[0].trade)
    assert dialog["원천기록"].startswith("delivery:") and dialog["가격"] == "110,000,000원"


def test_tab_labels_keep_the_same_item_wording() -> None:
    labels = ui.tab_labels(_market())
    assert labels[0].startswith("같은 품목의 다른 모델") and labels[1] == "도입 기관 3건"


def test_screen_text_has_no_banned_terms() -> None:
    from purchase_price.ui import result_summary as rs

    html = ui.summary_html(_market(), searched_model="Flow-c")
    assert rs.has_banned_term(html) is None
    assert rs.has_banned_term(cm.RULE_NOTE) is None


def test_dashboard_wires_the_view_into_result_overview_and_handoff() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")
    assert "market_main = bool(category_market is not None and not any_direct" in source
    assert "_render_category_market(market, key=f\"overview::{heading}\", records=records)" in source
    assert "section_heading=True" in source
    assert "_open_model_from_overview(model.model, identity_token=token)" in source
    assert "on_open_trade=_open_trade_dialog" in source
    assert "render_company_lookup=_render_business_license_lookup" in source
    assert 'search_timings["category_market"]' in source
    assert "identity_from_same_product" in source and "_retry_model_identity" in source
