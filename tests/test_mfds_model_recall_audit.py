from __future__ import annotations

import sqlite3
from pathlib import Path

from purchase_price.scripts.audit_mfds_model_recall import (
    TrackBModel,
    audit,
    classify_affix,
    load_track_b_models,
)
from purchase_price.services.matching import normalize_text
from purchase_price.services.mfds_identity_index import (
    parse_mfds_product_info_record,
    upsert_identity_records,
)


def _mfds_index(path: Path) -> None:
    connection = sqlite3.connect(path)
    records = [
        parse_mfds_product_info_record(
            {"PRDLST_NM": product, "FOML_INFO": model, "MNFT_IPRT_ENTP_NM": company}
        )
        for product, model, company in (
            ("의료용흡인기", "SJ-DFM100", "(주)세종메디칼"),
            ("의료용흡인기", "SJ-DFM100-1", "(주)세종메디칼"),
            ("전기수술기", "FT10", "메드트로닉코리아"),
            ("초음파영상진단장치", "LOGIQ E10", "지이헬스케어"),
            ("초음파영상진단장치", "LOGIQ E10S", "지이헬스케어"),
            ("환자감시장치", "ABC", "알파"),
        )
    ]
    upsert_identity_records(connection, records)
    connection.commit()
    connection.close()


def _model(name: str, manufacturer: str | None, lines: int = 1) -> TrackBModel:
    return TrackBModel(normalize_text(name), name, manufacturer, lines)


def test_classify_affix() -> None:
    assert classify_affix("dfm100", "dfm100") == "exact"
    assert classify_affix("dfm100", "sjdfm100") == "prefix_added"
    assert classify_affix("dfm100", "dfm1001") == "suffix_added"
    assert classify_affix("dfm100", "xdfm100y") == "infix"


def test_audit_buckets_exact_alias_affix_and_none_on_read_only_index(tmp_path: Path) -> None:
    path = tmp_path / "mfds.sqlite"
    _mfds_index(path)
    models = [
        _model("FT10", "Medtronic"),
        _model("VLFT10GEN", "Medtronic"),  # verified alias of FT10 in data/model_aliases.csv
        _model("DFM100", "세종메디칼", lines=7),  # MFDS: SJ-DFM100 and SJ-DFM100-1
        _model("LOGIQ-E10", "GE"),  # exact after normalization
        _model("NOPE-9999", "누구"),
        _model("AB", "알파"),  # too short for affix search
    ]
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        report = audit(connection, models, sample_size=100, seed=1)
    finally:
        connection.close()

    categories = report["categories"]
    assert categories["exact"]["models"] == 2
    assert categories["verified_alias"]["models"] == 1
    assert categories["mixed_affix"]["models"] == 1
    assert categories["mixed_affix"]["company"] == {"agree": 1}
    assert categories["mixed_affix"]["candidate_models"]["two_to_five"] == 1
    assert categories["none"]["models"] == 1
    assert categories["none_short_key"]["models"] == 1
    dfm = report["examples"]["mixed_affix"][0]
    assert dfm["track_b_model"] == "DFM100"
    assert {c["model"] for c in dfm["mfds_candidates"]} == {"SJ-DFM100", "SJ-DFM100-1"}


def test_prefix_only_candidate_is_reported_as_prefix_added(tmp_path: Path) -> None:
    path = tmp_path / "mfds.sqlite"
    connection = sqlite3.connect(path)
    upsert_identity_records(
        connection,
        [parse_mfds_product_info_record({"FOML_INFO": "SJ-ZX900", "MNFT_IPRT_ENTP_NM": "다른회사"})],
    )
    connection.commit()

    report = audit(connection, [_model("ZX900", "세종메디칼")], sample_size=10, seed=1)
    connection.close()

    assert report["categories"]["prefix_added"]["company"] == {"disagree": 1}


def test_load_track_b_models_groups_by_key_and_skips_conflicts(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "tb.sqlite")
    connection.executescript(
        """
        CREATE TABLE track_b_delivery_lines (
            model_key TEXT, model_name TEXT, manufacturer TEXT, identity_conflict INTEGER
        );
        INSERT INTO track_b_delivery_lines VALUES
            ('dfm100', 'DFM100', '세종', 0),
            ('dfm100', 'DFM-100', '세종', 0),
            ('bad', 'BAD', 'x', 1),
            ('', '', 'x', 0);
        """
    )

    models = load_track_b_models(connection)
    connection.close()

    assert [(m.model_key, m.line_count) for m in models] == [("dfm100", 2)]
