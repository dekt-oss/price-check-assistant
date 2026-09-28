from pathlib import Path

from purchase_price import domain
from purchase_price import evidence_domain


def test_legacy_domain_reexports_same_v3_enum_objects() -> None:
    assert domain.IdentityEvidenceStatus is evidence_domain.IdentityEvidenceStatus
    assert domain.PriceEvidenceStatus is evidence_domain.PriceEvidenceStatus
    assert domain.SafetyEvidenceStatus is evidence_domain.SafetyEvidenceStatus
    assert domain.MfdsItemAuthorizationType is evidence_domain.MfdsItemAuthorizationType
    assert domain.UnitPriceBasis is evidence_domain.UnitPriceBasis


def test_streamlit_runtime_does_not_require_new_v3_names_from_cached_legacy_domain() -> None:
    runtime_files = {
        "pages/1_대시보드.py": (
            "IdentityEvidenceStatus",
            "PriceEvidenceStatus",
        ),
        "src/purchase_price/services/mfds_identity_index.py": (
            "IdentityEvidenceStatus",
            "MfdsItemAuthorizationType",
        ),
        "src/purchase_price/services/safety_support.py": (
            "SafetyEvidenceStatus",
        ),
        "src/purchase_price/services/track_b_db_quote_comparison.py": (
            "PriceEvidenceStatus",
            "UnitPriceBasis",
        ),
    }

    for path, names in runtime_files.items():
        source = Path(path).read_text(encoding="utf-8")
        assert "from purchase_price.evidence_domain import" in source
        for name in names:
            assert name in source

    dashboard = Path("pages/1_대시보드.py").read_text(encoding="utf-8")
    assert "from purchase_price.domain import IdentityEvidenceStatus" not in dashboard
