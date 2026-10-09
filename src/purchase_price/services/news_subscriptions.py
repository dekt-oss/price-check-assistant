"""Email subscriptions for News Radar with confirmation (double opt-in).

Flow
1. Someone enters an address on the News Radar page and picks what to receive:
   ``immediate`` (우리병원 기사, within about 10 minutes) and/or ``daily`` (매일 아침 병원 동향 요약).
   The app stores a *pending* record; it never sends mail itself.
2. The 10-minute collector job emails a confirmation link (``?confirm=<token>``) to new pending
   records. Only after the owner of the address clicks it does the record become *confirmed*.
3. Every alert and digest email carries an unsubscribe link (``?unsubscribe=<token>``); clicking it
   deletes the record.

Storage is one small JSON object per address under ``subscribers/v1/`` in a dedicated R2 bucket
(``SUBSCRIBER_R2_*``), so the public app's write key cannot touch the evidence bucket. Records
hold only the address, choices, tokens and timestamps. Unconfirmed records are removed after 7 days.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

PREF_IMMEDIATE = "immediate"
PREF_DAILY = "daily"
PREF_LABELS = {PREF_IMMEDIATE: "우리병원 기사 즉시 알림", PREF_DAILY: "매일 아침 병원 동향 요약"}
STATUS_PENDING = "pending"
STATUS_CONFIRMED = "confirmed"
PREFIX = "subscribers/v1/"
PENDING_TTL = timedelta(days=7)
MAX_REQUESTS_PER_DAY = 3
MAX_PENDING_TOTAL = 50

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


class SubscriptionError(ValueError):
    """A request the page should explain to the person (bad address, too many requests...)."""


def normalize_email(value: str) -> str:
    email = (value or "").strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        raise SubscriptionError("이메일 주소 형식을 확인해 주세요.")
    return email


def email_id(email: str) -> str:
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:32]


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass(frozen=True)
class Subscriber:
    email: str
    prefs: tuple[str, ...]
    status: str
    confirm_token: str
    unsubscribe_token: str
    created_at: datetime
    confirm_sent_at: datetime | None = None
    confirmed_at: datetime | None = None
    pending_prefs: tuple[str, ...] | None = None
    requests: tuple[datetime, ...] = field(default_factory=tuple)

    @property
    def id(self) -> str:
        return email_id(self.email)

    @property
    def confirm_link_token(self) -> str:
        return f"{self.id}.{self.confirm_token}"

    @property
    def unsubscribe_link_token(self) -> str:
        return f"{self.id}.{self.unsubscribe_token}"

    @property
    def needs_confirmation_mail(self) -> bool:
        return (self.status == STATUS_PENDING or self.pending_prefs is not None) and self.confirm_sent_at is None

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.update(
            prefs=list(self.prefs),
            pending_prefs=list(self.pending_prefs) if self.pending_prefs is not None else None,
            created_at=_iso(self.created_at),
            confirm_sent_at=_iso(self.confirm_sent_at),
            confirmed_at=_iso(self.confirmed_at),
            requests=[_iso(r) for r in self.requests],
        )
        return payload

    @classmethod
    def from_payload(cls, raw: Mapping[str, Any]) -> Subscriber:
        pending = raw.get("pending_prefs")
        return cls(
            email=str(raw["email"]),
            prefs=tuple(raw.get("prefs") or ()),
            status=str(raw.get("status") or STATUS_PENDING),
            confirm_token=str(raw["confirm_token"]),
            unsubscribe_token=str(raw["unsubscribe_token"]),
            created_at=_parse(raw.get("created_at")) or datetime.now(UTC),
            confirm_sent_at=_parse(raw.get("confirm_sent_at")),
            confirmed_at=_parse(raw.get("confirmed_at")),
            pending_prefs=tuple(pending) if pending is not None else None,
            requests=tuple(d for r in raw.get("requests") or [] if (d := _parse(r)) is not None),
        )


class SubscriberStore(Protocol):
    def get(self, record_id: str) -> Subscriber | None: ...

    def put(self, subscriber: Subscriber) -> None: ...

    def delete(self, record_id: str) -> None: ...

    def all(self) -> list[Subscriber]: ...


class LocalSubscriberStore:
    """Directory store for tests and local review."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, record_id: str) -> Path:
        return self.root / f"{record_id}.json"

    def get(self, record_id: str) -> Subscriber | None:
        path = self._path(record_id)
        return Subscriber.from_payload(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None

    def put(self, subscriber: Subscriber) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._path(subscriber.id).write_text(json.dumps(subscriber.to_payload(), ensure_ascii=False), encoding="utf-8")

    def delete(self, record_id: str) -> None:
        self._path(record_id).unlink(missing_ok=True)

    def all(self) -> list[Subscriber]:
        if not self.root.exists():
            return []
        return [Subscriber.from_payload(json.loads(p.read_text(encoding="utf-8"))) for p in sorted(self.root.glob("*.json"))]


class R2SubscriberStore:
    def __init__(self, *, client: Any, bucket: str) -> None:
        self._client = client
        self.bucket = bucket

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> R2SubscriberStore | None:
        """``SUBSCRIBER_R2_BUCKET`` / ``_ACCESS_KEY_ID`` / ``_SECRET_ACCESS_KEY`` plus the shared
        ``R2_ENDPOINT_URL`` or ``R2_ACCOUNT_ID``. Returns None when anything is missing."""

        bucket = (env.get("SUBSCRIBER_R2_BUCKET") or "").strip()
        key_id = (env.get("SUBSCRIBER_R2_ACCESS_KEY_ID") or "").strip()
        secret = (env.get("SUBSCRIBER_R2_SECRET_ACCESS_KEY") or "").strip()
        endpoint = (env.get("R2_ENDPOINT_URL") or "").strip().rstrip("/")
        account = (env.get("R2_ACCOUNT_ID") or "").strip()
        if not endpoint and account:
            endpoint = f"https://{account}.r2.cloudflarestorage.com"
        if not (bucket and key_id and secret and endpoint):
            return None
        import boto3
        from botocore.config import Config

        client = boto3.client(
            service_name="s3",
            endpoint_url=endpoint,
            aws_access_key_id=key_id,
            aws_secret_access_key=secret,
            region_name="auto",
            config=Config(connect_timeout=5, read_timeout=15, retries={"max_attempts": 2}),
        )
        return cls(client=client, bucket=bucket)

    def _key(self, record_id: str) -> str:
        return f"{PREFIX}{record_id}.json"

    def get(self, record_id: str) -> Subscriber | None:
        try:
            body = self._client.get_object(Bucket=self.bucket, Key=self._key(record_id))["Body"].read()
        except Exception as exc:  # noqa: BLE001 - botocore NoSuchKey and friends
            if "NoSuchKey" in type(exc).__name__ or "NoSuchKey" in str(exc) or "404" in str(exc):
                return None
            raise
        return Subscriber.from_payload(json.loads(body.decode("utf-8")))

    def put(self, subscriber: Subscriber) -> None:
        self._client.put_object(
            Bucket=self.bucket,
            Key=self._key(subscriber.id),
            Body=json.dumps(subscriber.to_payload(), ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )

    def delete(self, record_id: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=self._key(record_id))

    def all(self) -> list[Subscriber]:
        result: list[Subscriber] = []
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self.bucket, "Prefix": PREFIX}
            if token:
                kwargs["ContinuationToken"] = token
            response = self._client.list_objects_v2(**kwargs)
            for obj in response.get("Contents", []) or []:
                body = self._client.get_object(Bucket=self.bucket, Key=obj["Key"])["Body"].read()
                result.append(Subscriber.from_payload(json.loads(body.decode("utf-8"))))
            if not response.get("IsTruncated"):
                return result
            token = response.get("NextContinuationToken")


def request_subscription(
    store: SubscriberStore,
    email: str,
    prefs: Iterable[str],
    *,
    now: datetime | None = None,
) -> Subscriber:
    """Record a subscription request. The confirmation mail is sent by the collector job."""

    now = now or datetime.now(UTC)
    address = normalize_email(email)
    chosen = tuple(p for p in (PREF_IMMEDIATE, PREF_DAILY) if p in set(prefs))
    if not chosen:
        raise SubscriptionError("받을 알림을 하나 이상 골라 주세요.")
    existing = store.get(email_id(address))
    recent = tuple(r for r in (existing.requests if existing else ()) if now - r < timedelta(days=1))
    if len(recent) >= MAX_REQUESTS_PER_DAY:
        raise SubscriptionError("같은 주소로 오늘 요청이 너무 많습니다. 내일 다시 시도해 주세요.")
    if existing is None:
        pending_total = sum(1 for s in store.all() if s.status == STATUS_PENDING)
        if pending_total >= MAX_PENDING_TOTAL:
            raise SubscriptionError("확인 대기 중인 신청이 많아 잠시 받을 수 없습니다. 나중에 다시 시도해 주세요.")
        subscriber = Subscriber(
            email=address,
            prefs=chosen,
            status=STATUS_PENDING,
            confirm_token=secrets.token_urlsafe(24),
            unsubscribe_token=secrets.token_urlsafe(24),
            created_at=now,
            requests=(*recent, now),
        )
    elif existing.status == STATUS_CONFIRMED:
        # Changing what a confirmed address receives also needs the owner's click.
        subscriber = replace(
            existing,
            pending_prefs=chosen,
            confirm_token=secrets.token_urlsafe(24),
            confirm_sent_at=None,
            requests=(*recent, now),
        )
    else:
        subscriber = replace(existing, prefs=chosen, confirm_sent_at=None, requests=(*recent, now))
    store.put(subscriber)
    return subscriber


def _split(token: str) -> tuple[str, str]:
    record_id, _, secret = (token or "").partition(".")
    if not record_id or not secret:
        raise SubscriptionError("링크가 올바르지 않습니다.")
    return record_id, secret


def confirm(store: SubscriberStore, token: str, *, now: datetime | None = None) -> Subscriber:
    record_id, secret = _split(token)
    subscriber = store.get(record_id)
    if subscriber is None or not secrets.compare_digest(subscriber.confirm_token, secret):
        raise SubscriptionError("확인 링크가 만료되었거나 올바르지 않습니다. 다시 신청해 주세요.")
    confirmed = replace(
        subscriber,
        status=STATUS_CONFIRMED,
        prefs=subscriber.pending_prefs or subscriber.prefs,
        pending_prefs=None,
        confirmed_at=now or datetime.now(UTC),
        confirm_token=secrets.token_urlsafe(24),  # one-time link
    )
    store.put(confirmed)
    return confirmed


def unsubscribe(store: SubscriberStore, token: str) -> str:
    record_id, secret = _split(token)
    subscriber = store.get(record_id)
    if subscriber is None:
        return "이미 수신 거부된 주소입니다."
    if not secrets.compare_digest(subscriber.unsubscribe_token, secret):
        raise SubscriptionError("수신 거부 링크가 올바르지 않습니다.")
    store.delete(record_id)
    return f"{subscriber.email} 주소의 알림을 모두 끊고 등록 정보를 지웠습니다."


def recipients(store: SubscriberStore, pref: str) -> list[Subscriber]:
    return [s for s in store.all() if s.status == STATUS_CONFIRMED and pref in s.prefs]


def purge_stale(store: SubscriberStore, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    removed = 0
    for subscriber in store.all():
        if subscriber.status == STATUS_PENDING and now - subscriber.created_at > PENDING_TTL:
            store.delete(subscriber.id)
            removed += 1
    return removed


def confirmation_mail(subscriber: Subscriber, page_url: str) -> tuple[str, str]:
    prefs = subscriber.pending_prefs or subscriber.prefs
    chosen = ", ".join(PREF_LABELS[p] for p in prefs)
    subject = "[병원 News Radar] 알림 신청 확인"
    body = "\n".join(
        [
            "병원 News Radar 이메일 알림 신청을 받았습니다.",
            f"신청 내용: {chosen}",
            "",
            "본인이 신청하셨다면 아래 링크를 눌러 확인해 주세요. 확인 전에는 알림을 보내지 않습니다.",
            f"{page_url}?confirm={subscriber.confirm_link_token}",
            "",
            "신청하지 않으셨다면 이 메일을 무시하세요. 7일 뒤 신청 정보가 자동으로 지워집니다.",
        ]
    )
    return subject, body


def unsubscribe_footer(subscriber: Subscriber, page_url: str) -> str:
    return f"\n\n--\n알림을 그만 받으려면: {page_url}?unsubscribe={subscriber.unsubscribe_link_token}"
