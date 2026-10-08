from __future__ import annotations

import json
import shutil
from decimal import Decimal
from pathlib import Path

from purchase_price.scripts import import_alio_disclosure as cli
from purchase_price.services import alio_disclosure as alio
from purchase_price.ui.result_summary import has_banned_term

FIXTURES = Path(__file__).parent / "fixtures" / "alio"


def _doc(root_no: str) -> dict:
    path = next(FIXTURES.glob(f"C0071_{root_no}_*.json"))
    return json.loads(path.read_text(encoding="utf-8"))


def _values(rows: list[alio.AlioRow], code: str) -> dict[int, str]:
    return {row.fiscal_year: row.value for row in rows if row.item_code == code}


def test_headcount_report_parses_real_published_numbers() -> None:
    rows = alio.rows_from_raw(_doc("2020"))
    assert _values(rows, "regular_quota")[2021] == "6508"
    assert _values(rows, "regular_actual")[2025] == "6220"
    assert _values(rows, "female_actual")[2021] == "4325"
    assert _values(rows, "outsourced_actual")[2024] == "322"
    latest = [r for r in rows if r.item_code == "headcount_quota_total" and r.fiscal_year == 2026]
    assert latest[0].value == "7138"
    assert "2분기 말" in latest[0].item_name  # the partial year says so


def test_income_statement_keeps_signs_and_units() -> None:
    rows = alio.rows_from_raw(_doc("3130"))
    assert _values(rows, "net_income")[2024] == "-65642"
    assert _values(rows, "revenue")[2025] == "990965"
    assert _values(rows, "net_margin")[2021] == "4.2"
    assert {r.unit for r in rows if r.item_code == "revenue"} == {"백만원"}
    assert all(r.scope == "법인" and r.hospital_id == "H-PNUH" for r in rows)


def test_new_hire_partial_year_is_labelled_as_running_total_and_dash_is_skipped() -> None:
    rows = alio.rows_from_raw(_doc("2040"))
    assert _values(rows, "new_hire_regular")[2025] == "879"
    assert "누적" in next(r.item_name for r in rows if r.item_code == "new_hire_regular" and r.fiscal_year == 2026)
    # a "-" cell means not applicable and is never stored as a number
    assert not [r for r in rows if r.item_code == "new_hire_regular" and r.value in ("", "-")]


def test_rebuild_from_the_same_raw_files_is_byte_identical(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    shutil.copytree(FIXTURES, raw_dir)
    csv_path = tmp_path / "alio.csv"
    assert cli.main(["--from-raw", "--raw-dir", str(raw_dir), "--csv", str(csv_path)]) == 0
    first = csv_path.read_bytes()
    assert cli.main(["--from-raw", "--raw-dir", str(raw_dir), "--csv", str(csv_path)]) == 0
    assert csv_path.read_bytes() == first
    header = first.decode("utf-8").splitlines()[0].split(",")
    assert header == list(alio.CSV_COLUMNS)


def test_unchanged_download_keeps_first_fetch_time(tmp_path: Path) -> None:
    doc = _doc("3130")
    alio.save_raw(tmp_path, doc["apba_id"], doc["root_no"], doc["disclosure_no"], doc["html"], "2026-10-08T00:00:00+09:00")
    path = alio.save_raw(tmp_path, doc["apba_id"], doc["root_no"], doc["disclosure_no"], doc["html"], "2026-10-09T00:00:00+09:00")
    assert json.loads(path.read_text(encoding="utf-8"))["fetched_at"] == "2026-10-08T00:00:00+09:00"


def test_rows_for_both_pusan_hospitals_share_one_corporate_set(tmp_path: Path) -> None:
    csv_path = tmp_path / "alio.csv"
    alio.write_alio_csv(alio.merge_rows(alio.rows_from_raw(_doc("3130"))), csv_path)
    own = alio.alio_rows_for("H-PNUH", csv_path)
    assert own and own == alio.alio_rows_for("H-PNUYH", csv_path)
    assert alio.alio_rows_for("H-DAUH", csv_path) == []
    assert isinstance(own[0]["value"], Decimal)
    table = alio.alio_table_for("H-PNUH", csv_path)
    assert table[0]["항목"] == "매출" and table[0]["2021년"] == Decimal("928106")


def test_scope_note_is_plain_korean() -> None:
    assert "양산" in alio.ALIO_SCOPE_NOTE
    assert has_banned_term(alio.ALIO_SCOPE_NOTE) is None
    for spec in alio.REPORT_SPECS:
        for item in spec.items:
            assert has_banned_term(item.name) is None
