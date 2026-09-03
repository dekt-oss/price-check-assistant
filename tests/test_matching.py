from purchase_price.services.matching import exact_model_match, normalize_text


def test_model_normalization():
    assert normalize_text("XYZ-100 ") == "xyz100"
    assert exact_model_match("XYZ-100", "xyz 100")
    assert not exact_model_match("XYZ-100", "XYZ-200")
