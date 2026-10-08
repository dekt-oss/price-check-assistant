"""KHIDI 의료기관 회계정보 공시 (haspa.khidi.or.kr) importer.

The disclosure site publishes each hospital's 손익계산서 (IS) and 재무상태표 (SFP) per fiscal year,
without login, both as JSON (the endpoints its own screen calls) and as BIFF ``.xls`` downloads.
This module parses either form into raw account lines, maps the lines we use onto
``hospital_metrics.ACCOUNT_LABELS`` keys, and keeps them in ``data/hospital_financial.csv``.

Only reported amounts are stored. Nothing is estimated: a line the statement does not carry is
absent from the CSV, and the metrics layer then shows "자료 없음".
"""

from __future__ import annotations

import csv
import json
import re
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx

from purchase_price.services.hospital_metrics import ACCOUNT_LABELS, BED_COUNT_KEY

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_FINANCIAL_CSV = REPO_ROOT / "data" / "hospital_financial.csv"
DEFAULT_RAW_DIR = REPO_ROOT / "data" / "khidi_raw"

SOURCE_KHIDI = "khidi_haspa"
HASPA_BASE_URL = "https://haspa.khidi.or.kr"
STATEMENT_IS = "IS"
STATEMENT_SFP = "SFP"
STATEMENT_TITLES = {STATEMENT_IS: "손익계산서", STATEMENT_SFP: "재무상태표"}

CSV_COLUMNS: tuple[str, ...] = (
    "hospital_id",
    "fiscal_year",
    "fiscal_period_start",
    "fiscal_period_end",
    "account_code",
    "account_name",
    "amount",
    "source",
    "source_url",
    "fetched_at",
)


@dataclass(frozen=True)
class HaspaAccount:
    statement: str
    haspa_code: str
    haspa_name: str
    key: str


# KHIDI standard account codes (의료기관 회계기준 규칙 별지 서식) -> our account keys.
HASPA_ACCOUNTS: tuple[HaspaAccount, ...] = (
    HaspaAccount(STATEMENT_IS, "60100000", "Ⅰ.의료수익", "medical_revenue"),
    HaspaAccount(STATEMENT_IS, "60101000", "1.입원수익", "inpatient_revenue"),
    HaspaAccount(STATEMENT_IS, "60102000", "2.외래수익", "outpatient_revenue"),
    HaspaAccount(STATEMENT_IS, "60200000", "Ⅱ.의료비용", "medical_expense"),
    HaspaAccount(STATEMENT_IS, "60201000", "1.인건비", "labor_cost"),
    HaspaAccount(STATEMENT_IS, "60202000", "2.재료비", "material_cost"),
    HaspaAccount(STATEMENT_IS, "60202010", "약품비", "drug_cost"),
    HaspaAccount(STATEMENT_IS, "60202020", "진료재료비", "supply_cost"),
    HaspaAccount(STATEMENT_IS, "60203000", "3.관리운영비", "admin_cost"),
    HaspaAccount(STATEMENT_IS, "60300000", "Ⅲ.의료이익(손실)", "medical_profit"),
    HaspaAccount(STATEMENT_IS, "60400000", "Ⅳ.의료외수익", "non_medical_revenue"),
    HaspaAccount(STATEMENT_IS, "60500000", "Ⅴ.의료외비용", "non_medical_expense"),
    HaspaAccount(STATEMENT_IS, "61100000", "당기순이익(순손실)", "net_income"),
    HaspaAccount(STATEMENT_SFP, "10100000", "Ⅰ.유동자산", "current_assets"),
    HaspaAccount(STATEMENT_SFP, "10000000", "자산총계", "total_assets"),
    HaspaAccount(STATEMENT_SFP, "20100000", "Ⅰ.유동부채", "current_liabilities"),
    HaspaAccount(STATEMENT_SFP, "20100020", "단기차입금", "short_term_borrowings"),
    HaspaAccount(STATEMENT_SFP, "20100080", "유동성장기부채", "current_long_term_debt"),
    HaspaAccount(STATEMENT_SFP, "20100120", "임직원단기차입금", "employee_short_term_borrowings"),
    HaspaAccount(STATEMENT_SFP, "20200010", "장기차입금", "long_term_borrowings"),
    HaspaAccount(STATEMENT_SFP, "20200020", "외화장기차입금", "foreign_long_term_borrowings"),
    HaspaAccount(STATEMENT_SFP, "20000000", "부채총계", "total_liabilities"),
    HaspaAccount(STATEMENT_SFP, "30000000", "자본총계", "total_equity"),
)
assert all(account.key in ACCOUNT_LABELS for account in HASPA_ACCOUNTS)

_NAME_SPACE_RE = re.compile(r"\s+")


def _normalize_account_name(name: str) -> str:
    return _NAME_SPACE_RE.sub("", name or "")


class KhidiParseError(ValueError):
    pass


@dataclass(frozen=True)
class StatementLine:
    code: str | None
    name: str
    amount: Decimal | None


@dataclass(frozen=True)
class Statement:
    """One disclosed statement exactly as published (current-period amounts only)."""

    statement: str
    fiscal_year: int
    period_start: date | None
    period_end: date | None
    lines: tuple[StatementLine, ...]
    hos_code: str | None = None
    hos_name: str | None = None
    bed_count: int | None = None
    kind_name: str | None = None
    found_name: str | None = None

    def mapped(self) -> dict[str, tuple[str, Decimal | None]]:
        """``{account_key: (published account name, amount)}`` for the accounts we use.

        Lines are matched by KHIDI account code when present (JSON) and otherwise by the
        published name (``.xls``); the first matching line wins, so a repeated name lower in
        the statement never overrides the headline line.
        """

        wanted = [a for a in HASPA_ACCOUNTS if a.statement == self.statement]
        by_code = {a.haspa_code: a for a in wanted}
        by_name = {_normalize_account_name(a.haspa_name): a for a in wanted}
        result: dict[str, tuple[str, Decimal | None]] = {}
        for line in self.lines:
            account = by_code.get(line.code or "") if line.code else None
            if account is None and not line.code:
                account = by_name.get(_normalize_account_name(line.name))
            if account is not None and account.key not in result:
                result[account.key] = (ACCOUNT_LABELS[account.key], line.amount)
        return result


def _amount(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "")).quantize(Decimal(1))
    except InvalidOperation:
        return None


def _ymd(year: Any, month: Any, day: Any) -> date | None:
    try:
        return date(int(year), int(month), int(day))
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(str(value).replace(",", "")) if value not in (None, "") else None
    except ValueError:
        return None


def parse_haspa_json(payload: Mapping[str, Any] | str, statement: str) -> Statement:
    """Parse ``/api/total-is/{code}`` or ``/api/total-sfp/{code}`` output."""

    if isinstance(payload, str):
        payload = json.loads(payload)
    if statement not in STATEMENT_TITLES:
        raise ValueError(f"unknown statement: {statement}")
    if payload.get("result") != "ok":
        raise KhidiParseError(f"HASPA returned result={payload.get('result')!r} msg={payload.get('msg')!r}")
    body = payload.get("json") or {}
    info = body.get("info") or {}
    period = info.get("map") or {}
    amount_field = "profitAmt" if statement == STATEMENT_IS else "basAmt"
    if statement == STATEMENT_IS:
        start = _ymd(period.get("cFyyyy"), period.get("cFmonth"), period.get("cFday"))
        end = _ymd(period.get("cTyyyy"), period.get("cTmonth"), period.get("cTday"))
    else:
        start = None
        end = _ymd(period.get("cyyyy"), period.get("cmonth"), period.get("cday"))
    lines = tuple(
        StatementLine(
            code=str(row.get("accCode") or "") or None,
            name=str(row.get("accName2") or "").strip(),
            amount=_amount(row.get(amount_field)),
        )
        for row in body.get("one") or []
    )
    if not lines:
        raise KhidiParseError("statement has no account lines")
    fiscal_year = _int_or_none(info.get("fyYyyy"))
    if fiscal_year is None:
        raise KhidiParseError("statement has no fiscal year")
    return Statement(
        statement=statement,
        fiscal_year=fiscal_year,
        period_start=start,
        period_end=end,
        lines=lines,
        hos_code=str(info.get("hosCode") or "") or None,
        hos_name=str(info.get("hosName") or "").strip() or None,
        bed_count=_int_or_none(info.get("bsNum")),
        kind_name=str(info.get("kindName") or "").strip() or None,
        found_name=str(info.get("foundName") or "").strip() or None,
    )


_XLS_PERIOD_RE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def parse_haspa_xls(source: Path | bytes, *, hos_name: str | None = None) -> Statement:
    """Parse the ``.xls`` from the site's 엑셀다운로드 button (BIFF, one sheet).

    Layout (checked against 인제대학교부산백병원 2024): row 3 title (손익계산서/재무상태표),
    row 4 당기 period text, row 8-9 headers, then column B account name and column C 당기 금액.
    The hospital name is only in the file name, so callers pass it (or it is read from
    ``<병원명>_손익계산서.xls``).
    """

    import xlrd

    if isinstance(source, Path):
        if hos_name is None:
            hos_name = source.stem.rsplit("_", 1)[0] or None
        book = xlrd.open_workbook(file_contents=source.read_bytes())
    else:
        book = xlrd.open_workbook(file_contents=source)
    sheet = book.sheet_by_index(0)
    cells = [[str(v).strip() if not isinstance(v, float) else v for v in sheet.row_values(r)] for r in range(sheet.nrows)]

    statement = None
    header_row = None
    for index, row in enumerate(cells[:15]):
        text = "".join(str(v) for v in row)
        compact = _normalize_account_name(text)
        if statement is None:
            for kind, title in STATEMENT_TITLES.items():
                if compact == title or compact.endswith(title) and "규칙" not in compact:
                    statement = kind
        if "계정과목" in compact:
            header_row = index
    if statement is None or header_row is None:
        raise KhidiParseError("not a KHIDI 손익계산서/재무상태표 download")

    period_dates: list[date] = []
    for row in cells[:header_row]:
        text = "".join(str(v) for v in row)
        if "당" in text and "기" in text and _XLS_PERIOD_RE.search(text):
            period_dates = [_ymd(*m) for m in _XLS_PERIOD_RE.findall(text)]
            period_dates = [d for d in period_dates if d is not None]
            break
    if not period_dates:
        raise KhidiParseError("current-period dates not found")
    if statement == STATEMENT_IS:
        if len(period_dates) < 2:
            raise KhidiParseError("income statement period needs a start and an end date")
        start, end = period_dates[0], period_dates[1]
        fiscal_year = start.year
    else:
        start, end = None, period_dates[0]
        # The SFP is dated at period end; a period ending in Jan-Jun belongs to the
        # fiscal year that started the previous calendar year (e.g. 2025-02-28 -> 2024).
        fiscal_year = end.year if end.month >= 7 else end.year - 1

    lines: list[StatementLine] = []
    for row in cells[header_row + 2 :]:
        if len(row) < 3:
            continue
        name = str(row[1]).strip()
        if not name:
            continue
        lines.append(StatementLine(code=None, name=name, amount=_amount(row[2])))
    if not lines:
        raise KhidiParseError("statement has no account lines")
    return Statement(
        statement=statement,
        fiscal_year=fiscal_year,
        period_start=start,
        period_end=end,
        lines=tuple(lines),
        hos_name=hos_name,
    )


@dataclass(frozen=True)
class FinancialRow:
    hospital_id: str
    fiscal_year: int
    fiscal_period_start: date | None
    fiscal_period_end: date | None
    account_code: str
    account_name: str
    amount: Decimal | None
    source: str
    source_url: str
    fetched_at: str

    @property
    def key(self) -> tuple[str, int, str, str]:
        return (self.hospital_id, self.fiscal_year, self.account_code, self.source)

    def as_csv(self) -> dict[str, str]:
        return {
            "hospital_id": self.hospital_id,
            "fiscal_year": str(self.fiscal_year),
            "fiscal_period_start": self.fiscal_period_start.isoformat() if self.fiscal_period_start else "",
            "fiscal_period_end": self.fiscal_period_end.isoformat() if self.fiscal_period_end else "",
            "account_code": self.account_code,
            "account_name": self.account_name,
            "amount": "" if self.amount is None else str(self.amount),
            "source": self.source,
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
        }


def statement_url(statement: str, hos_code: str, year: int) -> str:
    kind = "is" if statement == STATEMENT_IS else "sfp"
    return f"{HASPA_BASE_URL}/api/total-{kind}/{hos_code}?y={year}"


def rows_from_statements(
    hospital_id: str,
    statements: Sequence[Statement],
    *,
    fetched_at: str,
    source: str = SOURCE_KHIDI,
    source_urls: Mapping[str, str] | None = None,
) -> list[FinancialRow]:
    """Turn one hospital-year's IS and/or SFP into CSV rows.

    The fiscal period comes from the income statement (start and end). The end falls back to
    the balance-sheet date when the income statement has none (missing or not a real date).
    """

    if not statements:
        return []
    years = {s.fiscal_year for s in statements}
    if len(years) != 1:
        raise KhidiParseError(f"statements mix fiscal years: {sorted(years)}")
    fiscal_year = years.pop()
    income = next((s for s in statements if s.statement == STATEMENT_IS), None)
    balance = next((s for s in statements if s.statement == STATEMENT_SFP), None)
    period_start = income.period_start if income else None
    # The balance-sheet date is the published period end. It also covers an income statement
    # whose end date does not exist (동아대학교병원 2024 publishes "2025-02-29").
    period_end = (income.period_end if income else None) or (balance.period_end if balance else None)
    rows: list[FinancialRow] = []
    for stmt in statements:
        url = (source_urls or {}).get(stmt.statement) or (
            statement_url(stmt.statement, stmt.hos_code, stmt.fiscal_year) if stmt.hos_code else ""
        )
        mapped = dict(stmt.mapped())
        # The disclosure's 일반현황 shows that year's bed count (심평원 year-end figure). It is kept
        # as its own row, from the income statement only, so per-bed metrics use the same year.
        if stmt.statement == STATEMENT_IS and stmt.bed_count is not None:
            mapped[BED_COUNT_KEY] = (ACCOUNT_LABELS[BED_COUNT_KEY], Decimal(stmt.bed_count))
        for key, (name, amount) in mapped.items():
            rows.append(
                FinancialRow(
                    hospital_id=hospital_id,
                    fiscal_year=fiscal_year,
                    fiscal_period_start=period_start,
                    fiscal_period_end=period_end,
                    account_code=key,
                    account_name=name,
                    amount=amount,
                    source=source,
                    source_url=url,
                    fetched_at=fetched_at,
                )
            )
    return rows


def _parse_date(value: str) -> date | None:
    return date.fromisoformat(value) if value else None


def load_financial_csv(path: Path = DEFAULT_FINANCIAL_CSV) -> list[FinancialRow]:
    if not path.exists():
        return []
    rows: list[FinancialRow] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            if not raw.get("hospital_id"):
                continue
            rows.append(
                FinancialRow(
                    hospital_id=raw["hospital_id"],
                    fiscal_year=int(raw["fiscal_year"]),
                    fiscal_period_start=_parse_date(raw.get("fiscal_period_start") or ""),
                    fiscal_period_end=_parse_date(raw.get("fiscal_period_end") or ""),
                    account_code=raw["account_code"],
                    account_name=raw.get("account_name") or "",
                    amount=_amount(raw.get("amount")),
                    source=raw.get("source") or "",
                    source_url=raw.get("source_url") or "",
                    fetched_at=raw.get("fetched_at") or "",
                )
            )
    return rows


def merge_rows(existing: Iterable[FinancialRow], incoming: Iterable[FinancialRow]) -> list[FinancialRow]:
    """Upsert by (hospital, year, account, source). Re-importing the same data is a no-op.

    When the amount and period are unchanged the existing ``fetched_at`` is kept, so running the
    importer twice produces a byte-identical CSV.
    """

    merged: dict[tuple[str, int, str, str], FinancialRow] = {row.key: row for row in existing}
    for row in incoming:
        old = merged.get(row.key)
        if old is not None and (
            old.amount == row.amount
            and old.fiscal_period_start == row.fiscal_period_start
            and old.fiscal_period_end == row.fiscal_period_end
            and old.source_url == row.source_url
        ):
            continue
        merged[row.key] = row
    account_order = {key: index for index, key in enumerate(ACCOUNT_LABELS)}
    return sorted(
        merged.values(),
        key=lambda r: (r.hospital_id, r.fiscal_year, account_order.get(r.account_code, 999), r.source),
    )


def write_financial_csv(rows: Iterable[FinancialRow], path: Path = DEFAULT_FINANCIAL_CSV) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row.as_csv())


@dataclass(frozen=True)
class HospitalYear:
    """Accounts and fiscal period for one hospital-year, ready for ``compute_metrics``."""

    hospital_id: str
    fiscal_year: int
    accounts: dict[str, Decimal | None]
    period: tuple[str, str] | None
    sources: tuple[str, ...]
    fetched_at: str


def group_hospital_years(rows: Iterable[FinancialRow]) -> dict[tuple[str, int], HospitalYear]:
    grouped: dict[tuple[str, int], list[FinancialRow]] = {}
    for row in rows:
        grouped.setdefault((row.hospital_id, row.fiscal_year), []).append(row)
    result: dict[tuple[str, int], HospitalYear] = {}
    for (hospital_id, year), items in grouped.items():
        start = next((r.fiscal_period_start for r in items if r.fiscal_period_start), None)
        end = next((r.fiscal_period_end for r in items if r.fiscal_period_end), None)
        result[(hospital_id, year)] = HospitalYear(
            hospital_id=hospital_id,
            fiscal_year=year,
            accounts={r.account_code: r.amount for r in items},
            period=(start.isoformat(), end.isoformat()) if start and end else None,
            sources=tuple(sorted({r.source_url or r.source for r in items})),
            fetched_at=max(r.fetched_at for r in items),
        )
    return result


# --- live access -----------------------------------------------------------------------------


@dataclass(frozen=True)
class HaspaListing:
    fiscal_year: int
    hos_code: str
    name: str
    bed_count: int | None
    kind_name: str
    found_name: str


_LISTING_RE = re.compile(
    r'name="pi"\s+value="(?P<code>\d+)"\s+data-year="(?P<year>\d{4})".*?'
    r'board_name[^"]*"><span>(?P<name>[^<]+)</span>.*?'
    r'text-center">(?P<beds>[\d,]*)</div>.*?'
    r'no-padding">(?P<kind>[^<]*)</div>.*?'
    r'no-padding">(?P<found>[^<]*)</div>',
    re.S,
)


def parse_search_html(html: str) -> list[HaspaListing]:
    return [
        HaspaListing(
            fiscal_year=int(m["year"]),
            hos_code=m["code"],
            name=m["name"].strip(),
            bed_count=_int_or_none(m["beds"]),
            kind_name=m["kind"].strip(),
            found_name=m["found"].strip(),
        )
        for m in _LISTING_RE.finditer(html)
    ]


class HaspaClient:
    """Polite client for the public disclosure site (no key, no login)."""

    def __init__(self, *, timeout_seconds: float = 30.0, delay_seconds: float = 0.3) -> None:
        self._client = httpx.Client(
            base_url=HASPA_BASE_URL,
            timeout=timeout_seconds,
            headers={"User-Agent": "price-check-assistant hospital-benchmark importer"},
        )
        self._delay = delay_seconds

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HaspaClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get(self, path: str, params: dict[str, Any]) -> httpx.Response:
        time.sleep(self._delay)
        response = self._client.get(path, params=params)
        response.raise_for_status()
        return response

    def search(self, year: int, name: str) -> list[HaspaListing]:
        listings: list[HaspaListing] = []
        for page in range(1, 6):
            # The site pages with ``p`` (``page`` is ignored and always returns page 1).
            html = self._get("/total-public-inq", {"p": page, "y": year, "hn": name}).text
            found = [item for item in parse_search_html(html) if item.fiscal_year == year]
            new = [item for item in found if item not in listings]
            if not new:
                break
            listings.extend(new)
            if len(found) < 10:
                break
        return listings

    def list_all(self, year: int, *, max_pages: int = 400) -> list[HaspaListing]:
        """Every institution in one disclosure year (about 1,100 in 2024, 10 per page)."""

        listings: list[HaspaListing] = []
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            html = self._get("/total-public-inq", {"p": page, "y": year, "hn": ""}).text
            new = [i for i in parse_search_html(html) if i.fiscal_year == year and i.hos_code not in seen]
            if not new:
                break
            seen.update(i.hos_code for i in new)
            listings.extend(new)
        return listings

    def statement_payload(self, statement: str, hos_code: str, year: int) -> dict[str, Any]:
        kind = "is" if statement == STATEMENT_IS else "sfp"
        return self._get(f"/api/total-{kind}/{hos_code}", {"y": year}).json()


_LEGAL_PREFIX_RE = re.compile(r"^\s*\((?:학교법인|의|재|사|복지|사단법인|재단법인|의료법인|사회복지법인)\)\s*")


def resolve_disclosed_name(master: Any, name: str) -> Any:
    """Resolve a disclosed institution name to a master hospital.

    Some years prefix the legal form, e.g. "(학교법인)인제대학교부산백병원" (2016-2018); the
    prefix is dropped before the alias lookup. No fuzzy matching beyond that.
    """

    return master.resolve(name) or master.resolve(_LEGAL_PREFIX_RE.sub("", name or ""))


def raw_snapshot_path(raw_dir: Path, year: int, hos_code: str, statement: str) -> Path:
    return raw_dir / str(year) / f"{hos_code}_{statement}.json"


def save_raw_snapshot(raw_dir: Path, year: int, hos_code: str, statement: str, payload: Mapping[str, Any], fetched_at: str) -> Path:
    path = raw_snapshot_path(raw_dir, year, hos_code, statement)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "source_url": statement_url(statement, hos_code, year),
        "fetched_at": fetched_at,
        "payload": payload,
    }
    path.write_text(json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_raw_snapshot(path: Path) -> tuple[Statement, str, str]:
    """Return (statement, source_url, fetched_at) from a saved snapshot."""

    document = json.loads(path.read_text(encoding="utf-8"))
    statement = STATEMENT_IS if path.stem.endswith("_IS") else STATEMENT_SFP
    return parse_haspa_json(document["payload"], statement), document["source_url"], document["fetched_at"]


def now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def with_fetched_at(rows: Iterable[FinancialRow], fetched_at: str) -> list[FinancialRow]:
    return [replace(row, fetched_at=fetched_at) for row in rows]
