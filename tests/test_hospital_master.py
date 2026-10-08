from __future__ import annotations

import dataclasses

import pytest

from purchase_price.services import hospital_master as hm


@pytest.fixture(scope="module")
def master() -> hm.HospitalMaster:
    return hm.load_hospital_master()


def test_seed_contains_the_plan_hospitals_without_invented_bed_counts(master: hm.HospitalMaster) -> None:
    names = {hospital.canonical_name for hospital in master.hospitals}
    assert {
        "인제대학교부산백병원",
        "인제대학교해운대백병원",
        "인제대학교일산백병원",
        "인제대학교상계백병원",
        "부산대학교병원",
        "양산부산대학교병원",
        "동아대학교병원",
        "고신대학교복음병원",
    } <= names
    assert all(hospital.bed_count is None for hospital in master.hospitals)


@pytest.mark.parametrize(
    "spelling",
    ["부산백병원", "인제대부산백병원", "인제대학교 부산백병원", "인제대학교부산백병원", " 인제대 부산백병원 "],
)
def test_aliases_resolve_to_the_canonical_hospital(master: hm.HospitalMaster, spelling: str) -> None:
    hospital = master.resolve(spelling)
    assert hospital is not None and hospital.hospital_id == "H-BUSAN-PAIK"


def test_unknown_name_resolves_to_none(master: hm.HospitalMaster) -> None:
    assert master.resolve("서울아산병원") is None


def test_region_peer_group_for_busan_paik(master: hm.HospitalMaster) -> None:
    target = master.get("H-BUSAN-PAIK")
    assert target is not None
    peers = master.peer_group(target, hm.PEER_REGION)
    assert {peer.canonical_name for peer in peers} == {
        "부산대학교병원",
        "동아대학교병원",
        "고신대학교복음병원",
        "인제대학교해운대백병원",
    }


def test_network_peer_group_is_the_paik_network(master: hm.HospitalMaster) -> None:
    target = master.get("H-BUSAN-PAIK")
    assert target is not None
    peers = master.peer_group(target, hm.PEER_NETWORK)
    assert {peer.short_name for peer in peers} == {"해운대백병원", "일산백병원", "상계백병원"}


def test_same_type_peer_group_matches_type_and_ownership(master: hm.HospitalMaster) -> None:
    target = master.get("H-BUSAN-PAIK")
    assert target is not None
    peers = master.peer_group(target, hm.PEER_SAME_TYPE)
    assert all(p.hospital_type == "상급종합병원" and p.ownership == "사립대학병원" for p in peers)
    assert "부산대학교병원" not in {p.canonical_name for p in peers}


def test_similar_size_is_empty_until_bed_counts_exist(master: hm.HospitalMaster) -> None:
    target = master.get("H-BUSAN-PAIK")
    assert target is not None
    assert master.peer_group(target, hm.PEER_SIMILAR_SIZE) == ()
    sized = hm.HospitalMaster(
        [
            dataclasses.replace(target, bed_count=900),
            dataclasses.replace(master.get("H-PNUH"), bed_count=1_250),  # type: ignore[arg-type]
            dataclasses.replace(master.get("H-DAUH"), bed_count=990),  # type: ignore[arg-type]
        ]
    )
    peers = sized.peer_group(sized.get("H-BUSAN-PAIK"), hm.PEER_SIMILAR_SIZE)  # type: ignore[arg-type]
    assert [peer.hospital_id for peer in peers] == ["H-DAUH"]


def test_custom_peer_group_never_includes_the_target(master: hm.HospitalMaster) -> None:
    target = master.get("H-BUSAN-PAIK")
    assert target is not None
    peers = master.peer_group(target, hm.PEER_CUSTOM, custom_ids=["H-BUSAN-PAIK", "H-KOSIN"])
    assert [peer.hospital_id for peer in peers] == ["H-KOSIN"]


def test_unknown_peer_kind_raises(master: hm.HospitalMaster) -> None:
    target = master.hospitals[0]
    with pytest.raises(ValueError):
        master.peer_group(target, "nearby")
