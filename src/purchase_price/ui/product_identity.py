"""What product this is: one labelled grid shared by 가격 조사, 견적서 검토 and the device page.

Before 2026-10-10 the result title glued 품목명 and 모델명 together ("가스 마취기 Flow-c") with a grey
line of company and permit under it, so a reader could not tell which word was the model, which
the item and which the company. This block names every part in the same place for every product:

    모델명 | 품목명(식약처) | 제조·수입업체 | 식약처 허가번호 | 등급 | 나라장터 세부품명(코드) | 검색어

The model is the large value, labels are small and grey, and a field without data shows "확인 전"
or "—" instead of disappearing, so the grid keeps its shape. Each field can carry a status word
(``pc-pill``: colour never carries meaning alone). The same grid draws the values read from a
quote ("견적서에 적힌 값") next to the product the app matched ("확인된 제품").

Pure functions over plain values; class prefix ``pi-``. New module, so a Streamlit process that
keeps older modules after a deploy never mixes it up.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from purchase_price.ui.theme import TONE_MUTED, TONE_OK, TONE_WARN, esc, pill_html

PRODUCT_IDENTITY_V1 = True

NOT_CHECKED = "확인 전"
NONE = "—"

CSS = """
<style>
.pi-sr {position:absolute !important; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden;
  clip:rect(0,0,0,0); white-space:nowrap; border:0;}
.pi-cq {container-type:inline-size; min-width:0;}
.pi-block {margin:0 0 4px 0;}
.pi-title {display:flex; align-items:center; gap:8px; font-size:12px; font-weight:800; color:var(--pc-muted);
  margin:0 0 7px 2px; letter-spacing:-0.1px;}
/* Lines are cell shadows, not a coloured gap, so a short last row leaves white space, not a grey block. */
.pi-grid {display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:0; background:#FFFFFF;
  border:1px solid #E3EAF2; border-radius:11px; overflow:hidden;}
.pi-cell {background:#FFFFFF; padding:10px 14px 11px 14px; min-width:0; box-shadow:1px 0 0 #E3EAF2, 0 1px 0 #E3EAF2;}
.pi-cell.pi-span2 {grid-column:span 2;}
.pi-cell.pi-main {background:#F7FAFE;}
.pi-label {display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:3px 6px;
  font-size:11px; color:#6A7D90; line-height:1.4; min-height:20px;}
.pi-label .pc-pill {padding:2px 7px; font-size:10.5px; flex:none; margin:0 !important;}
.pi-value {font-size:14px; font-weight:700; color:var(--pc-navy); line-height:1.4; margin-top:3px;
  word-break:keep-all; overflow-wrap:anywhere;}
.pi-main .pi-value {font-size:22px; font-weight:800; letter-spacing:-0.6px; line-height:1.25; margin-top:2px;}
.pi-value.pi-empty {color:#98A5B5; font-weight:600;}
.pi-main .pi-value.pi-empty {font-size:17px;}
.pi-note {font-size:11px; color:#7A899B; line-height:1.45; margin-top:2px; word-break:keep-all;}
.pi-pair {display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:12px;}
.pi-pair .pi-grid {grid-template-columns:repeat(2,minmax(0,1fr));}
.pi-pair .pi-main .pi-value {font-size:18px;}
.pi-pair .pi-cell {padding:8px 11px 9px 11px;}
.pi-pair .pi-cell.pi-span2 {grid-column:auto;}
.pi-pair .pi-value {font-size:13px;}
.pi-pair .pi-note {display:none;}
#product-identity-v1 {margin:0 0 12px 0;}
/* 1024px window (sidebar open): three columns keep the grid at two rows. */
@container (max-width: 640px) {
  .pi-grid {grid-template-columns:repeat(3,minmax(0,1fr));}
  .pi-cell.pi-span2 {grid-column:auto;}
  .pi-pair {grid-template-columns:1fr; gap:14px;}
}
@container (max-width: 420px) {
  .pi-grid {grid-template-columns:repeat(2,minmax(0,1fr));}
}
@container (max-width: 250px) {
  .pi-grid, .pi-pair .pi-grid {grid-template-columns:1fr;}
  .pi-cell.pi-span2 {grid-column:auto;}
}
</style>
"""


@dataclass(frozen=True)
class IdentityField:
    """One labelled value. An empty ``value`` shows ``empty_text`` in grey; it never disappears."""

    key: str
    label: str
    value: str = ""
    status: str = ""
    tone: str = TONE_MUTED
    note: str = ""
    empty_text: str = NOT_CHECKED
    main: bool = False
    span: int = 1


def _text(value: object) -> str:
    return " ".join(str(value or "").split())


def _unique(values: Iterable[object]) -> list[str]:
    return list(dict.fromkeys(text for text in (_text(value) for value in values) if text))


def first_with_more(values: Iterable[object], counter: str) -> str:
    """'(주)메디아나 외 2곳' / '제인 20-5001 호 외 1건' / ''."""

    items = _unique(values)
    if not items:
        return ""
    return items[0] + (f" 외 {len(items) - 1}{counter}" if len(items) > 1 else "")


def grade_text(grade: object) -> str:
    text = _text(grade)
    if not text:
        return ""
    return text if text.endswith("등급") else f"{text}등급"


def detail_class_text(name: object, code: object) -> str:
    """'가스마취기 (4211180701)' with whichever half is known."""

    name_text, code_text = _text(name), _text(code)
    if name_text and code_text:
        return f"{name_text} ({code_text})"
    return name_text or code_text


def most_common(values: Iterable[object]) -> str:
    counts: dict[str, int] = {}
    for text in (_text(value) for value in values):
        if text:
            counts[text] = counts.get(text, 0) + 1
    if not counts:
        return ""
    return max(counts, key=lambda key: (counts[key], -list(counts).index(key)))


def detail_class_of(candidates: Iterable[Any]) -> tuple[str, str]:
    """(세부품명, 코드) most of the same-product 나라장터 trades were booked under.

    The 세부품명 is the first part of the 나라장터 title ("가스마취기, 드래거, Fabius, ...")
    of the trades under the most common code.
    """

    rows = [
        (_text(getattr(candidate, "detail_code", "")), _text(getattr(candidate, "product_title", "")))
        for candidate in candidates
    ]
    code = most_common(code for code, _title in rows)
    if not code:
        return most_common(title.split(",")[0] for _code, title in rows), ""
    name = most_common(title.split(",")[0] for row_code, title in rows if row_code == code)
    return name, code


def model_status(
    *,
    identity_status: str = "",
    identity_match: str = "",
    ambiguous: bool = False,
    direct_count: int = 0,
) -> tuple[str, str]:
    """(word, tone) for the model: what confirmed that this model exists as named."""

    if identity_status == "success" and identity_match in {"model", "udi", "permit"}:
        if ambiguous:
            return "허가 여러 건", TONE_WARN
        return "식약처 확인", TONE_OK
    if direct_count:
        return "나라장터 거래 확인", TONE_OK
    if identity_status == "success_0":
        return "식약처 목록에 없음", TONE_WARN
    return NOT_CHECKED, TONE_MUTED


def permit_status(*, permit: str, status_label: str = "", found: bool = False) -> tuple[str, str]:
    """(word, tone) for the 허가번호: 판매 가능/취소됨 when the item-status index knows, else 확인됨."""

    label = _text(status_label)
    if label:
        if "취소" in label:
            return "취소됨", "danger"
        if "수출" in label:
            return "수출 전용", TONE_WARN
        if "정상" in label or "판매" in label:
            return "판매 가능", TONE_OK
        return label, TONE_MUTED
    if permit and found:
        return "확인됨", TONE_OK
    if permit:
        return "", TONE_MUTED
    return NOT_CHECKED, TONE_MUTED


def product_fields(
    *,
    model: str,
    model_state: tuple[str, str] = (NOT_CHECKED, TONE_MUTED),
    mfds_product: str = "",
    companies: Sequence[str] = (),
    procurement_maker: str = "",
    permit_numbers: Sequence[str] = (),
    permit_type: str = "",
    permit_state: tuple[str, str] = ("", TONE_MUTED),
    permit_note: str = "",
    grade: str = "",
    detail_name: str = "",
    detail_code: str = "",
    detail_note: str = "",
    search_text: str = "",
) -> list[IdentityField]:
    """The fixed field list for a product, in the fixed order. 검색어 only when it differs."""

    company = first_with_more(companies, "곳")
    company_note = "식약처 등록" if company else ""
    if not company and _text(procurement_maker):
        company = _text(procurement_maker)
        company_note = "나라장터 거래에 적힌 제조사"
    permit = first_with_more(permit_numbers, "건")
    permit_label = f"식약처 {_text(permit_type)}번호" if _text(permit_type) in {"허가", "인증", "신고"} else "식약처 허가번호"
    detail = detail_class_text(detail_name, detail_code)
    fields = [
        IdentityField(
            "model", "모델명", _text(model), status=model_state[0], tone=model_state[1], main=True
        ),
        IdentityField("mfds_product", "품목명(식약처)", _text(mfds_product)),
        IdentityField("company", "제조·수입업체", company, note=company_note, span=2),
        IdentityField(
            "permit",
            permit_label,
            permit,
            status=permit_state[0],
            tone=permit_state[1],
            note=_text(permit_note),
        ),
        IdentityField("grade", "등급", grade_text(grade), empty_text=NONE if permit else NOT_CHECKED),
        IdentityField(
            "detail_class",
            "나라장터 세부품명(코드)",
            detail,
            note=_text(detail_note),
            empty_text=NONE,
            span=2,
        ),
    ]
    search = _text(search_text)
    if search and _normal(search) != _normal(model):
        fields[-1] = IdentityField(**{**fields[-1].__dict__, "span": 1})
        fields.append(IdentityField("search", "검색어", search))
    return fields


def _normal(value: str) -> str:
    return "".join(value.split()).casefold()


def _permit_type(permit: object) -> str:
    text = "".join(str(permit or "").split())
    if text.startswith(("제허", "수허")):
        return "허가"
    if text.startswith(("제인", "수인")):
        return "인증"
    if text.startswith(("제신", "수신")):
        return "신고"
    return ""


def matched_product_fields(
    *,
    identity: Any = None,
    workspace: Any = None,
    candidates: Sequence[Any] = (),
    fallback_model: str = "",
    status_labels: Mapping[str, str] | None = None,
) -> list[IdentityField]:
    """The product the app matched, from the 식약처 identity index (``MfdsIdentityLookup``), the
    식약처 search (``MfdsWorkspaceResult``) and the same-product 나라장터 trades. Read with getattr
    so a cached older result class still draws."""

    status = _text(getattr(identity, "status", ""))
    match = _text(getattr(identity, "match_type", ""))
    # A 품목- or 업체-level hit names other models' permits: only a model-level hit fills the grid.
    model_level = status == "success" and match in {"model", "udi", "permit"}
    records = tuple(getattr(identity, "records", ()) or ()) if model_level else ()
    ambiguous = _text(getattr(getattr(identity, "identity_status", ""), "value", "")).upper() == "AMBIGUOUS"
    exact = tuple(getattr(workspace, "exact_records", ()) or ()) if workspace is not None else ()
    if not records and exact and getattr(workspace, "exact_confirmed", False):
        status, match = "success", "model"
    first = records[0] if records else (exact[0] if exact else None)

    model = _text(getattr(first, "model_name", "")) or _text(fallback_model)
    permits = _unique(getattr(record, "permit_number", "") for record in (records or exact))
    companies = _unique(getattr(record, "registered_company", "") for record in records)
    if candidates:
        detail_name, detail_code = detail_class_of(candidates)
    else:
        detail_name, detail_code = "", ""
    maker = most_common(getattr(candidate, "manufacturer", "") for candidate in candidates)
    label = ""
    for permit in permits:
        label = (status_labels or {}).get("".join(permit.split()), "")
        if label:
            break
    models = _unique(getattr(record, "model_name", "") for record in records)
    return product_fields(
        model=model,
        model_state=model_status(
            identity_status=status, identity_match=match, ambiguous=ambiguous, direct_count=len(candidates)
        ),
        mfds_product=_text(getattr(first, "product_name", "")),
        companies=companies,
        procurement_maker=maker,
        permit_numbers=permits,
        permit_type=_permit_type(permits[0]) if permits else "",
        permit_state=permit_status(
            permit=permits[0] if permits else "", status_label=label, found=bool(permits) and status == "success"
        ),
        permit_note=f"이 허가의 모델 {len(models)}개" if len(models) > 1 else "",
        grade=_text(getattr(first, "grade", "")),
        detail_name=detail_name,
        detail_code=detail_code,
        detail_note=f"같은 제품 거래 {len(candidates)}건 기준" if candidates else "같은 제품 거래 0건",
    )


# ── 견적서에 적힌 값 ──


def _number(value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return _text(value)
    if not number.is_finite():
        return ""
    return f"{number:,.0f}" if number == number.to_integral_value() else f"{number.normalize():,}"


def quote_fields(item: Any) -> list[IdentityField]:
    """What the quote file says, as read: 모델, 품명, 제조사, 규격, 수량, 단위, 견적 단가."""

    def get(name: str) -> str:
        return _text(getattr(item, name, ""))

    price = _number(getattr(item, "unit_price", None))
    quantity = _number(getattr(item, "quantity", None))
    unit = get("unit")
    missing = "견적서에 없음"
    return [
        IdentityField("model", "모델", get("model_name"), empty_text=missing, main=True),
        IdentityField("product", "품명", get("product_name"), empty_text=missing),
        IdentityField("maker", "제조사", get("manufacturer"), empty_text=missing),
        IdentityField("spec", "규격", get("specification"), empty_text=missing),
        # One cell so "2 대" reads as one thing; a missing half says so in the note.
        IdentityField(
            "quantity",
            "수량 · 단위",
            " ".join(part for part in (quantity, unit) if part),
            note="" if (quantity and unit) or not (quantity or unit) else ("단위 없음" if quantity else "수량 없음"),
            empty_text=missing,
        ),
        IdentityField("price", "견적 단가", f"{price}원" if price else "", empty_text=missing),
    ]


# ── HTML ──


def _cell_html(field: IdentityField) -> str:
    classes = ["pi-cell"]
    if field.main:
        classes.append("pi-main")
    if field.span >= 2:
        classes.append("pi-span2")
    status = pill_html(field.status, field.tone) if field.status else ""
    value = field.value or field.empty_text
    value_class = "pi-value" if field.value else "pi-value pi-empty"
    note = f'<div class="pi-note">{esc(field.note)}</div>' if field.note else ""
    return (
        f'<div class="{" ".join(classes)}" data-field="{esc(field.key)}">'
        f'<div class="pi-label"><span>{esc(field.label)}</span>{status}</div>'
        f'<div class="{value_class}">{esc(value)}</div>{note}</div>'
    )


def grid_html(fields: Sequence[IdentityField], *, title: str = "") -> str:
    head = f'<div class="pi-title">{esc(title)}</div>' if title else ""
    cells = "".join(_cell_html(field) for field in fields)
    return f'<div class="pi-block">{head}<div class="pi-grid">{cells}</div></div>'


def identity_html(
    fields: Sequence[IdentityField],
    *,
    marker_heading: str = "",
    element_id: str = "product-identity-v1",
    include_css: bool = True,
) -> str:
    """The product grid. ``marker_heading`` is a visually hidden <h2> (the production smoke and
    screen readers read "DFM100 거래가격")."""

    heading = f'<div class="pi-sr"><h2>{esc(marker_heading)}</h2></div>' if marker_heading else ""
    return (
        (CSS if include_css else "")
        + f'<div class="pi-cq" id="{esc(element_id)}">{heading}{grid_html(fields)}</div>'
    )


def pair_html(
    left: Sequence[IdentityField],
    right: Sequence[IdentityField],
    *,
    left_title: str = "견적서에 적힌 값",
    right_title: str = "확인된 제품",
    include_css: bool = True,
) -> str:
    """Two grids side by side (stacked when narrow): what the file says next to what was matched."""

    return (
        (CSS if include_css else "")
        + '<div class="pi-cq" id="product-identity-pair-v1"><div class="pi-pair">'
        + grid_html(left, title=left_title)
        + grid_html(right, title=right_title)
        + "</div></div>"
    )


def field_map(fields: Iterable[IdentityField]) -> Mapping[str, IdentityField]:
    return {field.key: field for field in fields}
