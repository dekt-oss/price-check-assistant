from __future__ import annotations

import sqlite3
from pathlib import Path

from purchase_price.scripts.audit_mfds_model_recall import (
    TrackBModel,
    audit,
    classify_affix,
    load_track_b_models,
    model_key_shape,
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
    assert report["importer_pair_candidates"] == []
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
            model_key TEXT, model_name TEXT, manufacturer TEXT, identity_conflict INTEGER,
            detail_code TEXT
        );
        INSERT INTO track_b_delivery_lines VALUES
            ('dfm100', 'DFM100', '세종', 0, '4221150101'),
            ('dfm100', 'DFM-100', '세종', 0, '4221150101'),
            ('lamp1', 'LAMP-1', '조명', 0, '3910110101'),
            ('bad', 'BAD', 'x', 1, '4221150101'),
            ('', '', 'x', 0, '4221150101');
        """
    )

    models = load_track_b_models(connection)
    medical = load_track_b_models(connection, detail_prefix="42")
    connection.close()

    assert sorted((m.model_key, m.line_count) for m in models) == [("dfm100", 2), ("lamp1", 1)]
    assert [(m.model_key, m.line_count) for m in medical] == [("dfm100", 2)]


def test_model_key_shape() -> None:
    assert model_key_shape("021255") == "digits_only"
    assert model_key_shape("100ml") == "unit_like"
    assert model_key_shape("1015cm") == "unit_like"
    assert model_key_shape("rs30") == "short"
    assert model_key_shape("pads16") == "length_5_6"
    assert model_key_shape("sjdfm100") == "distinctive"


def test_exact_policy_counts_weak_keys_without_company_agreement(tmp_path: Path) -> None:
    path = tmp_path / "mfds.sqlite"
    connection = sqlite3.connect(path)
    upsert_identity_records(
        connection,
        [
            parse_mfds_product_info_record(
                {"FOML_INFO": model, "MNFT_IPRT_ENTP_NM": company, "PRDLST_NM": product}
            )
            for model, company, product in (
                ("02-1255", "(주)레이언스", "교정용브라켓"),
                ("RS-30", "디메드", "지혈용품"),
                ("MK-PL50", "(주)엠케이티", "플라즈마멸균기"),
                ("125", "월드바이오텍", "교정용겸자"),
            )
        ],
    )
    connection.commit()
    models = [
        _model("02-1255", "솔고바이오메디칼"),  # digits-only, other company -> downgrade
        _model("RS30", "시우라이팅"),  # short, other company -> downgrade
        _model("MK-PL50", "엠케이티"),  # length 5-6 -> not a weak shape, unaffected
        _model("125", "월드바이오텍"),  # digits-only but company agrees -> stays confirmed
    ]

    report = audit(connection, models, sample_size=10, seed=1)
    connection.close()

    policy = report["exact_match_policy"]
    assert policy["exact_models"] == 4
    assert policy["would_downgrade_to_needs_review"] == 2
    assert policy["by_shape"]["digits_only"]["models"] == {"disagree": 1, "agree_company": 1}
    assert policy["by_shape"]["short"]["models"] == {"disagree": 1}
    assert policy["by_shape"]["length_5_6"]["models"] == {"agree_company": 1}


def test_importer_pairs_need_two_distinctive_models(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "mfds.sqlite")
    upsert_identity_records(
        connection,
        [
            parse_mfds_product_info_record(
                {"FOML_INFO": model, "MNFT_IPRT_ENTP_NM": company, "PRDLST_NM": product}
            )
            for model, company, product in (
                ("B105M Patient Monitor", "애크미코리아(주)", "환자감시장치"),
                ("B125M Patient Monitor", "애크미코리아(주)", "환자감시장치"),
                ("Accu-Chek Guide meter", "한국로슈진단(주)", "혈당측정기"),
            )
        ],
    )
    connection.commit()
    models = [
        _model("B105M Patient Monitor", "Acme medical"),
        _model("B125M Patient Monitor", "Acme medical"),
        _model("Accu-Chek Guide meter", "Roche diabetes care"),
    ]

    report = audit(connection, models, sample_size=10, seed=1)
    connection.close()

    pairs = report["importer_pair_candidates"]
    assert [(p["manufacturer"], p["mfds_registered_company"], p["distinct_models"]) for p in pairs] == [
        ("Acme medical", "애크미코리아(주)", 2)
    ]


def test_product_name_agreement_counts_as_corroboration(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "mfds.sqlite")
    upsert_identity_records(
        connection,
        [
            parse_mfds_product_info_record(
                {"FOML_INFO": "3150", "MNFT_IPRT_ENTP_NM": "주식회사 유유메디컬스", "PRDLST_NM": "펄스 옥시미터"}
            )
        ],
    )
    connection.commit()
    model = TrackBModel(normalize_text("3150"), "3150", "Nonin medical", 1, "펄스옥시미터")

    report = audit(connection, [model], sample_size=10, seed=1)
    connection.close()

    assert report["exact_match_policy"]["by_shape"]["digits_only"]["models"] == {"agree_product": 1}
    assert report["exact_match_policy"]["would_downgrade_to_needs_review"] == 0
