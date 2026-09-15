"""Validate real R2-derived quote files through extraction and Track B lookup."""

from __future__ import annotations

import argparse
import json
import tempfile
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from purchase_price.config import Settings
from purchase_price.db import Base
from purchase_price.models import TrackBDeliveryLine
from purchase_price.schemas import ProductQuery
from purchase_price.scripts.import_g2b_track_b_r2_to_db import run as import_track_b
from purchase_price.services.quote_extraction import extract_quote_file, quote_item_query
from purchase_price.services.track_b_db_quote_comparison import compare_track_b_quote
from purchase_price.storage.r2_reader import R2RawEvidenceReader

QUOTE_HEADERS = (
    "품명",
    "제조사",
    "모델명",
    "규격",
    "수량",
    "단위",
    "단가",
    "금액",
    "부가세",
)


def write_r2_derived_quote(
    path: Path,
    *,
    row: TrackBDeliveryLine,
    quote_unit_price: Decimal,
) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Quote"
    sheet.append(QUOTE_HEADERS)
    sheet.append(
        (
            row.product_class,
            row.manufacturer,
            row.model_name,
            row.specification,
            1,
            row.unit or "EA",
            quote_unit_price,
            quote_unit_price,
            "포함",
        )
    )
    workbook.save(path)


def _current_searchable_rows(session: Session, *, limit: int) -> list[TrackBDeliveryLine]:
    rows = session.scalars(
        select(TrackBDeliveryLine)
        .where(
            TrackBDeliveryLine.unit_price > 0,
            TrackBDeliveryLine.model_key.is_not(None),
            TrackBDeliveryLine.product_class.is_not(None),
        )
        .order_by(TrackBDeliveryLine.transaction_date.desc(), TrackBDeliveryLine.id.desc())
        .limit(1000)
    ).all()
    selected: list[TrackBDeliveryLine] = []
    seen_models: set[str] = set()
    for row in rows:
        if row.unit_price is None or row.model_key is None or row.model_key in seen_models:
            continue
        quote_price = (row.unit_price * Decimal("1.10")).quantize(Decimal("0.01"))
        comparison = compare_track_b_quote(
            session,
            ProductQuery(
                product_name=row.product_class or "",
                manufacturer=row.manufacturer or "",
                model_name=row.model_name or "",
                specification=row.specification or "",
            ),
            quote_unit_price=quote_price,
        )
        if not comparison.candidates:
            continue
        seen_models.add(row.model_key)
        selected.append(row)
        if len(selected) >= limit:
            break
    return selected


def validate_quote_files(
    session: Session,
    *,
    rows: list[TrackBDeliveryLine],
    output_dir: Path,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    grades: dict[str, int] = {}
    matched = 0
    for index, row in enumerate(rows, start=1):
        assert row.unit_price is not None
        quote_price = (row.unit_price * Decimal("1.10")).quantize(Decimal("0.01"))
        path = output_dir / f"actual-r2-derived-quote-{index:02d}.xlsx"
        write_r2_derived_quote(path, row=row, quote_unit_price=quote_price)
        extraction = extract_quote_file(path)
        if len(extraction.items) != 1:
            raise RuntimeError("R2-derived quote did not extract exactly one item")
        item = extraction.items[0]
        comparison = compare_track_b_quote(
            session,
            quote_item_query(item),
            quote_unit_price=item.unit_price,
        )
        if not comparison.candidates:
            raise RuntimeError("R2-derived quote did not return a Track B candidate")
        grade = comparison.candidates[0].match_grade.value
        grades[grade] = grades.get(grade, 0) + 1
        matched += 1
    return {
        "quote_files_created": len(rows),
        "quote_files_extracted": len(rows),
        "quote_files_matched": matched,
        "match_grades": grades,
    }


def run(*, r2_limit: int, case_count: int, output_dir: Path) -> dict[str, object]:
    if r2_limit < 1 or case_count < 1:
        raise ValueError("limits must be positive")
    database_path = output_dir / "track-b-quote-uat.sqlite"
    output_dir.mkdir(parents=True, exist_ok=True)
    if database_path.exists():
        database_path.unlink()
    engine = create_engine(f"sqlite+pysqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    imported = import_track_b(
        reader=R2RawEvidenceReader.from_settings(Settings()),
        session_factory=factory,
        limit=r2_limit,
    )
    with Session(engine) as session:
        rows = _current_searchable_rows(session, limit=case_count)
        if len(rows) < case_count:
            raise RuntimeError("bounded R2 sample did not contain enough searchable quote rows")
        quote_report = validate_quote_files(session, rows=rows, output_dir=output_dir)
    engine.dispose()
    return {
        "status": "SUCCESS",
        "objects_scanned": imported["objects_scanned"],
        "rows_inserted": imported["inserted"],
        **quote_report,
        "public_api_requests": 0,
        "r2_writes": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--r2-limit", type=int, default=50)
    parser.add_argument("--case-count", type=int, default=5)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.output_dir is None:
        with tempfile.TemporaryDirectory(prefix="track-b-quote-upload-") as directory:
            report = run(
                r2_limit=args.r2_limit,
                case_count=args.case_count,
                output_dir=Path(directory),
            )
    else:
        report = run(
            r2_limit=args.r2_limit,
            case_count=args.case_count,
            output_dir=args.output_dir,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
