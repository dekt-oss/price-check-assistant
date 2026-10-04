from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from purchase_price.schemas import ProductQuery
from purchase_price.services import mfds_identity_corroboration as corroboration
from purchase_price.services.mfds_identity_corroboration import (
    identity_needs_review,
    is_weak_model_key,
    model_key_shape,
)
from purchase_price.services.mfds_identity_index import MfdsIdentityLookup, MfdsIdentityRecord
from purchase_price.services.structured_query_identity import canonicalize_product_query


def _record(model: str, company: str, product: str) -> MfdsIdentityRecord:
    return MfdsIdentityRecord(
        udi_di=None,
        product_name=product,
        classification_no=None,
        grade=None,
        permit_number="제허 00-000호",
        permit_date=None,
        model_name=model,
        trade_name=None,
        registered_company=company,
    )


def _lookup(query: str, *records: MfdsIdentityRecord) -> MfdsIdentityLookup:
    return MfdsIdentityLookup("success", query, "model", records)


@pytest.mark.parametrize(
    ("value", "shape"),
    [
        ("02-1255", "digits_only"),
        ("100mL", "unit_like"),
        ("16oz", "unit_like"),
        ("G5", "short"),
        ("RS-30", "short"),
        ("MK-PL50", "length_5_6"),
        ("SJ-DFM100", "distinctive"),
    ],
)
def test_model_key_shape(value: str, shape: str) -> None:
    from purchase_price.services.matching import normalize_text

    assert model_key_shape(normalize_text(value)) == shape


def test_weak_key_without_corroboration_needs_review() -> None:
    # Audit example: Heine G5 (ophthalmoscope maker) -> MFDS G-5 dental impression tray.
    lookup = _lookup("G5", _record("G-5", "(주)지니덴탈", "치과 인상 채득용 트레이"))

    assert identity_needs_review(lookup) is True
    assert identity_needs_review(lookup, manufacturer="Heine", product_name="검안경") is True


def test_weak_key_is_confirmed_by_company_or_product() -> None:
    lookup = _lookup("125", _record("125", "월드바이오텍", "교정용겸자"))

    assert identity_needs_review(lookup, manufacturer="월드바이오텍") is False
    assert identity_needs_review(lookup, product_name="교정용 겸자") is False


def test_weak_key_is_confirmed_by_recorded_importer_relation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        corroboration,
        "load_importer_relations",
        lambda: frozenset({("nonin", "유유메디컬스")}),
    )
    lookup = _lookup("3150", _record("3150", "주식회사 유유메디컬스", "펄스 옥시미터"))

    assert identity_needs_review(lookup, manufacturer="Masimo") is True
    assert identity_needs_review(lookup, manufacturer="Nonin medical") is False


def test_distinctive_key_is_never_held_for_review() -> None:
    lookup = _lookup("SJ-DFM100", _record("SJ-DFM100", "세종", "의료용흡인기"))

    assert is_weak_model_key("SJ-DFM100") is False
    assert identity_needs_review(lookup) is False


def test_non_model_matches_are_not_affected() -> None:
    record = _record("G-5", "(주)지니덴탈", "치과 인상 채득용 트레이")

    assert identity_needs_review(MfdsIdentityLookup("success", "G5", "permit", (record,))) is False
    assert identity_needs_review(MfdsIdentityLookup("success_0", "G5", None, ())) is False


def test_stale_lookup_object_is_supported() -> None:
    stale = SimpleNamespace(
        status="success",
        query="M1",
        match_type="model",
        records=(SimpleNamespace(registered_company="주식회사 탑메드", product_name="수동식의약품주입펌프"),),
    )

    assert identity_needs_review(stale, manufacturer="Permobil", product_name="전동휠체어") is True


def test_canonicalize_does_not_rewrite_query_from_uncorroborated_weak_key() -> None:
    # Audit example: Permobil M1 (power wheelchair) -> MFDS M1 infusion pump.
    lookup = _lookup("M1", _record("M1", "주식회사 탑메드", "수동식의약품주입펌프"))
    query = ProductQuery(product_name="전동휠체어", manufacturer="Permobil", model_name="M1")

    canonical = canonicalize_product_query(query, lookup)

    assert canonical.query == query
    assert canonical.canonicalized is False
    assert canonical.ambiguous is True


def test_canonicalize_still_applies_corroborated_weak_key() -> None:
    lookup = _lookup("125", _record("125", "월드바이오텍", "교정용겸자"))
    query = ProductQuery(product_name="", manufacturer="월드바이오텍", model_name="125")

    canonical = canonicalize_product_query(query, lookup)

    assert canonical.ambiguous is False
    assert canonical.query.product_name == "교정용겸자"


def test_importer_relations_registry_has_required_columns() -> None:
    header = Path("data/mfds_importer_relations.csv").read_text(encoding="utf-8").splitlines()[0]

    assert header == "manufacturer,mfds_registered_company,evidence_note"


def test_dashboard_routes_weak_keys_to_candidate_confirmation() -> None:
    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "from purchase_price.services.mfds_identity_corroboration import identity_needs_review" in source
    assert "selected_identity is None" in source
    assert '"review_reason": "weak_model_key" if weak_key_review else "ambiguous"' in source
    assert 'state.get("review_reason") == "weak_model_key"' in source
    live = source.index("live_identity = lookup_mfds_model_identity_live(query.model_name)")
    assert "identity_needs_review(\n            live_identity," in source[live : live + 400]


def test_importer_relations_are_evidenced_and_not_manufacturer_aliases() -> None:
    import csv

    from purchase_price.services.matching import normalize_text
    from purchase_price.services.product_matching import load_manufacturer_aliases

    with Path("data/mfds_importer_relations.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    aliases = load_manufacturer_aliases()

    assert rows
    for row in rows:
        assert len(normalize_text(row["manufacturer"])) >= 3
        assert len(normalize_text(row["mfds_registered_company"])) >= 3
        assert "audit" in row["evidence_note"]
        # Importers must stay out of the Track B manufacturer alias registry.
        assert normalize_text(row["mfds_registered_company"]) not in aliases
