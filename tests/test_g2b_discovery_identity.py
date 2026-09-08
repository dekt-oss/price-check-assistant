from purchase_price.services.g2b_unmapped_discovery import _model_matches_title


def test_short_model_requires_complete_title_token():
    assert _model_matches_title("M1", "환자감시장치 M1") is True
    assert _model_matches_title("M1", "환자감시장치 XM100") is False
    assert _model_matches_title("A3", "의료장비 A30 Pro") is False


def test_long_model_keeps_punctuation_tolerant_matching():
    assert _model_matches_title("C-5570", "ApeosPrint C5570 GK") is True
    assert _model_matches_title("GMSR-182", "GMSR182 약품냉장고") is True


def test_model_prefix_is_not_treated_as_exact_model():
    assert _model_matches_title("FLOW-C", "FLOW-C anesthesia machine") is True
    assert _model_matches_title("FLOW-C", "FLOW-C20 anesthesia machine") is False


def test_accessory_label_is_not_promoted_to_same_model_band():
    assert _model_matches_title("FLOW-C", "OTHER FLOW-C accessory") is False
    assert _model_matches_title("FLOW-C", "FLOW-C 부속품") is False
