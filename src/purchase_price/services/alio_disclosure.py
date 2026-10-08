"""ALIO (공공기관 경영정보 공개시스템, alio.go.kr) disclosure importer for 부산대학교병원.

ALIO's public item pages need no login. Each disclosure item (임직원 수, 신규채용, 요약 재무상태표,
요약 손익계산서, 장단기 차입금) is a server-rendered HTML fragment:

    GET /item/itemReportTerm.do?apbaId=C0071&reportFormRootNo=<item>   -> latest disclosureNo
    GET /item/itemReportRight.do?disclosureNo=<no>                      -> the report table

The raw fragment is kept under ``data/alio_raw/`` with its source URL and fetch time; the tidy
table ``data/alio_disclosure.csv`` is always rebuilt from the raw files, so re-running with the
same raw input never changes the CSV. Cells shown as "-" (not applicable) are not stored.

ALIO reports 부산대학교병원 as one institution (apbaId C0071). 양산부산대학교병원 is not a separate
ALIO institution, so every figure here covers 본원 and 양산 together (법인 단위).
"""

from __future__ import annotations

import csv
import html
import json
import re
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ALIO_CSV = REPO_ROOT / "data" / "alio_disclosure.csv"
DEFAULT_RAW_DIR = REPO_ROOT / "data" / "alio_raw"

SOURCE_ALIO = "alio"
ALIO_BASE_URL = "https://alio.go.kr"
USER_AGENT = "price-check-assistant/alio-importer (public disclosure pages; contact via repo owner)"

CSV_COLUMNS: tuple[str, ...] = (
    "hospital_id",
    "entity_name",
    "scope",
    "fiscal_year",
    "item_code",
    "item_name",
    "value",
    "unit",
    "source",
    "source_url",
    "fetched_at",
)

SCOPE_ENTITY = "법인"

ALIO_SCOPE_NOTE = (
    "이 표는 알리오(공공기관 경영정보 공개시스템)에 부산대학교병원이 한 기관으로 올린 자료입니다. "
    "양산부산대학교병원은 알리오에 따로 올라 있지 않아, 숫자에 본원과 양산이 함께 들어 있습니다. "
    "병원 하나만의 숫자가 아니므로 다른 병원과 같은 기준으로 비교하지 말고, 인력·빚·정부지원 같은 참고용으로만 보세요."
)

# ALIO institution id -> (hospital_id the rows are filed under, entity name, hospital_ids that share them).
ALIO_ENTITIES: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "C0071": ("H-PNUH", "부산대학교병원(양산부산대학교병원 포함)", ("H-PNUH", "H-PNUYH")),
}
# hospital_master id -> the id its ALIO rows are filed under.
ALIO_HOSPITAL_ALIASES: dict[str, str] = {
    member: owner for owner, _name, members in ALIO_ENTITIES.values() for member in members
}


@dataclass(frozen=True)
class ItemSpec:
    code: str
    name: str
    section: str  # table title row (first cell of the row followed by "(단위 ...)"), "" if none
    path: str  # row label cells joined with "/" (merged duplicates removed)
    unit: str


@dataclass(frozen=True)
class ReportSpec:
    root_no: str
    title: str
    flow: bool  # a partial-year column is a running total (신규채용) rather than a snapshot
    items: tuple[ItemSpec, ...]


def _items(section: str, unit: str, rows: Sequence[tuple[str, str, str]]) -> tuple[ItemSpec, ...]:
    return tuple(ItemSpec(code, name, section, path, unit) for code, name, path in rows)


REPORT_SPECS: tuple[ReportSpec, ...] = (
    ReportSpec(
        "2020",
        "임직원 수",
        False,
        _items(
            "",
            "명",
            [
                ("headcount_quota_total", "임직원 정원 합계", "임직원 총계 (A+B+C)"),
                ("regular_quota", "정규직(일반) 정원", "정규직/일반 정규직/정원/계(B)"),
                ("regular_actual", "정규직(일반) 현원", "정규직/일반 정규직/현원/계"),
                ("fixed_term_actual", "기간제(비정규직) 현원", "비정규직/기간제/계"),
                ("outsourced_actual", "용역(민간) 인력", "비정규직/소속외 인력/용역(민간)"),
                ("female_actual", "여성 현원", "여성현원/합계"),
            ],
        ),
    ),
    ReportSpec(
        "2040",
        "신규채용 현황",
        True,
        _items(
            "정규직(일반정규직)",
            "명",
            [
                ("new_hire_regular", "정규직(일반) 신규채용", "일반정규직 총신규채용"),
                ("new_hire_youth", "신규채용 중 청년", "청년"),
                ("new_hire_female", "신규채용 중 여성", "여성"),
                ("new_hire_non_capital", "신규채용 중 비수도권 지역인재", "비수도권 지역인재"),
            ],
        ),
    ),
    ReportSpec(
        "3120",
        "요약 재무상태표",
        False,
        _items(
            "요약 재무상태표(K-GAAP)",
            "백만원",
            [
                ("current_assets", "유동자산", "자산/유동자산"),
                ("non_current_assets", "비유동자산", "자산/비유동자산"),
                ("total_assets", "자산총계", "자산/자산총계"),
                ("current_liabilities", "유동부채", "부채/유동부채"),
                ("non_current_liabilities", "비유동부채", "부채/비유동부채"),
                ("total_liabilities", "부채총계", "부채/부채총계"),
                ("capital_stock", "자본금", "자본/자본금"),
                ("total_equity", "자본총계", "자본/자본총계"),
            ],
        )
        + _items("요약 재무상태표(K-GAAP)", "%", [("debt_ratio", "부채비율", "부채비율")]),
    ),
    ReportSpec(
        "3130",
        "요약 손익계산서",
        False,
        _items(
            "요약 손익계산서(K-GAAP)",
            "백만원",
            [
                ("revenue", "매출", "매출"),
                ("cost_of_revenue", "매출원가", "매출원가"),
                ("operating_income", "영업이익", "영업이익"),
                ("non_operating_income", "영업외 수익", "영업이익외 수익"),
                ("non_operating_expense", "영업외 비용", "영업외 비용"),
                ("total_income", "총 수익", "총 수익"),
                ("total_expense", "총 비용", "총 비용"),
                ("net_income", "당기순이익", "당기 순이익"),
            ],
        )
        + _items("요약 손익계산서(K-GAAP)", "%", [("net_margin", "매출액순이익률", "매출액순이익률")]),
    ),
    ReportSpec(
        "3180",
        "장단기 차입금 현황",
        False,
        _items(
            "장기차입금",
            "백만원",
            [("long_term_borrowing_end", "장기차입금 기말잔액", "기말잔액"), ("long_term_borrowing_change", "장기차입금 변동금액", "변동금액")],
        )
        + _items(
            "단기차입금",
            "백만원",
            [("short_term_borrowing_end", "단기차입금 기말잔액", "기말잔액"), ("short_term_borrowing_change", "단기차입금 변동금액", "변동금액")],
        )
        + _items("장기차입금", "%", [("long_term_borrowing_dependency", "장기차입금 의존도", "차입금의존도")])
        + _items("단기차입금", "%", [("short_term_borrowing_dependency", "단기차입금 의존도", "차입금의존도")]),
    ),
)
SPEC_BY_ROOT = {spec.root_no: spec for spec in REPORT_SPECS}
ITEM_ORDER = {item.code: index for index, item in enumerate(i for spec in REPORT_SPECS for i in spec.items)}


class AlioParseError(ValueError):
    pass


# --------------------------------------------------------------------------- HTML table parsing

_TR_RE = re.compile(r"<tr[^>]*>((?:(?!<tr[ >]).)*?)</tr>", re.S)
_CELL_RE = re.compile(r"<t([dh])([^>]*)>(.*?)</t\1>", re.S)


def _span(attrs: str, name: str) -> int:
    match = re.search(rf'{name}="?(\d+)', attrs)
    return int(match.group(1)) if match else 1


def _cell_text(raw: str) -> str:
    text = re.sub(r"<br\s*/?>", " ", raw)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def table_rows(fragment: str) -> list[list[str]]:
    """Every ``<tr>`` as a full-width row; ``rowspan``/``colspan`` cells are repeated into the grid."""

    rows: list[list[str]] = []
    pending: dict[int, tuple[str, int]] = {}
    for tr in _TR_RE.findall(fragment):
        cells = [(_cell_text(m.group(3)), _span(m.group(2), "rowspan"), _span(m.group(2), "colspan")) for m in _CELL_RE.finditer(tr)]
        if not cells:
            continue
        row: list[str] = []
        col = 0
        queue = list(cells)
        while queue or any(c >= col for c in pending):
            if col in pending:
                text, remaining = pending[col]
                row.append(text)
                if remaining <= 1:
                    del pending[col]
                else:
                    pending[col] = (text, remaining - 1)
                col += 1
                continue
            if not queue:
                break
            text, rowspan, colspan = queue.pop(0)
            for _ in range(colspan):
                row.append(text)
                if rowspan > 1:
                    pending[col] = (text, rowspan - 1)
                col += 1
        rows.append(row)
    return rows


_YEAR_HEADER_RE = re.compile(r"^(\d{4})년\s*(.*)$")
_QUARTER_RE = re.compile(r"(\d)\s*/\s*4\s*분기")


@dataclass(frozen=True)
class YearColumn:
    index: int
    year: int
    quarter: int | None  # None = full-year result


def _year_columns(header: Sequence[str]) -> list[YearColumn]:
    """Year columns of a header row; budget (예산) columns are skipped, never mixed with results."""

    columns: list[YearColumn] = []
    for index, cell in enumerate(header):
        match = _YEAR_HEADER_RE.match(cell)
        if not match:
            continue
        rest = match.group(2)
        if "예산" in rest:
            continue
        quarter = _QUARTER_RE.search(rest)
        columns.append(YearColumn(index, int(match.group(1)), int(quarter.group(1)) if quarter else None))
    return columns


def _label_path(cells: Sequence[str]) -> str:
    labels: list[str] = []
    for cell in cells:
        if cell and (not labels or labels[-1] != cell):
            labels.append(cell)
    return "/".join(labels)


def _number(text: str) -> Decimal | None:
    cleaned = text.replace(",", "").strip()
    if cleaned in ("", "-"):
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


@dataclass(frozen=True)
class ParsedValue:
    item: ItemSpec
    year: int
    quarter: int | None
    value: Decimal


def parse_report(fragment: str, spec: ReportSpec) -> list[ParsedValue]:
    """Pick the wanted rows of one report fragment, for every published year column."""

    wanted: dict[tuple[str, str], list[ItemSpec]] = {}
    for item in spec.items:
        wanted.setdefault((item.section, item.path), []).append(item)

    out: list[ParsedValue] = []
    section = ""
    columns: list[YearColumn] = []
    rows = table_rows(fragment)
    for position, row in enumerate(rows):
        if len(row) >= 2 and row[1].startswith("(단위") and row[0] != row[1]:
            section = row[0]
            continue
        if row and row[0] in ("구분", "직급 구분") and _year_columns(row):
            columns = _year_columns(row)
            continue
        if not columns or len(row) <= max(c.index for c in columns):
            continue
        first_value = min(c.index for c in columns)
        key = (section, _label_path(row[:first_value]))
        for item in wanted.get(key, []):
            for column in columns:
                value = _number(row[column.index])
                if value is not None:
                    out.append(ParsedValue(item, column.year, column.quarter, value))
    return out


# --------------------------------------------------------------------------- CSV rows

@dataclass(frozen=True)
class AlioRow:
    hospital_id: str
    entity_name: str
    scope: str
    fiscal_year: int
    item_code: str
    item_name: str
    value: str
    unit: str
    source: str
    source_url: str
    fetched_at: str

    def key(self) -> tuple[str, int, str]:
        return (self.hospital_id, self.fiscal_year, self.item_code)

    def as_csv(self) -> dict[str, str]:
        data = {name: getattr(self, name) for name in CSV_COLUMNS}
        data["fiscal_year"] = str(self.fiscal_year)
        return data


def _value_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text


def _item_name(item: ItemSpec, quarter: int | None, year: int, flow: bool) -> str:
    if quarter is None:
        return item.name
    if flow:
        return f"{item.name} ({year}년 {quarter}분기까지 누적)"
    return f"{item.name} ({year}년 {quarter}분기 말)"


def rows_from_raw(document: dict[str, Any]) -> list[AlioRow]:
    apba_id = document["apba_id"]
    owner, entity_name, _members = ALIO_ENTITIES[apba_id]
    spec = SPEC_BY_ROOT[document["root_no"]]
    parsed = parse_report(document["html"], spec)
    return [
        AlioRow(
            hospital_id=owner,
            entity_name=entity_name,
            scope=SCOPE_ENTITY,
            fiscal_year=p.year,
            item_code=p.item.code,
            item_name=_item_name(p.item, p.quarter, p.year, spec.flow),
            value=_value_text(p.value),
            unit=p.item.unit,
            source=SOURCE_ALIO,
            source_url=document["source_url"],
            fetched_at=document["fetched_at"],
        )
        for p in parsed
    ]


def merge_rows(rows: Iterable[AlioRow]) -> list[AlioRow]:
    """One row per (hospital, year, item); the newest disclosure wins, ties broken by source URL."""

    best: dict[tuple[str, int, str], AlioRow] = {}
    for row in rows:
        current = best.get(row.key())
        if current is None or (_disclosure_no(row.source_url), row.source_url) > (_disclosure_no(current.source_url), current.source_url):
            best[row.key()] = row
    return sorted(best.values(), key=lambda r: (r.hospital_id, r.fiscal_year, ITEM_ORDER.get(r.item_code, 999), r.item_code))


def _disclosure_no(url: str) -> str:
    match = re.search(r"disclosureNo=(\d+)", url)
    return match.group(1) if match else ""


def write_alio_csv(rows: Iterable[AlioRow], path: Path = DEFAULT_ALIO_CSV) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_csv())


def load_alio_csv(path: Path = DEFAULT_ALIO_CSV) -> list[AlioRow]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [
            AlioRow(**{**{name: raw[name] for name in CSV_COLUMNS}, "fiscal_year": int(raw["fiscal_year"])})
            for raw in csv.DictReader(handle)
        ]


# --------------------------------------------------------------------------- raw files + fetching

def raw_path(raw_dir: Path, apba_id: str, root_no: str, disclosure_no: str) -> Path:
    return raw_dir / f"{apba_id}_{root_no}_{disclosure_no}.json"


def term_url(apba_id: str, root_no: str, disclosure_no: str = "") -> str:
    return f"{ALIO_BASE_URL}/item/itemReportTerm.do?apbaId={apba_id}&reportFormRootNo={root_no}&disclosureNo={disclosure_no}"


def fragment_url(disclosure_no: str) -> str:
    return f"{ALIO_BASE_URL}/item/itemReportRight.do?disclosureNo={disclosure_no}"


def now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


_LATEST_NO_RE = re.compile(r'disclosureNo:\s*"(\d{10,})"')


def latest_disclosure_no(term_page: str) -> str:
    match = _LATEST_NO_RE.search(term_page)
    if not match:
        raise AlioParseError("itemReportTerm page has no disclosureNo")
    return match.group(1)


def save_raw(raw_dir: Path, apba_id: str, root_no: str, disclosure_no: str, fragment: str, fetched_at: str) -> Path:
    """Write one raw fragment. An unchanged fragment keeps its first ``fetched_at``."""

    path = raw_path(raw_dir, apba_id, root_no, disclosure_no)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("html") == fragment:
            return path
    document = {
        "apba_id": apba_id,
        "root_no": root_no,
        "disclosure_no": disclosure_no,
        "source_url": term_url(apba_id, root_no, disclosure_no),
        "fragment_url": fragment_url(disclosure_no),
        "fetched_at": fetched_at,
        "html": fragment,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return path


def fetch_raw(
    raw_dir: Path = DEFAULT_RAW_DIR,
    apba_ids: Sequence[str] = tuple(ALIO_ENTITIES),
    root_nos: Sequence[str] | None = None,
    *,
    client: httpx.Client | None = None,
    pause: float = 1.0,
) -> list[Path]:
    """Download the newest report of each wanted item. Public pages, no key, one request at a time."""

    own_client = client is None
    http = client or httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True)
    saved: list[Path] = []
    try:
        for apba_id in apba_ids:
            for root_no in root_nos or [spec.root_no for spec in REPORT_SPECS]:
                page = http.get(term_url(apba_id, root_no))
                page.raise_for_status()
                disclosure_no = latest_disclosure_no(page.text)
                time.sleep(pause)
                fragment = http.get(fragment_url(disclosure_no))
                fragment.raise_for_status()
                saved.append(save_raw(raw_dir, apba_id, root_no, disclosure_no, fragment.text, now_iso()))
                time.sleep(pause)
    finally:
        if own_client:
            http.close()
    return saved


def rows_from_raw_dir(raw_dir: Path = DEFAULT_RAW_DIR) -> list[AlioRow]:
    rows: list[AlioRow] = []
    for path in sorted(raw_dir.glob("*.json")):
        rows.extend(rows_from_raw(json.loads(path.read_text(encoding="utf-8"))))
    return merge_rows(rows)


# --------------------------------------------------------------------------- page helpers

@lru_cache(maxsize=4)
def _cached_rows(path: str, mtime_ns: int) -> tuple[AlioRow, ...]:
    return tuple(load_alio_csv(Path(path)))


def alio_rows_for(hospital_id: str, csv_path: Path = DEFAULT_ALIO_CSV) -> list[dict[str, Any]]:
    """ALIO rows for a hospital as plain dicts (empty when ALIO has nothing for it).

    ``H-PNUYH`` returns the same rows as ``H-PNUH``: ALIO files both under 부산대학교병원 (법인 단위).
    """

    owner = ALIO_HOSPITAL_ALIASES.get(hospital_id)
    if owner is None or not csv_path.exists():
        return []
    rows = _cached_rows(str(csv_path), csv_path.stat().st_mtime_ns)
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.hospital_id != owner:
            continue
        out.append(
            {
                "hospital_id": row.hospital_id,
                "entity_name": row.entity_name,
                "scope": row.scope,
                "fiscal_year": row.fiscal_year,
                "item_code": row.item_code,
                "item_name": row.item_name,
                "value": Decimal(row.value),
                "unit": row.unit,
                "source_url": row.source_url,
                "fetched_at": row.fetched_at,
            }
        )
    return out


def alio_table_for(hospital_id: str, csv_path: Path = DEFAULT_ALIO_CSV) -> list[dict[str, Any]]:
    """Screen table: one line per item with one column per year (``"2021년"`` ...) plus 항목 and 단위.

    A year with no published value is left out of that line (shown as blank), never filled in.
    """

    rows = alio_rows_for(hospital_id, csv_path)
    lines: dict[str, dict[str, Any]] = {}
    for row in rows:
        base_name = re.sub(r" \(\d{4}년 \d분기.*\)$", "", row["item_name"])
        line = lines.setdefault(row["item_code"], {"항목": base_name, "단위": row["unit"]})
        label = f"{row['fiscal_year']}년"
        if row["item_name"] != base_name:
            label += "(분기 중간)"
        line[label] = row["value"]
    return [lines[code] for code in sorted(lines, key=lambda code: ITEM_ORDER.get(code, 999))]
