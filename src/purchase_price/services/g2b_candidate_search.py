from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from purchase_price.collectors.g2b_shopping import (
    G2BShoppingCollector,
    G2BShoppingOperation,
    parse_official_report_record,
)
from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.services.g2b_pagination import iter_specific_item_pages
from purchase_price.services.g2b_product_mapping import (
    G2BMappingError,
    G2BProductMapping,
    filter_g2b_query_candidates,
    records_in_mapped_classification,
    resolve_verified_g2b_mapping,
)
from purchase_price.services.product_matching import grade_product_identity, parse_g2b_identity


@dataclass(frozen=True)
class G2BCandidateSearchResult:
    mapping: G2BProductMapping
    pages_fetched: int
    records_seen: int
    records_in_classification: int
    reported_total_count: int | None
    candidate_prices: tuple[CollectedPrice, ...]


def search_mapped_g2b_candidates(
    collector: G2BShoppingCollector,
    query: ProductQuery,
    *,
    begin_date: date,
    end_date: date,
    mappings: tuple[G2BProductMapping, ...] | None = None,
    num_of_rows: int = 100,
    max_pages: int = 20,
) -> G2BCandidateSearchResult:
    """Search verified G2B history, narrow candidates, and apply conservative F3 matching.

    The G2B classification itself must already be verified. Candidate records are narrowed by
    model/manufacturer tokens and then graded from their parsed manufacturer/model/specification.
    Explicit conflicts remain X. A/B grades may enter pricing analysis only because both the
    source amount semantics (F1 EvidenceType) and the product identity (F3 MatchGrade) are known.
    """

    mapping = resolve_verified_g2b_mapping(query, mappings)
    if mapping is None or not mapping.detail_product_name:
        raise G2BMappingError(
            "No verified G2B detail-product mapping for this query; "
            "automatic classification guessing is disabled"
        )

    pages_fetched = 0
    records_seen = 0
    records_in_classification = 0
    reported_total_count: int | None = None
    prices: list[CollectedPrice] = []

    for collected in iter_specific_item_pages(
        collector,
        detail_product_name=mapping.detail_product_name,
        begin_date=begin_date,
        end_date=end_date,
        num_of_rows=num_of_rows,
        max_pages=max_pages,
    ):
        pages_fetched += 1
        records_seen += len(collected.page.items)
        reported_total_count = collected.page.total_count

        # The service substring-matches the classification name, so a page can contain records
        # from neighbouring classifications. Drop those before any product matching.
        in_classification = records_in_mapped_classification(collected.page.items, mapping)
        records_in_classification += len(in_classification)

        candidates = filter_g2b_query_candidates(in_classification, query)
        for record in candidates:
            parsed = parse_official_report_record(
                record,
                operation=G2BShoppingOperation.SPECIFIC_ITEM_PROCUREMENTS,
            )
            if parsed is None:
                continue

            identity = parse_g2b_identity(parsed.original_title)
            decision = grade_product_identity(query, identity)
            prices.append(
                replace(
                    parsed,
                    manufacturer=identity.manufacturer,
                    product_name=identity.product_name or parsed.product_name,
                    model_name=identity.model_name,
                    specification=identity.specification,
                    match_grade=decision.grade,
                    match_note=decision.note,
                )
            )

    return G2BCandidateSearchResult(
        mapping=mapping,
        pages_fetched=pages_fetched,
        records_seen=records_seen,
        records_in_classification=records_in_classification,
        reported_total_count=reported_total_count,
        candidate_prices=tuple(prices),
    )
