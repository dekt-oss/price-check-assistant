"""전국 유사 규모 병원 찾기 (병원 경영 Benchmark).

    python -m purchase_price.scripts.discover_size_peers --min-beds 700 --max-beds 850

1. Reads the whole KHIDI disclosure list for ``--list-year`` (about 1,100 institutions) and keeps
   상급종합병원 / 종합병원 whose disclosed bed count is within the range.
2. Adds the ones not yet in ``data/hospital_master.json`` as ``group: "size_peer"`` hospitals
   (name, 시도, 종별, 설립형태, disclosed bed count and year, KHIDI code). Existing hospitals only get
   their ``disclosed_bed_count`` filled in. Nothing is estimated: a field the disclosure does not
   show stays empty.
3. Fetches each hospital's income statement and balance sheet for ``--years`` by KHIDI code, keeps
   the raw JSON under ``data/khidi_raw/`` and merges the accounts into ``data/hospital_financial.csv``
   (same importer path as the eight core hospitals, so ``import_hospital_financials --from-raw``
   reproduces it).
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from purchase_price.scripts.import_hospital_financials import parse_years
from purchase_price.services import hospital_master as master_service
from purchase_price.services import khidi_financials as khidi

DEFAULT_KINDS = ("상급종합병원", "종합병원")
_LEGAL_WORDS = ("학교법인", "의료법인", "재단법인", "사회복지법인", "사단법인", "공립", "(학교법인)", "(의)", "(재)")
_FOUNDATION_TOKEN = re.compile(r".*(재단|학원|교육재단|유지재단|의료재단|법인)$")
SHORT_NAME_OVERRIDES = {
    "재단법인예수병원유지재단예수병원": "예수병원",
    "의료법인한성재단포항세명기독병원": "포항세명기독병원",
    "학교법인성균관대학삼성창원병원": "삼성창원병원",
    "의료법인 온그룹의료재단 온종합병원": "온종합병원",
    "연세대학교의과대학 강남세브란스병원": "강남세브란스병원",
    "연세대학교 원주세브란스기독병원": "원주세브란스기독병원",
    "학교법인 건양교육재단 건양대학교병원": "건양대학교병원",
    "인하대학교의과대학부속병원": "인하대병원",
    "순천향대학교부속부천병원": "순천향대부천병원",
    "고려대학교의과대학부속안산병원": "고려대안산병원",
    "강동경희대학교의대병원": "강동경희대병원",
    "가톨릭대학교의정부성모병원": "의정부성모병원",
    "가톨릭대학교인천성모병원": "인천성모병원",
    "가톨릭대학교 성빈센트병원": "성빈센트병원",
    "가톨릭대학교 은평성모병원": "은평성모병원",
    "국민건강보험공단일산병원": "건보공단 일산병원",
    "서울특별시보라매병원": "보라매병원",
    "한림대학교동탄성심병원": "한림대동탄성심병원",
    "한림대학교성심병원": "한림대성심병원",
}


def short_name(name: str) -> str:
    """A readable label from the disclosed name, e.g. "의료법인 창원한마음병원" -> "창원한마음병원"."""

    text = re.sub(r"\s+", " ", (name or "").strip())
    if text in SHORT_NAME_OVERRIDES:
        return SHORT_NAME_OVERRIDES[text]
    tokens = [t for t in text.split(" ") if t]
    while len(tokens) > 1 and (tokens[0] in _LEGAL_WORDS or _FOUNDATION_TOKEN.match(tokens[0])):
        tokens.pop(0)
    result = " ".join(tokens)
    for word in _LEGAL_WORDS:
        if result.startswith(word) and len(result) > len(word) + 2:
            result = result[len(word):].strip()
    return result.replace("가톨릭대학교 ", "가톨릭대 ").strip() or text


def _info(payload: dict[str, Any]) -> dict[str, Any]:
    body = payload.get("json") if isinstance(payload.get("json"), dict) else {}
    info = body.get("info") if isinstance(body, dict) else None
    return info if isinstance(info, dict) else {}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list-year", type=int, default=2024)
    parser.add_argument("--min-beds", type=int, default=700)
    parser.add_argument("--max-beds", type=int, default=850)
    parser.add_argument("--kinds", default=",".join(DEFAULT_KINDS))
    parser.add_argument("--years", default="2019-2024")
    parser.add_argument("--master", type=Path, default=master_service.DEFAULT_MASTER_FILE)
    parser.add_argument("--csv", type=Path, default=khidi.DEFAULT_FINANCIAL_CSV)
    parser.add_argument("--raw-dir", type=Path, default=khidi.DEFAULT_RAW_DIR)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    kinds = {k.strip() for k in args.kinds.split(",") if k.strip()}
    years = parse_years(args.years)
    master = master_service.load_hospital_master(args.master)
    document = json.loads(args.master.read_text(encoding="utf-8"))
    entries: list[dict[str, Any]] = document["hospitals"]
    by_id = {e["hospital_id"]: e for e in entries}

    with khidi.HaspaClient() as client:
        listings = client.list_all(args.list_year)
        selected = [
            item
            for item in listings
            if item.bed_count is not None
            and args.min_beds <= item.bed_count <= args.max_beds
            and item.kind_name in kinds
        ]
        print(f"{args.list_year} 공시 {len(listings)}곳 중 {args.min_beds}~{args.max_beds}병상 {sorted(kinds)}: {len(selected)}곳")

        # Disclosed bed counts for every core hospital as well (same list, same year).
        for item in listings:
            hospital = khidi.resolve_disclosed_name(master, item.name)
            if hospital is not None and hospital.hospital_id in by_id and item.bed_count is not None:
                entry = by_id[hospital.hospital_id]
                entry["disclosed_bed_count"] = item.bed_count
                entry["disclosed_bed_year"] = args.list_year
                entry.setdefault("khidi_code", item.hos_code)

        new_rows: list[khidi.FinancialRow] = []
        for item in sorted(selected, key=lambda i: -(i.bed_count or 0)):
            existing = khidi.resolve_disclosed_name(master, item.name)
            hospital_id = existing.hospital_id if existing is not None else f"K{item.hos_code}"
            is_new = existing is None and hospital_id not in by_id
            region = ""
            for year in years:
                fetched_at = khidi.now_iso()
                statements: list[khidi.Statement] = []
                for kind in (khidi.STATEMENT_IS, khidi.STATEMENT_SFP):
                    saved = khidi.raw_snapshot_path(args.raw_dir, year, item.hos_code, kind)
                    try:
                        if saved.exists():  # resume: reuse a statement fetched by an earlier run
                            snapshot = json.loads(saved.read_text(encoding="utf-8"))
                            payload, fetched_at = snapshot["payload"], snapshot["fetched_at"]
                        else:
                            payload = client.statement_payload(kind, item.hos_code, year)
                        statement = khidi.parse_haspa_json(payload, kind)
                    except (khidi.KhidiParseError, ValueError) as exc:
                        print(f"  {item.name} {year} {kind}: 없음 ({type(exc).__name__})")
                        continue
                    if not statement.lines:
                        continue
                    region = region or str(_info(payload).get("addressLevel1") or "")
                    statements.append(statement)
                    if not args.dry_run and not saved.exists():
                        khidi.save_raw_snapshot(args.raw_dir, year, item.hos_code, kind, payload, fetched_at)
                if is_new and statements:
                    new_rows.extend(khidi.rows_from_statements(hospital_id, statements, fetched_at=fetched_at))
            if is_new:
                entry = {
                    "hospital_id": hospital_id,
                    "canonical_name": item.name,
                    "short_name": short_name(item.name),
                    "aliases": sorted({short_name(item.name), re.sub(r"\s+", "", item.name)} - {item.name}),
                    "foundation": item.found_name,
                    "network": "",
                    "region": region,
                    "hospital_type": item.kind_name,
                    "ownership": item.found_name,
                    "bed_count": None,
                    "bed_count_as_of": None,
                    "type_verified": False,
                    "group": "size_peer",
                    "disclosed_bed_count": item.bed_count,
                    "disclosed_bed_year": args.list_year,
                    "khidi_code": item.hos_code,
                }
                entries.append(entry)
                by_id[hospital_id] = entry
                print(f"+ {entry['short_name']} ({region}, {item.kind_name}, {item.bed_count}병상)")

    if args.dry_run:
        print("dry-run: 파일을 바꾸지 않았습니다.")
        return 0
    args.master.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    existing_rows = khidi.load_financial_csv(args.csv)
    merged = khidi.merge_rows(existing_rows, new_rows)
    khidi.write_financial_csv(merged, args.csv)
    print(f"병원 명단 {len(entries)}곳, 회계 rows: before={len(existing_rows)} after={len(merged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
