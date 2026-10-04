"""Present MFDS business-license (업허가) lookups for one registered company.

The official business-license API only supports a company-name *substring* filter (`Entrps`),
so a lookup for "메디칼" also returns every other company containing that word. This module
separates exact company matches from branch/plant registrations of the same company and from
unrelated partial-name matches, and hides closed/suspended/cancelled licenses by default.
It never turns a license into a supplier or distributor claim.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from purchase_price.services.matching import normalize_text

_LEGAL_FORM = re.compile(
    r"\(주\)|㈜|주식회사|\(유\)|유한책임회사|유한회사|합자회사|합명회사|\(사\)|사단법인|재단법인"
)
_ENGLISH_LEGAL_SUFFIX = re.compile(
    r"\b(co\.?,?\s*ltd\.?|corporation|corp\.?|inc\.?|ltd\.?|llc|gmbh|co\.?)\s*$",
    re.IGNORECASE,
)
_BRANCH_SUFFIX = re.compile(r"(지점|공장|사업장|연구소|센터|분점|출장소)$")

MATCH_LABELS = {
    "exact": "정확 일치",
    "branch": "같은 업체 지점·공장",
    "partial": "이름 일부 일치",
}


def company_core_key(value: str | None) -> str:
    """Normalized company name without legal-form markers such as (주) or 주식회사."""

    text = _LEGAL_FORM.sub(" ", value or "")
    text = _ENGLISH_LEGAL_SUFFIX.sub(" ", text.strip())
    return normalize_text(text)


def classify_company_match(query_company: str | None, record_company: str | None) -> str:
    query = company_core_key(query_company)
    record = company_core_key(record_company)
    if not query or not record:
        return "partial"
    if record == query:
        return "exact"
    if record.startswith(query) and _BRANCH_SUFFIX.search(record):
        return "branch"
    return "partial"


@dataclass(frozen=True)
class BusinessLicenseView:
    rows: tuple[dict[str, Any], ...]
    exact_or_branch_count: int
    hidden_partial_count: int
    hidden_inactive_count: int
    showing_partial_only: bool


def build_business_license_view(
    records: Iterable[Any],
    company: str,
    *,
    include_inactive: bool = False,
    include_partial: bool = False,
) -> BusinessLicenseView:
    """Order exact → branch → partial matches and apply the default filters.

    When no exact or branch match exists, partial matches are shown (flagged) instead of an
    empty table, because the user still needs to see what the substring lookup returned.
    """

    rank = {"exact": 0, "branch": 1, "partial": 2}
    classified = [
        (classify_company_match(company, getattr(record, "company_name", None)), record)
        for record in records
    ]
    active = [
        (match, record)
        for match, record in classified
        if include_inactive or bool(getattr(record, "is_active", True))
    ]
    hidden_inactive = len(classified) - len(active)
    strong = [(m, r) for m, r in active if m != "partial"]
    partial = [(m, r) for m, r in active if m == "partial"]
    showing_partial_only = not strong and bool(partial)
    shown = strong + (partial if include_partial or showing_partial_only else [])
    shown.sort(
        key=lambda item: (
            rank[item[0]],
            str(getattr(item[1], "industry_type", "") or ""),
            str(getattr(item[1], "company_name", "") or ""),
        )
    )
    rows = tuple(
        {
            "일치": MATCH_LABELS[match],
            "업종": getattr(record, "industry_type", None) or "",
            "업체": getattr(record, "company_name", None) or "",
            "영업상태": getattr(record, "business_status", None) or "",
            "업 허가·신고 번호": getattr(record, "business_permit_number", None) or "",
            "허가일": record.permit_date.isoformat()
            if getattr(record, "permit_date", None)
            else "",
            "주소": getattr(record, "address", None) or "",
        }
        for match, record in shown
    )
    return BusinessLicenseView(
        rows=rows,
        exact_or_branch_count=len(strong),
        hidden_partial_count=0 if include_partial or showing_partial_only else len(partial),
        hidden_inactive_count=hidden_inactive,
        showing_partial_only=showing_partial_only,
    )
