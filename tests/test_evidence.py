from purchase_price.evidence import canonical_payload_text, payload_sha256


def test_evidence_hash_is_order_independent_for_object_keys():
    left = {"model": "TN500", "price": 100, "nested": {"b": 2, "a": 1}}
    right = {"nested": {"a": 1, "b": 2}, "price": 100, "model": "TN500"}

    assert canonical_payload_text(left) == canonical_payload_text(right)
    assert payload_sha256(left) == payload_sha256(right)


def test_different_payload_has_different_hash():
    assert payload_sha256({"price": 100}) != payload_sha256({"price": 101})
