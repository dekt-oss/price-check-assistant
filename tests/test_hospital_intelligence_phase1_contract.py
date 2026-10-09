"""Phase 1 contract for the integrated home, News Radar and Benchmark screens."""

from __future__ import annotations

import importlib.machinery
from pathlib import Path

import sqlalchemy as sa
from alembic.config import Config

from alembic import command
from purchase_price import models
from purchase_price.config import get_settings
from purchase_price.ui import result_summary as rs

REPO_ROOT = Path(__file__).resolve().parents[1]
# Same helper as tests/test_simple_result_ui_contract.py; tests is not a package, so it is
# loaded by path instead of imported.
_screen_strings = importlib.machinery.SourceFileLoader(
    "simple_result_ui_contract", str(REPO_ROOT / "tests" / "test_simple_result_ui_contract.py")
).load_module()._screen_strings
HOME = REPO_ROOT / "Home.py"
NEW_PAGES = (
    REPO_ROOT / "pages" / "0_홈.py",
    REPO_ROOT / "pages" / "20_병원_News_Radar.py",
    REPO_ROOT / "pages" / "21_병원_경영_Benchmark.py",
)


def test_root_url_still_opens_the_price_search() -> None:
    source = HOME.read_text(encoding="utf-8")
    assert 'st.Page("pages/1_대시보드.py", title="가격 조사", icon="🔎", default=True)' in source
    assert 'url_path="home"' in source
    assert 'url_path="news-radar"' in source
    assert 'url_path="hospital-benchmark"' in source
    for label in ("홈", "가격 조사", "견적서 검토", "의료기기 허가·안전", "병원 뉴스", "병원 경영 비교"):
        assert f'label="{label}"' in source


def test_home_uses_the_app_name_and_the_new_menu_names() -> None:
    source = (REPO_ROOT / "pages" / "0_홈.py").read_text(encoding="utf-8")
    assert "page_header_html(APP_NAME" in source
    for old in ("AI Hospital Intelligence", "구매가격 조사", "News Radar", "Benchmark 열기", "병원 경영 Benchmark"):
        assert old not in source
    for name in ("가격 조사", "견적서 검토", "의료기기 허가·안전", "병원 뉴스", "병원 경영 비교"):
        assert f'"{name}"' in source
    # two groups, in the same order as the sidebar
    assert source.index("구매 업무") < source.index("병원 경영 정보")
    for target in (
        "pages/1_대시보드.py",
        "pages/2_견적_검토.py",
        "pages/4_의료기기_조회.py",
        "pages/20_병원_News_Radar.py",
        "pages/21_병원_경영_Benchmark.py",
    ):
        assert f'"{target}"' in source
        assert (REPO_ROOT / target).exists()


def test_new_screens_use_plain_words() -> None:
    offenders = [
        (page.name, line, text)
        for page in NEW_PAGES
        for line, text in _screen_strings(page.read_text(encoding="utf-8"))
        if rs.has_banned_term(text)
    ]
    assert offenders == []


def test_news_radar_page_never_passes_naver_results_to_ai() -> None:
    source = (REPO_ROOT / "pages" / "20_병원_News_Radar.py").read_text(encoding="utf-8")
    for forbidden in ("anthropic", "openai", "llm", "description"):
        assert forbidden not in source.casefold()


def test_hospital_intelligence_tables_migrate_and_downgrade(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'hi.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = Config(str(REPO_ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    engine = sa.create_engine(database_url)
    inspector = sa.inspect(engine)
    expected = {
        "hospital_master": models.HospitalMasterRecord,
        "hospital_financial": models.HospitalFinancial,
        "hospital_metric": models.HospitalMetric,
        "news_keyword": models.NewsKeyword,
        "news_item": models.NewsItem,
        "data_source_log": models.DataSourceLog,
    }
    for table, model in expected.items():
        assert table in inspector.get_table_names()
        assert {column["name"] for column in inspector.get_columns(table)} == set(
            model.__table__.columns.keys()
        ), table
    uniques = {u["name"] for u in inspector.get_unique_constraints("hospital_financial")}
    assert "uq_hospital_financial_account" in uniques
    command.downgrade(config, "0004_track_b_delivery_conditions")
    assert "hospital_master" not in sa.inspect(engine).get_table_names()
    engine.dispose()
    get_settings.cache_clear()
