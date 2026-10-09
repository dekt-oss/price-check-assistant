"""Result screen blocks (design steps 2–3): check points, conclusion card, price rail, chips."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from purchase_price.ui import result_layout as rl
from purchase_price.ui import result_summary as rs


def _stats(direct=0, low=None, mid=None, high=None, latest=None):
    return SimpleNamespace(
        direct_count=direct,
        reference_count=0,
        min_price=Decimal(low) if low is not None else None,
        median_price=Decimal(mid) if mid is not None else None,
        max_price=Decimal(high) if high is not None else None,
        latest_transaction_date=latest,
    )


def _rows(names: list[str]) -> list[dict[str, object]]:
    return [{"사업명": name, "가격": "1,000원"} for name in names]


def _text(markup: str) -> str:
    return re.sub(r"<[^>]+>", "", markup)


# ── 최종 판단 전에 확인하세요 ──


def test_bundle_words_in_business_names_are_counted_once_per_trade():
    matched, total, words = rl.bundle_keyword_hits(
        _rows(["2026 특수구급차 조달 구매", "구급차 장비 보강 사업", "보건소 심장충격기 구입", ""])
    )
    assert (matched, total) == (2, 4)
    # "구급차" covers "구급"; both rows name it, the second also 보강.
    assert words[0] == "구급차" and "구급" not in words


def test_check_points_flag_bundles_few_trades_outliers_units_and_live_failure():
    points = rl.check_points(
        _rows(["구급차 장비 보강 사업", "응급의료 지원사업"]),
        direct_count=2,
        other_unit_count=1,
        other_units=("set",),
        main_unit="대",
        outlier_count=1,
        live_failed=True,
    )
    texts = [point.text for point in points]
    assert any("2건뿐이라 가격대를 판단하기에는 부족" in text for text in texts)
    bundle = next(point for point in points if "사업명" in point.text)
    assert "비교 거래 2건 중 2건(100%)" in bundle.text and bundle.tone == rl.TONE_WARN
    assert any("3배 넘게 다른 거래가 1건" in text for text in texts)
    assert any("단위가 다른 거래 1건(set)은 대 단위 가격에 섞지 않고" in text for text in texts)
    live = next(text for text in texts if "실시간 확인에 실패" in text)
    # A failed live check is never reported as zero trades.
    assert "0건" not in live


def test_a_small_bundle_share_is_information_not_a_warning():
    rows = _rows(["응급실 장비 구입"] + ["보건소 구입"] * 9)
    points = rl.check_points(rows, direct_count=10)
    assert len(points) == 1
    assert points[0].tone == rl.TONE_INFO and "10건 중 1건(10%)" in points[0].text


def test_nothing_to_flag_is_said_plainly():
    points = rl.check_points(_rows(["보건소 구입"] * 5), direct_count=5)
    assert points == []
    panel = _text(rl.check_panel_html(points))
    assert "최종 판단 전에 확인하세요" in panel
    assert "눈에 띄는 점 없음" in panel
    assert "따로 확인할 점을 찾지 못했습니다" in panel
    assert rl.GENERAL_CHECK in panel


def test_panel_counts_only_warnings_in_its_pill():
    points = [rl.CheckPoint(rl.TONE_WARN, "a"), rl.CheckPoint(rl.TONE_INFO, "b")]
    assert "확인할 점 1가지" in rl.check_panel_html(points)


def test_unavailable_and_zero_trade_states():
    unavailable = rl.check_points([], direct_count=0, unavailable=True)
    assert len(unavailable) == 1 and "연결하지 못했습니다" in unavailable[0].text
    zero = rl.check_points([], direct_count=0)
    assert zero[0].tone == rl.TONE_MUTED and "가격을 비교하지 않았습니다" in zero[0].text


# ── 결론 카드 ──


def _conclusion(stats, quote=None, unit="대"):
    return rs.build_conclusion(stats, quote_unit_price=quote, unit=unit)


def test_quote_headline_names_the_quote_and_colours_the_difference():
    stats = _stats(93, "297000", "1980000", "1980000", latest="2026-10-01")
    quote = Decimal("1800000")
    lead = rl.lead_view(stats, _conclusion(stats, quote), quote=quote, unit="대", warn_count=2)
    # The production smoke waits for "내 견적가 12,000,000원은"-style text.
    assert _text(lead.headline_html) == "내 견적가 1,800,000원은 1대당 거래 가운데 값보다 9.1% 낮습니다."
    assert 'class="rl-down"' in lead.headline_html
    assert lead.basis == "같은 제품 1대 단위 거래 93건 기준 · 가운데 값 1,980,000원 · 최근 거래 2026-10-01"
    assert lead.eyebrow.endswith("확인할 점 2가지") and lead.eyebrow_tone == rl.TONE_WARN


def test_higher_quote_is_red_and_one_trade_says_it_is_not_enough():
    stats = _stats(1, "13200000", "13200000", "13200000", latest="2026-08-21")
    quote = Decimal("14000000")
    lead = rl.lead_view(stats, _conclusion(stats, quote, "식"), quote=quote, unit="식")
    assert _text(lead.headline_html) == "내 견적가 14,000,000원은 이 1건보다 6.1% 높습니다."
    assert 'class="rl-up"' in lead.headline_html
    # "1건뿐" lives in the check panel, not repeated under the headline.
    assert lead.basis == "같은 제품 1식 단위 거래 1건 기준 · 최근 거래 2026-08-21"


def test_two_trades_say_where_the_quote_sits_without_a_percent():
    stats = _stats(2, "1000", "1500", "2000")
    lead = rl.lead_view(stats, _conclusion(stats, Decimal("1500")), quote=Decimal("1500"), unit="대")
    assert _text(lead.headline_html) == "내 견적가 1,500원은 두 거래가 사이에 있습니다."
    assert lead.basis == "같은 제품 1대 단위 거래 2건 기준"


def test_without_quote_the_conclusion_sentence_is_the_headline():
    stats = _stats(16, "4389000", "4400000", "6585500", latest="2026-08-05")
    conclusion = _conclusion(stats)
    lead = rl.lead_view(stats, conclusion, quote=None, unit="대")
    assert _text(lead.headline_html) == conclusion.headline
    assert lead.basis.startswith("같은 제품 1대 단위 거래 16건 기준")
    assert lead.eyebrow_tone == rl.TONE_OK


def test_zero_trades_and_unavailable_use_the_plain_sentence():
    stats = _stats(0)
    lead = rl.lead_view(stats, _conclusion(stats), quote=Decimal("5"), unit=None)
    assert _text(lead.headline_html) == "같은 제품으로 확인된 나라장터 거래가 없습니다."
    assert lead.eyebrow_tone == rl.TONE_MUTED
    gone = rs.build_conclusion(stats, quote_unit_price=None, unavailable=True)
    assert "연결하지 못해" in _text(
        rl.lead_view(stats, gone, quote=None, unit=None, unavailable=True).headline_html
    )


# ── 가격 막대 ──


def _labels(markup: str) -> tuple[str, str]:
    match = re.search(r'<div class="rl-rail-labels"><span>(.*?)</span><span>(.*?)</span></div>', markup)
    assert match is not None
    return _text(match.group(1)), _text(match.group(2))


def test_rail_labels_sit_in_one_line_in_price_order_and_never_overlap():
    markup = rl.price_rail_html(
        low=Decimal("4389000"), high=Decimal("6585500"), median=Decimal("4400000"), quote=Decimal("6500000")
    )
    left, right = _labels(markup)
    assert left == "최저 4,389,000원·가운데 값 4,400,000원"
    assert right == "내 견적 6,500,000원·최고 6,585,500원"
    # Labels are not positioned on the bar, so close values cannot overlap.
    assert "pr-label" not in markup and 'id="purchase-price-band-v1"' in markup


def test_equal_prices_share_one_label():
    markup = rl.price_rail_html(
        low=Decimal("297000"), high=Decimal("1980000"), median=Decimal("1980000"), quote=Decimal("1800000")
    )
    left, right = _labels(markup)
    assert left == "최저 297,000원"
    assert right == "내 견적 1,800,000원·가운데 값·최고 1,980,000원"
    assert right.count("1,980,000원") == 1


def test_quote_outside_the_range_gets_an_arrow_beyond_the_bar():
    above = rl.price_rail_html(low=Decimal("100"), high=Decimal("200"), median=Decimal("150"), quote=Decimal("900"))
    assert 'rl-out rl-right' in above and "(최고보다 높음)" in _labels(above)[1]
    assert "rl-tick rl-quote" not in above
    below = rl.price_rail_html(low=Decimal("100"), high=Decimal("200"), median=Decimal("150"), quote=Decimal("10"))
    assert 'rl-out rl-left' in below
    assert _labels(below)[0].startswith("내 견적 10원 (최저보다 낮음)")


def test_single_price_is_a_card_not_a_bar():
    stats = _stats(1, "13200000", "13200000", "13200000", latest="2026-08-21")
    markup = rl.price_points_html(stats, quote=Decimal("12000000"), unit="식")
    text = _text(markup)
    assert "1식당 거래가 · 2026-08-21" in text and "13,200,000원" in text
    assert "내 견적" in text and "12,000,000원" in text
    assert "rl-rail" not in markup
    assert rl.price_points_html(_stats(0), quote=None, unit=None) == ""


# ── 머리말 · 카드 · 칩 ──


def test_header_title_puts_a_short_product_name_before_the_model():
    assert rl.header_title("M40", "환자감시장치") == "환자감시장치 M40"
    assert rl.header_title("M40", None) == "M40"
    assert rl.header_title("환자감시장치 M40", "환자감시장치") == "환자감시장치 M40"
    subtitle = rl.header_subtitle(
        title="환자감시장치 M40",
        procurement_product="환자감시장치",
        companies=["(주)메디아나"],
        permit_type="인증",
        permit_numbers=["제인 20-5001 호", "제인 20-5002 호"],
    )
    assert subtitle == "제조·수입 (주)메디아나 · 식약처 인증 제인 20-5001 호 외 1건"
    assert rl.header_subtitle(title="X", procurement_maker="Philips") == "제조사 Philips"


def test_header_keeps_the_smoke_heading_visually_hidden():
    markup = rl.header_html(title="A <b>", subtitle="", chips=["검색어 DFM100"], marker_heading="DFM100 거래가격")
    assert '<div class="rl-sr"><h2>DFM100 거래가격</h2></div>' in markup
    assert "A &lt;b&gt;" in markup and "검색어 DFM100" in markup


def test_cards_keep_the_header_id_and_show_a_word_with_every_dot():
    from purchase_price.ui import workspace_header as header

    cards = [
        header.SummaryCard("price", "1대당 거래 가운데 값", "1,980,000원", "같은 제품 거래 93건", header.TONE_OK),
        header.safety_card("CHECK_FAILED"),
        header.SummaryCard("x", "식약처 허가", "확인 전", "n", header.TONE_NEUTRAL),
    ]
    markup = rl.cards_html(cards)
    assert 'id="purchase-workspace-header-v1"' in markup
    assert markup.count("pc-dot") == 3
    assert "pc-dot pc-ok" in markup and "pc-dot pc-warn" in markup and "pc-dot pc-muted" in markup
    assert "같은 제품 거래 93건" in _text(markup)


def test_price_card_label_matches_what_the_value_is():
    assert rl.price_card_label(_stats(16, "1", "2", "3"), "대") == "1대당 거래 가운데 값"
    assert rl.price_card_label(_stats(1, "1", "1", "1"), "식") == "1식당 거래가"
    assert rl.price_card_label(_stats(0), None) == "거래가"


def test_chip_row_replaces_the_caption_lines():
    period = rs.choose_period(["2026-01-01"], requested=None, user_chose=False, today=date(2026, 10, 9))
    split = rs.split_by_main_unit(
        [SimpleNamespace(unit="대"), SimpleNamespace(unit="대"), SimpleNamespace(unit="SET")]
    )
    chips = [
        rl.period_chip(period),
        rl.unit_chip(split),
        rl.outlier_chip(1, has_median=True),
        rl.basis_chip(track_b_data_as_of="2026-10-05", live_failed=True, mfds_coverage_percent=53.0),
    ]
    text = _text(rl.chip_row_html(chips))
    assert "기간 · 최근 3년 (2023-10-10 이후 거래)" in text
    assert "단위 · 1대 기준 · 단위 다른 거래 1건(SET) 따로 표시" in text
    assert "이상 거래 · 가운데 값과 3배 넘게 다른 거래 1건" in text
    assert "자료 기준 · 나라장터 2026-10-05 수집분 · 최근 며칠 실시간 확인 실패" in text
    assert "식약처 자료 53% 수집 중" in text
    assert "0건" not in text


def test_widened_period_and_live_success_chips():
    widened = rs.choose_period(["2020-01-01"], requested=None, user_chose=False, today=date(2026, 10, 9))
    chip = rl.period_chip(widened)
    assert chip.tone == rl.TONE_WARN and "최근 3년 안에 거래가 없어 넓힘" in chip.text
    live = rl.basis_chip(track_b_data_as_of="2026-10-05", live_checked_until="2026-10-09", mfds_complete=True)
    assert live.text == "나라장터 2026-10-05 수집분 + 2026-10-09까지 실시간 확인" and live.tone == rl.TONE_MUTED
    assert rl.basis_chip(track_b_data_as_of=None) is None
    assert rl.outlier_chip(0, has_median=True).text == "없음"
    assert rl.outlier_chip(3, has_median=False) is None


def test_trade_numbers_show_total_quantity_and_unit_price():
    row = {"총액": "73,026,000원", "수량": "2", "단위": "set", "가격": "36,513,000원", "거래일": "2025-03-18", "구매처": "보건의료원"}
    text = _text(rl.trade_numbers_html(row))
    assert "거래 총액73,026,000원" in text and "수량2 set" in text and "1 set 가격36,513,000원" in text
    assert rl.trade_dialog_title(row) == "거래 원문 · 2025-03-18 · 보건의료원"
    unknown = _text(rl.trade_numbers_html({"총액": "미확인", "수량": "미확인", "단위": "미확인", "가격": "1,000원"}))
    assert "확인 안 됨" in unknown and "1단위 가격1,000원" in unknown


def test_screen_wording_has_no_developer_terms():
    stats = _stats(16, "4389000", "4400000", "6585500", latest="2026-08-05")
    pieces = [
        rl.check_panel_html(rl.check_points(_rows(["구급차"]), direct_count=2, live_failed=True, outlier_count=1)),
        rl.lead_row_html(
            rl.lead_view(stats, _conclusion(stats, Decimal("1")), quote=Decimal("1"), unit="대"),
            price_html=rl.price_rail_html(low=Decimal("1"), high=Decimal("3"), median=Decimal("2")),
            panel_html="",
        ),
    ]
    for piece in pieces:
        assert rs.has_banned_term(_text(piece)) is None


# ── 2026-10-09 production acceptance fixes ──


def test_nothing_found_only_when_no_source_matched():
    base = dict(direct_count=0, reference_count=0, identity_found=False, price_unavailable=False)
    assert rl.nothing_found(**base) is True
    assert rl.nothing_found(**{**base, "reference_count": 25}) is False
    assert rl.nothing_found(**{**base, "identity_found": True}) is False
    assert rl.nothing_found(**{**base, "price_unavailable": True}) is False
    assert rl.nothing_found(**base, recall_records=1) is False


def test_not_found_says_what_was_searched_and_what_to_try():
    text = _text(rl.not_found_html("zzqq없는모델123", basis="자료 기준 · 나라장터 2026-10-05 수집분"))
    assert "zzqq없는모델123" in text and "찾지 못했습니다" in text
    assert "나라장터" in text and "식약처" in text
    assert "철자" in text and "모델명만" in text and "업체명" in text
    assert "확인된 회수 없음" not in text and "Excel" not in text
    assert rs.has_banned_term(text) is None
    assert "<script" not in rl.not_found_html("<script>")


def test_lead_card_puts_the_chip_row_at_the_bottom_and_top_aligns():
    stats = _stats(16, "4389000", "4400000", "6585500")
    chips = rl.chip_row_html([rl.Chip("기간", "최근 3년")])
    markup = rl.lead_row_html(
        rl.lead_view(stats, _conclusion(stats, None), quote=None, unit="대"),
        price_html=rl.price_rail_html(low=Decimal("1"), high=Decimal("3"), median=Decimal("2")),
        panel_html="<div>panel</div>",
        foot_html=chips,
    )
    assert markup.index("rl-rail") < markup.index('class="rl-foot"') < markup.index("panel")
    assert "justify-content:flex-start" in rl.RESULT_CSS
    assert "justify-content:center" not in rl.RESULT_CSS


def test_quote_hint_shows_the_parsed_price_with_separators():
    assert "= 2,500,000원" in _text(rl.quote_hint_html(Decimal("2500000"), "대"))
    assert "1대 기준" in _text(rl.quote_hint_html(Decimal("2500000"), "대"))
    assert "원 / 1대 기준" in _text(rl.quote_hint_html(None, "대"))
    assert "숫자로만" in _text(rl.quote_hint_html(None, "대", invalid=True))


def test_record_fields_table_has_exactly_one_row_per_field():
    markup = rl.record_fields_html([("사업명", "구입"), ("단가", "1,980,000원"), ("", "skip")])
    assert markup.count("<tr>") == 2
    assert "<td>1,980,000원</td>" in markup


def test_mfds_check_done_line_says_what_changed():
    text = _text(
        rl.mfds_check_done_html(
            status="success", active_model_count=40, model_count=134, companies_before=14, companies_after=9
        )
    )
    assert "확인 완료" in text and "134개 중 판매 가능 40개" in text and "9곳" in text and "14곳" in text
    unchanged = _text(
        rl.mfds_check_done_html(
            status="success", active_model_count=1, model_count=1, companies_before=3, companies_after=3
        )
    )
    assert "곳만 남겼습니다" not in unchanged
    failed = rl.mfds_check_done_html(
        status="failure", active_model_count=0, model_count=0, companies_before=0, companies_after=0
    )
    assert "불러오지 못했습니다" in failed
    waiting = rl.mfds_check_done_html(
        status="deferred", active_model_count=0, model_count=0, companies_before=0, companies_after=0
    )
    assert waiting == ""


def test_settings_card_and_cards_fit_a_narrow_column():
    css = rl.RESULT_CSS
    assert ".st-key-rl_settings {container-type:inline-size;}" in css
    assert "@container (max-width: 860px)" in css
    assert "white-space:nowrap; overflow:hidden; text-overflow:ellipsis" in css
    assert 'class="rl-cq rl-keep"' in rl.cards_html([])
