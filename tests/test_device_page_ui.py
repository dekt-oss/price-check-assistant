from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from purchase_price.domain import ComparisonScope, EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice
from purchase_price.services.mfds_device_intelligence import (
    MedicalDeviceModelRecord,
    resolve_exact_model_identity,
)
from purchase_price.services.search import SearchRun, SourceRunStatus
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
        assert f'name="{name}"' in smoke
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
        "식약처 서비스 사용 승인"
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


def _price(grade: MatchGrade, price: str, unit: str | None = "대") -> CollectedPrice:
    return CollectedPrice(
        manufacturer="M",
        product_name="P",
        model_name="A16-DS",
        specification=None,
        price=Decimal(price),
        evidence_type=EvidenceType.PUBLIC_SALE_PRICE,
        source_type=SourceType.PROCUREMENT,
        source_name="나라장터",
        source_url="https://example.com/x",
        collected_at=date(2026, 10, 1),
        transaction_date=date(2026, 9, 1),
        quantity=Decimal("2") if unit else None,
        unit=unit,
        match_grade=grade,
        comparison_scope=ComparisonScope.OBSERVED_ONLY,
    )


def test_procurement_rows_use_plain_columns_and_put_confirmed_first() -> None:
    rows = dev.procurement_rows([_price(MatchGrade.C, "100"), _price(MatchGrade.A, "200")])
    assert rows[0]["같은 제품 여부"] == "같은 제품으로 확인"
    assert rows[1]["같은 제품 여부"].startswith("참고용")
    assert rows[0]["1개당 가격(원)"] == 200
    for column in rows[0]:
        assert has_banned_term(column) is None
        assert column not in {"Evidence Type", "근거ID", "등급", "비교범위", "자료성격"}


def test_procurement_state_separates_failed_empty_and_found() -> None:
    ok = SourceRunStatus(source_name="나라장터", succeeded=True, result_count=0)
    bad = SourceRunStatus(source_name="나라장터", succeeded=False, result_count=0, error="x")
    skipped = SourceRunStatus(source_name="나라장터", succeeded=False, result_count=0, skipped=True, note="키 없음")
    assert dev.procurement_state(SearchRun(source_statuses=[ok]))[0] == "empty"
    assert dev.procurement_state(SearchRun(source_statuses=[bad]))[0] == "failed"
    assert dev.procurement_state(SearchRun(source_statuses=[skipped]))[0] == "skipped"
    found = SearchRun(results=[_price(MatchGrade.A, "1")], source_statuses=[bad])
    assert dev.procurement_state(found)[0] == "found"
    assert "확인하지 못했습니다" in dev.procurement_partial_notice(found)
    assert dev.procurement_partial_notice(SearchRun(source_statuses=[ok])) == ""


def test_discovery_state_and_rows() -> None:
    candidate = SimpleNamespace(
        transaction_date=date(2026, 9, 1),
        title="t",
        classification_name="c",
        price=Decimal("1000"),
        relevance="분류 후보",
        match_reason="r",
    )
    assert dev.discovery_state(SimpleNamespace(status="failure", candidates=())) == "failed"
    assert dev.discovery_state(SimpleNamespace(status="partial", candidates=(candidate,))) == "partial"
    assert dev.discovery_state(SimpleNamespace(status="success_0", candidates=())) == "empty"
    assert dev.discovery_state(SimpleNamespace(status="success", candidates=(candidate,))) == "found"
    row = dev.discovery_rows(SimpleNamespace(candidates=(candidate,)))[0]
    assert row["표기 금액(원)"] == 1000
    assert "근거ID" not in row and "점수" not in row


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
