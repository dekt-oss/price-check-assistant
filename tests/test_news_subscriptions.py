"""Email subscriptions with confirmation, and the narrowed 우리병원 keywords."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from purchase_price.scripts import collect_news_radar as cli
from purchase_price.services import news_alerts
from purchase_price.services import news_radar as radar
from purchase_price.services import news_subscriptions as subs

NOW = datetime(2026, 10, 9, 3, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path):
    return subs.LocalSubscriberStore(tmp_path / "subs")


@pytest.fixture
def outbox(monkeypatch):
    sent: list[dict] = []

    def fake_send(subject, body, env, *, to=None, smtp_factory=None):
        sent.append({"subject": subject, "body": body, "to": list(to or [])})
        return news_alerts.SendResult("email", "sent")

    monkeypatch.setattr(news_alerts, "send_email", fake_send)
    monkeypatch.setenv(news_alerts.PAGE_URL_ENV, "https://app/news-radar")
    return sent


def test_request_confirm_alert_and_unsubscribe(store, outbox) -> None:
    pending = subs.request_subscription(store, " Me@Hospital.KR ", [subs.PREF_IMMEDIATE], now=NOW)
    assert pending.email == "me@hospital.kr" and pending.status == subs.STATUS_PENDING
    assert subs.recipients(store, subs.PREF_IMMEDIATE) == []  # nothing before the click

    assert cli.run_subscriber_upkeep(store, now=NOW).startswith("확인 메일 1건 발송")
    (mail,) = outbox
    assert mail["to"] == ["me@hospital.kr"] and "?confirm=" in mail["body"]
    assert cli.run_subscriber_upkeep(store, now=NOW).startswith("확인 메일 0건")  # sent once

    token = mail["body"].split("?confirm=")[1].split()[0]
    confirmed = subs.confirm(store, token, now=NOW)
    assert confirmed.status == subs.STATUS_CONFIRMED
    with pytest.raises(subs.SubscriptionError):
        subs.confirm(store, token)  # one-time link

    outbox.clear()
    assert cli.send_to_subscribers(store, subs.PREF_IMMEDIATE, "제목", "본문") == "구독자 1명 중 1명 발송"
    assert cli.send_to_subscribers(store, subs.PREF_DAILY, "제목", "본문") == "구독자 0명 중 0명 발송"
    (alert,) = outbox
    unsubscribe_token = alert["body"].split("?unsubscribe=")[1].strip()
    assert "me@hospital.kr" in subs.unsubscribe(store, unsubscribe_token)
    assert store.all() == []


def test_wrong_tokens_and_bad_addresses_are_rejected(store) -> None:
    with pytest.raises(subs.SubscriptionError):
        subs.request_subscription(store, "not-an-email", [subs.PREF_DAILY])
    with pytest.raises(subs.SubscriptionError):
        subs.request_subscription(store, "a@b.kr", [])
    person = subs.request_subscription(store, "a@b.kr", [subs.PREF_DAILY], now=NOW)
    with pytest.raises(subs.SubscriptionError):
        subs.confirm(store, f"{person.id}.wrong")
    with pytest.raises(subs.SubscriptionError):
        subs.unsubscribe(store, f"{person.id}.wrong")
    with pytest.raises(subs.SubscriptionError):
        subs.confirm(store, "garbage")


def test_rate_limit_and_pending_expiry(store) -> None:
    for minute in range(subs.MAX_REQUESTS_PER_DAY):
        subs.request_subscription(store, "x@y.kr", [subs.PREF_DAILY], now=NOW + timedelta(minutes=minute))
    with pytest.raises(subs.SubscriptionError, match="너무 많습니다"):
        subs.request_subscription(store, "x@y.kr", [subs.PREF_DAILY], now=NOW + timedelta(minutes=5))
    assert subs.purge_stale(store, now=NOW + timedelta(days=8)) == 1 and store.all() == []


def test_confirmed_address_needs_a_new_click_to_change_choices(store, outbox) -> None:
    subs.request_subscription(store, "c@d.kr", [subs.PREF_IMMEDIATE], now=NOW)
    first = store.all()[0]
    subs.confirm(store, first.confirm_link_token, now=NOW)
    subs.request_subscription(store, "c@d.kr", [subs.PREF_DAILY], now=NOW + timedelta(hours=1))
    still = store.all()[0]
    assert still.prefs == (subs.PREF_IMMEDIATE,) and still.pending_prefs == (subs.PREF_DAILY,)
    cli.run_subscriber_upkeep(store, now=NOW + timedelta(hours=1))
    token = outbox[-1]["body"].split("?confirm=")[1].split()[0]
    assert subs.confirm(store, token).prefs == (subs.PREF_DAILY,)


def test_no_store_means_nothing_happens() -> None:
    assert cli.run_subscriber_upkeep(None) == "not configured"
    assert cli.send_to_subscribers(None, subs.PREF_DAILY, "s", "b") == "구독 저장소 없음"
    assert subs.R2SubscriberStore.from_env({}) is None


def test_our_hospital_keywords_alert_on_titles_about_us_only() -> None:
    groups = radar.load_keyword_groups()
    ours = groups[0]
    assert ours.key == "our_hospital" and all(k.alert == "immediate" for k in ours.keywords)
    assert all(k.alert != "immediate" for g in groups[1:] for k in g.keywords)  # rest goes to the digest
    by_text = {k.text: k for k in ours.keywords}
    match = lambda title: [t for t, k in by_text.items() if radar.title_matches(title, k)]  # noqa: E731
    assert match("부산백병원, 권역모자의료센터 개소 10주년") == ["부산백병원", "인제대 백병원"] or match(
        "부산백병원, 권역모자의료센터 개소 10주년"
    )[0] == "부산백병원"
    assert match("김해시의원 “인제대 백병원 분원 유치를”") == ["인제대 백병원"]
    assert match("백병원 임금 이어 한림대의료원 '임금·단체협약'") == ["인제대 백병원"]
    assert match("해운대백병원 박병규 교수 최우수논문상") == []  # 같은 의료원 → 하루 요약
    assert match("인제대, THE 세계대학순위 첫 진입") == []
    assert match("부산백화점 세일") == []
