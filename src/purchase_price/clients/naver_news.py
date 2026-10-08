"""NAVER 뉴스 검색 API client used only as the News Radar *detection* layer.

The 2026-09-07 NAVER search API terms allow showing results as they are (title, time,
links) but forbid feeding them to AI input/training and cap server caching at 21 days.
This client therefore returns only what the screen shows and nothing is passed to any
AI step. Keys never appear in error messages or logs.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx

# NAVER API HUB (NAVER Cloud Platform) is the current platform; the Developers Center
# endpoint keeps working with its own key pair until 2027-06.
API_STYLE_HUB = "apihub"
API_STYLE_DEVELOPERS = "developers"
NAVER_NEWS_BASE_URLS: dict[str, str] = {
    API_STYLE_HUB: "https://naverapihub.apigw.ntruss.com/search/v1/news",
    API_STYLE_DEVELOPERS: "https://openapi.naver.com/v1/search/news.json",
}
NAVER_NEWS_BASE_URL = NAVER_NEWS_BASE_URLS[API_STYLE_HUB]
MAX_DISPLAY = 100
_TAG_RE = re.compile(r"<[^>]+>")


class NaverNewsClientError(RuntimeError):
    """Raised when the NAVER news search request fails (keys are never included)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code

    @property
    def rate_limited(self) -> bool:
        return self.status_code == 429


@dataclass(frozen=True)
class NaverNewsItem:
    title: str
    link: str
    original_link: str
    published_at: datetime | None
    source_domain: str

    @property
    def article_url(self) -> str:
        return self.original_link or self.link


def clean_title(raw: str) -> str:
    """Drop the <b> highlight tags and HTML entities so the title reads as plain text."""

    return html.unescape(_TAG_RE.sub("", raw or "")).strip()


def source_domain(url: str) -> str:
    host = urlsplit(url or "").netloc.casefold()
    return host[4:] if host.startswith("www.") else host


def parse_published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def _error_text(response: httpx.Response) -> str:
    """Readable error for both platforms; never includes request headers."""

    code = ""
    message = ""
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):  # API HUB: {"error": {"errorCode": 401, "message": ...}}
            code = str(error.get("errorCode") or "")
            message = str(error.get("message") or "")
        else:  # Developers Center: {"errorCode": "024", "errorMessage": ...}
            code = str(payload.get("errorCode") or "")
            message = str(payload.get("errorMessage") or "")
    text = f"NAVER 뉴스 검색 오류 HTTP {response.status_code}"
    if code and code != str(response.status_code):
        text += f" ({code})"
    if message:
        text += f": {message}"
    return text


def parse_news_payload(payload: dict) -> list[NaverNewsItem]:
    items: list[NaverNewsItem] = []
    for raw in payload.get("items") or []:
        if not isinstance(raw, dict):
            continue
        link = str(raw.get("link") or "").strip()
        original = str(raw.get("originallink") or "").strip()
        if not (link or original):
            continue
        items.append(
            NaverNewsItem(
                title=clean_title(str(raw.get("title") or "")),
                link=link,
                original_link=original,
                published_at=parse_published(raw.get("pubDate")),
                source_domain=source_domain(original or link),
            )
        )
    return items


class NaverNewsClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        api_style: str = API_STYLE_HUB,
        base_url: str | None = None,
        timeout_seconds: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not client_id.strip() or not client_secret.strip():
            raise NaverNewsClientError("NAVER API 키가 설정되지 않았습니다.")
        style = (api_style or API_STYLE_HUB).strip().casefold()
        if style not in NAVER_NEWS_BASE_URLS:
            raise NaverNewsClientError(f"알 수 없는 NAVER API 방식: {api_style}")
        if style == API_STYLE_HUB:
            self._headers = {
                "X-NCP-APIGW-API-KEY-ID": client_id.strip(),
                "X-NCP-APIGW-API-KEY": client_secret.strip(),
            }
        else:
            self._headers = {
                "X-Naver-Client-Id": client_id.strip(),
                "X-Naver-Client-Secret": client_secret.strip(),
            }
        self._base_url = (base_url or "").strip() or NAVER_NEWS_BASE_URLS[style]
        self._client = httpx.Client(timeout=timeout_seconds, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> NaverNewsClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def search(self, query: str, *, display: int = MAX_DISPLAY, sort: str = "date") -> list[NaverNewsItem]:
        params = {"query": query, "display": max(1, min(display, MAX_DISPLAY)), "start": 1, "sort": sort}
        try:
            response = self._client.get(self._base_url, params=params, headers=self._headers)
        except httpx.HTTPError as exc:
            raise NaverNewsClientError(f"NAVER 뉴스 검색 연결 실패: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise NaverNewsClientError(_error_text(response), status_code=response.status_code)
        try:
            payload = response.json()
        except ValueError as exc:
            raise NaverNewsClientError("NAVER 뉴스 검색 응답을 읽지 못했습니다.") from exc
        return parse_news_payload(payload)
