"""유사 규모 (nationwide size peers) grouping, name cleanup and the trend chart data."""

from __future__ import annotations

import dataclasses
from decimal import Decimal

from purchase_price.scripts.discover_size_peers import short_name
from purchase_price.services import hospital_master as hm
from purchase_price.ui import benchmark_charts as charts


def _hospital(hid: str, *, group: str = "core", beds: int | None = None, disclosed: int | None = None, region: str = "부산") -> hm.Hospital:
    return hm.Hospital(
        hospital_id=hid, canonical_name=hid, short_name=hid, aliases=(), foundation="", network="N" if group == "core" else "",
        region=region, hospital_type="상급종합병원", ownership="사립대학병원", bed_count=beds, bed_count_as_of=None,
        group=group, disclosed_bed_count=disclosed, disclosed_bed_year=2024 if disclosed else None,
    )


def test_similar_size_uses_bed_range_and_includes_nationwide_peers() -> None:
    master = hm.HospitalMaster(
        [
            _hospital("A", disclosed=810),
            _hospital("B", group="size_peer", disclosed=847, region="경기"),
            _hospital("C", group="size_peer", disclosed=700, region="서울"),
            _hospital("D", group="size_peer", disclosed=866, region="부산"),
            _hospital("E", group="size_peer", disclosed=None, region="부산"),
        ]
    )
    target = master.get("A")
    assert target is not None
    peers = master.peer_group(target, hm.PEER_SIMILAR_SIZE, bed_range=(700, 850))
    assert [p.hospital_id for p in peers] == ["B", "C"]  # largest first, target excluded, unknown beds excluded


def test_curated_groups_ignore_nationwide_size_peers() -> None:
    master = hm.HospitalMaster(
        [_hospital("A", disclosed=810), _hospital("B"), _hospital("D", group="size_peer", disclosed=866)]
    )
    target = master.get("A")
    assert target is not None
    assert [p.hospital_id for p in master.peer_group(target, hm.PEER_REGION)] == ["B"]
    assert [p.hospital_id for p in master.peer_group(target, hm.PEER_SAME_TYPE)] == ["B"]


def test_hira_bed_count_wins_over_disclosed_count() -> None:
    h = _hospital("A", beds=820, disclosed=810)
    assert h.size_beds == 820 and h.size_beds_text == "820"
    h2 = dataclasses.replace(h, bed_count=None)
    assert h2.size_beds == 810 and h2.size_beds_text == "810 (공시 2024)"
    assert dataclasses.replace(h2, disclosed_bed_count=None).size_beds_text == "자료 없음"


def test_committed_master_has_busan_paik_disclosed_beds_and_size_peers() -> None:
    master = hm.load_hospital_master()
    paik = master.get("H-BUSAN-PAIK")
    assert paik is not None and paik.disclosed_bed_count == 810
    peers = master.peer_group(paik, hm.PEER_SIMILAR_SIZE, bed_range=(700, 850))
    assert len(peers) >= 25
    assert all(700 <= (p.size_beds or 0) <= 850 for p in peers)
    assert {p.hospital_type for p in peers} <= {"상급종합병원", "종합병원"}


def test_short_names() -> None:
    assert short_name("의료법인 창원한마음병원") == "창원한마음병원"
    assert short_name("재단법인예수병원유지재단예수병원") == "예수병원"
    assert short_name("학교법인 건양교육재단 건양대학교병원") == "건양대학교병원"
    assert short_name("경희대학교병원") == "경희대학교병원"


def test_trend_frame_adds_computed_average_and_keeps_gaps() -> None:
    table = {
        "부산백": {2023: Decimal("45"), 2024: Decimal("50.4")},
        "P1": {2023: Decimal("40"), 2024: Decimal("46")},
        "P2": {2023: None, 2024: Decimal("48")},
    }
    frame = charts.trend_frame(table, "부산백")
    avg = frame[frame["구분"] == charts.ROLE_AVERAGE].set_index("연도")
    assert avg.loc["2023", "값"] == 40.0 and avg.loc["2023", "평균 병원 수"] == 1
    assert avg.loc["2024", "값"] == 47.0 and avg.loc["2024", "평균 병원 수"] == 2
    assert not ((frame["병원"] == "P2") & (frame["연도"] == "2023")).any()  # no filled gap
    chart = charts.trend_chart(frame, unit_label="%")
    spec = chart.to_dict()
    y_scale = spec["layer"][0]["encoding"]["y"]["scale"]
    assert y_scale["zero"] is False and y_scale["domain"][0] > 0
    wide = charts.wide_table(frame)
    assert list(wide["병원"])[:2] == ["부산백", "비교군 평균"]
