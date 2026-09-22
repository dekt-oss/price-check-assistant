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
