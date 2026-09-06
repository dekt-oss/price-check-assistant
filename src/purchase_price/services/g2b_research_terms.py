from __future__ import annotations

import csv
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


def research_terms_for_query(
    query: ProductQuery,
    rows: Iterable[G2BResearchTerm] | None = None,
) -> tuple[str, ...]:
    """Return curated candidate-search terms for an exact model/product identity.

    Model identity has precedence. If no model-specific rows exist, exact normalized product-name
    rows may be used. The result is research-only and deliberately does not call the verified
    mapping resolver.
    """

    registry = tuple(rows) if rows is not None else load_g2b_research_terms()
    model_key = normalize_text(query.model_name)
    product_key = normalize_text(query.product_name)

    selected: list[G2BResearchTerm] = []
    if model_key:
        selected = [row for row in registry if normalize_text(row.model_name) == model_key]
    if not selected and product_key:
        selected = [
            row
            for row in registry
            if normalize_text(row.product_name) == product_key and not row.model_name.strip()
        ]

    output: list[str] = []
    seen: set[str] = set()
    for row in selected:
        key = normalize_text(row.term)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(row.term)
    return tuple(output)
