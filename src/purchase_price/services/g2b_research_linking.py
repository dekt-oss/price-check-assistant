from __future__ import annotations

import re
from dataclasses import dataclass

from purchase_price.services.g2b_market_models import G2BResearchRecord, G2BResearchSource

_BID_NO_PATTERN = re.compile(r"[A-Z]\d{2}[A-Z]{2}\d+|\d{4,}-\d+|\d{8,}", re.IGNORECASE)


@dataclass(frozen=True)
class LinkedProcurementCase:
    """A research-only group connected by a public G2B bid notice identifier."""

    bid_notice_no: str
    bid_notices: tuple[G2BResearchRecord, ...] = ()
    bid_items: tuple[G2BResearchRecord, ...] = ()
    awards: tuple[G2BResearchRecord, ...] = ()
    prespecs: tuple[G2BResearchRecord, ...] = ()
    contracts: tuple[G2BResearchRecord, ...] = ()

    @property
    def has_award(self) -> bool:
        return bool(self.awards)

    @property
    def has_prespec(self) -> bool:
        return bool(self.prespecs)

    @property
    def has_item_detail(self) -> bool:
        return bool(self.bid_items)

    @property
    def has_contract(self) -> bool:
        return bool(self.contracts)


def normalize_bid_notice_no(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", "", value).upper()


def bid_notice_numbers(record: G2BResearchRecord) -> tuple[str, ...]:
    """Extract linkable bid identifiers without inventing relationships.

    Bid, item-detail, award and contract records normally expose one identifier. Pre-specification
    responses may expose a comma/space-delimited `bidNtceNoList`; only strings that look like public
    notice identifiers are admitted. Records with no explicit identifier remain unlinked research
    results.
    """

    raw = record.bid_notice_no or ""
    direct = normalize_bid_notice_no(raw)
    if record.source_type in {
        G2BResearchSource.BID_NOTICE,
        G2BResearchSource.BID_ITEM,
        G2BResearchSource.AWARD,
        G2BResearchSource.CONTRACT,
    }:
        return (direct,) if direct else ()

    matches = [normalize_bid_notice_no(match.group(0)) for match in _BID_NO_PATTERN.finditer(raw)]
    output: list[str] = []
    seen: set[str] = set()
    for value in matches:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return tuple(output)


def link_procurement_cases(
    records: tuple[G2BResearchRecord, ...] | list[G2BResearchRecord],
) -> tuple[LinkedProcurementCase, ...]:
    """Group explicit bid/item/award/pre-spec/contract links by bid notice number.

    This does not infer a link from title similarity, institution or price. Such fuzzy relations
    can be useful for discovery but are not strong enough to claim that an award or contract belongs
    to a bid.
    """

    groups: dict[str, dict[G2BResearchSource, list[G2BResearchRecord]]] = {}
    for record in records:
        for notice_no in bid_notice_numbers(record):
            source_group = groups.setdefault(notice_no, {})
            source_group.setdefault(record.source_type, []).append(record)

    cases: list[LinkedProcurementCase] = []
    for notice_no, source_group in groups.items():
        cases.append(
            LinkedProcurementCase(
                bid_notice_no=notice_no,
                bid_notices=tuple(source_group.get(G2BResearchSource.BID_NOTICE, ())),
                bid_items=tuple(source_group.get(G2BResearchSource.BID_ITEM, ())),
                awards=tuple(source_group.get(G2BResearchSource.AWARD, ())),
                prespecs=tuple(source_group.get(G2BResearchSource.PRESPEC, ())),
                contracts=tuple(source_group.get(G2BResearchSource.CONTRACT, ())),
            )
        )
    return tuple(sorted(cases, key=lambda item: item.bid_notice_no, reverse=True))
