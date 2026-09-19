from purchase_price.services.g2b_product_mapping import G2BProductMapping
from purchase_price.services.track_b_supplemental_targets import (
    supplemental_verified_codes,
    supplemental_verified_targets,
)


def _mapping(
    model: str,
    code: str,
    name: str,
    *,
    verified: bool = True,
) -> G2BProductMapping:
    return G2BProductMapping(
        model_name=model,
        product_name=model,
        detail_product_name=name,
        detail_product_code=code,
        mapping_status="verified" if verified else "unverified",
    )


def test_default_registry_yields_only_verified_outside_segment_codes() -> None:
    targets = supplemental_verified_targets()

    assert [(t.detail_product_code, t.detail_product_name, t.segment) for t in targets] == [
        ("4511181101", "영상모니터", "45")
    ]
    assert targets[0].models == ("CX30N",)
    assert supplemental_verified_codes() == ("4511181101",)


def test_base_segment_codes_and_unverified_rows_are_excluded() -> None:
    rows = (
        _mapping("A", "4218170101", "심전계"),
        _mapping("B", "4511181101", "영상모니터"),
        _mapping("C", "4511181102", "다른영상모니터", verified=False),
    )

    assert supplemental_verified_codes(rows, base_segments=("42",)) == ("4511181101",)


def test_duplicate_models_for_same_code_are_collapsed_deterministically() -> None:
    rows = (
        _mapping("Z model", "4511181101", "영상모니터"),
        _mapping("A model", "4511181101", "영상모니터"),
    )

    targets = supplemental_verified_targets(rows, base_segments=("42",))

    assert len(targets) == 1
    assert targets[0].models == ("A model", "Z model")


def test_conflicting_names_for_same_supplemental_code_fail_closed() -> None:
    rows = (
        _mapping("A", "4511181101", "영상모니터"),
        _mapping("B", "4511181101", "모니터"),
    )

    try:
        supplemental_verified_targets(rows, base_segments=("42",))
    except ValueError as exc:
        assert "conflicting names" in str(exc)
    else:
        raise AssertionError("conflicting supplemental mapping must fail closed")
