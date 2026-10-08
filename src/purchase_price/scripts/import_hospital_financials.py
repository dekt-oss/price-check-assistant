"""Load KHIDI 의료기관 회계정보 공시 statements into ``data/hospital_financial.csv``.

Three ways in, all ending in the same upsert (re-running is a no-op):

    # 1) fetch from haspa.khidi.or.kr (no key, no login) and keep raw JSON under data/khidi_raw/
    python -m purchase_price.scripts.import_hospital_financials --fetch --years 2016-2024

    # 2) re-parse the saved raw JSON only (offline)
    python -m purchase_price.scripts.import_hospital_financials --from-raw

    # 3) import files downloaded by hand from the site's 엑셀다운로드 button (or saved JSON)
    python -m purchase_price.scripts.import_hospital_financials \
        --file 인제대학교부산백병원_손익계산서.xls --file 인제대학교부산백병원_재무상태표.xls \
        --hospital 부산백병원

Every hospital is matched to ``data/hospital_master.json`` by name; a disclosure that does not
map to exactly one master hospital is reported and skipped, never guessed.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from purchase_price.services import hospital_master as master_service
from purchase_price.services import khidi_financials as khidi

DEFAULT_YEARS = tuple(range(2016, 2025))


@dataclass
class ImportReport:
    loaded: list[tuple[str, int, str]] = field(default_factory=list)
    missing: list[tuple[str, int, str]] = field(default_factory=list)

    def print(self, out=None) -> None:
        out = out or sys.stdout
        for hospital_id, year, note in sorted(self.loaded):
            print(f"loaded  {hospital_id} {year} {note}", file=out)
        for hospital_id, year, note in sorted(self.missing):
            print(f"missing {hospital_id} {year} {note}", file=out)


def parse_years(text: str) -> tuple[int, ...]:
    years: set[int] = set()
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            start, end = (int(x) for x in part.split("-", 1))
            years.update(range(start, end + 1))
        elif part:
            years.add(int(part))
    return tuple(sorted(years))


def search_terms(hospital: master_service.Hospital) -> list[str]:
    terms: list[str] = []
    for name in (hospital.short_name, hospital.canonical_name, *hospital.aliases):
        if name and name not in terms:
            terms.append(name)
    return terms


def find_listing(
    client: khidi.HaspaClient,
    master: master_service.HospitalMaster,
    hospital: master_service.Hospital,
    year: int,
) -> tuple[khidi.HaspaListing | None, str]:
    """The single HASPA listing that resolves to ``hospital`` for ``year``, else a reason."""

    for term in search_terms(hospital):
        listings = client.search(year, term)
        matches = {
            item.hos_code: item
            for item in listings
            if (resolved := khidi.resolve_disclosed_name(master, item.name)) is not None
            and resolved.hospital_id == hospital.hospital_id
        }
        if len(matches) == 1:
            return next(iter(matches.values())), f"검색어 {term}"
        if len(matches) > 1:
            names = ", ".join(f"{m.name}({m.hos_code})" for m in matches.values())
            return None, f"검색어 {term}: 여러 기관이 일치 {names}"
    return None, "공시 목록에서 찾지 못함"


def fetch(
    master: master_service.HospitalMaster,
    hospital_ids: Sequence[str],
    years: Sequence[int],
    raw_dir: Path,
    report: ImportReport,
    client: khidi.HaspaClient | None = None,
) -> list[khidi.FinancialRow]:
    rows: list[khidi.FinancialRow] = []
    own_client = client is None
    client = client or khidi.HaspaClient()
    try:
        for hospital in master.hospitals:
            if hospital_ids and hospital.hospital_id not in hospital_ids:
                continue
            for year in years:
                listing, reason = find_listing(client, master, hospital, year)
                if listing is None:
                    report.missing.append((hospital.hospital_id, year, reason))
                    continue
                fetched_at = khidi.now_iso()
                statements: list[khidi.Statement] = []
                for kind in (khidi.STATEMENT_IS, khidi.STATEMENT_SFP):
                    try:
                        payload = client.statement_payload(kind, listing.hos_code, year)
                        statements.append(khidi.parse_haspa_json(payload, kind))
                    except (khidi.KhidiParseError, ValueError) as exc:
                        report.missing.append((hospital.hospital_id, year, f"{kind} 읽기 실패: {exc}"))
                        continue
                    khidi.save_raw_snapshot(raw_dir, year, listing.hos_code, kind, payload, fetched_at)
                new_rows = khidi.rows_from_statements(hospital.hospital_id, statements, fetched_at=fetched_at)
                if new_rows:
                    rows.extend(new_rows)
                    report.loaded.append(
                        (hospital.hospital_id, year, f"{listing.name}({listing.hos_code}) {len(new_rows)}계정")
                    )
    finally:
        if own_client:
            client.close()
    return rows


def from_raw(
    master: master_service.HospitalMaster, raw_dir: Path, report: ImportReport
) -> list[khidi.FinancialRow]:
    grouped: dict[tuple[str, int], list[tuple[khidi.Statement, str, str]]] = {}
    # Disclosed names change between years (e.g. a legal-form prefix); the KHIDI code does not.
    by_code = {h.khidi_code: h for h in master.hospitals if getattr(h, "khidi_code", None)}
    for path in sorted(raw_dir.glob("*/*.json")):
        statement, url, fetched_at = khidi.load_raw_snapshot(path)
        hospital = khidi.resolve_disclosed_name(master, statement.hos_name or "") or by_code.get(
            statement.hos_code or path.stem.split("_")[0]
        )
        if hospital is None:
            report.missing.append(("?", statement.fiscal_year, f"{path.name}: 병원 명단에 없는 기관 {statement.hos_name}"))
            continue
        grouped.setdefault((hospital.hospital_id, statement.fiscal_year), []).append((statement, url, fetched_at))
    rows: list[khidi.FinancialRow] = []
    for (hospital_id, year), items in sorted(grouped.items()):
        new_rows = khidi.rows_from_statements(
            hospital_id,
            [s for s, _, _ in items],
            fetched_at=max(f for _, _, f in items),
            source_urls={s.statement: u for s, u, _ in items},
        )
        rows.extend(new_rows)
        report.loaded.append((hospital_id, year, f"raw {len(new_rows)}계정"))
    return rows


def from_files(
    master: master_service.HospitalMaster,
    files: Sequence[Path],
    hospital_name: str | None,
    report: ImportReport,
) -> list[khidi.FinancialRow]:
    grouped: dict[tuple[str, int], list[khidi.Statement]] = {}
    for path in files:
        if path.suffix.lower() == ".json":
            statement, _, _ = khidi.load_raw_snapshot(path)
        else:
            statement = khidi.parse_haspa_xls(path, hos_name=hospital_name)
        name = hospital_name or statement.hos_name or ""
        hospital = khidi.resolve_disclosed_name(master, name)
        if hospital is None:
            report.missing.append(("?", statement.fiscal_year, f"{path.name}: 병원을 특정할 수 없음({name})"))
            continue
        grouped.setdefault((hospital.hospital_id, statement.fiscal_year), []).append(statement)
    fetched_at = khidi.now_iso()
    rows: list[khidi.FinancialRow] = []
    for (hospital_id, year), statements in sorted(grouped.items()):
        new_rows = khidi.rows_from_statements(
            hospital_id,
            statements,
            fetched_at=fetched_at,
            source_urls={s.statement: f"{khidi.HASPA_BASE_URL}/total-public-inq (엑셀다운로드)" for s in statements},
        )
        rows.extend(new_rows)
        report.loaded.append((hospital_id, year, f"file {len(new_rows)}계정"))
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fetch", action="store_true", help="haspa.khidi.or.kr에서 직접 가져온다")
    mode.add_argument("--from-raw", action="store_true", help="저장된 원본 JSON만 다시 읽는다")
    mode.add_argument("--file", type=Path, action="append", help="내려받은 .xls 또는 저장한 JSON")
    parser.add_argument("--years", default=f"{DEFAULT_YEARS[0]}-{DEFAULT_YEARS[-1]}")
    parser.add_argument("--hospital", help="--fetch: 병원 ID만; --file: 파일의 병원 이름")
    parser.add_argument("--csv", type=Path, default=khidi.DEFAULT_FINANCIAL_CSV)
    parser.add_argument("--raw-dir", type=Path, default=khidi.DEFAULT_RAW_DIR)
    parser.add_argument("--master", type=Path, default=master_service.DEFAULT_MASTER_FILE)
    args = parser.parse_args(argv)

    master = master_service.load_hospital_master(args.master)
    report = ImportReport()
    if args.fetch:
        ids = [args.hospital] if args.hospital else []
        new_rows = fetch(master, ids, parse_years(args.years), args.raw_dir, report)
    elif args.from_raw:
        new_rows = from_raw(master, args.raw_dir, report)
    else:
        new_rows = from_files(master, args.file, args.hospital, report)

    existing = khidi.load_financial_csv(args.csv)
    merged = khidi.merge_rows(existing, new_rows)
    khidi.write_financial_csv(merged, args.csv)
    report.print()
    print(f"rows: before={len(existing)} after={len(merged)} csv={args.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
