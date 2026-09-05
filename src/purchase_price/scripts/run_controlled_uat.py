from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from openpyxl import Workbook

from purchase_price.collectors.manufacturer_public_catalog import ManufacturerPublicCatalogCollector
from purchase_price.domain import ComparisonScope, EvidenceType, MatchGrade, SourceType
from purchase_price.schemas import CollectedPrice, ProductQuery
from purchase_price.services.pricing import assess_prices
from purchase_price.services.product_matching import ProductIdentity, grade_product_identity
from purchase_price.services.public_provenance import build_public_evidence_provenance
from purchase_price.services.quote_comparable_approval import (
    apply_quote_comparable_approval,
    create_quote_comparable_approval,
)
from purchase_price.services.quote_comparability import (
    QuoteComparabilityContext,
    evaluate_quote_comparability_candidate,
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


def _template_rows() -> tuple[list[str], dict[str, dict[str, str]]]:
    with TEMPLATE_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise RuntimeError("controlled UAT template has no header")
        rows = {row["case_id"]: row for row in reader}
        return list(reader.fieldnames), rows


def _row(template: dict[str, str], **updates: Any) -> dict[str, Any]:
    result: dict[str, Any] = dict(template)
    for key, value in updates.items():
        if key not in result:
            raise KeyError(f"unknown UAT result field: {key}")
        if isinstance(value, bool):
            result[key] = "true" if value else "false"
        elif value is None:
            result[key] = ""
        else:
            result[key] = str(value)
    return result


def _write_xlsx(path: Path, rows: list[list[Any]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "견적"
    for row in rows:
        sheet.append(row)
    workbook.save(path)


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _write_text_pdf(path: Path, lines: list[str]) -> None:
    commands = ["BT", "/F1 10 Tf", "72 740 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append("0 -16 Td")
        commands.append(f"({_escape_pdf_text(line)}) Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
    ]

    payload = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{number} 0 obj\n".encode("ascii"))
        payload.extend(body)
        payload.extend(b"\nendobj\n")

    xref = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    payload.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(payload)


def _direct_evidence(
    *,
    quantity: Decimal = Decimal("1"),
    unit: str = "EA",
    specification: str = "A3,55ppm",
    price: Decimal = Decimal("5500000"),
) -> CollectedPrice:
    return CollectedPrice(
        manufacturer="FUJIFILM Business Innovation",
        product_name="컬러 레이저프린터",
        model_name="ApeosPrint C5570 GK",
        specification=specification,
        price=price,
        evidence_type=EvidenceType.PUBLIC_SALE_PRICE,
        source_type=SourceType.MANUFACTURER,
        source_name="UAT 공식가격 fixture",
        source_url="https://example.invalid/public-price",
        collected_at=date(2026, 9, 1),
        transaction_date=date(2026, 9, 1),
        quantity=quantity,
        unit=unit,
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


def _aligned_context(*, quantity: Decimal = Decimal("1")) -> QuoteComparabilityContext:
    return QuoteComparabilityContext(
        quote_unit_price=Decimal("5600000"),
        quantity=quantity,
        unit="EA",
        quote_date=date(2026, 9, 5),
        conditions=build_quote_condition_profile(
            vat="포함",
            delivery="무료",
            installation="포함",
            options="기본구성",
            warranty="2년",
            maintenance="별도계약",
        ),
    )


def _case_01(template: dict[str, str]) -> ExecutedCase:
    query = ProductQuery(
        product_name="컬러 레이저프린터",
        manufacturer="FUJIFILM Business Innovation",
        model_name="ApeosPrint C5570 GK",
        specification="A3,55ppm",
    )
    results = ManufacturerPublicCatalogCollector().search(query)
    assessment = assess_prices(results)
    ok = (
        len(results) == 1
        and results[0].match_grade == MatchGrade.A
        and assessment.observed_count == 1
        and assessment.low == Decimal("5500000")
        and assessment.quote_position is None
    )
    result = results[0] if results else None
    return ExecutedCase(
        _row(
            template,
            approved_public_sample=True,
            extraction_status="direct_search",
            human_product_name="컬러 레이저프린터",
            system_product_name=result.product_name if result else "",
            human_manufacturer="FUJIFILM Business Innovation",
            system_manufacturer=result.manufacturer if result else "",
            human_model="ApeosPrint C5570 GK",
            system_model=result.model_name if result else "",
            human_spec="A3,55ppm",
            system_spec=result.specification if result else "",
            human_match_grade="A",
            system_match_grade=result.match_grade.value if result else "NO_HIT",
            identity_agreement=bool(result and result.match_grade == MatchGrade.A),
            false_positive_identity=False,
            false_negative_identity=not bool(result and result.match_grade == MatchGrade.A),
            direct_evidence_found=bool(results),
            direct_evidence_count=assessment.observed_count,
            independent_source_count=assessment.source_count,
            observed_low_krw=assessment.low,
            observed_high_krw=assessment.high,
            quote_position=assessment.quote_position,
            collector_status="success" if results else "success_0",
            source_record_traceable=bool(result and result.source_record_id),
            source_url_traceable=bool(result and result.source_url),
            fingerprint_traceable=False,
            reviewer_notes="공식 제조사 snapshot 기반 deterministic offline UAT",
        ),
        "PASS" if ok else "FAIL",
    )


def _case_02(template: dict[str, str]) -> ExecutedCase:
    query = ProductQuery(
        product_name="컬러 레이저프린터",
        manufacturer="FUJIFILM Business Innovation",
        model_name="ApeosPrint C5570 G",
        specification="A3,55ppm",
    )
    candidate = ProductIdentity(
        product_name="컬러 레이저프린터",
        manufacturer="FUJIFILM Business Innovation",
        model_name="ApeosPrint C5570 GK",
        specification="A3,55ppm",
    )
    decision = grade_product_identity(query, candidate)
    results = ManufacturerPublicCatalogCollector().search(query)
    ok = decision.grade == MatchGrade.X and not results
    return ExecutedCase(
        _row(
            template,
            approved_public_sample=True,
            extraction_status="direct_search",
            human_product_name=query.product_name,
            system_product_name=candidate.product_name,
            human_manufacturer=query.manufacturer,
            system_manufacturer=candidate.manufacturer,
            human_model=query.model_name,
            system_model=candidate.model_name,
            human_spec=query.specification,
            system_spec=candidate.specification,
            human_match_grade="X",
            system_match_grade=decision.grade.value,
            identity_agreement=decision.grade == MatchGrade.X,
            false_positive_identity=decision.grade in {MatchGrade.A, MatchGrade.B},
            false_negative_identity=False,
            direct_evidence_found=bool(results),
            direct_evidence_count=len(results),
            collector_status="success_0" if not results else "success",
            reviewer_notes="모델명 한 글자 부족 시 exact 제품가격 자동 승격 금지",
        ),
        "PASS" if ok else "FAIL",
    )


def _case_03(template: dict[str, str], workdir: Path) -> ExecutedCase:
    path = workdir / "uat03_general_supply.xlsx"
    _write_xlsx(
        path,
        [
            ["품명", "제조사", "모델명", "규격", "수량", "단위", "단가"],
            ["수액걸이", "Sample Medical Furniture", "IV-STAND-01", "5발", 3, "EA", 120000],
        ],
    )
    extraction = extract_quote_file(path)
    item = extraction.items[0] if extraction.items else None
    search = search_all(
        ProductQuery(
            product_name=item.product_name if item else "",
            manufacturer=item.manufacturer if item else "",
            model_name=item.model_name if item else "",
            specification=item.specification if item else "",
        ),
        [_EmptyCollector()],
    )
    ok = bool(item and item.model_name == "IV-STAND-01" and not search.results)
    return ExecutedCase(
        _row(
            template,
            approved_public_sample=True,
            extraction_status="success" if item else "failed",
            human_product_name="수액걸이",
            system_product_name=item.product_name if item else "",
            human_manufacturer="Sample Medical Furniture",
            system_manufacturer=item.manufacturer if item else "",
            human_model="IV-STAND-01",
            system_model=item.model_name if item else "",
            human_spec="5발",
            system_spec=item.specification if item else "",
            identity_agreement=bool(item and item.model_name == "IV-STAND-01"),
            direct_evidence_found=False,
            direct_evidence_count=0,
            collector_status=search.source_statuses[0].status_label,
            zero_vs_failure_correct=bool(
                search.source_statuses and search.source_statuses[0].succeeded
            ),
            reviewer_notes="병원 일반 비품 synthetic sample; 외부가격 미연결은 근거부족으로 유지",
        ),
        "PASS" if ok else "FAIL",
    )


def _not_run_mfds(template: dict[str, str], reason: str) -> ExecutedCase:
    return ExecutedCase(
        _row(
            template,
            extraction_status="NOT_RUN_LIVE_REQUIRED",
            reviewer_notes=reason,
        ),
        "NOT_RUN",
        automated=False,
    )


def _case_05(template: dict[str, str], workdir: Path) -> ExecutedCase:
    path = workdir / "uat05_multi_item.xlsx"
    expected_models = ["NT960XJG-K72AG", "ApeosPrint C5570 GK", "GMSR-182"]
    _write_xlsx(
        path,
        [
            ["품명", "제조사", "모델명", "규격", "수량", "단위", "단가", "금액"],
            ["노트북", "삼성전자", expected_models[0], "1TB", 2, "EA", 2500000, 5000000],
            ["컬러 레이저프린터", "FUJIFILM Business Innovation", expected_models[1], "A3,55ppm", 1, "EA", 5500000, 5500000],
            ["약품냉장고", "GMS", expected_models[2], "182L", 1, "EA", 5000000, 5000000],
            ["합계", "", "", "", "", "", "", 15500000],
        ],
    )
    extraction = extract_quote_file(path)
    system_models = [item.model_name for item in extraction.items]
    ok = system_models == expected_models
    return ExecutedCase(
        _row(
            template,
            approved_public_sample=True,
            extraction_status=f"success_{len(extraction.items)}_items",
            human_model=" | ".join(expected_models),
            system_model=" | ".join(system_models),
            identity_agreement=ok,
            false_positive_identity=False,
            false_negative_identity=not ok,
            reviewer_notes="3개 품목 + 합계행 synthetic Excel; 합계행 제외 확인",
        ),
        "PASS" if ok else "FAIL",
    )


def _case_06(template: dict[str, str], workdir: Path) -> ExecutedCase:
    path = workdir / "uat06_text.pdf"
    _write_text_pdf(
        path,
        [
            "Brand  Model  Specification  Quantity  Unit  UnitPrice  Amount",
            "GMS  GMSR-182  182L  1  EA  5000000  5000000",
        ],
    )
    extraction = extract_quote_file(path)
    item = extraction.items[0] if extraction.items else None
    ok = bool(
        item
        and item.manufacturer == "GMS"
        and item.model_name == "GMSR-182"
        and item.specification == "182L"
        and item.unit_price == Decimal("5000000")
    )
    return ExecutedCase(
        _row(
            template,
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
            reviewer_notes="실제 최소 text-layer PDF를 생성해 pypdf 경로로 추출",
        ),
        "PASS" if ok else "FAIL",
    )


def _case_07(template: dict[str, str], workdir: Path) -> ExecutedCase:
    path = workdir / "uat07_conditions.xlsx"
    _write_xlsx(
        path,
        [
            [
                "품명",
                "제조사",
                "모델명",
                "규격",
                "수량",
                "단위",
                "단가",
                "VAT",
                "배송비",
                "설치비",
                "옵션",
                "보증기간",
                "유지보수",
            ],
            [
                "컬러 레이저프린터",
                "FUJIFILM Business Innovation",
                "ApeosPrint C5570 GK",
                "A3,55ppm",
                1,
                "EA",
                5600000,
                "포함",
                "무료",
                "포함",
                "기본구성",
                "2년",
                "별도계약",
            ],
        ],
    )
    extraction = extract_quote_file(path)
    item = extraction.items[0] if extraction.items else None
    context = _aligned_context()
    evidence = _direct_evidence()
    decision = evaluate_quote_comparability_candidate(context, evidence)
    approval = create_quote_comparable_approval(
        context,
        evidence,
        reviewer_confirmed=True,
        reviewer_note="synthetic UAT explicit approval",
    )
    promoted = apply_quote_comparable_approval(context, evidence, approval)
    assessment = assess_prices([promoted], current_quote=context.quote_unit_price)
    extracted_conditions_ok = bool(
        item
        and item.vat_status == "포함"
        and item.delivery_condition == "무료"
        and item.installation_condition == "포함"
        and item.option_condition == "기본구성"
        and item.warranty_condition == "2년"
        and item.maintenance_condition == "별도계약"
    )
    ok = extracted_conditions_ok and decision.eligible_candidate and assessment.quote_position == "상단 초과"
    return ExecutedCase(
        _row(
            template,
            approved_public_sample=True,
            extraction_status="success" if item else "failed",
            human_model="ApeosPrint C5570 GK",
            system_model=item.model_name if item else "",
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
            reviewer_notes="상업조건 6축 추출 → candidate → 명시적 pair 승인 → 견적 위치 연결",
        ),
        "PASS" if ok else "FAIL",
    )


def _case_08(template: dict[str, str], workdir: Path) -> ExecutedCase:
    path = workdir / "uat08_sparse_conditions.xlsx"
    _write_xlsx(
        path,
        [
            ["품명", "제조사", "모델명", "규격", "수량", "단위", "단가"],
            [
                "컬러 레이저프린터",
                "FUJIFILM Business Innovation",
                "ApeosPrint C5570 GK",
                "A3,55ppm",
                1,
                "EA",
                5600000,
            ],
        ],
    )
    extraction = extract_quote_file(path)
    item = extraction.items[0] if extraction.items else None
    context = QuoteComparabilityContext(
        quote_unit_price=item.unit_price if item else Decimal("5600000"),
        quantity=item.quantity if item else Decimal("1"),
        unit=item.unit if item else "EA",
        quote_date=date(2026, 9, 5),
        conditions=build_quote_condition_profile(),
    )
    evidence = _direct_evidence()
    decision = evaluate_quote_comparability_candidate(context, evidence)
    assessment = assess_prices([evidence], current_quote=context.quote_unit_price)
    ok = (
        item is not None
        and not decision.eligible_candidate
        and decision.condition_comparison.unknown_count == 6
        and assessment.quote_position is None
    )
    return ExecutedCase(
        _row(
            template,
            approved_public_sample=True,
            extraction_status="success" if item else "failed",
            human_model="ApeosPrint C5570 GK",
            system_model=item.model_name if item else "",
            condition_human_judgment="6축 미확인",
            condition_system_judgment=decision.condition_comparison.status_label,
            condition_agreement=decision.condition_comparison.unknown_count == 6,
            candidate_gate_result=decision.status_label,
            candidate_gate_reasons=decision.reason_text,
            false_positive_comparison=decision.eligible_candidate,
            false_negative_comparison=False,
            quote_position=assessment.quote_position,
            reviewer_notes="빈 조건을 해당없음으로 추정하지 않고 미확인으로 유지",
        ),
        "PASS" if ok else "FAIL",
    )


def _case_09(template: dict[str, str]) -> ExecutedCase:
    query = ProductQuery(
        product_name="컬러 레이저프린터",
        manufacturer="FUJIFILM Business Innovation",
        model_name="ApeosPrint C9999 GK",
        specification="A3,55ppm",
    )
    run = search_all(query, [ManufacturerPublicCatalogCollector()])
    assessment = assess_prices(run.results, current_quote=Decimal("5000000"))
    status = run.source_statuses[0]
    ok = status.succeeded and status.result_count == 0 and assessment.observed_count == 0
    return ExecutedCase(
        _row(
            template,
            approved_public_sample=True,
            extraction_status="direct_search",
            human_model=query.model_name,
            system_model="NO_HIT",
            human_match_grade="식별정보는 있으나 가격근거 없음",
            system_match_grade="NO_HIT",
            identity_agreement=True,
            direct_evidence_found=False,
            direct_evidence_count=0,
            quote_position=assessment.quote_position,
            collector_status=status.status_label,
            zero_vs_failure_correct=status.succeeded and status.result_count == 0,
            reviewer_notes="exact 모델 입력 자체를 가격 존재 근거로 해석하지 않음",
        ),
        "PASS" if ok else "FAIL",
    )


def _case_10(template: dict[str, str]) -> ExecutedCase:
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
    conflicting_evidence = _direct_evidence(specification="300L")
    conflicting_evidence = CollectedPrice(
        **{
            **conflicting_evidence.__dict__,
            "manufacturer": "GMS",
            "product_name": "약품냉장고",
            "model_name": "GMSR-182",
            "match_grade": decision.grade,
        }
    )
    assessment = assess_prices([conflicting_evidence])
    ok = decision.grade == MatchGrade.X and assessment.observed_count == 0
    return ExecutedCase(
        _row(
            template,
            approved_public_sample=True,
            extraction_status="direct_search",
            human_product_name=query.product_name,
            system_product_name=candidate.product_name,
            human_manufacturer=query.manufacturer,
            system_manufacturer=candidate.manufacturer,
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
            reviewer_notes="동일 모델이어도 단일 핵심규격 182L ↔ 300L 명백 충돌은 X",
        ),
        "PASS" if ok else "FAIL",
    )


def _case_11(template: dict[str, str]) -> ExecutedCase:
    context = _aligned_context(quantity=Decimal("5"))
    evidence = _direct_evidence(quantity=Decimal("1"))
    decision = evaluate_quote_comparability_candidate(context, evidence)
    expected_reason = "견적 수량과 외부근거 수량 불일치"
    expected_false_negative = not decision.eligible_candidate and expected_reason in decision.reasons
    return ExecutedCase(
        _row(
            template,
            approved_public_sample=True,
            extraction_status="synthetic_pair",
            human_model="ApeosPrint C5570 GK",
            system_model=evidence.model_name,
            condition_human_judgment="수량 차이 외 조건 동일; 명시 단가이므로 수동 확인 시 비교 가능",
            condition_system_judgment=decision.condition_comparison.status_label,
            condition_agreement=decision.condition_comparison.fully_aligned,
            candidate_gate_result=decision.status_label,
            candidate_gate_reasons=decision.reason_text,
            false_positive_comparison=False,
            false_negative_comparison=expected_false_negative,
            reviewer_notes=(
                "의도적으로 quantity equality의 보수적 false negative를 재현. "
                "synthetic 1건만으로 규칙 완화 근거로 사용하지 않음"
            ),
        ),
        "PASS" if expected_false_negative else "FAIL",
    )


def _case_12(template: dict[str, str]) -> ExecutedCase:
    run = search_all(ProductQuery(model_name="NO-HIT"), [_EmptyCollector()])
    status = run.source_statuses[0]
    ok = status.succeeded and status.result_count == 0 and not run.errors
    return ExecutedCase(
        _row(
            template,
            approved_public_sample=True,
            extraction_status="api_status_fixture",
            collector_status=status.status_label,
            zero_vs_failure_correct=ok,
            direct_evidence_found=False,
            direct_evidence_count=0,
            reviewer_notes="정상 0건은 succeeded=true / result_count=0",
        ),
        "PASS" if ok else "FAIL",
    )


def _case_13(template: dict[str, str]) -> ExecutedCase:
    run = search_all(ProductQuery(model_name="FAIL"), [_FailingCollector()])
    status = run.source_statuses[0]
    ok = not status.succeeded and status.result_count == 0 and bool(run.errors)
    return ExecutedCase(
        _row(
            template,
            approved_public_sample=True,
            extraction_status="api_status_fixture",
            collector_status=status.status_label,
            zero_vs_failure_correct=ok,
            direct_evidence_found=False,
            direct_evidence_count=0,
            reviewer_notes="transport/API 실패를 정상 0건으로 덮지 않음",
        ),
        "PASS" if ok else "FAIL",
    )


def _provenance_probe() -> bool:
    provenance = build_public_evidence_provenance(
        source_name="UAT public source",
        payload={
            "recordId": "REC-001",
            "publicField": {"value": "visible", "token": "must-not-survive"},
            "serviceKey": "must-not-survive",
        },
        allow_fields=("recordId", "publicField"),
        source_record_id="REC-001",
        source_url="https://example.invalid/record/REC-001",
    )
    return (
        provenance.source_record_id == "REC-001"
        and bool(provenance.source_url)
        and len(provenance.fingerprint) == 64
        and "must-not-survive" not in provenance.payload_text
        and "token" not in provenance.payload_text.casefold()
    )


def run_controlled_uat() -> tuple[list[ExecutedCase], dict[str, Any]]:
    fieldnames, templates = _template_rows()
    del fieldnames
    required_ids = {f"UAT-{index:02d}" for index in range(1, 16)}
    missing = required_ids - set(templates)
    if missing:
        raise RuntimeError(f"controlled UAT template missing cases: {sorted(missing)}")

    with TemporaryDirectory(prefix="controlled-uat-") as temp_dir:
        workdir = Path(temp_dir)
        cases = [
            _case_01(templates["UAT-01"]),
            _case_02(templates["UAT-02"]),
            _case_03(templates["UAT-03"], workdir),
            _not_run_mfds(
                templates["UAT-04"],
                "MFDS exact identity는 실제 공식 API/Production live UAT에서 별도 실행 필요",
            ),
            _case_05(templates["UAT-05"], workdir),
            _case_06(templates["UAT-06"], workdir),
            _case_07(templates["UAT-07"], workdir),
            _case_08(templates["UAT-08"], workdir),
            _case_09(templates["UAT-09"]),
            _case_10(templates["UAT-10"]),
            _case_11(templates["UAT-11"]),
            _case_12(templates["UAT-12"]),
            _case_13(templates["UAT-13"]),
            _not_run_mfds(
                templates["UAT-14"],
                "MFDS ambiguous permit는 실제 공식 API 응답 표본으로 live UAT 필요",
            ),
            _not_run_mfds(
                templates["UAT-15"],
                "취소/취하/수출전용 상태는 실제 MFDS 공식 응답 표본으로 live UAT 필요",
            ),
        ]

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
    provenance_ok = _provenance_probe()
    blocker_count = len(failed) + identity_fp + comparison_fp + zero_failure_errors + (not provenance_ok)

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
    fieldnames, _ = _template_rows()
    result_fields = [*fieldnames, "execution_status", "automated"]
    csv_path = output_dir / "controlled-uat-results.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=result_fields)
        writer.writeheader()
        for case in cases:
            writer.writerow(
                {
                    **case.row,
                    "execution_status": case.assertion_status,
                    "automated": "true" if case.automated else "false",
                }
            )

    summary_path = output_dir / "controlled-uat-summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"protocol_cases={summary['total_protocol_cases']}")
    print(f"automated_cases={summary['automated_cases']}")
    print(f"passed_automated_cases={summary['passed_automated_cases']}")
    print(f"not_run_live_cases={summary['not_run_live_cases']}")
    print(f"identity_false_positive_count={summary['identity_false_positive_count']}")
    print(f"comparison_false_positive_count={summary['comparison_false_positive_count']}")
    print(f"comparison_false_negative_count={summary['comparison_false_negative_count']}")
    print(f"zero_vs_failure_error_count={summary['zero_vs_failure_error_count']}")
    print(
        "provenance_secret_filter_and_fingerprint_ok="
        f"{summary['provenance_secret_filter_and_fingerprint_ok']}"
    )
    print(f"release_blocker_count={summary['release_blocker_count']}")
    print(f"results={csv_path}")
    print(f"summary={summary_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic offline pre-UAT cases without external API secrets."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/controlled-uat-offline"),
    )
    parser.add_argument(
        "--fail-on-blocker",
        action="store_true",
        help="Return exit 1 if an automated case or blocker safety metric fails.",
    )
    args = parser.parse_args()

    cases, summary = run_controlled_uat()
    _write_outputs(args.output_dir, cases, summary)
    if args.fail_on_blocker and summary["release_blocker_count"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
