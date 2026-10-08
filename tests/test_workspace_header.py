from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from purchase_price.ui import workspace_header as header


def _stats(**overrides):
    values = {
        "direct_count": 50,
        "reference_count": 0,
        "research_count": 0,
        "supplier_count": 1,
        "demand_institution_count": 45,
        "min_price": Decimal("396000"),
        "median_price": Decimal("396000"),
        "max_price": Decimal("396000"),
        "latest_transaction_date": "2026-10-01",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_price_card_single_price_keeps_count_phrase() -> None:
    card = header.price_card(_stats())

    assert card.value == "396,000원"
    assert card.note == "같은 제품 거래 50건 · 최근 2026-10-01"
    assert card.tone == header.TONE_OK


def test_price_card_range_shows_median() -> None:
    card = header.price_card(_stats(min_price=Decimal("100"), median_price=Decimal("150"), max_price=Decimal("300")))

    assert card.value == "150원"
    assert card.note.startswith("중앙값 · 같은 제품 거래 50건")

    two = header.price_card(
        _stats(direct_count=2, min_price=Decimal("100"), median_price=Decimal("200"), max_price=Decimal("300"))
    )
    assert two.value == "100 ~ 300원"


def test_price_card_zero_and_unavailable_are_distinct() -> None:
    zero = header.price_card(_stats(direct_count=0, min_price=None, max_price=None, reference_count=3))
    unavailable = header.price_card(_stats(), unavailable=True)

    assert zero.value == "같은 제품 거래 0건"
    assert "비슷한 품목 거래 3건은 비교에서 제외" in zero.note
    assert unavailable.value == "조회 불가"
    assert unavailable.tone == header.TONE_WARN
    # The dashboard contract bans this phrase; zero evidence is not "no trade".
    assert "거래 없음" not in zero.value + zero.note


def test_safety_codes_are_translated_and_only_recalls_raise_a_banner() -> None:
    assert header.safety_card("CHECKED_NONE").value == "확인된 회수 없음"
    assert header.safety_card("RED").tone == header.TONE_DANGER
    assert header.safety_card("weird").value == "안전정보 미확인"
    assert header.safety_needs_banner("RED")
    assert header.safety_needs_banner("AMBER")
    assert not header.safety_needs_banner("CHECKED_NONE")
    assert not header.safety_needs_banner("CHECK_FAILED")


def test_mfds_card_states() -> None:
    found = header.mfds_card("품목번호 확인", permit_numbers=["제허 12-1551 호"], companies=["지이헬스케어코리아"])
    waiting = header.mfds_card("조회 대기")
    missing = header.mfds_card("0건", coverage_percent=25.8)

    assert found.note == "제허 12-1551 호 · 지이헬스케어코리아"
    assert found.tone == header.TONE_OK
    assert waiting.value == "확인 전"
    assert "식약처에서 확인" in waiting.note
    assert missing.value == "찾지 못함"
    assert "26%" in missing.note
    assert "미등록" not in missing.value + missing.note
    same_item = header.mfds_card("품목 확인", model_count=632, active_model_count=410)
    assert same_item.note == "같은 품목 등록 모델 632개(판매 가능 410개) · 이 모델명과 같은 등록은 못 찾음"


def test_identity_line_prefers_mfds_then_procurement_name() -> None:
    assert (
        header.identity_line(
            product_name="자동심장충격기",
            permit_numbers=["제허 1 호", "제허 1 호", "제허 2 호"],
            permit_type="허가",
            companies=["A", "B"],
        )
        == "자동심장충격기 · 허가 제허 1 호 외 1건 · 제조·수입 A 외 1곳"
    )
    assert (
        header.identity_line(procurement_product="저출력심장충격기", procurement_maker="나눔테크")
        == "나라장터 품명 저출력심장충격기 · 제조사 나눔테크"
    )
    assert header.identity_line() == ""


def test_most_common_text_ignores_unknown() -> None:
    rows = [{"품목/모델": "a"}, {"품목/모델": "b"}, {"품목/모델": "b"}, {"품목/모델": "미확인"}]

    assert header.most_common_text(rows, "품목/모델") == "b"
    assert header.most_common_text([{"품목/모델": "미확인"}], "품목/모델") is None


def test_procurement_product_name_uses_title_class_part() -> None:
    rows = [{"품목/모델": "저출력심장충격기, 나눔테크, NT-SG, (부품)스탠드형보관함"}] * 2

    assert header.procurement_product_name(rows) == "저출력심장충격기"


def test_data_basis_line() -> None:
    line = header.data_basis_line(
        track_b_data_as_of="2026-09-18",
        live_note="나라장터 실시간 보강 2026-09-19 ~ 2026-10-05: 조회된 8건 모두 이미 반영",
        mfds_coverage_percent=25.8,
    )
    assert line == (
        "자료 기준 · 나라장터 2026-09-18까지 수집 · 나라장터 실시간 보강 2026-09-19 ~ 2026-10-05: "
        "조회된 8건 모두 이미 반영 · 식약처 제품정보 26% 수집 중"
    )
    assert "전체 수집 완료" in header.data_basis_line(track_b_data_as_of="x", mfds_complete=True)
    assert header.data_basis_line(track_b_data_as_of=None) == ""


def test_direct_table_columns_keep_only_available_compact_columns() -> None:
    rows = [{"거래일": "d", "모델": "m", "가격": "p", "원문근거키": "k"}]

    assert header.direct_table_columns(rows) == ["거래일", "모델", "가격"]


def test_cards_html_escapes_values() -> None:
    markup = header.render_cards_html([header.SummaryCard("x", "<b>", "1<2", "a&b", header.TONE_OK)])

    assert "&lt;b&gt;" in markup and "1&lt;2" in markup and "a&amp;b" in markup
    assert 'id="purchase-workspace-header-v1"' in markup


def test_dashboard_uses_fixed_header_before_area_tabs() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    conclusion = source.index("result_summary_ui.render_conclusion_html(conclusion)")
    cards = source.index("workspace_header_ui.render_cards_html(header_cards)")
    first_section = source.index('st.markdown("#### 얼마에 거래됐나")')
    assert conclusion < cards < first_section
    assert 'id="purchase-workspace-runtime-v11"' in source
    # Full trade list: total amount, quantity, then the price of one unit (UI 2026-10-08).
    assert "result_summary_ui.trade_table_rows(direct_rows)" in source
    assert 'st.expander("상세 자료 · 견적 조건 · 안전정보 · 식약처 원자료 · 자료 기준", expanded=False)' in source
    # The deferred research loader lives at the bottom, not above the fold.
    assert source.index('st.markdown("##### 입찰·계약 참고자료")') < source.index("research_button_label")


def test_mfds_not_applicable_does_not_claim_the_item_is_not_medical() -> None:
    card = header.mfds_card("대상 아님")

    assert card.value == "확인 못 함"
    assert card.note == "식약처 등록을 찾지 못해 조회하지 않았습니다"
    assert "의료기기" not in card.value + card.note
