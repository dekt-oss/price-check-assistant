from __future__ import annotations

from types import SimpleNamespace

from purchase_price.services.mfds_company_summary import (
    build_registered_company_summaries,
    company_identity_rows,
)


def _identity(
    company: str,
    model: str,
    permit: str,
    *,
    permit_date: str = "",
    udi: str = "",
):
    return SimpleNamespace(
        registered_company=company,
        model_name=model,
        permit_number=permit,
        permit_date=permit_date,
        udi_di=udi,
    )


def test_registered_company_summary_uses_only_live_confirmed_identity_rows() -> None:
    records = (
        _identity("회사A", "MODEL-1", "수허 1", permit_date="20240101"),
        _identity("회사A", "MODEL-2", "수허 2", permit_date="20250101"),
        _identity("회사B", "MODEL-3", "수허 3", permit_date="20230101"),
    )
    active_keys = {
        ("수허1", "model1"),
        ("수허3", "model3"),
    }
    crosslinks = (
        {
            "식약처 품목번호": "수허 1",
            "모델": "MODEL-1",
            "나라장터 직접거래": 2,
            "실제 조달 공급업체": "납품사A / 납품사B",
        },
        {
            "식약처 품목번호": "수허 3",
            "모델": "MODEL-3",
            "나라장터 직접거래": 0,
            "실제 조달 공급업체": "",
        },
    )

    summaries = build_registered_company_summaries(
        records,
        procurement_crosslinks=crosslinks,
        active_live_keys=active_keys,
    )

    assert [item.company_name for item in summaries] == ["회사A", "회사B"]
    company_a = summaries[0]
    assert company_a.registered_model_count == 1
    assert company_a.permit_count == 1
    assert company_a.latest_permit_date == "20240101"
    assert company_a.representative_models == ("MODEL-1",)
    assert company_a.direct_price_model_count == 1
    assert company_a.procurement_suppliers == ("납품사A", "납품사B")
    assert company_a.live_status == "국내 정상 확인"


def test_company_summary_never_claims_active_when_live_status_is_unavailable() -> None:
    summaries = build_registered_company_summaries(
        (
            _identity("회사A", "MODEL-1", "수허 1"),
            _identity("회사A", "MODEL-2", "수허 2"),
        )
    )

    assert len(summaries) == 1
    assert summaries[0].registered_model_count == 2
    assert summaries[0].live_status == "live 상태 미확인"


def test_company_drilldown_marks_non_live_rows_as_excluded_not_active() -> None:
    records = (
        _identity("회사A", "MODEL-1", "수허 1", udi="UDI-1"),
        _identity("회사A", "MODEL-2", "수허 2", udi="UDI-2"),
    )

    rows = company_identity_rows(
        records,
        "회사A",
        active_live_keys={("수허1", "model1")},
    )

    assert rows[0]["모델"] == "MODEL-1"
    assert rows[0]["상태"] == "국내 정상 확인"
    assert rows[1]["모델"] == "MODEL-2"
    assert rows[1]["상태"] == "기본표 제외 상태"


def test_company_drilldown_preserves_unverified_state_without_live_keys() -> None:
    rows = company_identity_rows(
        (_identity("회사A", "MODEL-1", "수허 1"),),
        "회사A",
        active_live_keys=None,
    )

    assert rows == [
        {
            "모델": "MODEL-1",
            "식약처 품목번호": "수허 1",
            "UDI-DI": "",
            "식약처 처리일": "",
            "상태": "live 상태 미확인",
        }
    ]


def test_dashboard_exposes_company_centric_workspace_contract() -> None:
    from pathlib import Path

    source = Path("pages/1_대시보드.py").read_text(encoding="utf-8")

    assert "품목 책임주체 · 식약처에 등록한 제조·수입업체" in source
    assert "나라장터 직접가격 보유 업체" in source
    assert "품목 책임주체 상세보기" in source
    assert "선택 업체 식약처 업허가 확인" in source
    assert "위 실제 납품업체와는 다른 관계입니다" in source
