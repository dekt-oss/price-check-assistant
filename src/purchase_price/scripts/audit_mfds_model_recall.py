"""Read-only audit: how procurement (Track B) model names resolve in the MFDS identity index.

The MFDS identity lookup only accepts an exact normalized model key. Procurement documents
often omit a maker prefix (``DFM100`` vs MFDS ``SJ-DFM100``) or a variant suffix
(``DFM100`` vs ``DFM100-1``). This audit measures how often each case happens and whether
the affix candidates agree on the manufacturer, so a matching-policy change can be decided
on evidence. It performs no writes and no public API requests.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from purchase_price.services.matching import normalize_text
from purchase_price.services.product_matching import (
    canonical_manufacturer,
    equivalent_model_keys,
    load_manufacturer_aliases,
)

MIN_AFFIX_KEY_LENGTH = 4
DEFAULT_SAMPLE_SIZE = 2000
DEFAULT_SEED = 20261004
ALWAYS_INCLUDE = ("DFM100",)
# Proposed policy: an exact normalized model match only confirms identity on its own when the
# key is distinctive. Weak keys additionally need manufacturer/importer agreement.
WEAK_KEY_SHAPES = ("digits_only", "unit_like", "short")
_UNIT_KEY = re.compile(r"^\d+(ml|cc|cm|mm|g|kg|l|ea|매|개|본)$")


@dataclass(frozen=True)
class TrackBModel:
    model_key: str
    model_name: str
    manufacturer: str | None
    line_count: int


@dataclass(frozen=True)
class MfdsCandidate:
    model_key: str
    model_name: str
    registered_company: str | None
    product_name: str | None


def classify_affix(query_key: str, candidate_key: str) -> str:
    if candidate_key == query_key:
        return "exact"
    if candidate_key.endswith(query_key):
        return "prefix_added"
    if candidate_key.startswith(query_key):
        return "suffix_added"
    return "infix"


def company_agrees(manufacturer: str | None, candidates: Iterable[MfdsCandidate]) -> bool | None:
    """True/False when Track B names a manufacturer, None when it does not.

    Agreement is a containment check on normalized names because MFDS lists the
    registered manufacturer *or importer*, while procurement lists the maker.
    """

    maker = normalize_text(manufacturer)
    if len(maker) < 2:
        return None
    aliases = _manufacturer_aliases()
    maker_canonical = normalize_text(canonical_manufacturer(manufacturer, aliases))
    for candidate in candidates:
        company = normalize_text(candidate.registered_company)
        if not company:
            continue
        company_canonical = normalize_text(
            canonical_manufacturer(candidate.registered_company, aliases)
        )
        for left, right in ((maker, company), (maker_canonical, company_canonical)):
            if left and right and (left in right or right in left):
                return True
    return False


_MANUFACTURER_ALIASES: dict[str, str] | None = None


def _manufacturer_aliases() -> dict[str, str]:
    global _MANUFACTURER_ALIASES
    if _MANUFACTURER_ALIASES is None:
        _MANUFACTURER_ALIASES = load_manufacturer_aliases()
    return _MANUFACTURER_ALIASES


def model_key_shape(key: str) -> str:
    if key.isdigit():
        return "digits_only"
    if _UNIT_KEY.match(key):
        return "unit_like"
    if len(key) <= 4:
        return "short"
    if len(key) <= 6:
        return "length_5_6"
    return "distinctive"


def load_track_b_models(
    connection: sqlite3.Connection,
    *,
    detail_prefix: str | None = None,
) -> list[TrackBModel]:
    tables = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "track_b_delivery_lines" not in tables:
        raise RuntimeError(f"Track B serving index has no track_b_delivery_lines: {sorted(tables)}")
    columns = {row[1] for row in connection.execute("PRAGMA table_info(track_b_delivery_lines)")}
    conflict_filter = "AND COALESCE(identity_conflict, 0) = 0" if "identity_conflict" in columns else ""
    params: tuple[str, ...] = ()
    detail_filter = ""
    if detail_prefix:
        if "detail_code" not in columns:
            raise RuntimeError("Track B serving index has no detail_code column")
        detail_filter = "AND detail_code LIKE ?"
        params = (f"{detail_prefix}%",)
    rows = connection.execute(
        f"""
        SELECT model_key, MAX(model_name), MAX(manufacturer), COUNT(*)
        FROM track_b_delivery_lines
        WHERE model_key IS NOT NULL AND model_key <> '' {conflict_filter} {detail_filter}
        GROUP BY model_key
        """,
        params,
    ).fetchall()
    return [TrackBModel(str(r[0]), str(r[1] or ""), r[2], int(r[3])) for r in rows]


def prepare_mfds_lookup(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TEMP TABLE IF NOT EXISTS mfds_model_keys AS
            SELECT DISTINCT model_key FROM mfds_identity WHERE model_key <> '';
        CREATE VIRTUAL TABLE IF NOT EXISTS temp.mfds_model_trigram
            USING fts5(model_key, tokenize='trigram');
        INSERT INTO temp.mfds_model_trigram(model_key) SELECT model_key FROM mfds_model_keys;
        """
    )


def _candidates(connection: sqlite3.Connection, keys: Sequence[str]) -> list[MfdsCandidate]:
    if not keys:
        return []
    placeholders = ",".join("?" for _ in keys)
    rows = connection.execute(
        f"""
        SELECT DISTINCT model_key, model_name, registered_company, product_name
        FROM mfds_identity WHERE model_key IN ({placeholders})
        """,
        tuple(keys),
    ).fetchall()
    return [MfdsCandidate(str(r[0]), str(r[1] or ""), r[2], r[3]) for r in rows]


def classify_model(connection: sqlite3.Connection, model: TrackBModel) -> dict[str, Any]:
    key = model.model_key
    exact = _candidates(connection, [key])
    if exact:
        return {"category": "exact", "candidates": exact}

    alias_keys = [k for k in equivalent_model_keys(model.model_name) if k != key]
    alias = _candidates(connection, alias_keys)
    if alias:
        return {"category": "verified_alias", "candidates": alias}

    if len(key) < MIN_AFFIX_KEY_LENGTH:
        return {"category": "none_short_key", "candidates": []}

    affix_keys = [
        str(row[0])
        for row in connection.execute(
            "SELECT model_key FROM temp.mfds_model_trigram WHERE model_key LIKE ? LIMIT 50",
            (f"%{key}%",),
        )
    ]
    if not affix_keys:
        return {"category": "none", "candidates": []}
    kinds = Counter(classify_affix(key, candidate) for candidate in affix_keys)
    category = (
        "prefix_added"
        if set(kinds) == {"prefix_added"}
        else "suffix_added"
        if set(kinds) == {"suffix_added"}
        else "mixed_affix"
    )
    return {"category": category, "candidates": _candidates(connection, affix_keys)}


def audit(
    mfds: sqlite3.Connection,
    track_b_models: Sequence[TrackBModel],
    *,
    sample_size: int,
    seed: int,
    sample_limit: int = 25,
) -> dict[str, Any]:
    rng = random.Random(seed)
    by_key = {model.model_key: model for model in track_b_models}
    sample = (
        list(track_b_models)
        if len(track_b_models) <= sample_size
        else rng.sample(list(track_b_models), sample_size)
    )
    for forced in ALWAYS_INCLUDE:
        forced_key = normalize_text(forced)
        if forced_key in by_key and by_key[forced_key] not in sample:
            sample.append(by_key[forced_key])

    prepare_mfds_lookup(mfds)
    categories: Counter[str] = Counter()
    weighted: Counter[str] = Counter()
    candidate_counts: dict[str, list[int]] = {}
    company: dict[str, Counter[str]] = {}
    examples: dict[str, list[dict[str, Any]]] = {}
    policy_counts: dict[str, Counter[str]] = {}
    policy_lines: dict[str, Counter[str]] = {}
    policy_examples: dict[str, list[dict[str, Any]]] = {}
    for model in sample:
        result = classify_model(mfds, model)
        category = result["category"]
        candidates: list[MfdsCandidate] = result["candidates"]
        categories[category] += 1
        weighted[category] += model.line_count
        candidate_counts.setdefault(category, []).append(
            len({candidate.model_key for candidate in candidates})
        )
        agreement = company_agrees(model.manufacturer, candidates) if candidates else None
        if category == "exact":
            shape = model_key_shape(model.model_key)
            verdict = "unknown" if agreement is None else "agree" if agreement else "disagree"
            policy_counts.setdefault(shape, Counter())[verdict] += 1
            policy_lines.setdefault(shape, Counter())[verdict] += model.line_count
            shape_examples = policy_examples.setdefault(shape, [])
            if verdict != "agree" and len(shape_examples) < sample_limit:
                shape_examples.append(
                    {
                        "track_b_model": model.model_name,
                        "track_b_manufacturer": model.manufacturer,
                        "track_b_lines": model.line_count,
                        "verdict": verdict,
                        "mfds": [
                            {
                                "model": c.model_name,
                                "company": c.registered_company,
                                "product": c.product_name,
                            }
                            for c in candidates[:3]
                        ],
                    }
                )
        company.setdefault(category, Counter())[
            "unknown" if agreement is None else "agree" if agreement else "disagree"
        ] += 1
        bucket = examples.setdefault(category, [])
        if len(bucket) < sample_limit or model.model_key in {normalize_text(k) for k in ALWAYS_INCLUDE}:
            bucket.append(
                {
                    "track_b_model": model.model_name,
                    "track_b_manufacturer": model.manufacturer,
                    "track_b_lines": model.line_count,
                    "company_agrees": agreement,
                    "mfds_candidates": [
                        {
                            "model": candidate.model_name,
                            "company": candidate.registered_company,
                            "product": candidate.product_name,
                        }
                        for candidate in candidates[:5]
                    ],
                }
            )

    total = sum(categories.values())
    total_lines = sum(weighted.values())

    def _distribution(values: list[int]) -> dict[str, int]:
        ordered = sorted(values)
        return {
            "single_model": sum(1 for v in ordered if v == 1),
            "two_to_five": sum(1 for v in ordered if 2 <= v <= 5),
            "more_than_five": sum(1 for v in ordered if v > 5),
        }

    return {
        "status": "SUCCESS",
        "track_b_distinct_models": len(track_b_models),
        "sampled_models": total,
        "seed": seed,
        "categories": {
            name: {
                "models": count,
                "share": round(count / total, 4) if total else 0.0,
                "line_weighted_share": round(weighted[name] / total_lines, 4) if total_lines else 0.0,
                "candidate_models": _distribution(candidate_counts.get(name, [])),
                "company": dict(company.get(name, Counter())),
            }
            for name, count in categories.most_common()
        },
        "examples": examples,
        "exact_match_policy": _exact_policy_summary(policy_counts, policy_lines, policy_examples),
    }


def _exact_policy_summary(
    counts: dict[str, Counter[str]],
    lines: dict[str, Counter[str]],
    examples: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    exact_total = sum(sum(c.values()) for c in counts.values())
    downgraded = sum(
        counts.get(shape, Counter())[verdict]
        for shape in WEAK_KEY_SHAPES
        for verdict in ("disagree", "unknown")
    )
    return {
        "weak_key_shapes": list(WEAK_KEY_SHAPES),
        "exact_models": exact_total,
        "would_downgrade_to_needs_review": downgraded,
        "would_downgrade_share_of_exact": round(downgraded / exact_total, 4) if exact_total else 0.0,
        "by_shape": {
            shape: {"models": dict(counts[shape]), "lines": dict(lines.get(shape, Counter()))}
            for shape in sorted(counts)
        },
        "non_agreeing_examples": examples,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--sample-limit", type=int, default=25)
    parser.add_argument(
        "--detail-prefix",
        default=None,
        help="Only Track B lines whose G2B detail code starts with this (42 = medical equipment)",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    from purchase_price.config import Settings
    from purchase_price.services import mfds_identity_r2, track_b_r2_quote_index
    from purchase_price.services.mfds_identity_status import get_mfds_identity_collection_status

    args = _parse_args()
    settings = Settings()
    mfds_path = mfds_identity_r2._local_index_path(settings)
    track_b_path, _pointer = track_b_r2_quote_index._local_index_snapshot(settings)
    if mfds_path is None or track_b_path is None:
        raise RuntimeError("MFDS identity index and Track B serving index are both required")

    status = get_mfds_identity_collection_status(settings=settings)
    track_b = sqlite3.connect(f"file:{track_b_path}?mode=ro", uri=True)
    try:
        models = load_track_b_models(track_b, detail_prefix=args.detail_prefix)
    finally:
        track_b.close()

    mfds = sqlite3.connect(f"file:{mfds_path}?mode=ro", uri=True)
    try:
        report = audit(
            mfds,
            models,
            sample_size=args.sample_size,
            seed=args.seed,
            sample_limit=args.sample_limit,
        )
    finally:
        mfds.close()
    report["detail_prefix"] = args.detail_prefix
    report["mfds_index"] = {
        "row_count": status.row_count,
        "source_total_count": status.source_total_count,
        "verified_complete_cycles": getattr(status, "verified_complete_cycles", None),
        "coverage_note": (
            "exact/none shares are biased toward 'none' until the index verifies full coverage"
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {name: value["models"] for name, value in report["categories"].items()}
    print(json.dumps({"sampled_models": report["sampled_models"], "categories": summary}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
