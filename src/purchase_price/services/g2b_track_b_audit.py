from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from purchase_price.services.g2b_track_b_normalization import (
    TrackBRawPage,
    build_track_b_price_candidate,
    normalize_track_b_pages,
)


@dataclass(frozen=True)
class TrackBAuditSummary:
    pages_seen: int
    normalized_records: int
    price_candidates: int
    non_price_records: int
    duplicate_pages: int
    duplicate_records: int
    issue_counts: tuple[tuple[str, int], ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "pages_seen": self.pages_seen,
            "normalized_records": self.normalized_records,
            "price_candidates": self.price_candidates,
            "non_price_records": self.non_price_records,
            "duplicate_pages": self.duplicate_pages,
            "duplicate_records": self.duplicate_records,
            "issue_counts": dict(self.issue_counts),
        }


def audit_track_b_raw_pages(pages: tuple[TrackBRawPage, ...]) -> TrackBAuditSummary:
    """Normalize Track B raw pages and report evidence quality without persisting DB rows."""

    result = normalize_track_b_pages(pages)
    candidate_count = sum(
        build_track_b_price_candidate(record) is not None for record in result.records
    )
    issues = Counter(issue.code for issue in result.issues)
    return TrackBAuditSummary(
        pages_seen=len(pages),
        normalized_records=len(result.records),
        price_candidates=candidate_count,
        non_price_records=len(result.records) - candidate_count,
        duplicate_pages=result.duplicate_pages,
        duplicate_records=result.duplicate_records,
        issue_counts=tuple(sorted(issues.items())),
    )
