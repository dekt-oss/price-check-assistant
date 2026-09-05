from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from openpyxl import Workbook

from purchase_price.collectors.manufacturer_public_catalog import (
    ManufacturerPublicCatalogCollector,
)
from purchase_price.domain import ComparisonScope, EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.services.pricing import assess_prices
from purchase_price.services.product_matching import ProductIdentity, grade_product_identity
from purchase_price.services.public_provenance import build_public_evidence_provenance
from purchase_price.services.quote_comparability import (
    QuoteComparabilityContext,
    evaluate_quote_comparability_candidate,
)
from purchase_price.services.quote_comparable_approval import (
    apply_quote_comparable_approval,
    create_quote_comparable_approval,
)
from purchase_price.services.quote_condition_comparison import build_quote_condition_profile
from purchase_price.services.quote_extraction import extract_quote_file
from purchase_price.services.search import search_all

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_PATH = ROOT / "data" / "uat" / "controlled_uat_template.csv"


@dataclass(frozen=True)
class ExecutedCase:
    row: dict[str, Any]
    assertion_status: str
    automated: bool = True


class _EmptyCollector:
    name = "uat_empty_source"

    def search(self, query: ProductQuery) -> list[CollectedPrice]:
        del query
        return []


class _FailingCollector:
    name = "uat_failing_source"

    def search(self, query: ProductQuery) -> list[CollectedPrice]:
        del query
        raise RuntimeError("synthetic transport failure")


def _templates() -> tuple[list[str], dict[str, dict[str, str]]]:
    with TEMPLATE_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise RuntimeError("controlled UAT template has no header")
        return list(reader.fieldnames), {row["case_id"]: row for row in reader}


def _row(template: dict[str, str], **updates: Any) -> dict[str, Any]:
    row: dict[str, Any] = dict(template)
    for key, value in updates.items():
        if key not in row:
            raise KeyError(f"unknown UAT field: {key}")
        row[key] = (
            "true"
            if value is True
            else "false"
            if value is False
            else ""
            if value is None
            else str(value)
        )
    return row


def _executed(template: dict[str, str], ok: bool, **updates: Any) -> ExecutedCase:
    return ExecutedCase(_row(template, **updates), "PASS" if ok else "FAIL")


def _write_xlsx(path: Path, rows: list[list[Any]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "견적"
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def _write_text_pdf(path: Path) -> None:
    lines = [
        "Brand  Model  Specification  Quantity  Unit  UnitPrice  Amount",
        "GMS  GMSR-182  182L  1  EA  5000000  5000000",
    ]
    commands = ["BT", "/F1 10 Tf", "72 740 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append("0 -16 Td")
        commands.append(f"({line}) Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{number} 0 obj\n".encode())
        payload.extend(body)
        payload.extend(b"\nendobj\n")
    xref = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode())
    payload.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode()
    )
    path.write_bytes(payload)


def _evidence(*, quantity: Decimal = Decimal("1")) -> CollectedPrice:
    return CollectedPrice(
        manufacturer="FUJIFILM Business Innovation",
        product_name="컬러 레이저프린터",
        model_name="ApeosPrint C5570 GK",
        specification="A3,55ppm",
        price=Decimal("5500000"),
        evidence_type=EvidenceType.PUBLIC_SALE_PRICE,
        source_type=SourceType.MANUFACTURER,
        source_name="UAT 공식가격 fixture",
        source_url="https://example.invalid/public-price",
        collected_at=date(2026, 9, 1),
        transaction_date=date(2026, 9, 1),
        quantity=quantity,
        unit="EA",
        currency="KRW",
        vat_status="포함",
        conditions=(
            "배송비=무료; 설치비=포함; 옵션=기본구성; "
            "보증기간=2년; 유지보수=별도계약"
        ),
        source_record_id="UAT-EVIDENCE-001",
        match_grade=MatchGrade.A,
        comparison_scope=ComparisonScope.OBSERVED_ONLY,
    )


def _context(*, quantity: Decimal = Decimal("1"), with_conditions: bool = True) -> QuoteComparabilityContext:
    conditions = (
        build_quote_condition_profile(
            vat="포함",
            delivery="무료",
            installation="포함",
            options="기본구성",
            warranty="2년",
            maintenance="별도계약",
        )
        if with_conditions
        else build_quote_condition_profile()
    )
    return QuoteComparabilityContext(
        quote_unit_price=Decimal("5600000"),
        quantity=quantity,
        unit="EA",
        quote_date=date(2026, 9, 5),
        conditions=conditions,
    )


def _case_01(t: dict[str, str], _: Path) -> ExecutedCase:
    query = ProductQuery(
        product_name="컬러 레이저프린터",
        manufacturer="FUJIFILM Business Innovation",
        model_name="ApeosPrint C5570 GK",
        specification="A3,55ppm",
    )
    results = ManufacturerPublicCatalogCollector().search(query)
    assessment = assess_prices(results)
    hit = results[0] if results else None
    ok = bool(
        hit
        and hit.match_grade == MatchGrade.A
        and assessment.observed_count == 1
        and assessment.low == Decimal("5500000")
        and assessment.quote_position is None
    )
    return _executed(
        t,
        ok,
        approved_public_sample=True,
        extraction_status="direct_search",
        human_model=query.model_name,
        system_model=hit.model_name if hit else "",
        human_match_grade="A",
        system_match_grade=hit.match_grade.value if hit else "NO_HIT",
        identity_agreement=bool(hit and hit.match_grade == MatchGrade.A),
        false_positive_identity=False,
        false_negative_identity=not bool(hit and hit.match_grade == MatchGrade.A),
        direct_evidence_found=bool(results),
        direct_evidence_count=assessment.observed_count,
        independent_source_count=assessment.source_count,
        observed_low_krw=assessment.low,
        observed_high_krw=assessment.high,
        collector_status="success" if results else "success_0",
        source_record_traceable=bool(hit and hit.source_record_id),
        source_url_traceable=bool(hit and hit.source_url),
        reviewer_notes="공식 제조사 snapshot exact-model offline pre-UAT",
    )


def _case_02(t: dict[str, str], _: Path) -> ExecutedCase:
    query = ProductQuery(
        product_name="컬러 레이저프린터",
        manufacturer="FUJIFILM Business Innovation",
        model_name="ApeosPrint C5570 G",
        specification="A3,55ppm",
    )
    candidate = ProductIdentity(
        product_name=query.product_name,
        manufacturer=query.manufacturer,
        model_name="ApeosPrint C5570 GK",
        specification=query.specification,
    )
    decision = grade_product_identity(query, candidate)
    results = ManufacturerPublicCatalogCollector().search(query)
    ok = decision.grade == MatchGrade.X and not results
    return _executed(
        t,
        ok,
        approved_public_sample=True,
        extraction_status="direct_search",
        human_model=query.model_name,
        system_model=candidate.model_name,
        human_match_grade="X",
        system_match_grade=decision.grade.value,
        identity_agreement=decision.grade == MatchGrade.X,
        false_positive_identity=decision.grade in {MatchGrade.A, MatchGrade.B},
        false_negative_identity=False,
        direct_evidence_found=bool(results),
        direct_evidence_count=len(results),
        collector_status="success_0" if not results else "success",
        reviewer_notes="근접 모델 문자열을 exact 모델 가격으로 승격하지 않는지 확인",
    )


def _case_03(t: dict[str, str], workdir: Path) -> ExecutedCase:
    path = workdir / "general-supply.xlsx"
    _write_xlsx(
        path,
        [
            ["품명", "제조사", "모델명", "규격", "수량", "단위", "단가"],
            ["수액걸이", "Sample Medical Furniture", "IV-STAND-01", "5발", 3, "EA", 120000],
        ],
    )
    extraction = extract_quote_file(path)
    item = extraction.items[0] if extraction.items else None
    run = search_all(ProductQuery(model_name=item.model_name if item else ""), [_EmptyCollector()])
    status = run.source_statuses[0]
    ok = bool(item and item.model_name == "IV-STAND-01" and status.succeeded and not run.results)
    return _executed(
        t,
        ok,
        approved_public_sample=True,
        extraction_status="success" if item else "failed",
        human_model="IV-STAND-01",
        system_model=item.model_name if item else "",
        identity_agreement=bool(item and item.model_name == "IV-STAND-01"),
        direct_evidence_found=False,
        direct_evidence_count=0,
        collector_status=status.status_label,
        zero_vs_failure_correct=status.succeeded and status.result_count == 0,
        reviewer_notes="병원 일반 비품 synthetic 견적 + 정상 0건",
    )


def _live_required(t: dict[str, str], _: Path) -> ExecutedCase:
    return ExecutedCase(
        _row(
            t,
            extraction_status="NOT_RUN_LIVE_REQUIRED",
            reviewer_notes="MFDS 공식 API/Production live 표본이 필요한 케이스",
        ),
        "NOT_RUN",
        automated=False,
    )


def _case_05(t: dict[str, str], workdir: Path) -> ExecutedCase:
    path = workdir / "multi.xlsx"
    expected = ["NT960XJG-K72AG", "ApeosPrint C5570 GK", "GMSR-182"]
    _write_xlsx(
        path,
        [
            ["품명", "제조사", "모델명", "규격", "수량", "단위", "단가", "금액"],
            ["노트북", "삼성전자", expected[0], "1TB", 2, "EA", 2500000, 5000000],
            ["컬러 레이저프린터", "FUJIFILM", expected[1], "A3,55ppm", 1, "EA", 5500000, 5500000],
            ["약품냉장고", "GMS", expected[2], "182L", 1, "EA", 5000000, 5000000],
            ["합계", "", "", "", "", "", "", 15500000],
        ],
    )
    extraction = extract_quote_file(path)
    actual = [item.model_name for item in extraction.items]
    return _executed(
        t,
        actual == expected,
        approved_public_sample=True,
        extraction_status=f"success_{len(actual)}_items",
        human_model=" | ".join(expected),
        system_model=" | ".join(actual),
        identity_agreement=actual == expected,
        false_positive_identity=False,
        false_negative_identity=actual != expected,
        reviewer_notes="3개 품목 추출 및 합계행 제외",
    )


def _case_06(t: dict[str, str], workdir: Path) -> ExecutedCase:
    path = workdir / "text.pdf"
    _write_text_pdf(path)
    extraction = extract_quote_file(path)
    item = extraction.items[0] if extraction.items else None
    ok = bool(
        item
        and item.manufacturer == "GMS"
        and item.model_name == "GMSR-182"
        and item.specification == "182L"
        and item.unit_price == Decimal("5000000")
    )
    return _executed(
        t,
        ok,
        approved_public_sample=True,
        extraction_status="success" if item else "failed",
        human_manufacturer="GMS",
        system_manufacturer=item.manufacturer if item else "",
        human_model="GMSR-182",
        system_model=item.model_name if item else "",
        human_spec="182L",
        system_spec=item.specification if item else "",
        identity_agreement=ok,
        false_positive_identity=False,
        false_negative_identity=not ok,
        reviewer_notes="실제 최소 text-layer PDF를 pypdf 경로로 추출",
    )


def _case_07(t: dict[str, str], workdir: Path) -> ExecutedCase:
    path = workdir / "conditions.xlsx"
    _write_xlsx(
        path,
        [
            [
                "품명", "모델명", "수량", "단위", "단가", "VAT", "배송비",
                "설치비", "옵션", "보증기간", "유지보수",
            ],
            [
                "컬러 레이저프린터", "ApeosPrint C5570 GK", 1, "EA", 5600000,
                "포함", "무료", "포함", "기본구성", "2년", "별도계약",
            ],
        ],
    )
    item = extract_quote_file(path).items[0]
    context = _context()
    evidence = _evidence()
    decision = evaluate_quote_comparability_candidate(context, evidence)
    approval = create_quote_comparable_approval(context, evidence, reviewer_confirmed=True)
    promoted = apply_quote_comparable_approval(context, evidence, approval)
    assessment = assess_prices([promoted], current_quote=context.quote_unit_price)
    extracted = (
        item.vat_status,
        item.delivery_condition,
        item.installation_condition,
        item.option_condition,
        item.warranty_condition,
        item.maintenance_condition,
    )
    expected = ("포함", "무료", "포함", "기본구성", "2년", "별도계약")
    ok = extracted == expected and decision.eligible_candidate and assessment.quote_position == "상단 초과"
    return _executed(
        t,
        ok,
        approved_public_sample=True,
        extraction_status="success",
        condition_human_judgment="6축 일치",
        condition_system_judgment=decision.condition_comparison.status_label,
        condition_agreement=decision.condition_comparison.fully_aligned,
        candidate_gate_result=decision.status_label,
        candidate_gate_reasons=decision.reason_text,
        false_positive_comparison=False,
        false_negative_comparison=False,
        direct_evidence_found=True,
        direct_evidence_count=assessment.observed_count,
        observed_low_krw=assessment.low,
        observed_high_krw=assessment.high,
        quote_position=assessment.quote_position,
        reviewer_notes="6축 조건 → candidate → 명시적 pair 승인 → 견적 위치",
    )


def _case_08(t: dict[str, str], workdir: Path) -> ExecutedCase:
    path = workdir / "sparse.xlsx"
    _write_xlsx(
        path,
        [
            ["품명", "모델명", "수량", "단위", "단가"],
            ["컬러 레이저프린터", "ApeosPrint C5570 GK", 1, "EA", 5600000],
        ],
    )
    item = extract_quote_file(path).items[0]
    context = _context(with_conditions=False)
    decision = evaluate_quote_comparability_candidate(context, _evidence())
    assessment = assess_prices([_evidence()], current_quote=item.unit_price)
    ok = (
        decision.condition_comparison.unknown_count == 6
        and not decision.eligible_candidate
        and assessment.quote_position is None
    )
    return _executed(
        t,
        ok,
        approved_public_sample=True,
        extraction_status="success",
        condition_human_judgment="6축 미확인",
        condition_system_judgment=decision.condition_comparison.status_label,
        condition_agreement=decision.condition_comparison.unknown_count == 6,
        candidate_gate_result=decision.status_label,
        candidate_gate_reasons=decision.reason_text,
        false_positive_comparison=decision.eligible_candidate,
        false_negative_comparison=False,
        quote_position=assessment.quote_position,
        reviewer_notes="빈 조건은 해당없음이 아니라 미확인",
    )


def _case_09(t: dict[str, str], _: Path) -> ExecutedCase:
    query = ProductQuery(
        product_name="컬러 레이저프린터",
        manufacturer="FUJIFILM Business Innovation",
        model_name="ApeosPrint C9999 GK",
        specification="A3,55ppm",
    )
    run = search_all(query, [ManufacturerPublicCatalogCollector()])
    status = run.source_statuses[0]
    assessment = assess_prices(run.results, current_quote=Decimal("5000000"))
    ok = status.succeeded and status.result_count == 0 and assessment.observed_count == 0
    return _executed(
        t,
        ok,
        approved_public_sample=True,
        extraction_status="direct_search",
        human_model=query.model_name,
        system_model="NO_HIT",
        direct_evidence_found=False,
        direct_evidence_count=0,
        quote_position=assessment.quote_position,
        collector_status=status.status_label,
        zero_vs_failure_correct=status.succeeded and status.result_count == 0,
        reviewer_notes="exact 입력을 가격 존재 증거로 해석하지 않음",
    )


def _case_10(t: dict[str, str], _: Path) -> ExecutedCase:
    query = ProductQuery(
        product_name="약품냉장고",
        manufacturer="GMS",
        model_name="GMSR-182",
        specification="182L",
    )
    candidate = ProductIdentity(
        product_name="약품냉장고",
        manufacturer="GMS",
        model_name="GMSR-182",
        specification="300L",
    )
    decision = grade_product_identity(query, candidate)
    conflict = replace(
        _evidence(),
        manufacturer="GMS",
        product_name="약품냉장고",
        model_name="GMSR-182",
        specification="300L",
        match_grade=decision.grade,
    )
    assessment = assess_prices([conflict])
    ok = decision.grade == MatchGrade.X and assessment.observed_count == 0
    return _executed(
        t,
        ok,
        approved_public_sample=True,
        extraction_status="direct_search",
        human_model=query.model_name,
        system_model=candidate.model_name,
        human_spec=query.specification,
        system_spec=candidate.specification,
        human_match_grade="X",
        system_match_grade=decision.grade.value,
        identity_agreement=decision.grade == MatchGrade.X,
        false_positive_identity=decision.grade in {MatchGrade.A, MatchGrade.B},
        false_negative_identity=False,
        direct_evidence_found=False,
        direct_evidence_count=assessment.observed_count,
        reviewer_notes="182L ↔ 300L 명백 규격충돌은 X",
    )


def _case_11(t: dict[str, str], _: Path) -> ExecutedCase:
    decision = evaluate_quote_comparability_candidate(
        _context(quantity=Decimal("5")),
        _evidence(quantity=Decimal("1")),
    )
    reason = "견적 수량과 외부근거 수량 불일치"
    false_negative = not decision.eligible_candidate and reason in decision.reasons
    return _executed(
        t,
        false_negative,
        approved_public_sample=True,
        extraction_status="synthetic_pair",
        condition_human_judgment="수량 차이 외 조건 동일; 명시 단가라 수동 확인 시 비교 가능",
        condition_system_judgment=decision.condition_comparison.status_label,
        condition_agreement=decision.condition_comparison.fully_aligned,
        candidate_gate_result=decision.status_label,
        candidate_gate_reasons=decision.reason_text,
        false_positive_comparison=False,
        false_negative_comparison=false_negative,
        reviewer_notes="quantity equality의 보수적 false negative 감시; 이 1건으로 규칙 완화 금지",
    )


def _case_12(t: dict[str, str], _: Path) -> ExecutedCase:
    run = search_all(ProductQuery(model_name="NO-HIT"), [_EmptyCollector()])
    status = run.source_statuses[0]
    ok = status.succeeded and status.result_count == 0 and not run.errors
    return _executed(
        t,
        ok,
        approved_public_sample=True,
        extraction_status="api_status_fixture",
        collector_status=status.status_label,
        zero_vs_failure_correct=ok,
        direct_evidence_found=False,
        direct_evidence_count=0,
        reviewer_notes="정상 0건은 succeeded=true",
    )


def _case_13(t: dict[str, str], _: Path) -> ExecutedCase:
    run = search_all(ProductQuery(model_name="FAIL"), [_FailingCollector()])
    status = run.source_statuses[0]
    ok = not status.succeeded and status.result_count == 0 and bool(run.errors)
    return _executed(
        t,
        ok,
        approved_public_sample=True,
        extraction_status="api_status_fixture",
        collector_status=status.status_label,
        zero_vs_failure_correct=ok,
        direct_evidence_found=False,
        direct_evidence_count=0,
        reviewer_notes="API 실패를 정상 0건으로 덮지 않음",
    )


def _provenance_ok() -> bool:
    provenance = build_public_evidence_provenance(
        source_name="UAT public source",
        payload={
            "recordId": "REC-001",
            "publicField": {"value": "visible", "token": "secret-value"},
            "serviceKey": "secret-value",
        },
        allow_fields=("recordId", "publicField"),
        source_record_id="REC-001",
        source_url="https://example.invalid/record/REC-001",
    )
    return (
        provenance.source_record_id == "REC-001"
        and bool(provenance.source_url)
        and len(provenance.fingerprint) == 64
        and "secret-value" not in provenance.payload_text
        and "token" not in provenance.payload_text.casefold()
    )


CaseRunner = Callable[[dict[str, str], Path], ExecutedCase]
CASE_RUNNERS: dict[str, CaseRunner] = {
    "UAT-01": _case_01,
    "UAT-02": _case_02,
    "UAT-03": _case_03,
    "UAT-04": _live_required,
    "UAT-05": _case_05,
    "UAT-06": _case_06,
    "UAT-07": _case_07,
    "UAT-08": _case_08,
    "UAT-09": _case_09,
    "UAT-10": _case_10,
    "UAT-11": _case_11,
    "UAT-12": _case_12,
    "UAT-13": _case_13,
    "UAT-14": _live_required,
    "UAT-15": _live_required,
}


def run_controlled_uat() -> tuple[list[ExecutedCase], dict[str, Any]]:
    _, templates = _templates()
    missing = set(CASE_RUNNERS) - set(templates)
    if missing:
        raise RuntimeError(f"controlled UAT template missing cases: {sorted(missing)}")

    with TemporaryDirectory(prefix="controlled-uat-") as temp_dir:
        workdir = Path(temp_dir)
        cases = [CASE_RUNNERS[case_id](templates[case_id], workdir) for case_id in CASE_RUNNERS]

    automated = [case for case in cases if case.automated]
    failed = [case for case in automated if case.assertion_status != "PASS"]
    identity_fp = sum(case.row.get("false_positive_identity") == "true" for case in automated)
    comparison_fp = sum(case.row.get("false_positive_comparison") == "true" for case in automated)
    comparison_fn = sum(case.row.get("false_negative_comparison") == "true" for case in automated)
    zero_failure_errors = sum(
        case.row.get("zero_vs_failure_correct") == "false"
        for case in automated
        if case.row.get("zero_vs_failure_correct")
    )
    provenance_ok = _provenance_ok()
    blocker_count = (
        len(failed)
        + identity_fp
        + comparison_fp
        + zero_failure_errors
        + (0 if provenance_ok else 1)
    )
    summary = {
        "mode": "deterministic_offline_pre_uat",
        "total_protocol_cases": len(cases),
        "automated_cases": len(automated),
        "not_run_live_cases": len(cases) - len(automated),
        "passed_automated_cases": len(automated) - len(failed),
        "failed_automated_cases": len(failed),
        "identity_false_positive_count": identity_fp,
        "comparison_false_positive_count": comparison_fp,
        "comparison_false_negative_count": comparison_fn,
        "zero_vs_failure_error_count": zero_failure_errors,
        "provenance_secret_filter_and_fingerprint_ok": provenance_ok,
        "release_blocker_count": blocker_count,
        "known_conservative_signal": (
            "UAT-11 intentionally demonstrates one synthetic quantity-equality false negative; "
            "do not relax the rule without repeated real/approved UAT evidence"
        ),
        "live_required_cases": ["UAT-04", "UAT-14", "UAT-15"],
    }
    return cases, summary


def _write_outputs(output_dir: Path, cases: list[ExecutedCase], summary: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    fieldnames, _ = _templates()
    with (output_dir / "controlled-uat-results.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=[*fieldnames, "execution_status", "automated"])
        writer.writeheader()
        for case in cases:
            writer.writerow(
                {
                    **case.row,
                    "execution_status": case.assertion_status,
                    "automated": "true" if case.automated else "false",
                }
            )
    (output_dir / "controlled-uat-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for key in (
        "total_protocol_cases",
        "automated_cases",
        "passed_automated_cases",
        "not_run_live_cases",
        "identity_false_positive_count",
        "comparison_false_positive_count",
        "comparison_false_negative_count",
        "zero_vs_failure_error_count",
        "provenance_secret_filter_and_fingerprint_ok",
        "release_blocker_count",
    ):
        print(f"{key}={summary[key]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic Controlled UAT preflight.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/controlled-uat-offline"),
    )
    parser.add_argument("--fail-on-blocker", action="store_true")
    args = parser.parse_args()
    cases, summary = run_controlled_uat()
    _write_outputs(args.output_dir, cases, summary)
    return 1 if args.fail_on_blocker and summary["release_blocker_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
