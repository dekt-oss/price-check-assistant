from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from statistics import mean

from purchase_price.services.quote_extraction import QuoteItem, parse_quote_decimal

TEXT_FIELDS = ("product_name", "manufacturer", "model_name", "specification", "unit", "vat_status")
DECIMAL_FIELDS = ("quantity", "unit_price", "total_amount")
UAT_FIELDS = TEXT_FIELDS + DECIMAL_FIELDS
_STRONG_IDENTITY_FIELDS = ("product_name", "model_name", "specification")
_GAP_COST = 1.0
_NO_ANCHOR_PENALTY = 1.2
REQUIRED_UAT_STRATEGIES = frozenset({"xlsx", "xls", "pdf_text", "pdf_ocr", "pdf_commercial"})


@dataclass(frozen=True)
class QuoteUatCaseMetric:
    case_id: str
    strategy: str
    expected_item_count: int
    actual_item_count: int
    matched_item_count: int
    false_positive_item_count: int
    false_negative_item_count: int
    scored_fields: int
    field_errors: int
    error_fields: tuple[str, ...]
    extraction_failed: bool = False
    processing_seconds: float | None = None
    review_seconds: float | None = None

    @property
    def exact_item_count(self) -> bool:
        return self.expected_item_count == self.actual_item_count

    @property
    def item_precision(self) -> float | None:
        return self.matched_item_count / self.actual_item_count if self.actual_item_count else None

    @property
    def item_recall(self) -> float | None:
        return self.matched_item_count / self.expected_item_count if self.expected_item_count else None

    @property
    def field_error_rate(self) -> float | None:
        return self.field_errors / self.scored_fields if self.scored_fields else None

    @property
    def status(self) -> str:
        if self.extraction_failed:
            return "EXTRACTION_FAILED"
        if self.false_positive_item_count == 0 and self.false_negative_item_count == 0 and self.field_errors == 0:
            return "PASS"
        return "REVIEW_REQUIRED"

    def to_redacted_dict(self) -> dict[str, object]:
        return {"case_id": self.case_id, "status": self.status, "strategy": self.strategy, "expected_item_count": self.expected_item_count, "actual_item_count": self.actual_item_count, "matched_item_count": self.matched_item_count, "false_positive_item_count": self.false_positive_item_count, "false_negative_item_count": self.false_negative_item_count, "exact_item_count": self.exact_item_count, "item_precision": self.item_precision, "item_recall": self.item_recall, "scored_fields": self.scored_fields, "field_errors": self.field_errors, "field_error_rate": self.field_error_rate, "error_fields": list(self.error_fields), "extraction_failed": self.extraction_failed, "processing_seconds": self.processing_seconds, "review_seconds": self.review_seconds}


@dataclass(frozen=True)
class _PairComparison:
    scored_fields: int
    field_errors: int
    error_fields: tuple[str, ...]
    alignment_cost: float


def quote_item_to_review_row(item: QuoteItem) -> dict[str, object]:
    return {"product_name": item.product_name, "manufacturer": item.manufacturer, "model_name": item.model_name, "specification": item.specification, "quantity": float(item.quantity) if item.quantity is not None else None, "unit": item.unit, "unit_price": float(item.unit_price) if item.unit_price is not None else None, "total_amount": float(item.total_amount) if item.total_amount is not None else None, "vat_status": item.vat_status}


def _normalize_text(value: object) -> str:
    return "" if value is None else re.sub(r"\s+", " ", str(value).strip()).casefold()


def _expected_decimal(value: object) -> Decimal | None:
    return parse_quote_decimal(value)


def _actual_field_value(actual: QuoteItem, field: str) -> object:
    return getattr(actual, field, None)


def _strong_anchor_match(expected: Mapping[str, object], actual: QuoteItem) -> bool:
    for field in _STRONG_IDENTITY_FIELDS:
        expected_value = _normalize_text(expected.get(field)); actual_value = _normalize_text(_actual_field_value(actual, field))
        if expected_value and actual_value and expected_value == actual_value:
            return True
    expected_unit_price = _expected_decimal(expected.get("unit_price")); expected_total = _expected_decimal(expected.get("total_amount"))
    if expected_unit_price is not None and actual.unit_price == expected_unit_price and (expected_total is None or actual.total_amount == expected_total):
        return True
    return False


def _compare_pair(expected: Mapping[str, object], actual: QuoteItem) -> _PairComparison:
    scored_fields = field_errors = 0; error_fields: set[str] = set()
    for field in TEXT_FIELDS:
        expected_value = _normalize_text(expected.get(field))
        if not expected_value: continue
        scored_fields += 1
        if expected_value != _normalize_text(_actual_field_value(actual, field)): field_errors += 1; error_fields.add(field)
    for field in DECIMAL_FIELDS:
        expected_value = _expected_decimal(expected.get(field))
        if expected_value is None: continue
        scored_fields += 1
        if expected_value != _actual_field_value(actual, field): field_errors += 1; error_fields.add(field)
    mismatch_rate = field_errors / scored_fields if scored_fields else 1.0
    return _PairComparison(scored_fields, field_errors, tuple(sorted(error_fields)), mismatch_rate + (0 if _strong_anchor_match(expected, actual) else _NO_ANCHOR_PENALTY))


def _align_rows(expected_rows: Sequence[Mapping[str, object]], actual_items: Sequence[QuoteItem]) -> tuple[tuple[int, int, _PairComparison], ...]:
    expected_count, actual_count = len(expected_rows), len(actual_items); pair_cache: dict[tuple[int, int], _PairComparison] = {}
    def pair(i: int, j: int) -> _PairComparison:
        if (i,j) not in pair_cache: pair_cache[(i,j)] = _compare_pair(expected_rows[i], actual_items[j])
        return pair_cache[(i,j)]
    costs = [[0.0]*(actual_count+1) for _ in range(expected_count+1)]; ops = [[""]*(actual_count+1) for _ in range(expected_count+1)]
    for i in range(1, expected_count+1): costs[i][0]=i*_GAP_COST; ops[i][0]="missing"
    for j in range(1, actual_count+1): costs[0][j]=j*_GAP_COST; ops[0][j]="extra"
    for i in range(1, expected_count+1):
        for j in range(1, actual_count+1):
            best_cost, _, best_op = min(((costs[i-1][j-1]+pair(i-1,j-1).alignment_cost,0,"pair"),(costs[i-1][j]+_GAP_COST,1,"missing"),(costs[i][j-1]+_GAP_COST,2,"extra")), key=lambda item:(item[0],item[1])); costs[i][j]=best_cost; ops[i][j]=best_op
    aligned=[]; i=expected_count; j=actual_count
    while i or j:
        op=ops[i][j]
        if op=="pair": aligned.append((i-1,j-1,pair(i-1,j-1))); i-=1; j-=1
        elif op=="missing": i-=1
        elif op=="extra": j-=1
        else: raise RuntimeError("quote UAT row alignment entered an invalid state")
    return tuple(reversed(aligned))


def compare_review_rows(*, case_id: str, strategy: str, actual_items: Sequence[QuoteItem], expected_rows: Sequence[Mapping[str, object]], extraction_failed: bool=False, processing_seconds: float|None=None, review_seconds: float|None=None) -> QuoteUatCaseMetric:
    aligned=_align_rows(expected_rows,actual_items); scored_fields=sum(c.scored_fields for _,_,c in aligned); field_errors=sum(c.field_errors for _,_,c in aligned); error_fields=sorted({field for _,_,c in aligned for field in c.error_fields}); matched=len(aligned)
    return QuoteUatCaseMetric(case_id,strategy,len(expected_rows),len(actual_items),matched,max(0,len(actual_items)-matched),max(0,len(expected_rows)-matched),scored_fields,field_errors,tuple(error_fields),extraction_failed,processing_seconds,review_seconds)


def _rate(numerator:int, denominator:int)->float|None: return numerator/denominator if denominator else None
def _average(values:Sequence[float|None])->float|None:
    usable=[v for v in values if v is not None]; return mean(usable) if usable else None


def _strategy_summary(metrics:Sequence[QuoteUatCaseMetric])->dict[str,dict[str,object]]:
    grouped: defaultdict[str,list[QuoteUatCaseMetric]]=defaultdict(list)
    for metric in metrics: grouped[metric.strategy].append(metric)
    summary={}
    for strategy,group in sorted(grouped.items()):
        matched=sum(m.matched_item_count for m in group); actual=sum(m.actual_item_count for m in group); expected=sum(m.expected_item_count for m in group); scored=sum(m.scored_fields for m in group); errors=sum(m.field_errors for m in group)
        summary[strategy]={"cases":len(group),"passed_cases":sum(m.status=="PASS" for m in group),"extraction_failures":sum(m.extraction_failed for m in group),"matched_items":matched,"false_positive_items":sum(m.false_positive_item_count for m in group),"false_negative_items":sum(m.false_negative_item_count for m in group),"item_precision":_rate(matched,actual),"item_recall":_rate(matched,expected),"field_error_rate":_rate(errors,scored),"average_processing_seconds":_average([m.processing_seconds for m in group]),"average_review_seconds":_average([m.review_seconds for m in group])}
    return summary


def evaluate_uat_release_gate(metrics: Sequence[QuoteUatCaseMetric], *, minimum_cases: int=5, required_strategies: frozenset[str]=REQUIRED_UAT_STRATEGIES) -> dict[str, object]:
    strategies={metric.strategy for metric in metrics}; missing=sorted(required_strategies-strategies); blockers=[]
    if len(metrics)<minimum_cases: blockers.append(f"confirmed cases {len(metrics)}/{minimum_cases}")
    if missing: blockers.append("missing strategies: "+", ".join(missing))
    if any(m.extraction_failed for m in metrics): blockers.append("extraction failure present")
    if any(m.false_positive_item_count for m in metrics): blockers.append("false-positive item present")
    if any(m.false_negative_item_count for m in metrics): blockers.append("false-negative item present")
    if any(m.field_errors for m in metrics): blockers.append("confirmed field error present")
    return {"release_ready": not blockers, "blockers": blockers, "required_strategies": sorted(required_strategies), "covered_strategies": sorted(strategies), "missing_strategies": missing}


def build_redacted_uat_summary(metrics:Sequence[QuoteUatCaseMetric], *, minimum_cases:int=5)->dict[str,object]:
    total=len(metrics); extraction_failures=sum(m.extraction_failed for m in metrics); exact=sum(m.exact_item_count for m in metrics); scored=sum(m.scored_fields for m in metrics); errors=sum(m.field_errors for m in metrics); matched=sum(m.matched_item_count for m in metrics); expected=sum(m.expected_item_count for m in metrics); actual=sum(m.actual_item_count for m in metrics); fp=sum(m.false_positive_item_count for m in metrics); fn=sum(m.false_negative_item_count for m in metrics); strategy_counts=Counter(m.strategy for m in metrics)
    return {"total_confirmed_cases":total,"minimum_case_target":minimum_cases,"minimum_case_target_met":total>=minimum_cases,"release_gate":evaluate_uat_release_gate(metrics,minimum_cases=minimum_cases),"extraction_failures":extraction_failures,"extraction_failure_rate":_rate(extraction_failures,total),"exact_item_count_cases":exact,"exact_item_count_rate":_rate(exact,total),"expected_items":expected,"actual_items":actual,"matched_items":matched,"false_positive_items":fp,"false_negative_items":fn,"item_precision":_rate(matched,actual),"item_recall":_rate(matched,expected),"scored_fields":scored,"field_errors":errors,"field_error_rate":_rate(errors,scored),"average_processing_seconds":_average([m.processing_seconds for m in metrics]),"total_review_seconds":sum(m.review_seconds for m in metrics if m.review_seconds is not None),"average_review_seconds":_average([m.review_seconds for m in metrics]),"strategy_counts":dict(sorted(strategy_counts.items())),"strategy_metrics":_strategy_summary(metrics),"cases":[m.to_redacted_dict() for m in metrics],"privacy_note":"이 결과에는 파일명, 견적 원문, 제품명, 제조사명, 모델명, 규격, 단가, 총액의 실제 값을 기록하지 않음"}


def redacted_uat_summary_json(metrics:Sequence[QuoteUatCaseMetric], *, minimum_cases:int=5)->str:
    return json.dumps(build_redacted_uat_summary(metrics,minimum_cases=minimum_cases),ensure_ascii=False,indent=2)
