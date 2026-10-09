"""Title relevance, trade-press priority and the KakaoTalk / email / SMS / webhook alerts."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import httpx

from purchase_price.services import news_alerts as alerts
from purchase_price.services import news_radar as radar

NOW = datetime(2026, 10, 9, 1, 0, tzinfo=UTC)


def _entry(aid: str, title: str, keywords: tuple[str, ...], domain: str = "a.kr", hours: int = 1) -> radar.NewsEntry:
    when = NOW - timedelta(hours=hours)
    return radar.NewsEntry(aid, title, f"https://{domain}/{aid}", "", domain, when, keywords, when)


def _groups() -> tuple[radar.KeywordGroup, ...]:
    return radar.load_keyword_groups()


def _kw(text: str) -> radar.Keyword:
    return next(k for g in _groups() for k in g.keywords if k.text == text)


def test_title_terms_reject_body_only_mentions() -> None:
    ai = _kw("병원 AI 도입")
    assert radar.title_matches("은평성모병원, 진료부터 운영까지 'AI 전환' 속도", ai)
    assert not radar.title_matches("조용호 오산시장 취임 100일…교통·일자리", ai)
    paik = _kw("부산백병원")
    assert radar.title_matches("인제대 부산백병원, 권역모자의료센터 10주년", paik)
    assert not radar.title_matches("해운대백병원 박병규 교수 최우수논문상", paik)
    # Default rule (no title_terms): every word of the keyword text.
    plain = radar.Keyword("의료 AI", "g", "g")
    assert radar.title_matches("의료AI 스타트업 투자", plain) and not radar.title_matches("AI 반도체", plain)


def test_every_seed_keyword_matches_its_own_text() -> None:
    for group in _groups():
        assert group.notify, group.key
        for keyword in group.keywords:
            assert keyword.title_terms, keyword.text
    assert _groups()[0].key == "our_hospital" and {"kakao", "email", "sms"} <= set(_groups()[0].notify)


def test_ranking_puts_relevant_our_hospital_and_trade_press_first() -> None:
    tiers = radar.load_source_tiers()
    entries = [
        _entry("1", "시장 취임 100일 기념식", ("부산백병원",), "news.kr", hours=1),
        _entry("2", "부산백병원, 권역모자의료센터 10주년", ("부산백병원",), "dailymedi.com", hours=5),
        _entry("3", "부산대병원, 권역응급의료센터 공모", ("부산대학교병원",), "kookje.co.kr", hours=2),
        _entry("4", "병원 AI 도입 확산", ("병원 AI 도입",), "m.medigatenews.com", hours=3),
    ]
    keywords = [k for g in _groups() for k in g.keywords]
    ranked = radar.rank_entries(entries, keywords, tiers)
    assert [r.entry.article_id for r in ranked if not r.relevant] == ["1"]
    order = [r.entry.article_id for r in radar.by_priority(r for r in ranked if r.relevant)]
    assert order[0] == "2"  # 우리병원 + 전문지
    tier = radar.source_tier("m.medigatenews.com", tiers)
    assert tier is not None and tier.key == "medical_trade"


def test_immediate_items_skip_body_mentions_and_route_by_group() -> None:
    groups = _groups()
    new = {
        "부산백병원": [
            _entry("a", "부산백병원 새 병동 개소", ("부산백병원",), "bosa.co.kr"),
            _entry("b", "오산시장 취임 100일", ("부산백병원",)),
        ],
        "부산대학교병원": [_entry("c", "부산대병원 소식", ("부산대학교병원",))],  # daily, not immediate
        "의료기기 회수": [_entry("d", "식약처, 의료기기 회수 명령", ("의료기기 회수",))],
    }
    items = alerts.immediate_items(new, groups, radar.load_source_tiers())
    assert [i.entry.article_id for i in items] == ["a", "d"]
    routed = alerts.route(items, groups)
    assert [i.entry.article_id for i in routed["kakao"]] == ["a"] and [i.entry.article_id for i in routed["sms"]] == ["a"]
    assert [i.entry.article_id for i in routed["email"]] == ["a", "d"]


def _items() -> list[alerts.AlertItem]:
    return alerts.immediate_items(
        {"부산백병원": [_entry("a", "부산백병원 새 병동 개소", ("부산백병원",), "bosa.co.kr")]},
        _groups(),
        radar.load_source_tiers(),
    )


def test_unconfigured_channels_are_skipped_without_error() -> None:
    results = alerts.dispatch({"kakao": _items(), "email": _items(), "sms": _items(), "webhook": _items()}, env={})
    assert {r.channel: r.status for r in results} == {
        "kakao": "skipped (not configured)",
        "email": "skipped (not configured)",
        "sms": "skipped (not configured)",
        "webhook": "skipped (not configured)",
    }


def test_kakao_refreshes_token_sends_memo_and_keeps_new_refresh_token() -> None:
    calls: list[httpx.Request] = []
    saved: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "kauth.kakao.com":
            return httpx.Response(200, json={"access_token": "AT", "refresh_token": "NEW-RT"})
        return httpx.Response(200, json={"result_code": 0})

    env = {"KAKAO_REST_API_KEY": "rest", "KAKAO_REFRESH_TOKEN": "OLD-RT"}
    result = alerts.send_kakao(
        _items(), "https://app/news-radar", env, save_refresh_token=saved.append, transport=httpx.MockTransport(handler)
    )
    assert result.status == "sent" and saved == ["NEW-RT"]
    token_form = parse_qs(calls[0].content.decode())
    assert token_form["grant_type"] == ["refresh_token"] and token_form["refresh_token"] == ["OLD-RT"]
    assert calls[1].headers["authorization"] == "Bearer AT"
    template = json.loads(parse_qs(calls[1].content.decode())["template_object"][0])
    assert template["object_type"] == "text" and "부산백병원 새 병동 개소" in template["text"]
    assert template["link"]["web_url"] == "https://app/news-radar" and len(template["text"]) <= 200


def test_solapi_header_matches_the_documented_hmac() -> None:
    header = alerts.solapi_authorization(
        "KEY", "SECRET", now=datetime(2019, 7, 1, 0, 41, 48, tzinfo=UTC), salt="jqsba2jxjnrjor"
    )
    import hashlib
    import hmac

    expected = hmac.new(b"SECRET", b"2019-07-01T00:41:48Zjqsba2jxjnrjor", hashlib.sha256).hexdigest()
    assert header == f"HMAC-SHA256 apiKey=KEY, date=2019-07-01T00:41:48Z, salt=jqsba2jxjnrjor, signature={expected}"


def test_sms_posts_messages_and_never_echoes_secret() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"groupInfo": {}})

    env = {"SOLAPI_API_KEY": "k", "SOLAPI_API_SECRET": "s3cret", "SMS_FROM": "051-000-0000", "SMS_TO": "010-1111-2222"}
    result = alerts.send_sms("[병원뉴스] 테스트", env, transport=httpx.MockTransport(handler))
    assert result.status == "sent" and "s3cret" not in result.status
    body = json.loads(seen[0].content)
    assert body == {"messages": [{"to": "01011112222", "from": "0510000000", "text": "[병원뉴스] 테스트"}]}
    assert seen[0].headers["authorization"].startswith("HMAC-SHA256 apiKey=k, date=")


def test_email_uses_starttls_login_and_lists_titles() -> None:
    sent: dict[str, object] = {}

    class FakeSMTP:
        def __init__(self, host, port):
            sent["host"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, user, password):
            sent["login"] = user

        def send_message(self, message):
            sent["subject"] = message["Subject"]
            sent["body"] = message.get_content()

    env = {"SMTP_HOST": "smtp.example", "SMTP_USER": "me@example", "SMTP_PASSWORD": "pw", "ALERT_EMAIL_TO": "a@x, b@y"}
    results = alerts.dispatch({"email": _items()}, env=env, smtp_factory=FakeSMTP)
    assert results[0].status == "sent" and sent["tls"] and sent["host"] == ("smtp.example", 587)
    assert "부산백병원" in str(sent["subject"]) and "부산백병원 새 병동 개소" in str(sent["body"])


def test_monthly_check_detects_a_new_year_and_writes_issue(tmp_path, monkeypatch) -> None:
    from purchase_price.scripts import check_khidi_new_year as check

    html = '<select><option value="2025">2025</option><option value="2024">2024</option></select>'
    monkeypatch.setattr(check.httpx, "get", lambda *a, **k: type("R", (), {"text": html})())
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    for name in ("SMTP_HOST", "NEWS_ALERT_WEBHOOK_URL", "GITHUB_STEP_SUMMARY"):
        monkeypatch.delenv(name, raising=False)
    assert check.site_years(html) == [2025, 2024]
    assert check.main(["--summary-json", str(tmp_path / "s.json")]) == 0
    assert out.read_text(encoding="utf-8") == "new_year=2025\n"
    issue = (tmp_path / "artifacts" / "khidi-new-year-issue.md").read_text(encoding="utf-8")
    assert "--years 2025" in issue and "2024년" in issue


def test_monthly_check_is_quiet_when_nothing_new(tmp_path, monkeypatch) -> None:
    from purchase_price.scripts import check_khidi_new_year as check

    html = '<option value="2024">2024</option>'
    monkeypatch.setattr(check.httpx, "get", lambda *a, **k: type("R", (), {"text": html})())
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "gh_out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert check.main([]) == 0 and not out.exists()


def test_kakao_helper_builds_consent_url_and_exchanges_code() -> None:
    from purchase_price.scripts import kakao_refresh_token as helper

    url = helper.authorize_url("rest", "https://localhost/cb")
    assert "scope=talk_message" in url and "response_type=code" in url
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"refresh_token": "RT", "access_token": "AT"})

    payload = helper.exchange_code("rest", "https://localhost/cb", "CODE", transport=httpx.MockTransport(handler))
    assert payload["refresh_token"] == "RT"
    assert parse_qs(seen[0].content.decode())["grant_type"] == ["authorization_code"]
