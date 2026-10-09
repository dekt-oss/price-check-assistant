from __future__ import annotations

from decimal import Decimal

from purchase_price.services.mfds_identity_index import MfdsIdentityLookup, MfdsIdentityRecord
from purchase_price.services.mfds_item_status_index import MfdsItemStatus
from purchase_price.services.mfds_item_status_r2 import ItemStatusLookup
from purchase_price.services.quote_extraction import QuoteItem
from purchase_price.ui.quote_review_steps import _mfds_exact_confirmed


def _item(product: str = "심장충격기", model: str = "DFM100") -> QuoteItem:
    return QuoteItem(
        source_sheet="Sheet1",
        source_row=2,
        product_name=product,
        manufacturer="Philips",
        model_name=model,
        specification="",
        quantity=Decimal("1"),
        unit="대",
        unit_price=Decimal("12500000"),
    )


def _record(permit: str = "제허 19-527 호", company: str = "(주)메디아나") -> MfdsIdentityRecord:
    return MfdsIdentityRecord(
        udi_di=None,
        product_name="저출력심장충격기",
        classification_no=None,
        grade=None,
        permit_number=permit,
        permit_date=None,
        model_name="DFM100",
        trade_name=None,
        registered_company=company,
    )


def _status(permit: str, *, active: bool = True) -> MfdsItemStatus:
    return MfdsItemStatus(
        item_number=permit,
        product_name="저출력심장충격기",
        permission_type="허가",
        permit_date=None,
        domestic_active=active,
        cancellation_status=None if active else "취소",
        cancellation_date=None,
        export_only=None,
    )


def _identity(*records, status="success", match_type="model"):
    return lambda query: MfdsIdentityLookup(status, query, match_type if records else None, tuple(records))


def _statuses(*statuses: MfdsItemStatus, status="success"):
    mapping = {"".join(s.item_number.split()): s for s in statuses}
    return lambda permits: ItemStatusLookup(status, mapping)


def test_exact_model_found_in_full_index_is_confirmed_even_if_api_first_page_misses_it() -> None:
    ok, text = _mfds_exact_confirmed(
        _item(),
        identity_lookup=_identity(_record()),
        status_lookup=_statuses(_status("제허 19-527 호")),
    )

    assert ok
    assert "같은 모델 확인" in text and "제허 19-527 호" in text


def test_model_missing_from_index_is_not_confirmed() -> None:
    ok, text = _mfds_exact_confirmed(
        _item(),
        identity_lookup=_identity(status="success_0"),
        status_lookup=_statuses(),
    )

    assert not ok
    assert "찾지 못했습니다" in text


def test_product_level_hit_is_not_an_exact_model_hit() -> None:
    ok, _ = _mfds_exact_confirmed(
        _item(),
        identity_lookup=_identity(_record(), match_type="product"),
        status_lookup=_statuses(_status("제허 19-527 호")),
    )

    assert not ok


def test_same_model_under_several_permits_is_left_for_a_person() -> None:
    ok, text = _mfds_exact_confirmed(
        _item(),
        identity_lookup=_identity(_record("제허 19-527 호"), _record("제허 20-111 호", "다른업체")),
        status_lookup=_statuses(_status("제허 19-527 호"), _status("제허 20-111 호")),
    )

    assert not ok
    assert "여러 허가번호" in text


def test_cancelled_or_unknown_status_is_not_approved() -> None:
    cancelled, text = _mfds_exact_confirmed(
        _item(),
        identity_lookup=_identity(_record()),
        status_lookup=_statuses(_status("제허 19-527 호", active=False)),
    )
    unknown, unknown_text = _mfds_exact_confirmed(
        _item(),
        identity_lookup=_identity(_record()),
        status_lookup=_statuses(),
    )

    assert not cancelled and "정상 등록된 상태가 아닙니다" in text
    assert not unknown and "확인하지 못했습니다" in unknown_text


def test_unavailable_index_says_so_instead_of_not_found() -> None:
    ok, text = _mfds_exact_confirmed(
        _item(),
        identity_lookup=_identity(status="unavailable"),
        status_lookup=_statuses(),
    )

    assert not ok
    assert "조회할 수 없습니다" in text and "찾지 못" not in text


def test_product_and_model_names_are_still_required() -> None:
    def must_not_run(query):
        raise AssertionError("lookup must not run without both names")

    for item in (_item(model=" "), _item(product="")):
        ok, text = _mfds_exact_confirmed(item, identity_lookup=must_not_run)
        assert not ok
        assert "품명과 모델명이 필요" in text
