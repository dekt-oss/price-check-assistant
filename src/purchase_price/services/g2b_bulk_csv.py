from __future__ import annotations

import csv
import hashlib
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Protocol, TextIO

from purchase_price.storage.r2 import RawObjectRef

DATASET_ID = "15053481"
REPORT_ID = "UI-ADOXAA-038R"
DATASET_NAME = "조달청_나라장터쇼핑몰 납품요구 물품 내역"
DATASET_URL = "https://www.data.go.kr/data/15053481/fileData.do"
BULK_DOWNLOAD_URL = "https://data.g2b.go.kr/link/AISC001_01/?reptNm=UI-ADOXAA-038R"
DEFAULT_TARGET_SEGMENTS = ("42", "41", "43", "44", "23", "27", "46", "39")

_DETAIL_CODE_ALIASES = ("세부품명", "세부품명번호", "세부물품분류번호", "dtilPrdctClsfcNo")
_APPROVAL_DATE_ALIASES = ("결재일자", "납품요구일자", "계약(납품요구)일자", "approval_date")
_REQUEST_NO_ALIASES = ("납품요구번호", "계약(납품요구)번호", "cntrctDlvrReqNo")
_CHANGE_ORDER_ALIASES = ("납품요구변경차수", "변경차수", "cntrctDlvrReqChgOrd")
_LINE_NO_ALIASES = ("납품요구물품순번", "물품순번", "품목", "prdctSno")
_FROM_RE = re.compile(r"기준일자\(From\)\s*\r?\n\s*(\d{8})")
_TO_RE = re.compile(r"기준일자\(To\)\s*\r?\n\s*(\d{8})")
_OUTPUT_RE = re.compile(r"출력일자\s*:\s*(\d{4}-\d{2}-\d{2})")
_MAX_PREAMBLE_LINES = 500


class BulkCsvContractError(RuntimeError):
    """Raised when the official G2B bulk export cannot be interpreted safely."""


class RawStore(Protocol):
    def put_public_json(self, *, source_operation: str, payload: object) -> RawObjectRef: ...


@dataclass(frozen=True)
class BulkSourceContract:
    encoding: str
    delimiter: str
    header_line: int
    query_begin_date: str
    query_end_date: str
    output_date: str | None


@dataclass(frozen=True)
class BulkGapPlan:
    source_begin_date: str
    source_cutoff_date: str
    requested_end_date: str
    api_gap_begin_date: str | None
    api_gap_end_date: str | None
    strategy: str
    reason: str


@dataclass(frozen=True)
class BulkCsvSummary:
    source_path: str
    source_sha256: str
    source_encoding: str
    source_delimiter: str
    source_query_begin_date: str
    source_query_end_date: str
    retrieved_date: str
    source_cutoff_date: str
    begin_date: str
    end_date: str
    target_segments: tuple[str, ...]
    rows_read: int
    rows_in_scope: int
    distinct_detail_codes: int
    earliest_approval_date: str | None
    latest_approval_date: str | None
    data_chunks_stored: int
    manifest_object_key: str
    r2_objects_created: int
    r2_objects_reused: int
    r2_stored_bytes_created: int
    first_object_key: str | None
    last_object_key: str | None
    gap_plan: BulkGapPlan

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _normalized_header(value: str) -> str:
    return value.replace("\ufeff", "").strip().strip('"')


def _resolve_header(fieldnames: Iterable[str], aliases: tuple[str, ...], label: str) -> str:
    normalized = {_normalized_header(name): name for name in fieldnames if name is not None}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    raise BulkCsvContractError(
        f"Bulk export is missing required {label} column. Expected one of: {', '.join(aliases)}"
    )


def _optional_header(fieldnames: Iterable[str], aliases: tuple[str, ...]) -> str | None:
    normalized = {_normalized_header(name): name for name in fieldnames if name is not None}
    return next((normalized[alias] for alias in aliases if alias in normalized), None)


def detect_csv_encoding(path: Path) -> str:
    with path.open("rb") as handle:
        sample = handle.read(131_072)
    if sample.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    for encoding in ("utf-8-sig", "cp949"):
        try:
            sample.decode(encoding)
        except UnicodeDecodeError:
            continue
        return encoding
    raise BulkCsvContractError("Bulk export must be decodable as UTF-16, UTF-8 or CP949")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_yyyymmdd(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def inspect_bulk_export(path: Path) -> BulkSourceContract:
    encoding = detect_csv_encoding(path)
    preamble_lines: list[str] = []
    delimiter: str | None = None
    header_line: int | None = None
    with path.open("r", encoding=encoding, newline="") as handle:
        for line_no, line in enumerate(handle, start=1):
            normalized = line.replace('"', "")
            if "납품요구번호" in normalized and "세부품명번호" in normalized:
                delimiter = "\t" if "\t" in line else "," if "," in line else None
                header_line = line_no
                break
            preamble_lines.append(line)
            if line_no >= _MAX_PREAMBLE_LINES:
                break
    if header_line is None or delimiter is None:
        raise BulkCsvContractError("Could not locate the G2B bulk export header row")

    preamble = "".join(preamble_lines)
    from_match = _FROM_RE.search(preamble)
    to_match = _TO_RE.search(preamble)
    if not from_match or not to_match:
        raise BulkCsvContractError("Official G2B export must include verified From/To search dates")
    output_match = _OUTPUT_RE.search(preamble)
    return BulkSourceContract(
        encoding=encoding,
        delimiter=delimiter,
        header_line=header_line,
        query_begin_date=_parse_yyyymmdd(from_match.group(1)).isoformat(),
        query_end_date=_parse_yyyymmdd(to_match.group(1)).isoformat(),
        output_date=output_match.group(1) if output_match else None,
    )


def _data_reader(path: Path, contract: BulkSourceContract) -> tuple[TextIO, csv.DictReader]:
    handle = path.open("r", encoding=contract.encoding, newline="")
    try:
        for _ in range(contract.header_line - 1):
            next(handle)
        return handle, csv.DictReader(handle, delimiter=contract.delimiter)
    except Exception:
        handle.close()
        raise


def parse_source_date(value: str) -> date:
    raw = value.strip()
    if not raw:
        raise BulkCsvContractError("Bulk export contains an empty approval date")
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    if len(raw) >= 10:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
            try:
                return datetime.strptime(raw[:10], fmt).date()
            except ValueError:
                continue
    raise BulkCsvContractError(f"Unsupported approval date format: {raw!r}")


def normalize_detail_code(value: str) -> str:
    digits = "".join(ch for ch in value.strip() if ch.isdigit())
    if len(digits) != 10:
        raise BulkCsvContractError(f"Invalid 10-digit detail product code: {value!r}")
    return digits


def build_gap_plan(
    *,
    retrieved_date: date,
    requested_begin: date,
    requested_end: date,
    source_begin: date,
    source_end: date,
) -> BulkGapPlan:
    declared_cutoff = retrieved_date - timedelta(days=1)
    effective_end = min(source_end, declared_cutoff)
    if source_begin > requested_begin:
        raise BulkCsvContractError(
            "Bulk export does not cover the requested historical start: "
            f"source_begin={source_begin.isoformat()} requested_begin={requested_begin.isoformat()}"
        )
    if effective_end < requested_begin:
        raise BulkCsvContractError(
            "Bulk export ends before the requested backfill window begins: "
            f"source_end={effective_end.isoformat()} requested_begin={requested_begin.isoformat()}"
        )
    if requested_end <= effective_end:
        return BulkGapPlan(
            source_begin_date=source_begin.isoformat(),
            source_cutoff_date=effective_end.isoformat(),
            requested_end_date=requested_end.isoformat(),
            api_gap_begin_date=None,
            api_gap_end_date=None,
            strategy="BULK_ONLY",
            reason="Verified source query coverage includes the full requested backfill window.",
        )
    gap_begin = effective_end + timedelta(days=1)
    return BulkGapPlan(
        source_begin_date=source_begin.isoformat(),
        source_cutoff_date=effective_end.isoformat(),
        requested_end_date=requested_end.isoformat(),
        api_gap_begin_date=gap_begin.isoformat(),
        api_gap_end_date=requested_end.isoformat(),
        strategy="RECENT_GAP_ONLY",
        reason=(
            "Use Track B only for the verified post-bulk freshness window and only for exact "
            "10-digit requested/gap codes; never repeat the historical all-code sweep."
        ),
    )


def _stable_source_key(
    row: dict[str, str],
    request_no_column: str | None,
    change_order_column: str | None,
    line_no_column: str | None,
) -> str | None:
    if not request_no_column or not change_order_column or not line_no_column:
        return None
    parts = tuple((row.get(column) or "").strip() for column in (request_no_column, change_order_column, line_no_column))
    return "|".join(parts) if all(parts) else None


def ingest_bulk_csv(
    *,
    path: Path,
    store: RawStore,
    begin: date,
    end: date,
    retrieved_date: date,
    target_segments: tuple[str, ...] = DEFAULT_TARGET_SEGMENTS,
    chunk_size: int = 1000,
) -> BulkCsvSummary:
    if begin > end:
        raise ValueError("begin must not be after end")
    if chunk_size < 1 or chunk_size > 10_000:
        raise ValueError("chunk_size must be between 1 and 10000")
    if not path.is_file():
        raise FileNotFoundError(path)

    contract = inspect_bulk_export(path)
    source_begin = date.fromisoformat(contract.query_begin_date)
    source_end = date.fromisoformat(contract.query_end_date)
    gap_plan = build_gap_plan(
        retrieved_date=retrieved_date,
        requested_begin=begin,
        requested_end=end,
        source_begin=source_begin,
        source_end=source_end,
    )
    source_hash = sha256_file(path)
    segment_set = set(target_segments)

    rows_read = rows_in_scope = data_chunks_stored = 0
    created = reused = created_bytes = 0
    seen_codes: set[str] = set()
    earliest: date | None = None
    latest: date | None = None
    first_key: str | None = None
    last_key: str | None = None
    chunk_rows: list[dict[str, str]] = []
    chunk_first_line = 0

    def flush_chunk(last_line: int) -> None:
        nonlocal data_chunks_stored, created, reused, created_bytes, first_key, last_key
        nonlocal chunk_rows, chunk_first_line
        if not chunk_rows:
            return
        payload = {
            "schema": "g2b-shopping-delivery-bulk-chunk-v2",
            "source": {
                "dataset_id": DATASET_ID,
                "report_id": REPORT_ID,
                "dataset_name": DATASET_NAME,
                "dataset_url": DATASET_URL,
                "source_sha256": source_hash,
                "encoding": contract.encoding,
                "delimiter": "TAB" if contract.delimiter == "\t" else "COMMA",
                "query_begin_date": contract.query_begin_date,
                "query_end_date": contract.query_end_date,
                "output_date": contract.output_date,
                "retrieved_date": retrieved_date.isoformat(),
            },
            "selection": {
                "begin_date": begin.isoformat(),
                "end_date": end.isoformat(),
                "target_segments": list(target_segments),
                "source_line_begin": chunk_first_line,
                "source_line_end": last_line,
            },
            "rows": chunk_rows,
        }
        ref = store.put_public_json(source_operation="g2b-shopping-delivery-bulk-csv-chunk", payload=payload)
        data_chunks_stored += 1
        first_key = first_key or ref.key
        last_key = ref.key
        if ref.created:
            created += 1
            created_bytes += ref.stored_bytes
        else:
            reused += 1
        chunk_rows = []
        chunk_first_line = 0

    handle, reader = _data_reader(path, contract)
    try:
        if not reader.fieldnames:
            raise BulkCsvContractError("Bulk export has no header row")
        detail_column = _resolve_header(reader.fieldnames, _DETAIL_CODE_ALIASES, "detail code")
        approval_column = _resolve_header(reader.fieldnames, _APPROVAL_DATE_ALIASES, "approval date")
        request_column = _optional_header(reader.fieldnames, _REQUEST_NO_ALIASES)
        change_column = _optional_header(reader.fieldnames, _CHANGE_ORDER_ALIASES)
        line_column = _optional_header(reader.fieldnames, _LINE_NO_ALIASES)
        detail_key = _normalized_header(detail_column)
        approval_key = _normalized_header(approval_column)
        request_key = _normalized_header(request_column) if request_column else None
        change_key = _normalized_header(change_column) if change_column else None
        line_key = _normalized_header(line_column) if line_column else None

        for source_line, raw_row in enumerate(reader, start=contract.header_line + 1):
            rows_read += 1
            row = {
                _normalized_header(str(key)): "" if value is None else str(value).strip()
                for key, value in raw_row.items()
                if key is not None
            }
            raw_code = row.get(detail_key, "")
            if not raw_code.strip():
                continue
            try:
                detail_code = normalize_detail_code(raw_code)
            except BulkCsvContractError:
                continue
            if detail_code[:2] not in segment_set:
                continue
            approval_date = parse_source_date(row.get(approval_key, ""))
            if approval_date < begin or approval_date > end:
                continue
            row["_normalized_detail_code"] = detail_code
            row["_normalized_approval_date"] = approval_date.isoformat()
            stable_key = _stable_source_key(row, request_key, change_key, line_key)
            if stable_key:
                row["_stable_source_key"] = stable_key
            if not chunk_rows:
                chunk_first_line = source_line
            chunk_rows.append(row)
            rows_in_scope += 1
            seen_codes.add(detail_code)
            earliest = approval_date if earliest is None else min(earliest, approval_date)
            latest = approval_date if latest is None else max(latest, approval_date)
            if len(chunk_rows) >= chunk_size:
                flush_chunk(source_line)
        flush_chunk(contract.header_line + rows_read)
    finally:
        handle.close()

    manifest_payload = {
        "schema": "g2b-shopping-delivery-bulk-manifest-v2",
        "dataset_id": DATASET_ID,
        "report_id": REPORT_ID,
        "dataset_url": DATASET_URL,
        "bulk_download_url": BULK_DOWNLOAD_URL,
        "source_sha256": source_hash,
        "source_encoding": contract.encoding,
        "source_delimiter": "TAB" if contract.delimiter == "\t" else "COMMA",
        "source_query_begin_date": contract.query_begin_date,
        "source_query_end_date": contract.query_end_date,
        "source_output_date": contract.output_date,
        "retrieved_date": retrieved_date.isoformat(),
        "source_cutoff_date": gap_plan.source_cutoff_date,
        "begin_date": begin.isoformat(),
        "end_date": end.isoformat(),
        "target_segments": list(target_segments),
        "rows_read": rows_read,
        "rows_in_scope": rows_in_scope,
        "distinct_detail_codes": len(seen_codes),
        "earliest_approval_date": earliest.isoformat() if earliest else None,
        "latest_approval_date": latest.isoformat() if latest else None,
        "data_chunks_stored": data_chunks_stored,
        "gap_plan": asdict(gap_plan),
    }
    manifest_ref = store.put_public_json(
        source_operation="g2b-shopping-delivery-bulk-csv-manifest",
        payload=manifest_payload,
    )
    first_key = first_key or manifest_ref.key
    last_key = manifest_ref.key
    if manifest_ref.created:
        created += 1
        created_bytes += manifest_ref.stored_bytes
    else:
        reused += 1

    return BulkCsvSummary(
        source_path=str(path),
        source_sha256=source_hash,
        source_encoding=contract.encoding,
        source_delimiter="TAB" if contract.delimiter == "\t" else "COMMA",
        source_query_begin_date=contract.query_begin_date,
        source_query_end_date=contract.query_end_date,
        retrieved_date=retrieved_date.isoformat(),
        source_cutoff_date=gap_plan.source_cutoff_date,
        begin_date=begin.isoformat(),
        end_date=end.isoformat(),
        target_segments=target_segments,
        rows_read=rows_read,
        rows_in_scope=rows_in_scope,
        distinct_detail_codes=len(seen_codes),
        earliest_approval_date=earliest.isoformat() if earliest else None,
        latest_approval_date=latest.isoformat() if latest else None,
        data_chunks_stored=data_chunks_stored,
        manifest_object_key=manifest_ref.key,
        r2_objects_created=created,
        r2_objects_reused=reused,
        r2_stored_bytes_created=created_bytes,
        first_object_key=first_key,
        last_object_key=last_key,
        gap_plan=gap_plan,
    )
