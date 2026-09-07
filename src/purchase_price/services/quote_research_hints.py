from __future__ import annotations

import re
from pathlib import Path

from purchase_price.services.matching import normalize_text

_DOCUMENT_WORDS = {
    "견적",
    "견적서",
    "quotation",
    "quote",
    "최종",
    "수정",
    "사본",
    "copy",
}
_ORG_SUFFIXES = (
    "과",
    "부",
    "팀",
    "센터",
    "실",
    "병동",
    "클리닉",
)


def _clean_stem(file_name: str) -> str:
    stem = Path(file_name or "").stem
    stem = re.sub(r"[_\-–—]+", " ", stem)
    stem = re.sub(r"[\[\](){}]+", " ", stem)
    stem = re.sub(r"(?i)\b(?:견적서?|quotation|quote|최종|수정|사본|copy)\s*\d*\b", " ", stem)
    stem = re.sub(r"\b20\d{2}[.\-_]?\d{1,2}[.\-_]?\d{1,2}\b", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem


def _tokens(value: str) -> list[str]:
    return [token for token in re.findall(r"[0-9A-Za-z가-힣]+", value) if token]


def _looks_like_org_prefix(token: str) -> bool:
    if not re.search(r"[가-힣]", token):
        return False
    return any(token.endswith(suffix) and len(token) > len(suffix) + 1 for suffix in _ORG_SUFFIXES)


def build_quote_filename_research_hints(file_name: str, *, max_terms: int = 6) -> tuple[str, ...]:
    """Return research-only category hints from a user-provided quote filename.

    Quote filenames often contain a department prefix followed by a generic purchase item, e.g.
    `재활의학과 로봇보조 정형용 운동장치 견적2.pdf`. The filename is not authoritative product
    identity, so these hints are used only to widen Research and can never promote MatchGrade or
    direct-price evidence.
    """

    if max_terms < 1:
        raise ValueError("max_terms must be positive")

    cleaned = _clean_stem(file_name)
    tokens = _tokens(cleaned)
    if not tokens:
        return ()

    while tokens and (
        tokens[-1].casefold() in _DOCUMENT_WORDS
        or bool(re.fullmatch(r"\d+", tokens[-1]))
    ):
        tokens.pop()
    if not tokens:
        return ()

    # Department/unit prefixes are common in hospital filenames and usually are not product terms.
    trimmed = list(tokens)
    if len(trimmed) >= 2 and _looks_like_org_prefix(trimmed[0]):
        trimmed = trimmed[1:]

    raw: list[str] = []
    # Prefer the most specific product-like suffixes. This yields, for example,
    # `로봇보조 정형용 운동장치` -> `정형용 운동장치` -> `운동장치`.
    for width in range(min(4, len(trimmed)), 0, -1):
        phrase = " ".join(trimmed[-width:]).strip()
        if phrase:
            raw.append(phrase)
            if re.search(r"[가-힣]", phrase) and " " in phrase:
                raw.append(phrase.replace(" ", ""))

    output: list[str] = []
    seen: set[str] = set()
    for term in raw:
        key = normalize_text(term)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(term)
        if len(output) >= max_terms:
            break
    return tuple(output)
