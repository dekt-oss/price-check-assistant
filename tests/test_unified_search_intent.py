from purchase_price.services.unified_search_intent import interpret_unified_search


def test_dfm100_short_model_hydrates_known_model_and_product() -> None:
    result = interpret_unified_search(search_text="DFM100")

    assert result.product_name == "심장 충격기"
    assert result.model_name == "Efficia DFM100"
    assert result.manufacturer == ""
    assert result.mapping_status == "unverified"
    assert result.mapping_verified is False
    assert result.auto_hydrated_fields == ("model_name", "product_name")


def test_compound_dfm100_input_hydrates_manufacturer_model_and_product() -> None:
    result = interpret_unified_search(
        search_text="필립스 Efficia DFM100 심장 충격기"
    )

    assert result.product_name == "심장 충격기"
    assert result.manufacturer == "Philips"
    assert result.model_name == "Efficia DFM100"
    assert result.mapping_status == "unverified"
    assert set(result.auto_hydrated_fields) == {
        "product_name",
        "manufacturer",
        "model_name",
    }


def test_rotapro_uses_verified_mapping_without_inventing_manufacturer() -> None:
    result = interpret_unified_search(search_text="ROTAPRO")

    assert result.product_name == "혈관박리카테터장치"
    assert result.model_name == "ROTAPRO"
    assert result.manufacturer == ""
    assert result.mapping_verified is True
    assert result.evidence_label == "검증된 모델 매핑"


def test_minion_stays_unverified_search_hint() -> None:
    result = interpret_unified_search(search_text="MinION Mk1D")

    assert result.product_name == "염기서열분석기"
    assert result.model_name == "MinION Mk1D"
    assert result.mapping_verified is False
    assert result.evidence_label == "등록된 모델 검색 힌트"


def test_explicit_detail_fields_are_not_overwritten() -> None:
    result = interpret_unified_search(
        search_text="DFM100",
        product_name="사용자 품명",
        manufacturer="사용자 제조사",
        model_name="사용자 모델",
        specification="사용자 규격",
    )

    assert result.product_name == "사용자 품명"
    assert result.manufacturer == "사용자 제조사"
    assert result.model_name == "사용자 모델"
    assert result.specification == "사용자 규격"
    assert result.auto_hydrated is False


def test_short_ambiguous_text_is_not_forced_into_model_mapping() -> None:
    result = interpret_unified_search(search_text="P2")

    assert result.product_name == "P2"
    assert result.model_name == ""
    assert result.mapping_status is None


def test_quote_short_model_finds_identity_through_the_search_model_table() -> None:
    from types import SimpleNamespace

    from purchase_price.services.unified_search_intent import lookup_identity_with_model_alias

    asked: list[str] = []

    def lookup(model: str):
        asked.append(model)
        return SimpleNamespace(status="success" if model == "Efficia DFM100" else "success_0")

    assert lookup_identity_with_model_alias("DFM100", lookup).status == "success"
    assert asked == ["DFM100", "Efficia DFM100"]

    asked.clear()
    # An exact registration is used as written, and an unknown model is not retried.
    assert lookup_identity_with_model_alias("Efficia DFM100", lookup).status == "success"
    assert lookup_identity_with_model_alias("ZZ-9999X", lookup).status == "success_0"
    assert asked == ["Efficia DFM100", "ZZ-9999X"]
