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


def _home(recent: object = None) -> AppTest:
    app = AppTest.from_file(str(ROOT / "pages" / "0_홈.py"), default_timeout=20)
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


def test_home_shows_this_sessions_recent_searches_as_links() -> None:
    html = _html(_home([("PNB-704", "14:05"), ("HeartOn A16-DS", "13:50"), ("M40", "13:40"), ("X", "13:00")]))
    assert "이번 접속 최근 조사" in html
    assert "PNB-704" in html and "14:05 조사 · 모두 4건" in html
    assert 'href="./?q=HeartOn%20A16-DS"' in html
    assert ">X<" not in html  # only the three newest are linked


def test_home_ignores_malformed_recent_state() -> None:
    html = _html(_home(["oops", ("", "1"), None]))
    assert "제품·견적 검색" in html


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
