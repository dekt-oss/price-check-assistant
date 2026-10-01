from pathlib import Path
from types import SimpleNamespace

from streamlit.testing.v1 import AppTest

from purchase_price.domain import SafetyEvidenceStatus
from purchase_price.services.safety_support import (
    MedicalDeviceRecallRecord,
    SafetyCheckStatus,
    build_manual_safety_check_state,
    build_safety_state_from_recall_lookup,
    evaluate_official_recall_records,
    no_match_safety_state,
)


def test_manual_safety_state_preserves_exact_verification_keys() -> None:
    state = build_manual_safety_check_state(
        model_name="DFM-100",
        permit_numbers=["수허 24-1", "수허 24-1", "제허 25-2"],
    )

    assert state.status == SafetyCheckStatus.CHECK_REQUIRED
    assert state.evidence_status == SafetyEvidenceStatus.NOT_CONNECTED
    assert state.search_keys == (
        "모델명: DFM-100",
        "식약처 품목번호: 수허 24-1",
        "식약처 품목번호: 제허 25-2",
    )
    assert "공식 안전정보 확인 결과가 아닙니다" in state.message


def test_manual_safety_state_without_identity_is_not_connected() -> None:
    state = build_manual_safety_check_state()

    assert state.status == SafetyCheckStatus.NOT_CONNECTED
    assert state.evidence_status == SafetyEvidenceStatus.NOT_CONNECTED
    assert not state.search_keys
    assert "identity를 먼저 확인" in state.message


def test_successful_zero_match_wording_never_claims_safe() -> None:
    state = no_match_safety_state(model_name="DFM-100", permit_numbers=["수허 24-1"])

    assert state.status == SafetyCheckStatus.NO_MATCH
    assert state.evidence_status == SafetyEvidenceStatus.CHECKED_NONE
    assert state.message == "현재 연결된 공식 안전정보에서 일치 항목을 확인하지 못함"
    assert "안전함" not in state.message
    assert "문제없" not in state.message


def test_safety_supplier_page_loads_without_live_api_calls() -> None:
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(root / "pages" / "5_의료기기_안전_공급사.py")

    app.run(timeout=10)

    assert not app.exception
    assert app.title[0].value == "의료기기 안전·업체·조달 확인"
    assert any("공식 API를 자동조회" in item.value for item in app.caption)



def test_legacy_error_maps_to_v3_check_failed() -> None:
    from purchase_price.services.safety_support import SafetyCheckState

    state = SafetyCheckState(
        status=SafetyCheckStatus.ERROR,
        message="조회 실패",
    )

    assert state.evidence_status == SafetyEvidenceStatus.CHECK_FAILED


def test_checked_none_preserves_query_timestamp_and_source() -> None:
    state = no_match_safety_state(
        model_name="C101",
        permit_numbers=["수신 22-2177호"],
        checked_at="2026-09-28T02:30:00Z",
        source_url="https://example.test/mfds-safety",
    )

    assert state.evidence_status == SafetyEvidenceStatus.CHECKED_NONE
    assert state.checked_at == "2026-09-28T02:30:00Z"
    assert state.source_url == "https://example.test/mfds-safety"


def test_official_recall_exact_permit_and_model_is_red_without_inventing_lot_scope() -> None:
    state = evaluate_official_recall_records(
        [
            MedicalDeviceRecallRecord(
                permit_number="수신 22-2177호",
                model_name="C101",
                reason="품질 문제",
                action_date="2026-09-20",
            )
        ],
        model_name="C101",
        permit_numbers=["수신22-2177호"],
        checked_at="2026-09-28T08:00:00Z",
    )

    assert state.evidence_status == SafetyEvidenceStatus.RED
    assert state.lot_scope is None
    assert "Source 미제공" in state.message
    assert "2026-09-20" in state.message


def test_official_recall_permit_match_with_unknown_model_scope_is_amber() -> None:
    state = evaluate_official_recall_records(
        [
            MedicalDeviceRecallRecord(
                permit_number="수신 22-2177호",
                model_name=None,
                manufacturing_number="LOT-1",
            )
        ],
        model_name="C101",
        permit_numbers=["수신 22-2177호"],
    )

    assert state.evidence_status == SafetyEvidenceStatus.AMBER
    assert state.status == SafetyCheckStatus.CHECK_REQUIRED
    assert state.lot_scope is None


def test_official_recall_explicit_all_models_scope_can_be_red() -> None:
    state = evaluate_official_recall_records(
        [
            MedicalDeviceRecallRecord(
                permit_number="수신 22-2177호",
                applies_to_all_models=True,
                manufacturing_number="LOT-A",
            )
        ],
        model_name="C101",
        permit_numbers=["수신 22-2177호"],
    )

    assert state.evidence_status == SafetyEvidenceStatus.RED
    assert state.lot_scope == "LOT-A"


def test_official_recall_model_only_never_confirms_exact_product_action() -> None:
    state = evaluate_official_recall_records(
        [
            MedicalDeviceRecallRecord(
                permit_number="수신 99-9999호",
                model_name="C101",
            )
        ],
        model_name="C101",
        permit_numbers=[],
    )

    assert state.evidence_status == SafetyEvidenceStatus.AMBER
    assert "exact 식약처 품목번호" in state.message


def test_official_recall_successful_zero_is_checked_none_not_safe() -> None:
    state = evaluate_official_recall_records(
        [],
        model_name="C101",
        permit_numbers=["수신 22-2177호"],
        checked_at="2026-09-28T08:00:00Z",
    )

    assert state.evidence_status == SafetyEvidenceStatus.CHECKED_NONE
    assert "안전함" not in state.message



def test_recall_lookup_not_authorized_is_explicit_semantically() -> None:
    state = build_safety_state_from_recall_lookup(
        SimpleNamespace(
            status="not_authorized",
            checked_at="2026-09-30T08:00:00+09:00",
            source_url="https://www.data.go.kr/data/15056785/openapi.do",
            records=(),
        ),
        model_name="DFM100",
        permit_numbers=["수허 12-3456"],
    )

    assert state.status == SafetyCheckStatus.NOT_AUTHORIZED
    assert state.evidence_status == SafetyEvidenceStatus.NOT_AUTHORIZED
    assert "활용승인" in state.message
    assert "안전함" not in state.message
    assert state.checked_at == "2026-09-30T08:00:00+09:00"


def test_recall_lookup_failure_is_check_failed_not_zero() -> None:
    state = build_safety_state_from_recall_lookup(
        SimpleNamespace(
            status="failure",
            checked_at="2026-09-30T08:00:00+09:00",
            source_url="https://example.test/recall",
            records=(),
        ),
        model_name="DFM100",
    )

    assert state.status == SafetyCheckStatus.ERROR
    assert state.evidence_status == SafetyEvidenceStatus.CHECK_FAILED
    assert "0건으로 해석하지" in state.message


def test_recall_lookup_success_zero_is_checked_none_without_safe_claim() -> None:
    state = build_safety_state_from_recall_lookup(
        SimpleNamespace(
            status="success_0",
            checked_at="2026-09-30T08:00:00+09:00",
            source_url="https://example.test/recall",
            records=(),
        ),
        model_name="DFM100",
    )

    assert state.status == SafetyCheckStatus.NO_MATCH
    assert state.evidence_status == SafetyEvidenceStatus.CHECKED_NONE
    assert "exact 일치 기록을 확인하지 못했습니다" in state.message
    assert "제품이 안전하다는 판정이 아니며" in state.message


def test_service04_positive_model_hit_remains_amber_without_permit_scope() -> None:
    state = build_safety_state_from_recall_lookup(
        SimpleNamespace(
            status="success",
            query_type="model",
            checked_at="2026-09-30T08:00:00+09:00",
            source_url="https://example.test/recall",
            records=(
                SimpleNamespace(
                    report_state_name="회수중",
                    report_kind_name="회수",
                    report_submit_date="20260920",
                ),
            ),
        ),
        model_name="DFM100",
        permit_numbers=["수허 12-3456"],
    )

    assert state.status == SafetyCheckStatus.CHECK_REQUIRED
    assert state.evidence_status == SafetyEvidenceStatus.AMBER
    assert "일치 기록 1건" in state.message
    assert "exact 식약처 품목번호가 없어" in state.message
    assert state.evidence_status != SafetyEvidenceStatus.RED


def test_safety_supplier_page_uses_official_recall_lookup_contract() -> None:
    source = Path("pages/5_의료기기_안전_공급사.py").read_text(encoding="utf-8")

    assert "lookup_mfds_recall" in source
    assert "build_safety_state_from_recall_lookup" in source
    assert "식약처 Safety API" in source
    assert "식약처 회수·판매중지 API 확인시각" in source
    assert "exact 식약처 품목번호가 없어" in source
