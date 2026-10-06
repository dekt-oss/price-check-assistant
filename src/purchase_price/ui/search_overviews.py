"""Company-centric and product-centric search results (#221 §9.4, §9.5).

A search that matches an MFDS 품목 책임주체 (company) or 품목명 (product name) exactly is not a
single product, so it must not open the product workspace with the company injected as the
manufacturer. These builders turn the MFDS identity records plus the per-model 나라장터 direct
evidence (the same crosslink rows the 동일품목 비교 table uses) into overview tables.

Company identity across sources: the MFDS product info and 업허가 data carry no 사업자등록번호,
and the price index does not store the supplier's, so a 나라장터 supplier whose name equals the
MFDS company is shown as "명칭 일치 · 사업자번호 미확인", never as the same company.

New module so a Streamlit hot reload that keeps older modules never sees a partial import.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any

from purchase_price.services.matching import normalize_text
from purchase_price.ui.same_item_compare import price_bounds

NAME_MATCH_LABEL = "명칭 일치 · 사업자번호 미확인"
OVERVIEW_ROUTES = ("company_overview", "product_overview")


_LEGAL_FORM_PREFIXES = ("(주)", "주식회사 ", "(유)", "유한회사 ")
_LEGAL_FORM_SUFFIXES = ("(주)", " 주식회사", " 유한회사", "(유)")


def company_name_variants(text: str) -> list[str]:
    """Registered spellings to try when a typed company name has no legal form.

    MFDS stores names like "(주)메디아나" or "주식회사 라디안큐바이오", and the identity index
    matches the whole normalized name, so "메디아나" alone finds nothing. Only these exact
    legal-form spellings are tried (no partial or fuzzy matching).
    """

    core = " ".join(str(text or "").split())
    if len(core) < 2 or any(core.startswith(p.strip()) or core.endswith(p.strip()) for p in _LEGAL_FORM_PREFIXES + _LEGAL_FORM_SUFFIXES):
        return []
    return [f"{prefix}{core}" for prefix in _LEGAL_FORM_PREFIXES] + [f"{core}{suffix}" for suffix in _LEGAL_FORM_SUFFIXES]


def _text(value: object) -> str:
    return str(value or "").strip()


def _key(permit: object, model: object) -> tuple[str, str]:
    return normalize_text(_text(permit)), normalize_text(_text(model))


def _count(row: Mapping[str, object] | None) -> int:
    try:
        return int((row or {}).get("나라장터 직접거래") or 0)
    except (TypeError, ValueError):
        return 0


def _range_text(low: Decimal | None, high: Decimal | None) -> str:
    if low is None or high is None:
        return ""
    return f"{low:,.0f}원" if low == high else f"{low:,.0f} ~ {high:,.0f}원"


def _crosslink_index(crosslinks: Iterable[Mapping[str, object]]) -> dict[tuple[str, str], Mapping[str, object]]:
    return {_key(row.get("식약처 품목번호"), row.get("모델")): row for row in crosslinks}


def company_product_rows(
    records: Sequence[Any],
    crosslinks: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """One row per MFDS 품목 the company is responsible for, busiest procurement first."""

    links = _crosslink_index(crosslinks)
    groups: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"models": {}, "permits": set(), "trades": 0, "low": None, "high": None, "latest": ""}
    )
    for record in records:
        product = _text(getattr(record, "product_name", None)) or "품목 미확인"
        model = _text(getattr(record, "model_name", None))
        permit = _text(getattr(record, "permit_number", None))
        group = groups[product]
        if permit:
            group["permits"].add(permit)
        if not model:
            continue
        link = links.get(_key(permit, model))
        count = _count(link)
        group["models"][model] = max(group["models"].get(model, 0), count)
        if link is None or not count:
            continue
        bounds = price_bounds(link.get("나라장터 가격범위"))
        if bounds:
            group["low"] = bounds[0] if group["low"] is None else min(group["low"], bounds[0])
            group["high"] = bounds[1] if group["high"] is None else max(group["high"], bounds[1])
        group["latest"] = max(group["latest"], _text(link.get("최근거래")))

    rows: list[dict[str, object]] = []
    for product, group in groups.items():
        models: dict[str, int] = group["models"]
        trades = sum(models.values())
        priced = sorted((m for m, c in models.items() if c), key=lambda m: -models[m])
        unpriced = sorted(m for m, c in models.items() if not c)
        rows.append(
            {
                "품목": product,
                "등록 모델": len(models),
                "식약처 품목번호": len(group["permits"]),
                "조달가격 있는 모델": len(priced),
                "나라장터 거래": f"{trades}건",
                "가격범위": _range_text(group["low"], group["high"]),
                "최근거래": group["latest"],
                "대표 모델": " / ".join((priced + unpriced)[:3]),
                "_trades": trades,
            }
        )
    rows.sort(key=lambda row: (-int(row["_trades"]), -int(row["등록 모델"]), str(row["품목"])))
    for row in rows:
        row.pop("_trades")
    return rows


def company_model_rows(
    records: Sequence[Any],
    crosslinks: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Every registered model of the company with its direct 나라장터 evidence."""

    links = _crosslink_index(crosslinks)
    seen: set[tuple[str, str]] = set()
    rows: list[dict[str, object]] = []
    for record in records:
        model = _text(getattr(record, "model_name", None))
        permit = _text(getattr(record, "permit_number", None))
        key = _key(permit, model)
        if not model or key in seen:
            continue
        seen.add(key)
        link = links.get(key) or {}
        kind = _text(link.get("유형"))
        rows.append(
            {
                "품목": _text(getattr(record, "product_name", None)),
                "모델": model,
                "식약처 품목번호": f"[{kind}] {permit}" if kind and permit else permit,
                "나라장터 거래": "조회 불가" if link and link.get("나라장터 직접거래") is None else f"{_count(link)}건",
                "가격범위": _text(link.get("나라장터 가격범위")) if _count(link) else "",
                "최근거래": _text(link.get("최근거래")),
                "실제 납품업체": _text(link.get("실제 조달 공급업체")),
                "_trades": _count(link),
            }
        )
    rows.sort(key=lambda row: (-int(row["_trades"]), str(row["품목"]), str(row["모델"])))
    for row in rows:
        row.pop("_trades")
    return rows


def classification_rows(records: Sequence[Any]) -> list[dict[str, object]]:
    """Product-name search: one row per MFDS 분류번호 and 등급 under that 품목명."""

    groups: dict[tuple[str, str, str], dict[str, set[str]]] = defaultdict(
        lambda: {"companies": set(), "models": set(), "permits": set()}
    )
    for record in records:
        key = (
            _text(getattr(record, "classification_no", None)) or "분류번호 미확인",
            _text(getattr(record, "grade", None)) or "미확인",
            _text(getattr(record, "product_name", None)),
        )
        group = groups[key]
        for name, attr in (("companies", "registered_company"), ("models", "model_name"), ("permits", "permit_number")):
            value = _text(getattr(record, attr, None))
            if value:
                group[name].add(value)
    rows = [
        {
            "분류번호": classification,
            "등급": grade,
            "품목": product,
            "품목 책임주체": len(group["companies"]),
            "등록 모델": len(group["models"]),
            "식약처 품목번호": len(group["permits"]),
        }
        for (classification, grade, product), group in groups.items()
    ]
    rows.sort(key=lambda row: (-int(row["등록 모델"]), str(row["분류번호"])))
    return rows


def supplier_summary_row(summary: Mapping[str, object] | None, company: str) -> dict[str, object] | None:
    """The company as an actual 나라장터 supplier, matched by name only."""

    if not summary or not int(summary.get("trade_count") or 0):
        return None
    return {
        "나라장터 납품업체명": " / ".join(summary.get("matched_names") or ()) or company,
        "업체 동일성": NAME_MATCH_LABEL,
        "납품 건수": int(summary.get("trade_count") or 0),
        "납품 모델 수": int(summary.get("model_count") or 0),
        "구매기관 수": int(summary.get("institution_count") or 0),
        "최근 납품일": _text(summary.get("latest")),
        "많이 납품한 모델": " / ".join(summary.get("top_models") or ()),
    }
