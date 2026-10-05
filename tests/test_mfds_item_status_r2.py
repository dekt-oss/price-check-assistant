from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from purchase_price.scripts import sync_mfds_item_status_index as sync_module
from purchase_price.services import mfds_item_status_r2 as r2
from purchase_price.services.mfds_item_status_index import MfdsItemStatus
from purchase_price.ui import same_item_compare as same


def _status(*, active: bool, cancelled: bool = False, export: bool | None = False) -> MfdsItemStatus:
    return MfdsItemStatus(
        item_number="제허 1 호",
        product_name="심장충격기",
        permission_type="허가",
        permit_date="2020-01-01",
        domestic_active=active,
        cancellation_status="3" if cancelled else None,
        cancellation_date=None,
        export_only=export,
    )


def test_state_names_match_the_collector() -> None:
    assert r2.ITEM_STATUS_POINTER_STATE == sync_module.POINTER_STATE
    assert r2.ITEM_STATUS_POINTER_SCHEMA == sync_module.POINTER_SCHEMA
    assert r2.ITEM_STATUS_PIPELINE_STATE == sync_module.PIPELINE_STATE


def test_labels_are_fail_closed_until_a_cycle_is_verified() -> None:
    assert r2.item_status_label(_status(active=True), cycle_verified=False) == "국내 정상(품목)"
    assert r2.item_status_label(_status(active=False, cancelled=True), cycle_verified=False) is None
    assert r2.item_status_label(_status(active=False, cancelled=True), cycle_verified=True) == "취소·취하(품목)"
    assert r2.item_status_label(_status(active=False, export=True), cycle_verified=True) == "수출용(품목)"
    assert r2.item_status_label(_status(active=False, export=None), cycle_verified=True) is None
    assert r2.item_status_label(None, cycle_verified=True) is None


def test_lookup_never_raises(monkeypatch) -> None:
    r2.reset_cache_for_tests()

    def boom(_settings):
        raise RuntimeError("R2 down")

    monkeypatch.setattr(r2, "_snapshot", boom)
    assert r2.lookup_item_status_from_r2(["제허 1 호"]).status == "unavailable"


def _link(model, permit, company, count, price="1,000,000 ~ 1,200,000원"):
    return {
        "유형": "허가",
        "식약처 품목번호": permit,
        "모델": model,
        "현재 모델": "",
        "품목 책임주체": company,
        "나라장터 직접거래": count,
        "나라장터 가격범위": price if count else "직접 동일성 확인 거래 0건",
        "최근거래": "",
        "실제 조달 공급업체": "",
    }


def test_item_status_fills_unknown_rows_and_hides_definitive_inactive() -> None:
    links = [_link("A", "제허 1 호", "가", 3), _link("B", "제허 2 호", "가", 2), _link("C", "제허 3 호", "나", 1)]
    view = same.build_same_item_rows(
        links,
        None,
        item_status_labels={"제허1호": "국내 정상(품목)", "제허2호": "취소·취하(품목)"},
    )

    assert [(r["모델"], r["식약처 상태"]) for r in view.rows] == [("A", "국내 정상(품목)"), ("C", "상태 미확인")]
    assert view.hidden_inactive == 1
    assert view.status_loaded is True


def test_price_gap_note_flags_rows_three_times_apart() -> None:
    links = [
        _link("AED", "제허 1 호", "가", 5, "1,650,000 ~ 1,980,000원"),
        _link("Pro", "제허 2 호", "나", 2, "10,000,000 ~ 12,000,000원"),
    ]
    view = same.build_same_item_rows(links, None, reference_price=Decimal("11550000"))

    assert view.price_gap_count == 1
    assert "1개 모델은 검색 모델 가격(중앙값 11,550,000원)과 3배 이상" in same.price_gap_note(view)
    assert same.price_bounds("직접 동일성 확인 거래 0건") is None


def test_dashboard_wires_item_status_part_warning_and_note_order() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "mfds_item_status_service.lookup_item_status_from_r2(" in source
    assert "item_status_labels=item_status_labels" in source
    assert "reference_price=stats.median_price" in source
    assert 'if "부품" in procurement_spec:' in source
    assert source.index("same_item_ui.current_model_note(same_item_view)") < source.index(
        "list(same_item_view.rows)"
    )
    assert '(same_item_ui, "ITEM_STATUS_AWARE")' in source
    assert 'id="purchase-workspace-runtime-v15"' in source
