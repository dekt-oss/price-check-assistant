from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from purchase_price.domain import MatchGrade
from purchase_price.services.mfds_device_intelligence import (
    MedicalDeviceModelRecord,
    resolve_exact_model_identity,
)
from purchase_price.ui import device_page as dev
from purchase_price.ui.result_summary import has_banned_term

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "pages" / "4_의료기기_조회.py"


def _model(
    model: str,
    permit: str,
    *,
    cancelled: str | None = None,
    export_only: bool | None = None,
    permit_date: date | None = date(2020, 1, 1),
) -> MedicalDeviceModelRecord:
    return MedicalDeviceModelRecord(
        product_serial_number=None,
        regional_office=None,
        industry_type="제조업",
        permission_type=None,
        permit_number=permit,
        product_name="저출력심장충격기",
        permit_date=permit_date,
        cancellation_status=cancelled,
        cancellation_date=None,
        trade_name=None,
        model_name=model,
        export_only=export_only,
    )


@dataclass
class _Recall:
    status: str
    records: tuple = ()
    error_message: str | None = None


def test_tab_names_match_the_production_smoke_script() -> None:
    smoke = (ROOT / "scripts" / "production_browser_smoke.py").read_text(encoding="utf-8")
    for name in dev.TAB_NAMES:
        assert f'("{name}"' in smoke
    page = PAGE.read_text(encoding="utf-8")
    assert "st.tabs(list(dev.TAB_NAMES))" in page
    assert "page_header_html(dev.PAGE_TITLE" in page
    assert dev.PAGE_TITLE == "의료기기 허가·안전"


def test_page_wording_has_no_screen_jargon() -> None:
    texts = [
        dev.PAGE_SUBTITLE,
        dev.RECALL_TITLE,
        dev.RECALL_ACTION,
        dev.SUPPLIER_NOTE,
        dev.lookup_failed_html("식약처 허가정보"),
        dev.not_found_html("X", ("a",)),
        dev.safety_not_checked_html(False),
        dev.udi_not_found_html("123"),
        *dev.TAB_NAMES,
    ]
    for text in texts:
        assert has_banned_term(text) is None, text
    page = PAGE.read_text(encoding="utf-8")
    for old in ("Safety·", "등록·시장근거", "exact-normalized", "identity와", "자동 API 미연결"):
        assert old not in page


def test_recall_hit_is_a_red_banner_with_a_word() -> None:
    record = SimpleNamespace(
        model_name="M1",
        product_name="P",
        manufacturer_name="Maker",
        report_kind_name="자발적 회수",
        report_state_name="진행중",
        report_submit_date="2026-09-30",
        reason="사유",
    )
    view = dev.recall_view(_Recall("success", (record,)), searched="M1")
    assert view.is_hit
    assert "pc-danger" in view.banner
    assert dev.RECALL_TITLE in view.banner
    assert view.card_tone == "danger"
    assert "1건 있음" in view.card_value
    assert view.rows[0]["회수 구분"] == "자발적 회수"


def test_failed_recall_never_reads_as_zero_or_none() -> None:
    for status in ("failure", "not_authorized", "not_configured"):
        view = dev.recall_view(_Recall(status, error_message="boom"), searched="M1")
        assert not view.is_hit
        assert view.card_tone == "warn"
        combined = view.card_value + view.card_sub + view.notice
        assert "0건" not in combined
        assert "없음" not in view.card_value
    failed = dev.recall_view(_Recall("failure", error_message="boom"))
    assert "확인하지 못했습니다" in failed.notice
    assert dev.RETRY_BUTTON in failed.notice


def test_recall_none_says_it_is_not_a_full_history() -> None:
    view = dev.recall_view(_Recall("success_0"), searched="M1")
    assert view.state == "none"
    assert view.card_tone == "ok"
    assert "전체 이력이 없다는 뜻은 아니므로" in view.notice
    assert dev.recall_view(None).state == "not_checked"


def test_failed_lookup_notice_hides_urls_and_keys() -> None:
    html_text = dev.lookup_failed_html(
        "UDI-DI",
        "request failed https://apis.data.go.kr/x?serviceKey=SECRET123&a=1 serviceKey=SECRET123",
    )
    assert "SECRET123" not in html_text
    assert "https://" not in html_text
    assert "확인하지 못했습니다 (다시 시도)" in html_text
    assert dev.safe_error_text("HTTP 403 error=SERVICE_KEY_IS_NOT_REGISTERED_ERROR code=30").startswith(
        "식약처 조회 서비스가 아직 연결되지"
    )
    assert "제때 응답" in dev.safe_error_text("Read timed out")
    assert len(dev.safe_error_text("가" * 500)) <= 140


def test_failed_notice_particle_follows_the_last_syllable() -> None:
    assert "허가정보를 확인하지 못했습니다" in dev.lookup_failed_html("허가정보")
    assert "회수 자료를 확인하지 못했습니다" in dev.lookup_failed_html("회수 자료")
    assert "업체 허가·신고를 확인하지 못했습니다" in dev.lookup_failed_html("업체 허가·신고")
    assert "납품 사례는 찾지 않았습니다" not in dev.lookup_failed_html("납품 사례")
    assert "UDI-DI를 확인하지 못했습니다" in dev.lookup_failed_html("UDI-DI")
    assert "품목을 확인하지 못했습니다" in dev.lookup_failed_html("품목")


def test_not_found_names_what_was_searched_and_what_to_try() -> None:
    html_text = dev.not_found_html("식약처 등록 자료에서 품목명 ‘abc’", ("철자를 확인하세요",))
    assert "‘abc’" in html_text
    assert "찾지 못했습니다" in html_text
    assert "철자를 확인하세요" in html_text
    assert "pc-muted" in html_text
    assert "pc-danger" not in html_text


def test_permit_rows_put_the_same_model_first_then_valid_then_newest() -> None:
    records = [
        _model("OLD", "p1", permit_date=date(1998, 1, 1)),
        _model("CANCELLED", "p2", cancelled="3", permit_date=date(2026, 1, 1)),
        _model("NEW", "p3", permit_date=date(2025, 1, 1)),
        _model("A16-DS", "p4", permit_date=date(2019, 1, 1)),
        _model("EXPORT", "p5", export_only=True, permit_date=date(2024, 1, 1)),
    ]
    rows = dev.permit_rows(records, "a16 ds")
    assert [row["모델명"] for row in rows][:3] == ["A16-DS", "NEW", "OLD"]
    assert rows[0]["입력한 모델과"] == "같음"
    assert {row["모델명"]: row["상태"] for row in rows}["CANCELLED"] == "효력 없음"
    assert {row["모델명"]: row["상태"] for row in rows}["EXPORT"] == "수출 전용"
    assert dev.sale_status_text(records[0]) == "유효"
    assert "허가번호" in rows[0] and "식약처 품목번호" not in rows[0]


def test_summary_cards_keep_four_equal_cards_in_every_state() -> None:
    params = dev.MarketParams(product_name="심장충격기", model_name="A16-DS")
    records = (_model("A16-DS", "p4"), _model("OTHER", "p6", cancelled="3"))
    ok = dev.MarketResult(
        params=params,
        records=records,
        exact=resolve_exact_model_identity(records, "A16-DS"),
        recall=_Recall("success_0"),
    )
    failed = dev.MarketResult(params=params, records_error="오류", recall=_Recall("failure"))
    for result in (ok, failed):
        cards = dev.permit_summary_cards(result)
        assert cards.count("pc-card pc-metric") == 4
        assert cards.count("pc-dot") == 4
    cards = dev.permit_summary_cards(failed)
    assert "0건" not in cards
    assert "확인하지 못함" in cards
    cards = dev.permit_summary_cards(ok)
    assert "2건" in cards and "1건" in cards
    assert ok.active_count == 1


def test_identity_notice_covers_confirmed_missing_and_ambiguous() -> None:
    records = (_model("A16-DS", "p4"),)
    confirmed = resolve_exact_model_identity(records, "A16-DS")
    assert "pc-ok" in dev.identity_notice_html("A16-DS", confirmed)
    missing = resolve_exact_model_identity(records, "ZZZ")
    assert "찾지 못했습니다" in dev.identity_notice_html("ZZZ", missing)
    ambiguous = resolve_exact_model_identity(
        (_model("A16-DS", "p1"), _model("A16-DS", "p2")), "A16-DS"
    )
    assert "하나로 정하지 않았습니다" in dev.identity_notice_html("A16-DS", ambiguous)
    assert dev.identity_notice_html("", None) == ""


def _trade(grade: MatchGrade, price: str, day: str, unit: str | None = "대", supplier: str = "A사"):
    return SimpleNamespace(
        match_grade=grade,
        price=Decimal(price),
        transaction_date=day,
        unit=unit,
        quantity=Decimal("2"),
        supplier=supplier,
        demand_institution="B병원",
    )


def _track_b(*candidates, references=()):
    return SimpleNamespace(status="success", candidates=tuple(candidates), reference_candidates=tuple(references))


TODAY = date(2026, 10, 9)


def test_trade_summary_counts_only_same_product_trades_in_the_main_unit() -> None:
    track_b = _track_b(
        _trade(MatchGrade.A, "1980000", "2026-09-29"),
        _trade(MatchGrade.B, "2000000", "2026-09-17"),
        _trade(MatchGrade.A, "1900000", "2026-08-01"),
        _trade(MatchGrade.A, "5000000", "2026-08-01", unit="set"),
        _trade(MatchGrade.C, "100", "2026-08-01"),
    )
    summary = dev.build_trade_summary(track_b, TODAY)
    assert summary.count == 3
    assert summary.median_price == Decimal("1980000")
    assert (summary.low_price, summary.high_price) == (Decimal("1900000"), Decimal("2000000"))
    assert summary.main_unit == "대"
    assert summary.other_unit_count == 1
    assert summary.reference_count == 1
    assert summary.trades[0].transaction_date == "2026-09-29"


def test_trade_cards_and_rows_write_money_with_commas_and_won() -> None:
    summary = dev.build_trade_summary(
        _track_b(_trade(MatchGrade.A, "1980000", "2026-09-29"), _trade(MatchGrade.A, "2000000", "2026-09-17")),
        TODAY,
    )
    cards = dev.trade_summary_cards(summary)
    assert cards.count("pc-card pc-metric") == 4
    assert "2건" in cards and "1,990,000원" in cards and "1,980,000 ~ 2,000,000원" in cards
    row = dev.trade_rows(summary)[0]
    assert row["1대당 가격"] == "1,980,000원"
    assert row["수량"] == "2 대"
    for column in row:
        assert has_banned_term(column) is None
    assert dev.won_text("1980000") == "1,980,000원"
    assert dev.won_text(None) == "미확인"


def test_trade_summary_leaves_entry_errors_out_and_says_how_many() -> None:
    swapped = _trade(MatchGrade.A, "1", "2026-09-20")
    swapped.quantity = Decimal("1731000")
    swapped.total_amount = Decimal("1731000")
    summary = dev.build_trade_summary(
        _track_b(
            _trade(MatchGrade.A, "1980000", "2026-09-29"),
            _trade(MatchGrade.A, "297000", "2026-09-17"),
            swapped,
        ),
        TODAY,
    )

    assert summary.count == 2 and summary.entry_error_count == 1
    assert (summary.low_price, summary.high_price) == (Decimal("297000"), Decimal("1980000"))
    cards = dev.trade_summary_cards(summary)
    assert "297,000 ~ 1,980,000원" in cards and "1 ~" not in cards
    note = dev.entry_error_note_html(summary)
    assert "입력 오류 의심 1건" in note
    assert dev.entry_error_note_html(dev.build_trade_summary(_track_b(), TODAY)) == ""


def test_device_page_reloads_stale_trade_modules_before_importing_them() -> None:
    source = PAGE.read_text(encoding="utf-8")
    entry = source.index("purchase_price.ui.track_b_transactions\", \"ENTRY_ERRORS_EXCLUDED_V1\"")
    page_marker = source.index("purchase_price.ui.device_page\", \"DEVICE_PAGE_ENTRY_ERRORS_V1\"")
    assert entry < page_marker
    assert dev.DEVICE_PAGE_ENTRY_ERRORS_V1 is True


def test_trade_summary_without_same_product_trades_shows_dashes_not_zero_prices() -> None:
    summary = dev.build_trade_summary(_track_b(_trade(MatchGrade.C, "100", "2026-09-01")), TODAY)
    assert summary.count == 0 and summary.reference_count == 1
    cards = dev.trade_summary_cards(summary)
    assert "0건" in cards and "—" in cards
    empty = dev.trade_empty_html(dev.MarketParams(product_name="심장충격기", model_name="X1"), summary)
    assert "찾지 못했습니다" in empty and "참고 거래 1건" in empty


def test_trade_suppliers_are_ranked_by_same_product_trades() -> None:
    summary = dev.build_trade_summary(
        _track_b(
            _trade(MatchGrade.A, "1000000", "2026-09-01", supplier="가사"),
            _trade(MatchGrade.A, "1000000", "2026-09-05", supplier="나사"),
            _trade(MatchGrade.A, "1000000", "2026-09-09", supplier="나사"),
        ),
        TODAY,
    )
    rows = dev.trade_supplier_rows(summary)
    assert [row["업체"] for row in rows] == ["나사", "가사"]
    assert rows[0]["설명"] == "같은 제품 거래 2건 · 가장 최근 2026-09-09"


def test_page_uses_the_same_trade_lookup_as_price_research() -> None:
    page = PAGE.read_text(encoding="utf-8")
    assert "lookup_track_b_quote_with_live" in page
    assert "build_purchase_workspace_handoff" in page
    assert "search_all" not in page and "discover_unmapped_g2b_candidates" not in page


def test_times_are_shown_in_korean_time() -> None:
    from datetime import UTC, datetime

    assert dev.kst_time_text(datetime(2026, 10, 9, 7, 50, tzinfo=UTC)) == "10-09 16:50"
    assert dev.kst_time_text(datetime(2026, 10, 9, 7, 50)) == "10-09 16:50"  # naive means UTC
    assert "datetime.now()" not in PAGE.read_text(encoding="utf-8")


def test_connection_chips_say_which_service_is_not_connected_yet() -> None:
    ready = dev.connection_chips_html(mfds_ready=True, g2b_ready=True)
    assert "연결 전" not in ready and ready.count("사용 가능") == 5
    chips = dev.connection_chips_html(
        mfds_ready=True, g2b_ready=True, service_states={dev.SERVICE_UDI: dev.STATE_PENDING}
    )
    assert "UDI-DI <b>연결 전</b>" in chips
    assert "식약처 허가정보 <b>사용 가능</b>" in chips
    off = dev.connection_chips_html(mfds_ready=False, g2b_ready=True)
    assert "식약처 허가정보 <b>사용 불가</b>" in off and "나라장터 자료 <b>사용 가능</b>" in off


def test_not_approved_errors_have_no_service_key_wording() -> None:
    raw = "Public Data Portal request failed: HTTP 403 error=SERVICE_KEY_IS_NOT_REGISTERED_ERROR code=30"
    assert dev.is_not_approved_error(raw)
    assert dev.is_not_approved_error(dev.safe_error_text(raw))
    assert not dev.is_not_approved_error("Read timed out")
    for text in (
        dev.safe_error_text(raw),
        dev.lookup_failed_html("식약처 허가정보", raw),
        dev.udi_not_connected_html(),
        dev.missing_key_notice_html("UDI-DI"),
    ):
        assert "서비스키" not in text
        assert has_banned_term(text) is None
    assert "다시 시도" not in dev.lookup_failed_html("식약처 허가정보", raw)
    html_text = dev.udi_not_connected_html()
    assert "UDI-DI 조회 서비스가 아직 연결되지 않았습니다" in html_text
    assert "식약처 의료기기 통합정보시스템(UDI)에서 직접 확인하세요" in html_text


def test_udi_product_rows_use_plain_headers() -> None:
    record = SimpleNamespace(
        udi_di="18800003462138",
        product_name="환자 감시장치",
        model_name="M40",
        permit_number="제인 20-5001 호",
        permit_date="2020-11-10",
        company_name="(주)메디아나",
    )
    row = dev.udi_product_rows([record])[0]
    assert row["모델명"] == "M40" and row["제조·수입업체"] == "(주)메디아나"
    for column in row:
        assert has_banned_term(column) is None


def test_business_and_udi_rows_use_plain_headers() -> None:
    business = SimpleNamespace(
        company_name="(주)A",
        industry_type="수입업",
        business_status="영업",
        business_permit_number="제 1 호",
        address="서울",
        is_active=True,
    )
    row = dev.business_rows([business])[0]
    assert row["지금 취급 가능"] == "예"
    udi = SimpleNamespace(
        udi_di="123", company_name="B", company_type="제조", code_system_name="GS1"
    )
    assert dev.udi_rows([udi])[0]["UDI-DI"] == "123"
    assert "찾지 못했습니다" in dev.udi_not_found_html("123")
    assert "찾지 못했습니다" in dev.company_not_found_html("A")


def test_supplier_note_text_is_shortened_without_the_disclaimer() -> None:
    long_text = "식약처 의료기기 업허가가 확인됨 (수입업 / 제 1 호); 특정 모델의 공식 총판·대리점 관계를 의미하지 않음"
    assert dev.supplier_evidence_text(long_text) == "식약처 의료기기 업허가가 확인됨 (수입업 / 제 1 호)"


def test_safety_chips_carry_keys_and_time() -> None:
    chips = dev.safety_key_chips_html("A16-DS", ["제허 19-527 호"], "심장충격기", checked_at="10-09 14:57")
    assert chips.count("class=\"pc-chip\"") == 4
    assert "10-09 14:57" in chips
    assert dev.safety_key_chips_html("", [], "") == ""
    assert "확인 전에는 안전하다는 뜻이 아닙니다" in dev.safety_not_checked_html(True)


def test_searched_chips_show_only_filled_conditions() -> None:
    params = dev.MarketParams(product_name="심장충격기", manufacturer="A<b>")
    chips = dev.searched_chips_html(params, "10-09 14:57")
    assert chips.count("class=\"pc-chip\"") == 3
    assert "&lt;b&gt;" in chips and "A<b>" not in chips


def test_udi_input_rejects_obviously_invalid_numbers_before_any_lookup() -> None:
    assert dev.check_udi_di_input("00000000000000")[1]
    assert dev.check_udi_di_input("0")[1]
    assert "13자리" in dev.check_udi_di_input("1234567890123")[1]
    assert dev.check_udi_di_input("")[1]
    assert dev.check_udi_di_input("가나다")[1]


def test_udi_input_accepts_fourteen_digits_and_label_forms() -> None:
    assert dev.check_udi_di_input("08801234567895") == ("08801234567895", "")
    assert dev.check_udi_di_input("0880-1234 567895") == ("08801234567895", "")
    assert dev.check_udi_di_input("+H123ABC4567890")[1] == ""


def test_udi_match_note_shows_the_matched_number() -> None:
    assert "08801234567895" in dev.udi_match_note_html("08801234567895", 1)


def test_company_wording_has_no_stray_eop() -> None:
    assert "업 허가" not in dev.SUPPLIER_NOTE.replace("업체 허가", "")
    assert "식약처 업체 허가·신고" in dev.SUPPLIER_NOTE


def _identity_lookup(*, udi: str | None = "08801234567895"):
    from purchase_price.services.mfds_identity_index import MfdsIdentityLookup, MfdsIdentityRecord

    record = MfdsIdentityRecord(
        udi_di=udi,
        product_name="저출력심장충격기",
        classification_no=None,
        grade="3",
        permit_number="제허 19-527 호",
        permit_date=None,
        model_name="DFM100",
        trade_name=None,
        registered_company="(주)메디아나",
    )
    return MfdsIdentityLookup("success", "DFM100", "model", (record,))


def test_result_header_uses_the_shared_labelled_product_block() -> None:
    result = dev.MarketResult(
        params=dev.MarketParams(product_name="저출력심장충격기", model_name="DFM100"),
        identity=_identity_lookup(),
        status_labels={"제허19-527호": "국내 정상(품목)"},
    )

    html = dev.identity_header_html(result)

    for label in ("모델명", "품목명(식약처)", "제조·수입업체", "식약처 허가번호", "등급", "UDI-DI"):
        assert label in html, label
    for value in ("DFM100", "저출력심장충격기", "(주)메디아나", "제허 19-527 호", "3등급", "08801234567895"):
        assert value in html, value
    assert "판매 가능" in html


def test_result_header_leaves_out_udi_when_unknown_and_keeps_typed_values() -> None:
    result = dev.MarketResult(
        params=dev.MarketParams(product_name="심장충격기", manufacturer="필립스코리아"),
    )

    fields = {field.key: field for field in dev.identity_header_fields(result)}

    assert "udi" not in fields
    assert fields["model"].empty_text == "입력 안 함"
    assert fields["mfds_product"].value == "심장충격기"
    assert fields["company"].value == "필립스코리아" and "확인 전" in fields["company"].note


def test_meta_chips_keep_only_what_the_block_does_not_show() -> None:
    params = dev.MarketParams(product_name="심장충격기", model_name="A", specification="2 채널")
    chips = dev.meta_chips_html(params, "10-09 14:57")

    assert chips.count('class="pc-chip"') == 2
    assert "심장충격기" not in chips


def test_card_and_notice_agree_with_the_header_when_the_full_index_confirms_the_model() -> None:
    result = dev.MarketResult(
        params=dev.MarketParams(product_name="저출력심장충격기", model_name="DFM100"),
        identity=_identity_lookup(),
        exact=resolve_exact_model_identity((), "DFM100"),
    )

    cards = dev.permit_summary_cards(result)
    notice = dev.identity_notice_html("DFM100", result.exact, dev.index_exact_permits(result))

    assert "전체 허가 목록에서 확인" in cards and "찾지 못함" not in cards
    assert "pc-ok" in notice and "제허 19-527 호" in notice
    assert "찾지 못했습니다" in dev.identity_notice_html("DFM100", result.exact)


def test_identity_block_and_trade_card_state_the_same_period_and_count() -> None:
    track_b = _track_b(
        _trade(MatchGrade.A, "1980000", "2026-09-29"),
        _trade(MatchGrade.A, "1900000", "2026-08-01"),
        _trade(MatchGrade.A, "1800000", "2021-01-05"),
        _trade(MatchGrade.A, "1700000", "2019-03-05"),
    )
    summary = dev.build_trade_summary(track_b, TODAY)
    assert (summary.all_period_count, summary.count) == (4, 2)
    assert dev.trade_period_note(summary) == "같은 제품 거래 4건 (전체 기간) · 최근 3년 2건"

    result = dev.MarketResult(
        params=dev.MarketParams(product_name="저출력심장충격기", model_name="DFM100"),
        track_b=track_b,
        trades=summary,
    )
    fields = {field.key: field for field in dev.identity_header_fields(result)}
    assert fields["detail_class"].note == "같은 제품 거래 4건 (전체 기간) · 최근 3년 2건"
    cards = dev.trade_summary_cards(summary)
    assert "2건" in cards and "나라장터 · 최근 3년 (전체 기간 4건)" in cards


def test_trade_period_wording_is_plain_when_every_trade_is_in_the_period() -> None:
    track_b = _track_b(_trade(MatchGrade.A, "1980000", "2026-09-29"), _trade(MatchGrade.A, "1900000", "2026-08-01"))
    summary = dev.build_trade_summary(track_b, TODAY)

    assert dev.trade_period_note(summary) == "같은 제품 거래 2건 (전체 기간)"
    assert "전체 기간" not in dev.trade_summary_cards(summary)


def test_device_page_reloads_the_trade_period_marker() -> None:
    source = PAGE.read_text(encoding="utf-8")
    assert '("purchase_price.ui.device_page", "DEVICE_PAGE_TRADE_PERIOD_V1")' in source
    assert source.index("RESULT_LAYOUT_SEARCH_FIXES_V1") < source.index("DEVICE_PAGE_TRADE_PERIOD_V1")
    assert dev.DEVICE_PAGE_TRADE_PERIOD_V1 is True
