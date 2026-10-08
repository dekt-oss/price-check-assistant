"""HIRA (건강보험심사평가원) hospital info on data.go.kr: 종별 · 소재지 · 병상수.

Two services (both need a data.go.kr 활용신청 on the same key):

* 병원정보서비스 ``hospInfoServicev2/getHospBasisList`` — search by name (``yadmNm``); returns the
  encrypted 요양기호 ``ykiho``, 종별 ``clCdNm``, ``addr``, ``sidoCdNm``.
* 의료기관별상세정보서비스 ``MadmDtlInfoService2.8/getEqpInfo2.8`` — by ``ykiho``; returns
  ``permSbdCnt`` (허가병상수).

A name search must resolve to exactly one master hospital; otherwise the hospital is reported
and left untouched. Missing bed counts stay empty — nothing is estimated.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.services import hospital_master as master_service

HIRA_HOSP_INFO_BASE_URL = "https://apis.data.go.kr/B551182/hospInfoServicev2"
HIRA_HOSP_BASIS_OPERATION = "getHospBasisList"
HIRA_DETAIL_BASE_URL = "https://apis.data.go.kr/B551182/MadmDtlInfoService2.8"
HIRA_EQUIPMENT_OPERATION = "getEqpInfo2.8"
NOT_SUBSCRIBED_CODES = frozenset({"30", "12", "20"})


class JsonClient(Protocol):
    def get_json(self, base_url: str, endpoint: str, **params: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class HiraHospital:
    ykiho: str
    name: str
    type_name: str
    sido: str
    address: str


@dataclass(frozen=True)
class HiraResolution:
    hospital_id: str
    status: str  # "matched" | "not_found" | "ambiguous" | "error"
    hira: HiraHospital | None = None
    bed_count: int | None = None
    note: str = ""


def is_not_subscribed(exc: BaseException) -> bool:
    text = str(exc)
    return any(f"code={code}" in text for code in NOT_SUBSCRIBED_CODES) or "NOT_REGISTERED" in text


def _items(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    body = (payload.get("response") or {}).get("body") or {}
    items = body.get("items") or {}
    if isinstance(items, str):  # empty result is "" in HIRA JSON
        return []
    item = items.get("item") if isinstance(items, dict) else items
    if item is None:
        return []
    return item if isinstance(item, list) else [item]


def parse_basis_list(payload: Mapping[str, Any]) -> list[HiraHospital]:
    return [
        HiraHospital(
            ykiho=str(row.get("ykiho") or ""),
            name=str(row.get("yadmNm") or "").strip(),
            type_name=str(row.get("clCdNm") or "").strip(),
            sido=str(row.get("sidoCdNm") or "").strip(),
            address=str(row.get("addr") or "").strip(),
        )
        for row in _items(payload)
        if row.get("ykiho")
    ]


def parse_bed_count(payload: Mapping[str, Any]) -> int | None:
    """허가병상수 (``permSbdCnt``) only; other bed lines are not summed into a substitute."""

    for row in _items(payload):
        value = row.get("permSbdCnt")
        if value not in (None, ""):
            try:
                return int(str(value).replace(",", ""))
            except ValueError:
                return None
    return None


def resolve_hospital(
    client: JsonClient,
    master: master_service.HospitalMaster,
    hospital: master_service.Hospital,
) -> HiraResolution:
    """Search HIRA by each known name; accept only a single result that maps back to ``hospital``."""

    candidates: dict[str, HiraHospital] = {}
    for term in (hospital.canonical_name, hospital.short_name, *hospital.aliases):
        payload = client.get_json(
            HIRA_HOSP_INFO_BASE_URL, HIRA_HOSP_BASIS_OPERATION, yadmNm=term, numOfRows=50, pageNo=1, _type="json"
        )
        for item in parse_basis_list(payload):
            resolved = master.resolve(item.name)
            if resolved is not None and resolved.hospital_id == hospital.hospital_id:
                candidates[item.ykiho] = item
        if candidates:
            break
    if not candidates:
        return HiraResolution(hospital.hospital_id, "not_found", note="심평원 병원 목록에서 이름이 일치하는 곳이 없음")
    if len(candidates) > 1:
        names = ", ".join(sorted(c.name for c in candidates.values()))
        return HiraResolution(hospital.hospital_id, "ambiguous", note=f"여러 곳이 일치: {names}")
    hira = next(iter(candidates.values()))
    beds = parse_bed_count(
        client.get_json(HIRA_DETAIL_BASE_URL, HIRA_EQUIPMENT_OPERATION, ykiho=hira.ykiho, _type="json")
    )
    return HiraResolution(hospital.hospital_id, "matched", hira=hira, bed_count=beds)


def sync_master(
    client: JsonClient,
    master: master_service.HospitalMaster,
    payload: dict[str, Any],
    *,
    as_of: date,
    hospital_ids: Sequence[str] = (),
) -> tuple[dict[str, Any], list[HiraResolution]]:
    """Return an updated master JSON payload and the per-hospital outcome.

    Only matched hospitals are changed. A matched hospital without a 허가병상수 keeps
    ``bed_count`` empty but still gets its 종별 confirmed.
    """

    results: list[HiraResolution] = []
    by_id = {raw["hospital_id"]: raw for raw in payload.get("hospitals") or []}
    for hospital in master.hospitals:
        if hospital_ids and hospital.hospital_id not in hospital_ids:
            continue
        try:
            outcome = resolve_hospital(client, master, hospital)
        except PublicDataClientError as exc:
            if is_not_subscribed(exc):
                raise
            outcome = HiraResolution(hospital.hospital_id, "error", note=str(exc))
        results.append(outcome)
        if outcome.status != "matched" or outcome.hira is None:
            continue
        raw = by_id[hospital.hospital_id]
        raw["hospital_type"] = outcome.hira.type_name or raw.get("hospital_type")
        raw["type_verified"] = bool(outcome.hira.type_name)
        raw["hira_address"] = outcome.hira.address
        if outcome.bed_count is not None:
            raw["bed_count"] = outcome.bed_count
            raw["bed_count_as_of"] = as_of.isoformat()
        raw["hira_synced_at"] = as_of.isoformat()
    return payload, results


def write_master(payload: Mapping[str, Any], path: Path) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
