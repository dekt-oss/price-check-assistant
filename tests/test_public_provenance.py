import json

import pytest

from purchase_price.services.public_provenance import (
    allow_list_public_payload,
    build_public_evidence_provenance,
)


def test_unknown_and_secret_like_fields_never_enter_public_payload() -> None:
    payload = {
        "recordId": "R-1",
        "publicField": "visible",
        "serviceKey": "do-not-store",
        "token": "do-not-store",
        "password": "do-not-store",
        "secret": "do-not-store",
    }

    safe = allow_list_public_payload(
        payload,
        allow_fields=("recordId", "publicField"),
    )

    assert safe == {"recordId": "R-1", "publicField": "visible"}
    text = json.dumps(safe, ensure_ascii=False)
    assert "do-not-store" not in text
    for forbidden in ("serviceKey", "token", "password", "secret"):
        assert forbidden not in text


def test_sensitive_field_name_cannot_be_allow_listed() -> None:
    with pytest.raises(ValueError, match="sensitive"):
        allow_list_public_payload(
            {"serviceKey": "should-never-be-stored"},
            allow_fields=("serviceKey",),
        )


def test_nested_secret_like_keys_are_removed_recursively() -> None:
    safe = allow_list_public_payload(
        {
            "public": {
                "name": "visible",
                "metadata": {
                    "api_token": "nested-secret",
                    "safe": "kept",
                },
            }
        },
        allow_fields=("public",),
    )

    assert safe == {"public": {"name": "visible", "metadata": {"safe": "kept"}}}
    assert "nested-secret" not in json.dumps(safe, ensure_ascii=False)


def test_fingerprint_is_stable_for_same_allow_listed_public_fields() -> None:
    first = build_public_evidence_provenance(
        source_name="source",
        payload={"b": 2, "ignored": "x", "a": 1},
        allow_fields=("a", "b"),
        source_record_id="R-1",
        source_url="https://example.invalid/R-1",
        parser_version="test-v1",
    )
    second = build_public_evidence_provenance(
        source_name="source",
        payload={"a": 1, "b": 2, "ignored": "changed"},
        allow_fields=("a", "b"),
        source_record_id="R-1",
        source_url="https://example.invalid/R-1",
        parser_version="test-v1",
    )

    assert first.payload_text == '{"a":1,"b":2}'
    assert first.fingerprint == second.fingerprint
    assert len(first.fingerprint) == 64
