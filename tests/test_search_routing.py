from __future__ import annotations

from pathlib import Path

import pytest

from purchase_price.services import search_routing as sr

DASHBOARD = Path("pages/1_대시보드.py")


# ── 1. 허가번호 in any spacing ──


@pytest.mark.parametrize(
    "typed",
    ["제허 19-527 호", "제허19-527", "제허19-527호", "제허 19 527", "제허19527호", " 제허 19-527호 ", "제허 제19-527호"],
)
def test_permit_number_is_recognised_in_any_spacing(typed: str) -> None:
    permit = sr.parse_permit_number(typed)
    assert permit is not None
    assert permit.display == "제허 19-527 호"
    assert permit.key == "제허19527호"


@pytest.mark.parametrize(
    ("typed", "display"),
    [
        ("수허17-398", "수허 17-398 호"),
        ("제인 00-1", "제인 00-1 호"),
        ("수인99-988호", "수인 99-988 호"),
        ("제신 26-993", "제신 26-993 호"),
        ("수신00-1972", "수신 00-1972 호"),
        ("서울 체외 수신 03-313", "서울 체외 수신 03-313 호"),
        ("체외제허26-97호", "체외 제허 26-97 호"),
    ],
)
def test_every_permit_kind_and_region_keeps_the_stored_spelling(typed: str, display: str) -> None:
    permit = sr.parse_permit_number(typed)
    assert permit is not None and permit.display == display


@pytest.mark.parametrize("typed", ["HeartOn A16-DS", "DFM100", "제허", "제허 19", "허가 19-527", "제허 19-0", ""])
def test_non_permit_text_is_not_a_permit(typed: str) -> None:
    assert sr.parse_permit_number(typed) is None


def test_permit_attempt_detection_for_the_hint() -> None:
    assert sr.looks_like_permit_attempt("제허19")
    assert sr.looks_like_permit_attempt("서울 수신 1")
    assert not sr.looks_like_permit_attempt("메디아나")


def test_dashboard_routes_permits_to_the_model_or_a_permit_picker() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    assert "permit = search_routing.parse_permit_number(lookup_key)" in source
    assert "lookup_key = permit.display" in source
    assert 'and indexed_identity.match_type == "permit"\n    ):' in source
    assert "return _build_permit_picker_state(raw_search, indexed_identity, snapshot_runtime)" in source
    assert '"review_reason": "permit"' in source
    assert "이 허가번호에 등록된 모델이 여러 개입니다" in source
    # The permit branch runs before the company/product overview and the ambiguity picker.
    assert source.index("return _build_permit_picker_state(") < source.index(
        'and indexed_identity.match_type in {"company", "product"}'
    )


# ── 3. A Korean word that is no 식약처 품목명 ──


def test_word_pieces_put_the_head_noun_first() -> None:
    assert sr.word_pieces("수액펌프") == ["액펌프", "수액펌", "펌프", "액펌", "수액"]
    assert sr.word_pieces("수액 펌프") == sr.word_pieces("수액펌프")
    assert sr.word_pieces("a") == []


def test_name_suggestions_share_the_meaningful_part() -> None:
    pieces = sr.word_pieces("수액펌프")
    rows = [
        {"name": "전동식 의약품 주입 펌프", "key": "전동식의약품주입펌프", "companies": 40, "models": 129},
        {"name": "수동식 의약품 주입 펌프", "key": "수동식의약품주입펌프", "companies": 22, "models": 4363},
        {"name": "일반 수액세트", "key": "일반수액세트", "companies": 90, "models": 900},
        {"name": "환자감시장치", "key": "환자감시장치", "companies": 23, "models": 184},
    ]
    ranked = sr.rank_name_suggestions(rows, pieces)
    names = [item.name for item in ranked]
    # "펌프" (the word end) before "수액"; most companies first within the same part.
    assert names == ["전동식 의약품 주입 펌프", "수동식 의약품 주입 펌프", "일반 수액세트"]
    assert ranked[0].shared == "펌프"
    assert "환자감시장치" not in names


def test_only_whole_words_count_as_the_meaningful_part() -> None:
    names = ["전동식 의약품 주입 펌프", "심폐용 혈액펌프", "전동식 의약품 주입 펌프용 수액세트"]
    assert sr.meaningful_pieces(sr.word_pieces("수액펌프"), names) == ["펌프"]
    pieces = sr.meaningful_pieces(sr.word_pieces("수액펌프"), names)
    rows = [
        {"name": "심폐용 혈액펌프", "companies": 4},
        {"name": "전동식 의약품 주입 펌프", "companies": 40},
    ]
    assert [s.name for s in sr.rank_name_suggestions(rows, pieces)] == ["전동식 의약품 주입 펌프", "심폐용 혈액펌프"]
    # Without spaced names every piece is kept.
    assert sr.meaningful_pieces(["액펌프", "펌프"], ["의약품주입펌프"]) == ["액펌프", "펌프"]


def test_matching_keys_is_one_pass_over_the_names() -> None:
    assert sr.matching_keys(["의약품주입펌프", "소방용펌프", "환자감시장치", ""], ["펌프"]) == [
        "의약품주입펌프",
        "소방용펌프",
    ]


def test_dashboard_shows_the_empty_state_with_suggestions_for_unknown_korean_words() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    assert '"route": NO_MATCH_ROUTE' in source
    assert '"suggestions": _name_suggestions(raw_search, snapshot_runtime)' in source
    assert "_render_no_match(search_state)" in source
    assert "search_routing.MEDICAL_DETAIL_PREFIX" in source
    # Category words with 식약처 품목명 still go to the picker first (환자감시장치, 가스마취기).
    assert source.index('"route": overview_ui.CATEGORY_ROUTE') < source.index('"route": NO_MATCH_ROUTE')


# ── 4. Korean names of foreign makers (search expansion only) ──


def test_company_needles_expand_known_maker_names_both_ways() -> None:
    assert sr.company_search_needles("필립스") == ("필립스", "한국필립스", "필립스코리아", "philips")
    assert set(sr.company_search_needles("Philips")) == {"philips", "필립스", "한국필립스", "필립스코리아"}
    assert "필립스" in sr.company_search_needles("한국필립스")
    assert "지이헬스케어" in sr.company_search_needles("GE헬스케어")
    assert "siemens" in sr.company_search_needles("지멘스")
    assert "draeger" in sr.company_search_needles("드레거")
    assert "medtronic" in sr.company_search_needles("메드트로닉")
    assert "mindray" in sr.company_search_needles("마인드레이")
    assert "nihonkohden" in sr.company_search_needles("니혼코덴")
    # Outside the map the word is searched as itself (no invented names).
    assert sr.company_search_needles("(주)나눔테크") == ("나눔테크",)
    assert sr.company_search_needles("a") == ()


def test_company_matching_uses_the_name_without_legal_form() -> None:
    assert sr.company_matches_needle("(주)필립스코리아", "필립스")
    assert sr.company_matches_needle("주식회사 필립스코리아", "필립스코리아")
    assert not sr.company_matches_needle("(주)메디아나", "필립스")
    # Short needles ("ge", "지이") only match a whole name.
    assert not sr.company_matches_needle("(주)지이엠", "지이")
    assert sr.company_matches_needle("지이", "지이")


def test_rank_company_matches_keeps_registered_names_and_orders_by_size() -> None:
    needles = sr.company_search_needles("필립스")
    ranked = sr.rank_company_matches(
        [("(주)필립스전자", 82), ("(주)필립스코리아", 701), ("(주)메디아나", 900)], needles
    )
    assert [match.name for match in ranked] == ["(주)필립스코리아", "(주)필립스전자"]
    assert ranked[0].source == "식약처"
    suppliers = sr.rank_company_matches([("주식회사 필립스코리아", 33)], needles, source="나라장터")
    assert suppliers[0].name == "주식회사 필립스코리아" and suppliers[0].source == "나라장터"


def test_dashboard_tries_partial_company_names_before_the_empty_state() -> None:
    source = DASHBOARD.read_text(encoding="utf-8")
    assert "company_state = _partial_company_overview(raw_search, snapshot_runtime, prefer_traded_company)" in source
    assert source.index("_partial_company_overview(raw_search, snapshot_runtime") < source.index(
        '"route": NO_MATCH_ROUTE'
    )
    assert 'state["matched_from"] = raw_search' in source
    assert "업체 이름은 바꾸지 않고 등록된 그대로 보여줍니다" in source
