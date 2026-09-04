import json

from purchase_price.services.g2b_contract_evidence import (
    G2B_CONTRACT_DATASET_URL,
    G2B_CONTRACT_PARSER_VERSION,
    G2B_CONTRACT_SOURCE_NAME,
    parse_contract_evidence,
)


def test_contract_evidence_links_public_raw_provenance() -> None:
    evidence = parse_contract_evidence(
        {
            "dcsnCntrctNo": "2026-001",
            "cntrctCnclsMthdNm": "일반경쟁",
            "cntrctInsttNm": "예시기관",
            "prdctClsfcNoNm": "심장충격기",
            "cntrctCnclsDate": "20260901",
            "cntrctDtlInfoUrl": "https://example.invalid/contract/2026-001",
            "totCntrctAmt": "999999999",
            "serviceKey": "must-not-leak",
            "token": "must-not-leak",
            "password": "must-not-leak",
            "secret": "must-not-leak",
        }
    )

    provenance = evidence.provenance
    assert provenance is not None
    assert provenance.source_name == G2B_CONTRACT_SOURCE_NAME
    assert provenance.source_record_id == "2026-001"
    assert provenance.source_url == "https://example.invalid/contract/2026-001"
    assert provenance.parser_version == G2B_CONTRACT_PARSER_VERSION
    assert len(provenance.fingerprint) == 64

    payload = json.loads(provenance.payload_text)
    assert payload == {
        "cntrctCnclsDate": "20260901",
        "cntrctCnclsMthdNm": "일반경쟁",
        "cntrctDtlInfoUrl": "https://example.invalid/contract/2026-001",
        "cntrctInsttNm": "예시기관",
        "dcsnCntrctNo": "2026-001",
        "prdctClsfcNoNm": "심장충격기",
    }
    assert "totCntrctAmt" not in payload
    for forbidden in ("serviceKey", "token", "password", "secret", "must-not-leak"):
        assert forbidden not in provenance.payload_text


def test_contract_evidence_uses_dataset_url_when_detail_url_missing() -> None:
    evidence = parse_contract_evidence(
        {
            "dcsnCntrctNo": "2026-002",
            "prdctClsfcNoNm": "의료용냉장고",
        }
    )

    assert evidence.provenance is not None
    assert evidence.provenance.source_record_id == "2026-002"
    assert evidence.provenance.source_url == G2B_CONTRACT_DATASET_URL
