"""Pick the product name used for the MFDS model-info (형명) lookup.

The 형명 API only filters by product name (PRDLST_NM). A one-line model search such as
`NT-SG` leaves the search text itself in the product-name slot, so the lookup asked MFDS for a
product called "NT-SG" and always found nothing. When that happens, the product class of the
procurement rows that already matched the model (e.g. "심장충격기") is a far better filter.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Any

from purchase_price.services.matching import normalize_text
from purchase_price.services.product_matching import parse_g2b_identity

_DIRECT_GRADES = {"A", "B"}


def _grade(candidate: Any) -> str:
    grade = getattr(candidate, "match_grade", None)
    return str(getattr(grade, "value", grade) or "").strip().upper()


def model_info_product_name(
    product_name: str | None,
    model_name: str | None,
    track_b_candidates: Iterable[Any] = (),
) -> str:
    current = (product_name or "").strip()
    current_key = normalize_text(current)
    if current_key and current_key != normalize_text(model_name):
        return current

    candidates = tuple(track_b_candidates)
    for pool in (
        [c for c in candidates if _grade(c) in _DIRECT_GRADES],
        list(candidates),
    ):
        classes = Counter(
            name
            for name in (
                (parse_g2b_identity(getattr(c, "product_title", None)).product_name or "").strip()
                for c in pool
            )
            if name and normalize_text(name) != normalize_text(model_name)
        )
        if classes:
            return classes.most_common(1)[0][0]
    return current
