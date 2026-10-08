"""KHIDI 회계정보 공시 parser and importer, against real files downloaded on 2026-10-08."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from purchase_price.scripts import import_hospital_financials as cli
from purchase_price.services import hospital_master as master_service
from purchase_price.services import khidi_financials as khidi

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "khidi"
IS_JSON = FIXTURES / "haspa_is_21100063_2024.json"
SFP_JSON = FIXTURES / "haspa_sfp_21100063_2024.json"
IS_XLS = FIXTURES / "인제대학교부산백병원_손익계산서.xls"
SFP_XLS = FIXTURES / "인제대학교부산백병원_재무상태표.xls"


def _is() -> khidi.Statement:
    return khidi.parse_haspa_json(IS_JSON.read_text(encoding="utf-8"), khidi.STATEMENT_IS)


def _sfp() -> khidi.Statement:
    return khidi.parse_haspa_json(SFP_JSON.read_text(encoding="utf-8"), khidi.STATEMENT_SFP)


def test_json_income_statement_keeps_published_amounts_and_school_fiscal_year() -> None:
    statement = _is()
    assert statement.hos_code == "21100063"
    assert statement.hos_name == "인제대학교부산백병원"
    assert statement.fiscal_year == 2024
    # 학교법인 회계연도: 2024 = 2024-03-01 ~ 2025-02-28
    assert (statement.period_start, statement.period_end) == (date(2024, 3, 1), date(2025, 2, 28))
    mapped = statement.mapped()
    assert mapped["medical_revenue"] == ("의료수익", Decimal("343174249448"))
    assert mapped["labor_cost"][1] == Decimal("172870249328")
    assert mapped["drug_cost"][1] == Decimal("63795872220")
    assert mapped["supply_cost"][1] == Decimal("59443242972")
    assert mapped["medical_profit"][1] == Decimal("-13407302634")
    assert mapped["net_income"][1] == Decimal("5681921676")
    # Only current-period amounts are used; the prior-year column is ignored.
    assert all(v != Decimal("399521805245") for _, v in mapped.values())


def test_json_balance_sheet_maps_balance_lines() -> None:
    statement = _sfp()
    assert statement.period_start is None
    assert statement.period_end == date(2025, 2, 28)
    mapped = statement.mapped()
    assert mapped["total_assets"][1] == Decimal("257618963131")
    assert mapped["total_equity"][1] == Decimal("-422633912")
    assert mapped["current_long_term_debt"][1] == Decimal("3878009971")
    assert set(mapped) == {a.key for a in khidi.HASPA_ACCOUNTS if a.statement == khidi.STATEMENT_SFP}


def test_xls_download_parses_to_the_same_numbers_as_json() -> None:
    xls_is = khidi.parse_haspa_xls(IS_XLS)
    xls_sfp = khidi.parse_haspa_xls(SFP_XLS)
    assert xls_is.hos_name == "인제대학교부산백병원"
    assert (xls_is.statement, xls_is.fiscal_year) == (khidi.STATEMENT_IS, 2024)
    assert (xls_sfp.statement, xls_sfp.fiscal_year) == (khidi.STATEMENT_SFP, 2024)
    assert xls_is.period_start == date(2024, 3, 1)
    assert xls_is.mapped() == _is().mapped()
    assert xls_sfp.mapped() == _sfp().mapped()


def test_error_payload_is_rejected() -> None:
    with pytest.raises(khidi.KhidiParseError):
        khidi.parse_haspa_json({"result": "fail", "msg": "x"}, khidi.STATEMENT_IS)


def test_rows_use_income_period_and_fall_back_to_balance_date() -> None:
    rows = khidi.rows_from_statements("H-BUSAN-PAIK", [_is(), _sfp()], fetched_at="2026-10-08T00:00:00+09:00")
    assert len(rows) == 24  # 23 accounts + 병상수(공시 일반현황)
    assert {(r.fiscal_period_start, r.fiscal_period_end) for r in rows} == {(date(2024, 3, 1), date(2025, 2, 28))}
    assert {r.account_code for r in rows} <= set(khidi.ACCOUNT_LABELS)
    revenue = next(r for r in rows if r.account_code == "medical_revenue")
    assert revenue.source_url == "https://haspa.khidi.or.kr/api/total-is/21100063?y=2024"

    # An income statement whose end date does not exist (동아대 2024: 2025-02-29) keeps the
    # published start and takes the balance-sheet date as the end.
    broken = khidi.Statement(**{**_is().__dict__, "period_end": None})
    rows = khidi.rows_from_statements("H-X", [broken, _sfp()], fetched_at="t")
    assert {(r.fiscal_period_start, r.fiscal_period_end) for r in rows} == {(date(2024, 3, 1), date(2025, 2, 28))}


def test_merge_is_idempotent_and_keeps_first_fetch_time(tmp_path: Path) -> None:
    csv_path = tmp_path / "fin.csv"
    first = khidi.rows_from_statements("H-BUSAN-PAIK", [_is(), _sfp()], fetched_at="2026-10-08T01:00:00+09:00")
    khidi.write_financial_csv(khidi.merge_rows([], first), csv_path)
    before = csv_path.read_bytes()
    again = khidi.rows_from_statements("H-BUSAN-PAIK", [_is(), _sfp()], fetched_at="2026-10-09T01:00:00+09:00")
    khidi.write_financial_csv(khidi.merge_rows(khidi.load_financial_csv(csv_path), again), csv_path)
    assert csv_path.read_bytes() == before
    loaded = khidi.load_financial_csv(csv_path)
    assert len(loaded) == 24 and loaded[0].fetched_at == "2026-10-08T01:00:00+09:00"


def test_search_html_listing_and_legal_prefix_resolution() -> None:
    html = (
        '<div class="row"><div><input type="checkbox" name="pi" value="21100063" data-year="2017"></div>'
        '<div class="col-md-1 hidden-sm hidden-xs text-center">1</div>'
        '<div class="col-md-1 hidden-sm col-xs-3 text-center board_year">2017</div>'
        '<div class="col-md-3 col-sm-3 col-xs-9  board_name text-overflow"><span>(학교법인)인제대학교부산백병원</span></div>'
        '<div class="col-md-1 col-sm-1 hidden-xs text-center">878</div>'
        '<div class="col-md-1 col-sm-1 hidden-xs text-center">부산</div>'
        '<div class="col-md-1 col-sm-2 hidden-xs text-center no-padding">상급종합병원</div>'
        '<div class="col-md-1 col-sm-2 hidden-xs text-center no-padding">학교법인</div></div>'
    )
    (listing,) = khidi.parse_search_html(html)
    assert (listing.hos_code, listing.fiscal_year, listing.bed_count) == ("21100063", 2017, 878)
    master = master_service.load_hospital_master()
    assert master.resolve(listing.name) is None
    assert khidi.resolve_disclosed_name(master, listing.name).hospital_id == "H-BUSAN-PAIK"
    assert khidi.resolve_disclosed_name(master, "양산부산대학교병원").hospital_id == "H-PNUYH"
    assert khidi.resolve_disclosed_name(master, "(학교법인)어느대학교병원") is None


def test_cli_imports_downloaded_files_twice_without_change(tmp_path: Path, capsys) -> None:
    csv_path = tmp_path / "fin.csv"
    args = ["--file", str(IS_XLS), "--file", str(SFP_XLS), "--csv", str(csv_path)]
    assert cli.main(args) == 0
    first = csv_path.read_text(encoding="utf-8")
    assert "H-BUSAN-PAIK,2024,2024-03-01,2025-02-28,medical_revenue,의료수익,343174249448" in first
    assert cli.main(args) == 0
    assert csv_path.read_text(encoding="utf-8") == first
    assert "loaded  H-BUSAN-PAIK 2024" in capsys.readouterr().out


def test_cli_from_raw_reparses_saved_snapshots(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    for statement, path in ((khidi.STATEMENT_IS, IS_JSON), (khidi.STATEMENT_SFP, SFP_JSON)):
        khidi.save_raw_snapshot(raw_dir, 2024, "21100063", statement, json.loads(path.read_text(encoding="utf-8")), "2026-10-08T20:00:00+09:00")
    csv_path = tmp_path / "fin.csv"
    assert cli.main(["--from-raw", "--raw-dir", str(raw_dir), "--csv", str(csv_path)]) == 0
    rows = khidi.load_financial_csv(csv_path)
    assert len(rows) == 24  # 23 accounts + 병상수(공시 일반현황)
    assert {r.fetched_at for r in rows} == {"2026-10-08T20:00:00+09:00"}


def test_committed_csv_only_uses_known_account_keys() -> None:
    rows = khidi.load_financial_csv()
    assert rows, "data/hospital_financial.csv should be committed"
    assert {r.account_code for r in rows} <= set(khidi.ACCOUNT_LABELS)
    assert all(r.source == khidi.SOURCE_KHIDI and r.source_url.startswith(khidi.HASPA_BASE_URL) for r in rows)
    assert all(r.fetched_at for r in rows)


def test_parse_years() -> None:
    assert cli.parse_years("2016-2018,2024") == (2016, 2017, 2018, 2024)
