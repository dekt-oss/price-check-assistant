from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from purchase_price.services.g2b_track_b_normalization import (
    TrackBAmountCheck,
    TrackBIdentityConflictError,
    TrackBRawPage,
    TrackBStableIdentity,
    build_track_b_price_candidate,
    normalize_track_b_page,
)
from purchase_price.storage.r2 import payload_sha256


@dataclass(frozen=True)
class TrackBAuditSummary:
    pages_seen: int
    rows_seen: int
    normalized_records: int
    price_candidates: int
    non_price_records: int
    duplicate_pages: int
    duplicate_records: int
    issue_counts: tuple[tuple[str, int], ...]
    price_counts: tuple[tuple[str, int], ...] = ()
    identity_counts: tuple[tuple[str, int], ...] = ()
    amount_check_counts: tuple[tuple[str, int], ...] = ()
    classification_counts: tuple[tuple[str, tuple[tuple[str, int], ...]], ...] = ()
    invalid_pages: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "pages_seen": self.pages_seen,
            "pages_parsed": self.pages_seen,
            "invalid_pages": self.invalid_pages,
            "rows_seen": self.rows_seen,
            "normalized_records": self.normalized_records,
            "price_candidates": self.price_candidates,
            "non_price_records": self.non_price_records,
            "duplicate_pages": self.duplicate_pages,
            "duplicate_records": self.duplicate_records,
            "issue_counts": dict(self.issue_counts),
            "price_counts": dict(self.price_counts),
            "identity_counts": dict(self.identity_counts),
            "amount_check_counts": dict(self.amount_check_counts),
            "classification_counts": {
                code: dict(counts) for code, counts in self.classification_counts
            },
        }


def audit_track_b_raw_pages(
    pages: tuple[TrackBRawPage, ...], *, invalid_pages: int = 0
) -> TrackBAuditSummary:
    """Normalize Track B raw pages and report evidence quality without persisting DB rows."""

    audit = TrackBAuditAccumulator()
    for page in pages:
        audit.add_page(page)
    audit.invalid_pages = invalid_pages
    return audit.summary()


class TrackBAuditAccumulator:
    """Bounded raw-page audit state; retains hashes, counts and no raw page bodies."""

    def __init__(self) -> None:
        self.pages_seen = 0
        self.rows_seen = 0
        self.invalid_pages = 0
        self.duplicate_pages = 0
        self.duplicate_records = 0
        self.normalized_records = 0
        self.price_candidates = 0
        self.issue_counts: Counter[str] = Counter()
        self.price_counts: Counter[str] = Counter()
        self.identity_counts: Counter[str] = Counter()
        self.amount_counts: Counter[str] = Counter()
        self.classifications: dict[str, Counter[str]] = {}
        self._page_hashes: set[str] = set()
        self._item_hashes: dict[TrackBStableIdentity, str] = {}

    def add_page(self, page: TrackBRawPage) -> None:
        result = normalize_track_b_page(
            page.payload,
            raw_object_key=page.raw_object_key,
            raw_payload_sha256=page.raw_payload_sha256,
            fetched_at=page.fetched_at,
        )
        if any(issue.code == "IDENTITY_CONFLICT" for issue in result.issues):
            raise TrackBIdentityConflictError("Track B page contains divergent stable identities")
        self.pages_seen += 1
        items = page.payload["response"]["items"]
        code = str(page.payload["request"]["detail_code"])
        self.rows_seen += len(items)
        self.classifications.setdefault(code, Counter())["raw_rows"] += len(items)
        page_hash = page.raw_payload_sha256 or payload_sha256(page.payload)[0]
        if page_hash in self._page_hashes:
            self.duplicate_pages += 1
            return
        self._page_hashes.add(page_hash)
        self.issue_counts.update(issue.code for issue in result.issues)
        self.duplicate_records += result.duplicate_count
        for record in result.records:
            existing_hash = self._item_hashes.get(record.identity)
            if existing_hash is not None:
                if existing_hash != record.item_sha256:
                    raise TrackBIdentityConflictError(
                        f"stable identity {record.identity.source_record_id} has divergent payloads"
                    )
                self.duplicate_records += 1
                continue
            self._item_hashes[record.identity] = record.item_sha256
            self.normalized_records += 1
            classification = self.classifications.setdefault(record.detail_code, Counter())
            classification["normalized_rows"] += 1
            self.identity_counts["valid_three_field"] += 1
            if record.identity.change_order.isdigit() and int(record.identity.change_order) > 0:
                self.identity_counts["changed_order_records"] += 1
            raw_price = record.raw_item.get("prdctUprc")
            if raw_price is None or str(raw_price).strip() == "":
                self.price_counts["missing"] += 1
            else:
                self.price_counts["present"] += 1
                if record.unit_price is None:
                    self.price_counts["invalid"] += 1
                else:
                    self.price_counts["positive" if record.unit_price > 0 else (
                        "zero" if record.unit_price == 0 else "negative"
                    )] += 1
            self.amount_counts[record.amount_check.value] += 1
            if record.amount_check == TrackBAmountCheck.INCONSISTENT:
                classification["mismatch_rows"] += 1
            if build_track_b_price_candidate(record) is None:
                classification["no_price_rows"] += 1
            else:
                classification["price_candidates"] += 1
                self.price_candidates += 1

    def summary(self) -> TrackBAuditSummary:
        identities = self.identity_counts.copy()
        identities["missing"] = self.issue_counts["INVALID_IDENTITY"]
        identities["replay"] = self.duplicate_records
        identities["conflict"] = 0
        return TrackBAuditSummary(
            pages_seen=self.pages_seen,
            rows_seen=self.rows_seen,
            normalized_records=self.normalized_records,
            price_candidates=self.price_candidates,
            non_price_records=self.normalized_records - self.price_candidates,
            duplicate_pages=self.duplicate_pages,
            duplicate_records=self.duplicate_records,
            issue_counts=tuple(sorted(self.issue_counts.items())),
            price_counts=tuple(sorted(self.price_counts.items())),
            identity_counts=tuple(sorted(identities.items())),
            amount_check_counts=tuple(sorted(self.amount_counts.items())),
            classification_counts=tuple(
                (code, tuple(sorted(counts.items())))
                for code, counts in sorted(self.classifications.items())
            ),
            invalid_pages=self.invalid_pages,
        )
