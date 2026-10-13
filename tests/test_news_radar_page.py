"""News Radar page reads a stored list (local file override) and keeps statuses."""

from __future__ import annotations

import importlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from purchase_price.clients.naver_news import NaverNewsItem
from purchase_price.config import get_settings
from purchase_price.services import news_radar as radar
from purchase_price.services import news_radar_index as nri

AppTest = importlib.import_module("streamlit.testing.v1").AppTest
PAGE = Path(__file__).resolve().parents[1] / "pages" / "20_병원_News_Radar.py"
FINISHED = datetime(2026, 10, 8, 10, 48, tzinfo=UTC)  # 19:48 KST


@pytest.fixture
def stored_list(tmp_path, monkeypatch):
    index_path = tmp_path / "news.json.gz"
    keyword = radar.Keyword("부산백병원", "our_hospital", "우리병원", "immediate")
    failing = radar.Keyword("병원 AI 도입", "ai_digital", "AI·디지털", "daily")
    index = nri.NewsRadarIndex()

    def search(text, display):
        if text == failing.text:
            from purchase_price.clients.naver_news import NaverNewsClientError

            raise NaverNewsClientError("NAVER 뉴스 검색 오류 HTTP 500", status_code=500)
        titles = (
            "부산백병원 원내 약 조제 알림톡 서비스 운영",
            "부산백병원 원내약 조제현황 알림톡 서비스",
            "약 나왔어요 부산백병원 조제 알림톡 운영",
        )
        return [
            NaverNewsItem(title, "", f"https://a.kr/{n}", FINISHED, "a.kr")
            for n, title in enumerate(titles)
        ]

    groups = (
        radar.KeywordGroup("our_hospital", "우리병원", True, (keyword,)),
        radar.KeywordGroup("ai_digital", "AI·디지털", True, (failing,)),
    )
    nri.collect(index, [keyword, failing], search, groups=groups, clock=lambda: FINISHED)
    nri.LocalNewsRadarStore(index_path).write_index(index)
    monkeypatch.setenv("NEWS_RADAR_INDEX_PATH", str(index_path))
    monkeypatch.delenv("NEWS_RADAR_STATUS_PATH", raising=False)
    get_settings.cache_clear()
    yield index_path
    get_settings.cache_clear()


def _run() -> AppTest:
    app = AppTest.from_file(str(PAGE), default_timeout=30)
    app.run()
    assert [item.value for item in app.exception] == []
    return app


def _captions(app: AppTest) -> list[str]:
    return [item.value for item in app.caption]


def test_page_shows_stored_articles_and_collection_status_in_korean_time(stored_list) -> None:
    app = _run()
    captions = _captions(app)
    status = next(text for text in captions if text.startswith("자동 수집 상태"))
    assert "19:48" in status  # 10:48 UTC, shown as Korean time
    assert "키워드 2개 중 1개 확인" in status and "확인 못 한 키워드: 병원 AI 도입" in status
    assert "읽음·중요 표시의 저장 연결 상태는 표시를 처음 바꿀 때 확인됩니다." in captions
    assert len(app.selectbox) == 3
    assert any("**NEW** 10-08 19:48" == item.value for item in app.markdown)
    assert all("HTTP 500" not in warning.value for warning in app.warning)
    assert all("HTTP 500" not in caption for caption in captions)


def test_page_presents_a_simple_primary_news_workflow(stored_list) -> None:
    app = _run()

    assert app.title[0].value == "병원 뉴스"
    assert [metric.label for metric in app.metric] == ["새 기사", "오늘 기사", "마지막 확인"]
    assert app.button[0].label == "새 기사 확인"
    assert app.subheader[0].value == "오늘의 주요 이슈"
    assert any("관련 기사 3건" in expander.label for expander in app.expander)
    assert [expander.label for expander in app.expander if expander.label in {"관심 키워드 설정", "상세 필터"}] == [
        "관심 키워드 설정",
        "상세 필터",
    ]
    assert any("문자·이메일 알림 준비 중" in item.value for item in app.info)


def test_page_explains_how_to_get_issues_when_old_index_has_none(stored_list) -> None:
    store = nri.LocalNewsRadarStore(stored_list)
    index = store.read_index()
    assert index is not None
    index.issues = ()
    store.write_index(index)

    app = _run()

    assert any("다음 자동 확인" in item.value for item in app.info)


def test_status_survives_a_new_session(stored_list) -> None:
    app = _run()
    app.selectbox[0].set_value(radar.STATUS_IMPORTANT).run()
    saved = nri.LocalNewsRadarStore(stored_list).read_statuses()
    assert [value["status"] for value in saved.values()] == [radar.STATUS_IMPORTANT]

    again = _run()
    assert sorted(box.value for box in again.selectbox) == ["important", "new", "new"]
    assert again.metric[0].value == "2건"


def test_status_falls_back_to_this_session_when_saving_fails(stored_list, monkeypatch) -> None:
    def refuse(self, statuses, *, now):
        raise PermissionError("read-only")

    monkeypatch.setattr(nri.LocalNewsRadarStore, "write_statuses", refuse)
    app = _run()
    app.selectbox[0].set_value(radar.STATUS_READ).run()
    assert "읽음·중요 표시는 이 화면을 연 동안만 유지됩니다 (저장 권한이 없는 연결)." in _captions(app)
    assert sorted(box.value for box in app.selectbox) == ["new", "new", "read"]


def test_sort_explanation_follows_the_chosen_sort(stored_list) -> None:
    app = _run()
    assert any(text.startswith("중요도순:") for text in _captions(app))

    sort_radio = next(radio for radio in app.radio if radio.label == "정렬")
    sort_radio.set_value("최신순").run()
    captions = _captions(app)
    assert any(text.startswith("최신순: 기사가 나온 시간이 최근인 것부터") for text in captions)
    assert not any(text.startswith("중요도순:") for text in captions)


def test_page_uses_neutral_title_mismatch_wording() -> None:
    source = PAGE.read_text(encoding="utf-8")

    assert "본문에서만 언급" not in source
    assert "제목에 키워드 없음" in source
