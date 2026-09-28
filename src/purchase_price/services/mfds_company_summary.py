from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

from purchase_price.services.matching import normalize_text


@dataclass(frozen=True)
class MfdsRegisteredCompanySummary:
    company_name: str
    registered_model_count: int
    permit_count: int
    latest_permit_date: str | None
    representative_models: tuple[str, ...]
    direct_price_model_count: int
    procurement_suppliers: tuple[str, ...]
    live_status: str


def _text(value: Any) -> str:
    return str(value or "").strip()


def _date_key(value: Any) -> tuple[int, str]:
    text = _text(value)
    if not text:
        return (0, "")
    normalized = text.replace("-", "").replace("/", "")
    try:
        parsed = datetime.strptime(normalized[:8], "%Y%m%d").date()
    except ValueError:
        return (0, text)
    return (1, parsed.isoformat())


def _identity_key(item: Any) -> tuple[str, str]:
    return (
        normalize_text(getattr(item, "permit_number", None)),
        normalize_text(getattr(item, "model_name", None)),
    )


def _crosslink_index(
    rows: Iterable[dict[str, object]],
) -> dict[tuple[str, str], dict[str, object]]:
    index: dict[tuple[str, str], dict[str, object]] = {}
    for row in rows:
        key = (
            normalize_text(row.get("식약처 품목번호")),
            normalize_text(row.get("모델")),
        )
        if any(key):
            index[key] = row
    return index


def build_registered_company_summaries(
    identity_records: Iterable[Any],
    *,
    procurement_crosslinks: Iterable[dict[str, object]] = (),
    active_live_keys: set[tuple[str, str]] | None = None,
) -> tuple[MfdsRegisteredCompanySummary, ...]:
    """Aggregate MFDS product-responsible companies without conflating them with suppliers.

    When active_live_keys is None, live cancellation/export status was not available. Indexed
    identity rows may still be summarized, but the output is explicitly marked live-status
    unverified. When live keys are provided, only permit+model pairs confirmed as domestic-active
    candidates are included.
    """

    crosslinks = _crosslink_index(procurement_crosslinks)
    grouped: dict[str, list[Any]] = {}
    company_display: dict[str, str] = {}

    for item in identity_records:
        company = _text(getattr(item, "registered_company", None))
        model = _text(getattr(item, "model_name", None))
        if not company or not model:
            continue
        key = _identity_key(item)
        if active_live_keys is not None and key not in active_live_keys:
            continue
        company_key = normalize_text(company)
        if not company_key:
            continue
        grouped.setdefault(company_key, []).append(item)
        company_display.setdefault(company_key, company)

    summaries: list[MfdsRegisteredCompanySummary] = []
    for company_key, items in grouped.items():
        models = sorted(
            {
                _text(getattr(item, "model_name", None))
                for item in items
                if _text(getattr(item, "model_name", None))
            }
        )
        permits = {
            _text(getattr(item, "permit_number", None))
            for item in items
            if _text(getattr(item, "permit_number", None))
        }
        permit_dates = [
            _text(getattr(item, "permit_date", None))
            for item in items
            if _text(getattr(item, "permit_date", None))
        ]
        latest_permit_date = max(permit_dates, key=_date_key) if permit_dates else None

        direct_models: set[str] = set()
        suppliers: set[str] = set()
        for item in items:
            row = crosslinks.get(_identity_key(item))
            if row is None:
                continue
            direct_count = row.get("나라장터 직접거래")
            try:
                has_direct = int(direct_count or 0) > 0
            except (TypeError, ValueError):
                has_direct = False
            if has_direct:
                model = _text(getattr(item, "model_name", None))
                if model:
                    direct_models.add(model)
            raw_suppliers = _text(row.get("실제 조달 공급업체"))
            for supplier in raw_suppliers.split("/"):
                supplier = supplier.strip()
                if supplier:
                    suppliers.add(supplier)

        summaries.append(
            MfdsRegisteredCompanySummary(
                company_name=company_display[company_key],
                registered_model_count=len(models),
                permit_count=len(permits),
                latest_permit_date=latest_permit_date,
                representative_models=tuple(models[:5]),
                direct_price_model_count=len(direct_models),
                procurement_suppliers=tuple(sorted(suppliers)),
                live_status=(
                    "국내 정상 확인"
                    if active_live_keys is not None
                    else "live 상태 미확인"
                ),
            )
        )

    return tuple(
        sorted(
            summaries,
            key=lambda item: (
                -item.direct_price_model_count,
                -item.registered_model_count,
                normalize_text(item.company_name),
            ),
        )
    )


def company_identity_rows(
    identity_records: Iterable[Any],
    company_name: str,
    *,
    active_live_keys: set[tuple[str, str]] | None = None,
) -> list[dict[str, str]]:
    company_key = normalize_text(company_name)
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in identity_records:
        if normalize_text(getattr(item, "registered_company", None)) != company_key:
            continue
        key = _identity_key(item)
        is_live = active_live_keys is not None and key in active_live_keys
        dedupe = (
            _text(getattr(item, "permit_number", None)),
            _text(getattr(item, "model_name", None)),
            _text(getattr(item, "udi_di", None)),
        )
        if dedupe in seen:
            continue
        seen.add(dedupe)
        rows.append(
            {
                "모델": _text(getattr(item, "model_name", None)),
                "식약처 품목번호": _text(getattr(item, "permit_number", None)),
                "UDI-DI": _text(getattr(item, "udi_di", None)),
                "식약처 처리일": _text(getattr(item, "permit_date", None)),
                "상태": (
                    "국내 정상 확인"
                    if is_live
                    else "live 상태 미확인"
                    if active_live_keys is None
                    else "기본표 제외 상태"
                ),
            }
        )
    rows.sort(
        key=lambda row: (
            row["상태"] != "국내 정상 확인",
            row["모델"],
            row["식약처 품목번호"],
        )
    )
    return rows
