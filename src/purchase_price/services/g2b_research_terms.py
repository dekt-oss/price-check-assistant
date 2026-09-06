from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from purchase_price.schemas import ProductQuery
from purchase_price.services.matching import normalize_text

DEFAULT_RESEARCH_TERMS_PATH = (
    Path(__file__).resolve().parents[3] / "data" / "g2b_research_terms.csv"
)


@dataclass(frozen=True)
class G2BResearchTerm:
    model_name: str
    product_name: str
    term: str
    rationale: str = ""


def load_g2b_research_terms(
    path: Path = DEFAULT_RESEARCH_TERMS_PATH,
) -> tuple[G2BResearchTerm, ...]:
    """Load research-only G2B terms.

    These terms expand candidate discovery only. They are never a verified mapping and can never
    promote a record into direct-price evidence by themselves.
    """

    if not path.exists():
        return ()

    rows: list[G2BResearchTerm] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"model_name", "product_name", "term", "rationale"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise ValueError("G2B research term registry is missing required columns")
        for row in reader:
            term = (row.get("term") or "").strip()
            if not term:
                continue
            rows.append(
                G2BResearchTerm(
                    model_name=(row.get("model_name") or "").strip(),
                    product_name=(row.get("product_name") or "").strip(),
                    term=term,
                    rationale=(row.get("rationale") or "").strip(),
                )
            )
    return tuple(rows)


def _product_family_rows(
    product_key: str,
    registry: tuple[G2BResearchTerm, ...],
) -> list[G2BResearchTerm]:
    """Return the most-specific research-only product-family rows.

    This intentionally affects discovery recall only. A short curated family key such as `마취`
    may expand a quote label like `마취기(Anesthesia Machine)`, but that relationship can never be
    used as product identity evidence.
    """

    candidates: list[tuple[int, G2BResearchTerm]] = []
    for row in registry:
        if row.model_name.strip():
            continue
        row_key = normalize_text(row.product_name)
        if not row_key:
            continue
        if row_key == product_key or row_key in product_key or product_key in row_key:
            candidates.append((len(row_key), row))
    if not candidates:
        return []
    longest = max(length for length, _ in candidates)
    return [row for length, row in candidates if length == longest]


def research_terms_for_query(
    query: ProductQuery,
    rows: Iterable[G2BResearchTerm] | None = None,
) -> tuple[str, ...]:
    """Return curated research-only terms for a model or product family.

    Exact model identity has precedence. If no model-specific rows exist, product-family rows may
    be selected by exact/containment match, preferring the longest family key. This only expands
    Research Layer recall; it never calls or modifies the verified G2B mapping resolver and never
    upgrades MatchGrade.
    """

    registry = tuple(rows) if rows is not None else load_g2b_research_terms()
    model_key = normalize_text(query.model_name)
    product_key = normalize_text(query.product_name)

    selected: list[G2BResearchTerm] = []
    if model_key:
        selected = [row for row in registry if normalize_text(row.model_name) == model_key]
    if not selected and product_key:
        selected = _product_family_rows(product_key, registry)

    output: list[str] = []
    seen: set[str] = set()
    for row in selected:
        request_term = re.sub(r"\s+", " ", row.term).strip()
        key = request_term.casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(request_term)
    return tuple(output)
