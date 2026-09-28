from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from purchase_price.schemas import ProductQuery
from purchase_price.services.mfds_identity_index import MfdsIdentityRecord
from purchase_price.services.mfds_identity_presenter import mfds_item_authorization_type


def _grade(candidate: Any) -> str:
    value = getattr(candidate, "match_grade", None)
    return str(getattr(value, "value", value) or "").strip().upper()


def _direct_candidates(comparison: Any) -> tuple[Any, ...]:
    return tuple(
        candidate
        for candidate in tuple(getattr(comparison, "candidates", ()) or ())
        if _grade(candidate) in {"A", "B"}
    )


def build_company_procurement_rows(
    records: Sequence[MfdsIdentityRecord],
    *,
    track_b_snapshot: Any,
) -> list[dict[str, object]]:
    """Cross-link one MFDS responsible company's products to procurement evidence.

    The relationship is deliberately asymmetric: MFDS records establish product
    responsibility while G2B records establish observed suppliers. Matching names
    never upgrades the relationship to distributor/dealer/authorized seller.
    """

    unique: dict[tuple[str, str, str, str], MfdsIdentityRecord] = {}
    for record in records:
        model = str(record.model_name or "").strip()
        product = str(record.product_name or "").strip()
        if not model or not product:
            continue
        key = (
            str(record.permit_number or "").strip(),
            model,
            product,
            str(record.registered_company or "").strip(),
        )
        unique.setdefault(key, record)

    items = list(unique.values())
    if not items:
        return []

    queries = tuple(
        ProductQuery(
            product_name=str(item.product_name or "").strip(),
            model_name=str(item.model_name or "").strip(),
        )
        for item in items
    )
    comparisons = track_b_snapshot.lookup_model_summaries(queries)

    rows: list[dict[str, object]] = []
    for item, comparison in zip(items, comparisons, strict=True):
        direct = _direct_candidates(comparison)
        prices = sorted(
            Decimal(str(candidate.price))
            for candidate in direct
            if getattr(candidate, "price", None) is not None
        )
        suppliers = sorted(
            {
                str(getattr(candidate, "supplier", "") or "").strip()
                for candidate in direct
                if str(getattr(candidate, "supplier", "") or "").strip()
            }
        )
        dates = sorted(
            str(getattr(candidate, "transaction_date", "") or "").strip()
            for candidate in direct
            if str(getattr(candidate, "transaction_date", "") or "").strip()
        )
        evidence_status = str(
            getattr(getattr(comparison, "evidence_status", None), "value", "")
            or getattr(comparison, "status", "")
            or "미확인"
        )
        rows.append(
            {
                "유형": mfds_item_authorization_type(item).value,
                "식약처 품목번호": item.permit_number or "미확인",
                "품목": item.product_name or "미확인",
                "모델": item.model_name or "미확인",
                "UDI-DI": item.udi_di or "미확인",
                "품목 책임주체": item.registered_company or "미확인",
                "조달 상태": evidence_status,
                "A/B 직접거래": len(direct) if evidence_status != "UNAVAILABLE" else None,
                "실제 조달 납품업체": " / ".join(suppliers) or "미확인",
                "가격범위": (
                    f"{prices[0]:,.0f} ~ {prices[-1]:,.0f}원"
                    if prices
                    else "조회 불가"
                    if evidence_status == "UNAVAILABLE"
                    else "직접 동일성 확인 거래 0건"
                ),
                "최근거래": dates[-1] if dates else "미확인",
                "data_as_of": getattr(comparison, "data_as_of", None) or "미확인",
            }
        )
    return rows
