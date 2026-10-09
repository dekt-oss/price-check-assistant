"""Immediate News Radar alerts by KakaoTalk, email, SMS and webhook.

Only articles whose *title* matches a keyword marked ``alert: "immediate"`` are sent (see
``news_radar.title_matches``); body-only mentions never alert. Each keyword group lists its
channels in ``data/news_keywords.json`` (``notify``), so 우리병원 can go to KakaoTalk, email and SMS
while other groups stay on email.

Messages carry only what NAVER allows us to show: title, source, time and link. Nothing here
calls an AI model. Channel credentials come from environment variables (GitHub Secrets); a channel
without credentials is skipped, never an error, and credentials never appear in output.

Channels
- kakao: KakaoTalk "나에게 보내기" (the account that authorised the app receives it).
  KAKAO_REST_API_KEY, KAKAO_REFRESH_TOKEN, optional KAKAO_CLIENT_SECRET.
- email: SMTP with STARTTLS. SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD,
  ALERT_EMAIL_TO (comma separated), optional ALERT_EMAIL_FROM.
- sms: SOLAPI. SOLAPI_API_KEY, SOLAPI_API_SECRET, SMS_FROM (registered sender), SMS_TO.
- webhook: NEWS_ALERT_WEBHOOK_URL (Teams/Slack ``{"text": ...}``).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import smtplib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage

import httpx

from purchase_price.services import news_radar as radar

PAGE_URL_ENV = "NEWS_RADAR_PAGE_URL"
DEFAULT_PAGE_URL = "https://bp-price-research.streamlit.app/news-radar"
MAX_ITEMS = 20
KAKAO_MAX_MESSAGES = 5
KAKAO_TEXT_LIMIT = 200

KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
SOLAPI_SEND_URL = "https://api.solapi.com/messages/v4/send-many/detail"


@dataclass(frozen=True)
class AlertItem:
    keyword: str
    group_key: str
    group_name: str
    entry: radar.NewsEntry
    source_label: str | None = None


def immediate_items(
    new_by_keyword: Mapping[str, Sequence[radar.NewsEntry]],
    groups: Iterable[radar.KeywordGroup],
    tiers: Iterable[radar.SourceTier] = (),
) -> list[AlertItem]:
    """New articles for 즉시 keywords whose title matches; one item per article (first keyword wins).

    Ordered 우리병원 first, then trade press, then newest.
    """

    by_text = {k.text: k for g in groups for k in g.keywords}
    tier_list = tuple(tiers)
    seen: set[str] = set()
    items: list[AlertItem] = []
    for keyword_text, entries in new_by_keyword.items():
        keyword = by_text.get(keyword_text)
        if keyword is None or keyword.alert != "immediate":
            continue
        for entry in entries:
            if entry.article_id in seen or not radar.title_matches(entry.title, keyword):
                continue
            seen.add(entry.article_id)
            tier = radar.source_tier(entry.source_domain, tier_list)
            items.append(AlertItem(keyword.text, keyword.group_key, keyword.group_name, entry, tier.label if tier else None))

    def order(item: AlertItem) -> tuple[int, int, float]:
        when = item.entry.published_at or item.entry.detected_at
        return (
            -radar.GROUP_WEIGHTS.get(item.group_key, 0),
            0 if item.source_label else 1,
            -radar.to_seoul(when).timestamp(),
        )

    return sorted(items, key=order)


def route(items: Iterable[AlertItem], groups: Iterable[radar.KeywordGroup]) -> dict[str, list[AlertItem]]:
    channels_by_group = {g.key: g.notify for g in groups}
    routed: dict[str, list[AlertItem]] = {}
    for item in items:
        for channel in channels_by_group.get(item.group_key, ("webhook",)):
            routed.setdefault(channel, []).append(item)
    return routed


def _line(item: AlertItem) -> str:
    source = item.entry.source_domain or "출처 확인 안 됨"
    if item.source_label:
        source += f"·{item.source_label}"
    return f"[{item.keyword}] {item.entry.title} ({source}, {radar.seoul_time_text(item.entry.published_at)})"


def long_text(items: Sequence[AlertItem], page_url: str) -> str:
    shown = list(items[:MAX_ITEMS])
    lines = [f"병원 News Radar 새 기사 {len(items)}건"]
    for item in shown:
        lines.append(f"- {_line(item)}\n  {item.entry.url}")
    if len(items) > len(shown):
        lines.append(f"외 {len(items) - len(shown)}건")
    lines.append(f"전체 보기: {page_url}")
    return "\n".join(lines)


def sms_text(items: Sequence[AlertItem], page_url: str) -> str:
    first = items[0]
    more = f" 외 {len(items) - 1}건" if len(items) > 1 else ""
    return f"[병원뉴스] {first.keyword}: {first.entry.title}{more}\n{page_url}"


# --------------------------------------------------------------------------- channels


@dataclass(frozen=True)
class SendResult:
    channel: str
    status: str  # sent | skipped (...) | failed (...)


def send_webhook(text: str, env: Mapping[str, str], *, transport: httpx.BaseTransport | None = None) -> SendResult:
    url = (env.get("NEWS_ALERT_WEBHOOK_URL") or "").strip()
    if not url:
        return SendResult("webhook", "skipped (not configured)")
    try:
        with httpx.Client(timeout=10.0, transport=transport) as client:
            response = client.post(url, json={"text": text})
    except httpx.HTTPError as exc:
        return SendResult("webhook", f"failed ({type(exc).__name__})")
    return SendResult("webhook", "sent" if 200 <= response.status_code < 300 else f"failed (HTTP {response.status_code})")


def send_email(
    subject: str,
    body: str,
    env: Mapping[str, str],
    *,
    smtp_factory: Callable[[str, int], smtplib.SMTP] = lambda host, port: smtplib.SMTP(host, port, timeout=20),
) -> SendResult:
    host = (env.get("SMTP_HOST") or "").strip()
    user = (env.get("SMTP_USER") or "").strip()
    password = env.get("SMTP_PASSWORD") or ""
    to = [a.strip() for a in (env.get("ALERT_EMAIL_TO") or "").split(",") if a.strip()]
    if not (host and user and password and to):
        return SendResult("email", "skipped (not configured)")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = (env.get("ALERT_EMAIL_FROM") or user).strip()
    message["To"] = ", ".join(to)
    message.set_content(body)
    try:
        with smtp_factory(host, int(env.get("SMTP_PORT") or 587)) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        return SendResult("email", f"failed ({type(exc).__name__})")
    return SendResult("email", "sent")


TokenSaver = Callable[[str], None]


def kakao_access_token(
    env: Mapping[str, str],
    refresh_token: str,
    *,
    save_refresh_token: TokenSaver | None = None,
    client: httpx.Client,
) -> str:
    """Exchange the refresh token for an access token. Kakao returns a new refresh token when the
    old one has less than a month left; it is handed to ``save_refresh_token`` so it is kept."""

    data = {
        "grant_type": "refresh_token",
        "client_id": (env.get("KAKAO_REST_API_KEY") or "").strip(),
        "refresh_token": refresh_token,
    }
    secret = (env.get("KAKAO_CLIENT_SECRET") or "").strip()
    if secret:
        data["client_secret"] = secret
    response = client.post(KAKAO_TOKEN_URL, data=data)
    response.raise_for_status()
    payload = response.json()
    new_refresh = payload.get("refresh_token")
    if new_refresh and save_refresh_token is not None:
        save_refresh_token(str(new_refresh))
    return str(payload["access_token"])


def send_kakao(
    items: Sequence[AlertItem],
    page_url: str,
    env: Mapping[str, str],
    *,
    refresh_token: str | None = None,
    save_refresh_token: TokenSaver | None = None,
    transport: httpx.BaseTransport | None = None,
) -> SendResult:
    """KakaoTalk 나에게 보내기: one text message per article (up to 5), button to the radar page.

    The button links to the News Radar page because Kakao only opens links on domains registered
    in the app (register ``bp-price-research.streamlit.app`` under 플랫폼 > Web).
    """

    token = (refresh_token or env.get("KAKAO_REFRESH_TOKEN") or "").strip()
    if not ((env.get("KAKAO_REST_API_KEY") or "").strip() and token):
        return SendResult("kakao", "skipped (not configured)")
    try:
        with httpx.Client(timeout=10.0, transport=transport) as client:
            access = kakao_access_token(env, token, save_refresh_token=save_refresh_token, client=client)
            shown = list(items[:KAKAO_MAX_MESSAGES])
            for position, item in enumerate(shown, start=1):
                text = _line(item)
                if position == len(shown) and len(items) > len(shown):
                    text += f"\n외 {len(items) - len(shown)}건"
                template = {
                    "object_type": "text",
                    "text": text[:KAKAO_TEXT_LIMIT],
                    "link": {"web_url": page_url, "mobile_web_url": page_url},
                    "button_title": "News Radar 열기",
                }
                response = client.post(
                    KAKAO_MEMO_URL,
                    headers={"Authorization": f"Bearer {access}"},
                    data={"template_object": json.dumps(template, ensure_ascii=False)},
                )
                if response.status_code != 200 or response.json().get("result_code") != 0:
                    return SendResult("kakao", f"failed (HTTP {response.status_code})")
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        return SendResult("kakao", f"failed ({type(exc).__name__})")
    return SendResult("kakao", "sent")


def solapi_authorization(api_key: str, api_secret: str, *, now: datetime | None = None, salt: str | None = None) -> str:
    """SOLAPI HMAC-SHA256 header: signature = hex(HMAC(secret, date + salt))."""

    date = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    salt = salt or secrets.token_hex(16)
    signature = hmac.new(api_secret.encode(), (date + salt).encode(), hashlib.sha256).hexdigest()
    return f"HMAC-SHA256 apiKey={api_key}, date={date}, salt={salt}, signature={signature}"


def send_sms(text: str, env: Mapping[str, str], *, transport: httpx.BaseTransport | None = None) -> SendResult:
    key = (env.get("SOLAPI_API_KEY") or "").strip()
    secret = (env.get("SOLAPI_API_SECRET") or "").strip()
    sender = (env.get("SMS_FROM") or "").replace("-", "").strip()
    to = [n.replace("-", "").strip() for n in (env.get("SMS_TO") or "").split(",") if n.strip()]
    if not (key and secret and sender and to):
        return SendResult("sms", "skipped (not configured)")
    body = {"messages": [{"to": number, "from": sender, "text": text} for number in to]}
    try:
        with httpx.Client(timeout=10.0, transport=transport) as client:
            response = client.post(
                SOLAPI_SEND_URL,
                headers={"Authorization": solapi_authorization(key, secret), "Content-Type": "application/json"},
                content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            )
    except httpx.HTTPError as exc:
        return SendResult("sms", f"failed ({type(exc).__name__})")
    return SendResult("sms", "sent" if 200 <= response.status_code < 300 else f"failed (HTTP {response.status_code})")


def dispatch(
    routed: Mapping[str, Sequence[AlertItem]],
    env: Mapping[str, str] | None = None,
    *,
    kakao_refresh_token: str | None = None,
    save_kakao_refresh_token: TokenSaver | None = None,
    transport: httpx.BaseTransport | None = None,
    smtp_factory: Callable[[str, int], smtplib.SMTP] | None = None,
) -> list[SendResult]:
    env = env if env is not None else os.environ
    page_url = (env.get(PAGE_URL_ENV) or DEFAULT_PAGE_URL).strip()
    results: list[SendResult] = []
    for channel, items in routed.items():
        if not items:
            continue
        if channel == "webhook":
            results.append(send_webhook(long_text(items, page_url), env, transport=transport))
        elif channel == "email":
            subject = f"[병원 News Radar] {items[0].keyword} 등 새 기사 {len(items)}건"
            kwargs = {"smtp_factory": smtp_factory} if smtp_factory else {}
            results.append(send_email(subject, long_text(items, page_url), env, **kwargs))
        elif channel == "kakao":
            results.append(
                send_kakao(
                    items,
                    page_url,
                    env,
                    refresh_token=kakao_refresh_token,
                    save_refresh_token=save_kakao_refresh_token,
                    transport=transport,
                )
            )
        elif channel == "sms":
            results.append(send_sms(sms_text(items, page_url), env, transport=transport))
        else:
            results.append(SendResult(channel, "skipped (unknown channel)"))
    return results
