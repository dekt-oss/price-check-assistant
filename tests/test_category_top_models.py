"""P3b: who sold most - top_models (service) and top_models_html (screen)."""

from __future__ import annotations

import dataclasses
import re
from decimal import Decimal

from purchase_price.services import category_market as cm
from purchase_price.ui import category_market as ui

BANNED = ("인기", "대표", "추천", "우수", "적정")


def _trade(
    model: str,
    *,
    maker: str = "나눔",
    price: str = "1000000",
    institution: str = "가 병원",
    unit: str = "대",
    date: str = "2026-03-01",
    number: str = "1",
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
        supplier="가 상사",
        business_name="저출력심장충격기 구매",
        product_title="저출력심장충격기",
        specification="",
        detail_code="4217210101",
    )


def _market(trades: list, **kwargs) -> cm.CategoryMarket:
    rows = tuple(
        row if isinstance(row, cm.ClassifiedTrade) else cm.ClassifiedTrade(row, cm.KIND_EQUIPMENT) for row in trades
    )
    return cm.CategoryMarket(status="success", product_name="저출력심장충격기", trades=rows, **kwargs)


def _numbered(items: list[cm.CategoryTrade]) -> list[cm.CategoryTrade]:
    return [
        dataclasses.replace(trade, source_record_id=f"delivery:{index}|change:00|line:1")
        for index, trade in enumerate(items)
    ]


def test_marker_is_set() -> None:
    assert cm.CATEGORY_MARKET_TOP_MODELS_V1 is True and ui.CATEGORY_MARKET_TOP_MODELS_V1 is True


def test_groups_by_maker_and_model_and_counts_rows_and_institutions() -> None:
    market = _market(
        [
            _trade("NT-381.B", institution="가 병원"),
            _trade("NT-381.B", institution="나 병원", date="2026-04-01"),
            _trade("nt 381.b", institution="가 병원", date="2026-02-01"),  # same key after normalize_text
            _trade("NT-381.B", maker="다른", institution="다 병원"),  # other maker = other group
        ]
    )
    top = cm.top_models(market, by="trades")
    assert [(m.label, m.trade_count, m.institution_count) for m in top] == [
        ("나눔 NT-381.B", 3, 2),
        ("다른 NT-381.B", 1, 1),
    ]
    assert top[0].latest == "2026-04-01" and top[0].model_name == "NT-381.B" and top[0].manufacturer == "나눔"


def test_only_equipment_rows_with_a_stated_model_count() -> None:
    rows = [
        cm.ClassifiedTrade(_trade("A-1"), cm.KIND_EQUIPMENT),
        cm.ClassifiedTrade(_trade("A-1"), cm.KIND_PARTS),
        cm.ClassifiedTrade(_trade("A-1"), cm.KIND_VETERINARY),
        cm.ClassifiedTrade(_trade("A-1"), cm.KIND_ENTRY_ERROR),
        cm.ClassifiedTrade(_trade("A-1"), cm.KIND_OTHER_UNIT),
        cm.ClassifiedTrade(_trade("A-1"), cm.KIND_PRICE_GAP),
        cm.ClassifiedTrade(_trade("수요기관규격", maker="기타물품포함"), cm.KIND_EQUIPMENT),
        cm.ClassifiedTrade(_trade("", maker=""), cm.KIND_EQUIPMENT),
    ]
    top = cm.top_models(_market(rows), by="trades")
    assert [(m.label, m.trade_count) for m in top] == [("나눔 A-1", 1)]
    assert all(m.label != cm.UNSTATED_MODEL_LABEL for m in top)


def test_orderings_and_tie_breaks() -> None:
    trades = (
        [_trade("T-many", institution="가", date=f"2026-01-0{day}") for day in (1, 2, 3)]
        + [_trade("I-wide", institution=name, date="2026-02-01") for name in ("가", "나")]
        + [_trade("Z-same", institution=name, date="2026-02-01") for name in ("가", "나")]
        + [_trade("B-late", institution=name, date="2026-05-01") for name in ("가", "나")]
    )
    market = _market(_numbered(trades))
    by_trades = [m.model_name for m in cm.top_models(market, by="trades")]
    # T-many has 3 rows; the 2-row models tie on rows and institutions -> latest desc, then label
    assert by_trades == ["T-many", "B-late", "I-wide", "Z-same"]
    by_inst = [m.model_name for m in cm.top_models(market, by="institutions")]
    # 2 institutions beat T-many's 1, even though T-many has more rows
    assert by_inst == ["B-late", "I-wide", "Z-same", "T-many"]
    assert [m.model_name for m in cm.top_models(market, by="trades", limit=2)] == ["T-many", "B-late"]


def test_unknown_sort_is_rejected() -> None:
    try:
        cm.top_models(_market([_trade("A")]), by="price")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_institution_names_ignore_spaces_and_brackets_but_are_not_merged_by_similarity() -> None:
    market = _market(
        [
            _trade("A-1", institution="서울 대학교 병원"),
            _trade("A-1", institution="서울대학교병원"),
            _trade("A-1", institution="(재)서울대학교병원"),
            _trade("A-1", institution="서울대학교 치과병원"),
            _trade("A-1", institution="  "),
            _trade("A-1", institution=""),
        ]
    )
    (model,) = cm.top_models(market, by="trades")
    assert model.trade_count == 6
    # 서울대학교병원 and 서울대학교치과병원; "(재)" is a prefix, not a bracket-only difference
    assert model.institution_count == 3
    assert cm.institution_key("서울 (대학교) 병원") == "서울대학교병원"


def test_median_uses_only_the_main_unit_group() -> None:
    market = _market(
        [
            _trade("A-1", price="1000000", unit="대"),
            _trade("A-1", price="3000000", unit="SET"),  # same group as 대
            _trade("A-1", price="5000000", unit="식"),
            _trade("A-1", price="10", unit="개"),  # other unit group: counted as a row, not in the median
            _trade("B-2", price="777", unit="개"),
        ]
    )
    top = {m.model_name: m for m in cm.top_models(market, by="trades")}
    assert top["A-1"].trade_count == 4 and top["A-1"].median == Decimal("3000000") and top["A-1"].unit == "대"
    assert top["B-2"].median is None and top["B-2"].unit == ""


def test_empty_market_has_no_top_models() -> None:
    assert cm.top_models(_market([]), by="trades") == ()
    assert ui.top_models_html(_market([_trade("수요기관규격", maker="기타물품포함")]), searched_model="A") == ""


def test_searched_model_key_is_normalized_equality() -> None:
    assert cm.searched_model_key("NT-381.B") == cm.searched_model_key(" nt 381.b ")
    assert cm.searched_model_key("NT-381") != cm.searched_model_key("NT-381.B")
    assert cm.searched_model_key("") == ""


def _wide_market() -> cm.CategoryMarket:
    trades: list[cm.CategoryTrade] = []
    for index in range(7):  # M0..M6, M0 most traded
        for n in range(7 - index):
            trades.append(_trade(f"M{index}", institution=f"기관{index}-{n}", price=f"{1000000 + index}"))
    trades.append(_trade("RARE-1", maker="희귀", institution="기관 X", price="2200000", date="2026-06-01"))
    return _market(_numbered(trades), period_label="최근 3년", period_start="2023-10-10")


def test_html_marks_the_searched_model_and_shows_numbers() -> None:
    html = ui.top_models_html(_wide_market(), searched_model="m0")
    assert 'id="category-top-models-v1"' in html
    assert "거래 건수가 많은 모델" in html and "납품 기관이 많은 모델" in html
    assert "▶ 나눔 M0" in html and "cm-top-me" in html
    assert "7건 · 납품 기관 7곳 · 1대당 가운데 값 1,000,000원" in html
    assert "최근 3년(2023-10-10 이후)" in html
    assert "많이 거래된 순서일 뿐 품질이나 권장 순위가 아닙니다." in html
    assert "검색한 모델:" not in html  # it is already in the lists
    assert html.count('<li class="cm-top-row') <= 10
    assert "나눔 M6" not in html and "나눔 M5" not in html  # only the top 5 rows of each list


def test_html_adds_an_extra_line_when_the_searched_model_is_outside_the_top_five() -> None:
    html = ui.top_models_html(_wide_market(), searched_model="RARE-1")
    assert "▶ 검색한 모델: 희귀 RARE-1 · 1건 · 납품 기관 1곳 · 1대당 가운데 값 2,200,000원" in html
    assert "cm-top-me" not in html.split('class="cm-top-grid"')[1]  # no list row is highlighted
    # a searched model without equipment trades adds nothing
    assert "검색한 모델" not in ui.top_models_html(_wide_market(), searched_model="NOPE-9")
    assert "검색한 모델" not in ui.top_models_html(_wide_market())


def test_html_omits_the_price_part_without_a_median_and_escapes_text() -> None:
    market = _market([_trade("<b>X</b>", maker="A&B", unit="")])
    html = ui.top_models_html(market, searched_model="")
    assert "가운데 값" not in html
    assert "&lt;b&gt;X&lt;/b&gt;" in html and "<b>X</b>" not in html and "A&amp;B" in html


def test_html_uses_no_verdict_words() -> None:
    for searched in ("M0", "RARE-1", ""):
        html = ui.top_models_html(_wide_market(), searched_model=searched)
        text = re.sub(r"<[^>]+>", " ", html)
        for word in BANNED:
            assert word not in text, word
        assert text.count("권장") == text.count("권장 순위가 아닙니다") >= 1
