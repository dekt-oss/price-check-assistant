from __future__ import annotations

import json

import httpx
import pytest

from purchase_price.clients.naver_news import (
    NaverNewsClient,
    NaverNewsClientError,
    clean_title,
    parse_news_payload,
    source_domain,
)

SAMPLE = {
    "lastBuildDate": "Wed, 08 Oct 2026 09:15:00 +0900",
    "total": 2,
    "items": [
        {
            "title": "<b>부산백병원</b>, 중환자실 &amp; 병상 확충",
            "originallink": "https://www.example-news.co.kr/news/view?id=123&utm_source=naver",
            "link": "https://n.news.naver.com/mnews/article/001/0001",
            "description": "본문 요약은 사용하지 않는다.",
            "pubDate": "Wed, 08 Oct 2026 08:42:00 +0900",
        },
        {
            "title": "두 번째 기사",
            "originallink": "",
            "link": "https://n.news.naver.com/mnews/article/002/0002",
            "pubDate": "not a date",
        },
        {"title": "링크 없는 항목은 건너뛴다"},
    ],
}


def test_clean_title_strips_highlight_tags_and_entities() -> None:
    assert clean_title("<b>부산백병원</b>, 중환자실 &amp; 병상 확충") == "부산백병원, 중환자실 & 병상 확충"


def test_source_domain_drops_www() -> None:
    assert source_domain("https://www.example-news.co.kr/news/view?id=1") == "example-news.co.kr"


def test_parse_news_payload_keeps_only_display_fields() -> None:
    items = parse_news_payload(SAMPLE)
    assert [item.title for item in items] == ["부산백병원, 중환자실 & 병상 확충", "두 번째 기사"]
    first, second = items
    assert first.article_url.startswith("https://www.example-news.co.kr/")
    assert first.published_at is not None and first.published_at.hour == 8
    assert first.source_domain == "example-news.co.kr"
    assert second.article_url == second.link
    assert second.published_at is None
    assert not hasattr(first, "description")


def test_client_sends_headers_and_parses_response() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=SAMPLE)

    with NaverNewsClient("id-1", "secret-1", transport=httpx.MockTransport(handler)) as client:
        items = client.search("부산백병원", display=500)
    assert len(items) == 2
    assert seen["headers"]["x-naver-client-id"] == "id-1"
    assert seen["headers"]["x-naver-client-secret"] == "secret-1"
    assert seen["params"] == {"query": "부산백병원", "display": "100", "start": "1", "sort": "date"}


def test_client_error_never_includes_secret() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"errorMessage": "bad", "errorCode": "024"})

    with NaverNewsClient("id-1", "secret-xyz", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(NaverNewsClientError) as excinfo:
            client.search("부산백병원")
    assert "401" in str(excinfo.value) and "024" in str(excinfo.value)
    assert "secret-xyz" not in str(excinfo.value)


def test_client_wraps_transport_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout")

    with NaverNewsClient("id-1", "secret", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(NaverNewsClientError, match="ConnectTimeout"):
            client.search("의료수가")


def test_client_requires_keys() -> None:
    with pytest.raises(NaverNewsClientError):
        NaverNewsClient("", "x")


def test_sample_payload_round_trips_as_json() -> None:
    assert json.loads(json.dumps(SAMPLE))["total"] == 2
