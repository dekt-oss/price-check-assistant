from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from purchase_price.ui import same_item_compare as same


def _link(model, permit, company, count, *, current=False, kind="허가"):
    return {
        "유형": kind,
        "식약처 품목번호": permit,
        "모델": model,
        "현재 모델": "현재 모델" if current else "",
        "품목 책임주체": company,
        "나라장터 직접거래": count,
        "나라장터 가격범위": f"{count}원" if count else "직접 동일성 확인 거래 0건",
        "최근거래": "2026-10-01" if count else "",
        "실제 조달 공급업체": "납품사" if count else "",
    }


def _record(model, permit, *, cancelled=False, export=False):
    return SimpleNamespace(
        model_name=model,
        permit_number=permit,
        cancellation_status="3" if cancelled else None,
        active_for_domestic_candidate=not cancelled and not export,
    )


LINKS = [
    _link("B1", "제허 2", "B사", 2),
    _link("A1", "제허 1", "A사", 7, current=True),
    _link("A2", "제허 1", "A사", 0),
    _link("A3", "제허 3", "A사", 4),
    _link("C1", "제허 9", "C사", 5),
]


def test_status_index_prefers_active_and_needs_loading() -> None:
    index = same.live_status_index(
        [_record("A1", "제허 1"), _record("A3", "제허 3", cancelled=True), _record("A3", "제허 3"), _record("C1", "제허 9", cancelled=True)]
    )
    assert same.live_status_index(None) is None
    assert set(index.values()) == {same.STATUS_ACTIVE, same.STATUS_CANCELLED}


def test_rows_group_by_company_with_current_first_and_default_filters() -> None:
    index = same.live_status_index([_record("A1", "제허 1"), _record("A3", "제허 3"), _record("C1", "제허 9", cancelled=True), _record("B1", "제허 2")])
    view = same.build_same_item_rows(LINKS, index)

    assert [row["모델"] for row in view.rows] == ["▶ A1", "A3", "B1"]
    assert [row["품목 책임주체"] for row in view.rows] == ["A사", "", "B사"]
    assert view.rows[0]["식약처 품목번호"] == "[허가] 제허 1"
    assert view.rows[0]["식약처 상태"] == same.STATUS_ACTIVE
    assert view.hidden_unpriced == 1 and view.hidden_inactive == 1
    assert same.hidden_note(view) == "숨김 · 조달가격 없는 모델 1개 · 취소·취하·수출용 1개"


def test_filters_can_show_everything() -> None:
    index = same.live_status_index([_record("C1", "제허 9", cancelled=True)])
    view = same.build_same_item_rows(LINKS, index, include_unpriced=True, include_inactive=True)

    assert len(view.rows) == len(LINKS)
    assert {row["식약처 상태"] for row in view.rows} == {same.STATUS_CANCELLED, same.STATUS_UNKNOWN}


def test_unloaded_status_is_unknown_never_active_and_current_model_always_kept() -> None:
    links = [_link("A1", "제허 1", "A사", 0, current=True), _link("X", "제허 5", "A사", 0)]
    view = same.build_same_item_rows(links, None)

    assert [row["모델"] for row in view.rows] == ["▶ A1"]
    assert view.rows[0]["식약처 상태"] == same.STATUS_UNKNOWN
    assert view.status_loaded is False
    assert view.rows[0]["나라장터 거래"] == "0건"


def test_unavailable_price_is_not_zero() -> None:
    link = _link("A1", "제허 1", "A사", 0, current=True)
    link["나라장터 직접거래"] = None
    view = same.build_same_item_rows([link], None)
    assert view.rows[0]["나라장터 거래"] == "조회 불가"


def test_dashboard_tabs_use_plain_headings() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")
    supplier = source.index('elif selected_view == "supplier":')
    assert source.index("#### 실제 납품업체 · 나라장터", supplier) < source.index(
        "#### 품목 책임주체 · 식약처에 등록한 제조·수입업체", supplier
    )
    assert '"조달가격 있는 것만"' in source and '"취소·취하·수출용 포함"' in source
    assert 'id="purchase-workspace-runtime-v12"' in source
    for jargon in ("Identity Index", '"exact 모델"', "식약처 live", "식약처 품목·Identity"):
        assert jargon not in source


def test_resolved_identity_marks_current_model_even_when_search_text_differs() -> None:
    links = [_link("Efficia DFM100", "수허 15-1338 호", "T사", 0), _link("A1", "제허 1", "A사", 3)]
    view = same.build_same_item_rows(links, None, current_keys=[("수허 15-1338 호", "Efficia DFM100")])

    assert view.rows[0]["모델"] == "▶ Efficia DFM100"
    assert view.hidden_unpriced == 0


def test_status_notes_explain_unknown_rows_and_missing_current_model() -> None:
    index = same.live_status_index([_record("A1", "제허 1")])
    links = [{**link, "현재 모델": ""} for link in LINKS]
    view = same.build_same_item_rows(links, index, current_keys=[("수허 15-1338 호", "Efficia DFM100")])
    notes = same.status_notes(view)

    assert any("상태 미확인" in note and "형명 조회 결과에 없던" in note for note in notes)
    assert any("검색한 모델은 아직" in note for note in notes)
    assert same.status_notes(same.build_same_item_rows(LINKS, None))[0].startswith("식약처 상태는 상단 버튼")
