"""Hospital master data: canonical names, aliases and peer-group selection.

The seed lives in ``data/hospital_master.json``. Bed counts stay empty until HIRA data is
loaded; nothing here estimates a missing number.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MASTER_FILE = Path(__file__).resolve().parents[3] / "data" / "hospital_master.json"

PEER_REGION = "region"
PEER_NETWORK = "network"
PEER_SIMILAR_SIZE = "similar_size"
PEER_SAME_TYPE = "same_type"
PEER_CUSTOM = "custom"
PEER_GROUP_LABELS: dict[str, str] = {
    PEER_REGION: "지역 경쟁군",
    PEER_NETWORK: "동일 의료원",
    PEER_SIMILAR_SIZE: "유사 규모",
    PEER_SAME_TYPE: "동일 유형",
    PEER_CUSTOM: "직접 선택",
}

_SPACE_RE = re.compile(r"[\s·\-_()]+")


def normalize_hospital_name(value: str) -> str:
    text = _SPACE_RE.sub("", (value or "").strip()).casefold()
    return text.replace("학교", "") if text.endswith("병원") else text


@dataclass(frozen=True)
class Hospital:
    hospital_id: str
    canonical_name: str
    short_name: str
    aliases: tuple[str, ...]
    foundation: str
    network: str
    region: str
    hospital_type: str
    ownership: str
    bed_count: int | None
    bed_count_as_of: str | None
    type_verified: bool = False

    @property
    def names(self) -> tuple[str, ...]:
        return (self.canonical_name, self.short_name, *self.aliases)


class HospitalMaster:
    def __init__(self, hospitals: Iterable[Hospital]) -> None:
        self._hospitals = tuple(hospitals)
        self._by_id = {h.hospital_id: h for h in self._hospitals}
        self._by_name: dict[str, Hospital] = {}
        for hospital in self._hospitals:
            for name in hospital.names:
                self._by_name.setdefault(normalize_hospital_name(name), hospital)

    @property
    def hospitals(self) -> tuple[Hospital, ...]:
        return self._hospitals

    def get(self, hospital_id: str) -> Hospital | None:
        return self._by_id.get(hospital_id)

    def resolve(self, name: str) -> Hospital | None:
        """Map any known spelling of a hospital to its canonical record."""

        return self._by_name.get(normalize_hospital_name(name))

    def peer_group(
        self,
        target: Hospital,
        kind: str,
        *,
        bed_tolerance: int = 100,
        custom_ids: Sequence[str] = (),
    ) -> tuple[Hospital, ...]:
        """Return comparison hospitals for ``target`` (never including the target)."""

        others = [h for h in self._hospitals if h.hospital_id != target.hospital_id]
        if kind == PEER_REGION:
            return tuple(h for h in others if h.region == target.region)
        if kind == PEER_NETWORK:
            return tuple(h for h in others if h.network == target.network)
        if kind == PEER_SAME_TYPE:
            return tuple(
                h
                for h in others
                if h.hospital_type == target.hospital_type and h.ownership == target.ownership
            )
        if kind == PEER_SIMILAR_SIZE:
            if target.bed_count is None:
                return ()
            return tuple(
                h
                for h in others
                if h.bed_count is not None and abs(h.bed_count - target.bed_count) <= bed_tolerance
            )
        if kind == PEER_CUSTOM:
            wanted = set(custom_ids)
            return tuple(h for h in others if h.hospital_id in wanted)
        raise ValueError(f"unknown peer group: {kind}")


def load_hospital_master(path: Path = DEFAULT_MASTER_FILE) -> HospitalMaster:
    payload = json.loads(path.read_text(encoding="utf-8"))
    hospitals: list[Hospital] = []
    for raw in payload.get("hospitals") or []:
        bed_count = raw.get("bed_count")
        hospitals.append(
            Hospital(
                hospital_id=str(raw["hospital_id"]),
                canonical_name=str(raw["canonical_name"]),
                short_name=str(raw.get("short_name") or raw["canonical_name"]),
                aliases=tuple(str(a) for a in raw.get("aliases") or []),
                foundation=str(raw.get("foundation") or ""),
                network=str(raw.get("network") or ""),
                region=str(raw.get("region") or ""),
                hospital_type=str(raw.get("hospital_type") or ""),
                ownership=str(raw.get("ownership") or ""),
                bed_count=int(bed_count) if bed_count is not None else None,
                bed_count_as_of=raw.get("bed_count_as_of"),
                type_verified=bool(raw.get("type_verified", False)),
            )
        )
    return HospitalMaster(hospitals)
