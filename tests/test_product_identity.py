from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from purchase_price.ui import product_identity as pi


def _fields(**overrides):
    values = {
        "model": "Flow-c",
        "model_state": pi.model_status(identity_status="success", identity_match="model"),
        "mfds_product": "가스 마취기",
        "companies": ["(주)게팅게메디칼코리아"],
        "permit_numbers": ["수허 21-193 호"],
        "permit_type": "허가",
        "permit_state": pi.permit_status(permit="수허 21-193 호", found=True),
        "grade": "3",
        "detail_name": "가스마취기",
        "detail_code": "4227250101",
    }
    values.update(overrides)
    return pi.product_fields(**values)


def test_every_field_has_its_own_label_in_a_fixed_order():
    fields = _fields()
    assert [field.label for field in fields] == [
        "모델명",
        "품목명(식약처)",
        "제조·수입업체",
        "식약처 허가번호",
        "등급",
        "나라장터 세부품명(코드)",
    ]
    by_key = pi.field_map(fields)
    assert by_key["model"].value == "Flow-c" and by_key["model"].main
    assert by_key["mfds_product"].value == "가스 마취기"
    assert by_key["company"].value == "(주)게팅게메디칼코리아"
    assert by_key["grade"].value == "3등급"
    assert by_key["detail_class"].value == "가스마취기 (4227250101)"
    assert (by_key["model"].status, by_key["permit"].status) == ("식약처 확인", "확인됨")


def test_missing_values_keep_their_cell_and_say_not_checked():
    fields = pi.product_fields(model="ZZ-1")
    assert len(fields) == 6
    html = pi.identity_html(fields, include_css=False)
    assert html.count('class="pi-cell') == 6
    assert html.count("확인 전") >= 4  # model status, 품목명, 업체, 허가번호, 등급
    assert "—" in html  # 세부품명 without trades


def test_search_text_only_when_it_differs_from_the_model():
    assert "search" not in pi.field_map(_fields(search_text="flow-c"))
    fields = _fields(search_text="마취기 flow")
    assert pi.field_map(fields)["search"].value == "마취기 flow"
    # Still two rows of four: 세부품명 gives up its second column to 검색어.
    assert sum(field.span for field in fields) == 8


def test_several_companies_and_permits_show_the_first_and_a_count():
    fields = pi.field_map(
        _fields(companies=["A", "B", "B", "C"], permit_numbers=["제인 1 호", "제인 2 호"], permit_type="인증")
    )
    assert fields["company"].value == "A 외 2곳"
    assert fields["permit"].value == "제인 1 호 외 1건"
    assert fields["permit"].label == "식약처 인증번호"


def test_procurement_maker_fills_in_when_no_mfds_company():
    fields = pi.field_map(_fields(companies=[], procurement_maker="Philips"))
    assert fields["company"].value == "Philips"
    assert fields["company"].note == "나라장터 거래에 적힌 제조사"


def test_status_words():
    assert pi.model_status(direct_count=3) == ("나라장터 거래 확인", "ok")
    assert pi.model_status(identity_status="success", identity_match="model", ambiguous=True)[0] == "허가 여러 건"
    assert pi.model_status(identity_status="success_0")[0] == "식약처 목록에 없음"
    assert pi.model_status()[0] == "확인 전"
    assert pi.permit_status(permit="x", status_label="국내 정상") == ("판매 가능", "ok")
    assert pi.permit_status(permit="x", status_label="취소·취하(품목)")[0] == "취소됨"
    assert pi.permit_status(permit="") == ("확인 전", "muted")


def test_html_escapes_and_keeps_the_hidden_heading():
    html = pi.identity_html(_fields(model="A <b>"), marker_heading="DFM100 거래가격", include_css=False)
    assert '<div class="pi-sr"><h2>DFM100 거래가격</h2></div>' in html
    assert "A &lt;b&gt;" in html
    assert "pc-pill" in html


@dataclass
class _Candidate:
    detail_code: str
    product_title: str


def test_detail_class_comes_from_the_most_common_code():
    name, code = pi.detail_class_of(
        [
            _Candidate("4227250101", "가스마취기, 드래거, Fabius"),
            _Candidate("4227250101", "가스마취기, 드래거, Fabius plus"),
            _Candidate("4211999999", "마취기부품, 드래거, 센서"),
        ]
    )
    assert (name, code) == ("가스마취기", "4227250101")
    assert pi.detail_class_of([]) == ("", "")


@dataclass
class _Item:
    product_name: str = "환자감시장치"
    model_name: str = "M40"
    manufacturer: str = ""
    specification: str = ""
    quantity: Decimal | None = Decimal("2")
    unit: str = "대"
    unit_price: Decimal | None = Decimal("6500000")


def test_quote_fields_show_what_the_file_says_and_what_it_left_out():
    fields = pi.field_map(pi.quote_fields(_Item()))
    assert fields["model"].value == "M40"
    assert fields["product"].value == "환자감시장치"
    assert fields["quantity"].value == "2 대" and fields["quantity"].note == ""
    assert fields["price"].value == "6,500,000원"
    assert fields["maker"].value == "" and fields["maker"].empty_text == "견적서에 없음"
    assert pi.field_map(pi.quote_fields(_Item(unit="")))["quantity"].note == "단위 없음"
    assert len(pi.quote_fields(_Item())) == 6  # three rows of two in the narrow card


@dataclass
class _Record:
    model_name: str
    product_name: str = "환자감시장치"
    permit_number: str = "제인 20-5001 호"
    registered_company: str = "(주)메디아나"
    grade: str = "2"


@dataclass
class _Identity:
    status: str
    match_type: str | None
    records: tuple


@dataclass
class _Trade:
    detail_code: str = "4227160701"
    product_title: str = "환자감시장치, 메디아나, M40"
    manufacturer: str = "메디아나"


def test_matched_fields_use_a_model_level_identity_and_the_trades():
    fields = pi.field_map(
        pi.matched_product_fields(
            identity=_Identity("success", "model", (_Record("M40"),)),
            candidates=[_Trade(), _Trade()],
            fallback_model="m40",
            status_labels={"제인20-5001호": "국내 정상"},
        )
    )
    assert fields["model"].value == "M40" and fields["model"].status == "식약처 확인"
    assert fields["company"].value == "(주)메디아나"
    assert fields["permit"].label == "식약처 인증번호" and fields["permit"].status == "판매 가능"
    assert fields["grade"].value == "2등급"
    assert fields["detail_class"].value == "환자감시장치 (4227160701)"
    assert fields["detail_class"].note == "같은 제품 거래 2건 기준"


def test_matched_fields_ignore_a_product_level_hit():
    fields = pi.field_map(
        pi.matched_product_fields(
            identity=_Identity("success", "product", (_Record("다른모델"),)), fallback_model="ZZ-9"
        )
    )
    assert fields["model"].value == "ZZ-9" and fields["model"].status == "확인 전"
    assert fields["company"].value == "" and fields["permit"].value == ""


def test_result_header_uses_the_grid_and_keeps_the_smoke_heading():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "pages" / "1_대시보드.py").read_text(encoding="utf-8")
    assert "product_identity_ui.identity_html(" in source
    assert 'marker_heading=f"{search_text or heading} 거래가격"' in source
    # The 같은 품목 시장 follows the result's 거래 기간.
    assert "category_market_service.within_period(" in source


def test_pair_puts_quote_values_next_to_the_matched_product():
    html = pi.pair_html(pi.quote_fields(_Item()), _fields(), include_css=False)
    assert html.index("견적서에 적힌 값") < html.index("확인된 제품")
    assert "6,500,000원" in html and "Flow-c" in html
