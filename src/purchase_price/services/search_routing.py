"""How one search box word is routed before the price lookup (2026-10-10 production check).

* 식약처 허가·인증·신고번호 in any spacing ("제허 19-527 호", "제허19-527", "제허19527호").
* Korean and English names of common foreign makers ("필립스" <-> "Philips"), used only to widen a
  company search. Registered names are never rewritten.
* Parts of a Korean word that is not an MFDS 품목명 ("수액펌프" -> "펌프"), to suggest the 식약처
  품목명 and 나라장터 세부품명 that share them.

Pure functions; the dashboard runs the lookups. New module, so a Streamlit process that keeps
older modules after a deploy imports it fresh.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from purchase_price.services.matching import normalize_text
from purchase_price.services.mfds_business_license_view import company_core_key

# ── 식약처 허가번호 ──

PERMIT_KINDS = ("제허", "수허", "제인", "수인", "제신", "수신")
PERMIT_REGIONS = ("서울", "경인", "부산", "대전", "대구", "광주")
_PERMIT_RE = re.compile(
    r"^\s*(?:(?P<region>" + "|".join(PERMIT_REGIONS) + r")\s*)?"
    r"(?:(?P<ivd>체외)\s*)?"
    r"(?P<kind>" + "|".join(PERMIT_KINDS) + r")\s*(?:제\s*)?"
    r"(?P<year>\d{2})\s*[-‐‑–—_.\s]?\s*(?P<serial>\d{1,5})\s*(?:호)?\s*$"
)


@dataclass(frozen=True)
class PermitNumber:
    region: str
    ivd: bool
    kind: str
    year: str
    serial: str

    @property
    def display(self) -> str:
        """The spelling 식약처 stores: "제허 19-527 호", "서울 체외 수신 03-313 호"."""

        parts = [self.region] if self.region else []
        if self.ivd:
            parts.append("체외")
        parts.append(f"{self.kind} {self.year}-{int(self.serial)} 호")
        return " ".join(parts)

    @property
    def key(self) -> str:
        return normalize_text(self.display)


def parse_permit_number(text: object) -> PermitNumber | None:
    """A 허가·인증·신고번호 typed with or without spaces, hyphen or 호; None for anything else."""

    match = _PERMIT_RE.match(str(text or ""))
    if not match:
        return None
    serial = match.group("serial")
    if int(serial) == 0:
        return None
    return PermitNumber(
        region=match.group("region") or "",
        ivd=bool(match.group("ivd")),
        kind=match.group("kind"),
        year=match.group("year"),
        serial=serial,
    )


def looks_like_permit_attempt(text: object) -> bool:
    """Starts like a permit number ("제허…", "수신 22…") even if the digits are incomplete."""

    core = "".join(str(text or "").split())
    for region in PERMIT_REGIONS:
        core = core.removeprefix(region)
    core = core.removeprefix("체외")
    return any(core.startswith(kind) for kind in PERMIT_KINDS) and any(char.isdigit() for char in core)


# ── 외국 제조사의 한글·영문 이름 (검색 확장 전용) ──

# Each group lists names a buyer may type for the same maker family. Used only to widen a company
# search (the registered 식약처/나라장터 names are shown as they are). "지이" alone is too short to
# match inside other names, so it is an exact-only alias.
MAKER_ALIAS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("필립스", "한국필립스", "필립스코리아", "philips"),
    ("지이헬스케어", "지이", "ge헬스케어", "gehealthcare", "ge"),
    ("지멘스", "지멘스헬시니어스", "siemens", "siemenshealthineers"),
    ("드레거", "드래거", "draeger", "dräger", "drager"),
    ("메드트로닉", "medtronic"),
    ("마인드레이", "mindray"),
    ("니혼코덴", "니혼코덴코리아", "nihonkohden"),
)
# Needles shorter than this (after normalising) only match a whole name, never inside one.
MIN_PARTIAL_NEEDLE = 3


def _alias_group(key: str) -> tuple[str, ...] | None:
    for group in MAKER_ALIAS_GROUPS:
        keys = [normalize_text(alias) for alias in group]
        if key in keys:
            return group
    return None


def company_search_needles(text: object) -> tuple[str, ...]:
    """Normalised names to look for inside registered company and supplier names.

    "필립스" -> ("필립스", "philips"); "한국필립스" -> the same group. A word outside the alias map
    is searched as itself once it is long enough to be a name part (Hangul 2+, Latin 4+).
    """

    raw = str(text or "")
    for marker in ("주식회사", "(주)", "㈜", "(유)", "유한회사"):
        raw = raw.replace(marker, " ")
    key = normalize_text(raw)
    if not key:
        return ()
    group = _alias_group(key)
    names = [key]
    if group is not None:
        names.extend(normalize_text(alias) for alias in group)
    needles: list[str] = []
    for name in names:
        if not name or name in needles:
            continue
        hangul = bool(re.search(r"[가-힣]", name))
        if len(name) >= (2 if hangul else 4) or (group is not None and name == key):
            needles.append(name)
    return tuple(needles)


def company_matches_needle(company_name: str, needle: str) -> bool:
    """Whole-name match for short needles ("ge"), name-part match for the rest.

    The name is compared without its legal form, so "(주)필립스코리아" contains "필립스".
    """

    core = company_core_key(company_name)
    if not core or not needle:
        return False
    if len(needle) < MIN_PARTIAL_NEEDLE:
        return core == needle
    return needle in core


@dataclass(frozen=True)
class CompanyMatch:
    name: str
    models: int = 0
    source: str = "식약처"


def rank_company_matches(
    candidates: Iterable[tuple[str, int]],
    needles: Sequence[str],
    *,
    limit: int = 6,
    source: str = "식약처",
) -> list[CompanyMatch]:
    """(name, model or trade count) rows whose name contains a needle; the busiest first."""

    found: dict[str, CompanyMatch] = {}
    for name, count in candidates:
        if not name or not any(company_matches_needle(str(name), needle) for needle in needles):
            continue
        key = normalize_text(str(name))
        current = found.get(key)
        if current is None or int(count or 0) > current.models:
            found[key] = CompanyMatch(str(name).strip(), int(count or 0), source)
    return sorted(found.values(), key=lambda match: (-match.models, match.name))[:limit]


# ── 품목명이 아닌 한글 낱말: 공통 부분으로 비슷한 품목 제안 ──

SUGGESTION_LIMIT = 8


def word_pieces(text: object, *, min_length: int = 2) -> list[str]:
    """Distinct Hangul substrings, longest first; within a length, the word's end first.

    Korean compound nouns put the head at the end ("수액펌프" -> 펌프 is what the thing is), so a
    suffix piece is tried before a prefix piece of the same length.
    """

    core = "".join(char for char in str(text or "") if "가" <= char <= "힣")
    pieces: list[str] = []
    for length in range(len(core) - 1, min_length - 1, -1):
        starts = sorted(range(len(core) - length + 1), key=lambda start: -start)
        for start in starts:
            piece = core[start : start + length]
            if piece not in pieces:
                pieces.append(piece)
    return pieces


@dataclass(frozen=True)
class NameSuggestion:
    name: str
    shared: str  # the part of the search word it shares
    companies: int = 0
    models: int = 0
    trades: int = 0
    code: str = ""


def rank_name_suggestions(
    names: Iterable[Mapping[str, object]],
    pieces: Sequence[str],
    *,
    limit: int = SUGGESTION_LIMIT,
) -> list[NameSuggestion]:
    """Names (with their counts) that contain a piece: longest shared piece, word end first,
    then the most companies / trades. ``names`` rows: name, key, companies, models, trades, code."""

    order = {piece: index for index, piece in enumerate(pieces)}
    ranked: list[tuple[int, int, int, str, NameSuggestion]] = []
    seen: set[str] = set()
    for row in names:
        name = str(row.get("name") or "").strip()
        key = str(row.get("key") or normalize_text(name))
        if not name or key in seen:
            continue
        shared = next((piece for piece in pieces if piece in key), None)
        if shared is None:
            continue
        seen.add(key)
        suggestion = NameSuggestion(
            name=name,
            shared=shared,
            companies=int(row.get("companies") or 0),
            models=int(row.get("models") or 0),
            trades=int(row.get("trades") or 0),
            code=str(row.get("code") or ""),
        )
        weight = suggestion.companies or suggestion.trades
        ranked.append((order[shared], -weight, len(name), name, suggestion))
    ranked.sort(key=lambda item: item[:4])
    return [item[4] for item in ranked[:limit]]


def matching_keys(keys: Iterable[str], pieces: Sequence[str], *, limit: int = 80) -> list[str]:
    """Keys that contain a piece, the longest pieces' matches first, at most ``limit``."""

    keys = [key for key in keys if key]
    found: list[str] = []
    for piece in pieces:
        for key in keys:
            if piece in key and key not in found:
                found.append(key)
                if len(found) >= limit:
                    return found
    return found


def meaningful_pieces(pieces: Sequence[str], names: Iterable[str]) -> list[str]:
    """Pieces that are a whole word in some registered 품목명 ("펌프" in "전동식 의약품 주입 펌프").

    "액펌프" is inside "혈액펌프" but is no word, so it must not rank 심폐용 혈액펌프 above the
    infusion pumps. Falls back to every piece when no name has spaces to tell words apart.
    """

    words: set[str] = set()
    for name in names:
        for word in str(name or "").split():
            key = normalize_text(word)
            if key:
                words.add(key)
                words.add(key.removesuffix("용"))
    return [piece for piece in pieces if piece in words] or list(pieces)


MEDICAL_DETAIL_PREFIX = "42"
