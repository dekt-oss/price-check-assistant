from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from purchase_price.clients.data_go_kr import PublicDataClientError
from purchase_price.services import hira_hospital_info as hira
from purchase_price.services import hospital_master as master_service


def _basis(*names: str) -> dict[str, Any]:
    items = [
        {"ykiho": f"Y{i}", "yadmNm": name, "clCdNm": "상급종합병원", "sidoCdNm": "부산", "addr": "부산 어딘가"}
        for i, name in enumerate(names)
    ]
    return {"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": items}}}}


class FakeClient:
    def __init__(self, by_term: dict[str, dict[str, Any]], beds: dict[str, Any]) -> None:
        self.by_term = by_term
        self.beds = beds
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get_json(self, base_url: str, endpoint: str, **params: Any) -> dict[str, Any]:
        self.calls.append((endpoint, params))
        if endpoint == hira.HIRA_HOSP_BASIS_OPERATION:
            return self.by_term.get(params["yadmNm"], {"response": {"body": {"items": ""}}})
        item = self.beds.get(params["ykiho"])
        return {"response": {"body": {"items": {"item": item} if item else ""}}}


def _master_payload() -> tuple[master_service.HospitalMaster, dict[str, Any]]:
    payload = json.loads(master_service.DEFAULT_MASTER_FILE.read_text(encoding="utf-8"))
    return master_service.load_hospital_master(), payload


def test_unambiguous_match_fills_type_beds_and_date() -> None:
    master, payload = _master_payload()
    client = FakeClient(
        {"인제대학교부산백병원": _basis("인제대학교부산백병원")},
        {"Y0": {"permSbdCnt": "810", "stdSickbdCnt": "700"}},
    )
    payload, results = hira.sync_master(client, master, payload, as_of=date(2026, 10, 8), hospital_ids=["H-BUSAN-PAIK"])
    (result,) = results
    assert result.status == "matched" and result.bed_count == 810
    raw = next(h for h in payload["hospitals"] if h["hospital_id"] == "H-BUSAN-PAIK")
    assert raw["bed_count"] == 810
    assert raw["bed_count_as_of"] == "2026-10-08"
    assert raw["hospital_type"] == "상급종합병원" and raw["type_verified"] is True
    other = next(h for h in payload["hospitals"] if h["hospital_id"] == "H-PNUH")
    assert other["bed_count"] is None


def test_names_that_map_to_another_master_hospital_are_ignored() -> None:
    master, payload = _master_payload()
    # Searching 부산대학교병원 also returns 양산부산대학교병원; only the exact hospital counts.
    client = FakeClient(
        {"부산대학교병원": _basis("부산대학교병원", "양산부산대학교병원", "부산대학교치과병원")},
        {"Y0": {"permSbdCnt": "1048"}},
    )
    _, results = hira.sync_master(client, master, payload, as_of=date(2026, 10, 8), hospital_ids=["H-PNUH"])
    assert results[0].status == "matched" and results[0].hira.ykiho == "Y0"


def test_ambiguous_or_missing_match_changes_nothing() -> None:
    master, payload = _master_payload()
    before = json.dumps(payload, ensure_ascii=False)
    client = FakeClient({"인제대학교부산백병원": _basis("인제대학교부산백병원", "인제대학교 부산백병원")}, {})
    payload, results = hira.sync_master(client, master, payload, as_of=date(2026, 10, 8), hospital_ids=["H-BUSAN-PAIK", "H-KOSIN"])
    assert [r.status for r in results] == ["ambiguous", "not_found"]
    assert json.dumps(payload, ensure_ascii=False) == before


def test_missing_bed_count_stays_empty_but_type_is_confirmed() -> None:
    master, payload = _master_payload()
    client = FakeClient({"동아대학교병원": _basis("동아대학교병원")}, {"Y0": {"stdSickbdCnt": "900"}})
    payload, results = hira.sync_master(client, master, payload, as_of=date(2026, 10, 8), hospital_ids=["H-DAUH"])
    raw = next(h for h in payload["hospitals"] if h["hospital_id"] == "H-DAUH")
    assert results[0].bed_count is None
    assert raw["bed_count"] is None and raw["bed_count_as_of"] is None
    assert raw["type_verified"] is True


def test_unsubscribed_key_stops_the_sync() -> None:
    master, payload = _master_payload()

    class Unsubscribed:
        def get_json(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
            raise PublicDataClientError(
                "Public Data Portal request failed: HTTP 403 error=SERVICE_KEY_IS_NOT_REGISTERED_ERROR code=30"
            )

    with pytest.raises(PublicDataClientError):
        hira.sync_master(Unsubscribed(), master, payload, as_of=date(2026, 10, 8))
    assert hira.is_not_subscribed(PublicDataClientError("x code=30"))


def test_committed_master_has_no_unverified_bed_counts() -> None:
    payload = json.loads(master_service.DEFAULT_MASTER_FILE.read_text(encoding="utf-8"))
    for raw in payload["hospitals"]:
        if raw.get("bed_count") is not None:
            assert raw.get("bed_count_as_of") and raw.get("type_verified") is True
