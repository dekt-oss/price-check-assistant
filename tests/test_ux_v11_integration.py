"""UX v1.1 integration (I0-a): home recent searches, track boundaries, deployment marker.

Owned by the integration step (docs/coordination/UX_V11_OWNERSHIP.md). The boundary test keeps the
two parallel tracks from importing each other's modules, so either can change without breaking the
other; the home page and the shared modules are the only places that read both.
"""

from __future__ import annotations

import ast
import importlib
import pathlib
import re
from datetime import UTC, datetime

import pytest

AppTest = importlib.import_module("streamlit.testing.v1").AppTest
ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "purchase_price"

# Track H (news & management) code, by path.
TRACK_H_FILES = (
    *(SRC / "services").glob("news_*.py"),
    *(SRC / "services").glob("hospital_*.py"),
    SRC / "services" / "khidi_financials.py",
    SRC / "services" / "alio_disclosure.py",
    SRC / "services" / "hira_hospital_info.py",
    SRC / "clients" / "naver_news.py",
    SRC / "ui" / "benchmark_charts.py",
    ROOT / "pages" / "20_병원_News_Radar.py",
    ROOT / "pages" / "21_병원_경영_Benchmark.py",
)
TRACK_H_MODULE = re.compile(
    r"^purchase_price\.(services\.(news_\w+|hospital_\w+|khidi_financials|alio_disclosure|hira_hospital_info)"
    r"|clients\.naver_news|ui\.benchmark_charts)$"
)
# Track P (price) modules Track H must not import.
TRACK_P_MODULE = re.compile(
    r"^purchase_price\.(services\.(track_b_\w+|g2b_\w+|mfds_\w+|price_\w+|pricing|quote_\w+|category_market"
    r"|market_\w+|purchase_\w+|product_matching|matching|search\w*)|ui\.(result_\w+|quote_\w+|price_\w+"
    r"|category_market|track_b_\w+|purchase_workspace\w*|device_page|product_identity|market_research))$"
)


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            for alias in node.names:
                found.add(f"{node.module}.{alias.name}")
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def test_track_h_code_does_not_import_price_modules() -> None:
    offenders = {
        str(path.relative_to(ROOT)): sorted(m for m in _imports(path) if TRACK_P_MODULE.match(m))
        for path in TRACK_H_FILES
        if path.exists()
    }
    assert {k: v for k, v in offenders.items() if v} == {}


def test_price_code_does_not_import_track_h_modules() -> None:
    track_h = {path.resolve() for path in TRACK_H_FILES}
    price_files = [
        path
        for path in (*SRC.rglob("*.py"), *(ROOT / "pages").glob("*.py"))
        if path.resolve() not in track_h
        and path.name != "0_홈.py"  # the home page reads both tracks on purpose
        and "scripts" not in path.parts
    ]
    offenders = {
        str(path.relative_to(ROOT)): sorted(m for m in _imports(path) if TRACK_H_MODULE.match(m))
        for path in price_files
    }
    assert {k: v for k, v in offenders.items() if v} == {}


@pytest.fixture(autouse=True)
def _no_remote_news_list(tmp_path, monkeypatch):
    """Point the home at a local stored list that does not exist, so no test downloads the real R2
    index (a developer machine with R2 secrets did, and the home run then overran its timeout)."""

    from purchase_price.config import get_settings

    monkeypatch.setenv("NEWS_RADAR_INDEX_PATH", str(tmp_path / "no-news.json.gz"))
    monkeypatch.delenv("NEWS_RADAR_STATUS_PATH", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _home(recent: object = None) -> AppTest:
    app = AppTest.from_file(str(ROOT / "pages" / "0_홈.py"), default_timeout=60)
    if recent is not None:
        app.session_state["home_recent_searches"] = recent
    app.run()
    assert not app.exception, [str(item.value) for item in app.exception]
    return app


def _html(app: AppTest) -> str:
    return "\n".join(str(block.value) for block in app.markdown)


def test_home_without_searches_keeps_the_plain_price_card() -> None:
    html = _html(_home())
    assert "제품·견적 검색" in html
    assert 'id="home-recent-searches-v1"' not in html
    assert "아직 자동 수집 자료가 없습니다" in html  # a store without a list yet is not an error


def test_home_shows_this_sessions_recent_searches_as_links() -> None:
    html = _html(_home([("PNB-704", "14:05"), ("HeartOn A16-DS", "13:50"), ("M40", "13:40"), ("X", "13:00")]))
    assert "이번 접속 최근 조사" in html
    assert "PNB-704" in html and "14:05 조사 · 모두 4건" in html
    assert 'href="./?q=HeartOn%20A16-DS"' in html
    assert ">X<" not in html  # only the three newest are linked


def test_home_ignores_malformed_recent_state() -> None:
    html = _html(_home(["oops", ("", "1"), None]))
    assert "제품·견적 검색" in html


@pytest.fixture
def stored_news_list(tmp_path, monkeypatch):
    """A local stored list with one 우리병원 issue (two title variants) collected just now."""

    from purchase_price.clients.naver_news import NaverNewsItem
    from purchase_price.config import get_settings
    from purchase_price.services import news_radar as radar
    from purchase_price.services import news_radar_index as nri

    now = datetime.now(UTC).replace(microsecond=0)
    keyword = radar.Keyword("부산백병원", "our_hospital", "우리병원", "immediate")
    titles = ("부산백병원 원내 약 조제 알림톡 서비스 운영", "부산백병원 원내약 조제현황 알림톡 서비스")
    index = nri.NewsRadarIndex()
    nri.collect(
        index,
        [keyword],
        lambda _text, _display: [NaverNewsItem(t, "", f"https://a.kr/{n}", now, "a.kr") for n, t in enumerate(titles)],
        groups=(radar.KeywordGroup("our_hospital", "우리병원", True, (keyword,)),),
        clock=lambda: now,
    )
    path = tmp_path / "news.json.gz"
    nri.LocalNewsRadarStore(path).write_index(index)
    monkeypatch.setenv("NEWS_RADAR_INDEX_PATH", str(path))
    monkeypatch.delenv("NEWS_RADAR_STATUS_PATH", raising=False)
    get_settings.cache_clear()
    yield index
    get_settings.cache_clear()


def test_home_counts_recent_issues_from_the_stored_list(stored_news_list) -> None:
    html = _html(_home())
    assert "병원 뉴스 · 최근 3일 주요 이슈" in html
    assert ">1건<" in html  # the two title variants are one issue
    assert "기사 2건 이상 묶인 이슈 · 오늘 기사 2건" in html
    assert "새 관심기사" not in html  # session-only numbers are gone once the stored list exists


def test_home_says_so_when_the_stored_list_cannot_be_read(tmp_path, monkeypatch) -> None:
    from purchase_price.config import get_settings

    broken = tmp_path / "news.json.gz"
    broken.write_bytes(b"not gzip")
    monkeypatch.setenv("NEWS_RADAR_INDEX_PATH", str(broken))
    get_settings.cache_clear()
    try:
        html = _html(_home())
    finally:
        get_settings.cache_clear()
    assert "확인 안 됨" in html and "불러오지 못했습니다" in html


def test_home_shows_the_newest_management_briefing() -> None:
    html = _html(_home())
    assert "부산백병원 브리핑" in html
    assert "공시 기준" in html
    assert "지역 경쟁군" in html  # 비교병원 N곳 is written as the peer-group label + count


def test_production_smoke_checks_the_news_and_management_pages() -> None:
    smoke = (ROOT / "scripts" / "production_unified_search_smoke.py").read_text(encoding="utf-8")
    assert "_verify_track_h_pages" in smoke
    assert '"news-radar"' in smoke and '"hospital-benchmark"' in smoke
    assert "주요 이슈" in smoke and "경영 브리핑" in smoke


def test_production_smoke_waits_for_the_current_deployment_marker() -> None:
    dashboard = (ROOT / "pages" / "1_대시보드.py").read_text(encoding="utf-8")
    smoke = (ROOT / "scripts" / "production_unified_search_smoke.py").read_text(encoding="utf-8")
    markers = [int(v) for v in re.findall(r'id="purchase-workspace-runtime-v(\d+)"', dashboard)]
    expected = max(markers)
    assert f'DEPLOYMENT_MARKER = "#purchase-workspace-runtime-v{expected}"' in smoke


def test_production_smoke_waits_for_the_bottom_of_the_result_page() -> None:
    smoke = (ROOT / "scripts" / "production_unified_search_smoke.py").read_text(encoding="utf-8")
    assert "SECTIONS_RENDER_SECONDS" in smoke
    assert "sections_deadline" in smoke
