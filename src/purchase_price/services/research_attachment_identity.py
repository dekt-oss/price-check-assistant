from __future__ import annotations

import csv
import io
import ipaddress
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
import openpyxl
import xlrd
from pypdf import PdfReader

from purchase_price.schemas import ProductQuery
from purchase_price.services.g2b_market_models import G2BResearchRecord, ResearchAttachment
from purchase_price.services.matching import normalize_text
from purchase_price.services.product_matching import (
    canonical_manufacturer,
    load_manufacturer_aliases,
)

DEFAULT_MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
DEFAULT_MAX_EXTRACTED_CHARS = 250_000


class AttachmentIdentityStatus(StrEnum):
    EXACT_IDENTITY = "exact_identity"
    MODEL_MATCH = "model_match"
    MANUFACTURER_MATCH = "manufacturer_match"
    NO_MATCH = "no_match"
    UNSUPPORTED = "unsupported"
    TOO_LARGE = "too_large"
    DOWNLOAD_FAILED = "download_failed"
    PARSE_FAILED = "parse_failed"


@dataclass(frozen=True)
class AttachmentIdentityEvidence:
    attachment_name: str | None
    attachment_url: str
    status: AttachmentIdentityStatus
    model_found: bool = False
    manufacturer_found: bool = False
    excerpt: str = ""
    error_type: str = ""
    error_message: str = ""


class UnsupportedAttachmentError(ValueError):
    pass


class AttachmentTooLargeError(ValueError):
    pass


def _safe_error(exc: Exception) -> str:
    text = str(exc).replace("\n", " ").strip()
    return text[:300] if text else type(exc).__name__


def _suffix(name: str | None, url: str) -> str:
    candidate = name or PurePosixPath(urlparse(url).path).name
    return PurePosixPath(candidate).suffix.casefold()


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _xlsx_text(data: bytes) -> str:
    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    values: list[str] = []
    try:
        for sheet in workbook.worksheets:
            values.append(sheet.title)
            for row in sheet.iter_rows(values_only=True):
                values.extend(str(value) for value in row if value not in (None, ""))
    finally:
        workbook.close()
    return "\n".join(values)


def _xls_text(data: bytes) -> str:
    workbook = xlrd.open_workbook(file_contents=data)
    values: list[str] = []
    for sheet in workbook.sheets():
        values.append(sheet.name)
        for row_index in range(sheet.nrows):
            for value in sheet.row_values(row_index):
                if value not in (None, ""):
                    values.append(str(value))
    return "\n".join(values)


def _hwpx_text(data: bytes) -> str:
    values: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        section_names = sorted(
            name
            for name in archive.namelist()
            if name.casefold().startswith("contents/section") and name.casefold().endswith(".xml")
        )
        if not section_names:
            raise ValueError("HWPX Contents/section*.xml not found")
        for name in section_names:
            root = ElementTree.fromstring(archive.read(name))
            values.extend(text.strip() for text in root.itertext() if text and text.strip())
    return "\n".join(values)


def extract_attachment_text(
    *,
    name: str | None,
    url: str,
    data: bytes,
    max_chars: int = DEFAULT_MAX_EXTRACTED_CHARS,
) -> str:
    suffix = _suffix(name, url)
    if suffix == ".pdf":
        text = _pdf_text(data)
    elif suffix == ".xlsx":
        text = _xlsx_text(data)
    elif suffix == ".xls":
        text = _xls_text(data)
    elif suffix == ".hwpx":
        text = _hwpx_text(data)
    elif suffix in {".txt", ".csv"}:
        text = _decode_text(data)
        if suffix == ".csv":
            text = "\n".join(" | ".join(row) for row in csv.reader(io.StringIO(text)))
    elif suffix == ".hwp":
        raise UnsupportedAttachmentError("binary HWP parsing is not configured")
    else:
        raise UnsupportedAttachmentError(f"unsupported attachment type: {suffix or 'unknown'}")
    return text[:max_chars]


def _query_manufacturer_aliases(query_manufacturer: str) -> tuple[str, ...]:
    if not query_manufacturer.strip():
        return ()
    aliases = load_manufacturer_aliases()
    canonical = canonical_manufacturer(query_manufacturer, aliases)
    values = {normalize_text(query_manufacturer)}
    for alias_key, alias_canonical in aliases.items():
        if alias_canonical == canonical:
            values.add(alias_key)
    if canonical:
        values.add(normalize_text(canonical))
    return tuple(sorted(value for value in values if value))


def classify_attachment_identity(
    text: str,
    query: ProductQuery,
) -> tuple[AttachmentIdentityStatus, bool, bool, str]:
    """Classify explicit text evidence without treating category similarity as exact identity."""

    normalized = normalize_text(text)
    model_key = normalize_text(query.model_name)
    model_found = bool(model_key and len(model_key) >= 3 and model_key in normalized)
    manufacturer_keys = _query_manufacturer_aliases(query.manufacturer)
    manufacturer_found = bool(manufacturer_keys and any(key in normalized for key in manufacturer_keys))

    manufacturer_requested = bool(query.manufacturer.strip())
    if model_found and (manufacturer_found or not manufacturer_requested):
        status = AttachmentIdentityStatus.EXACT_IDENTITY
    elif model_found:
        status = AttachmentIdentityStatus.MODEL_MATCH
    elif manufacturer_found:
        status = AttachmentIdentityStatus.MANUFACTURER_MATCH
    else:
        status = AttachmentIdentityStatus.NO_MATCH

    anchors = [value for value in (query.manufacturer.strip(), query.model_name.strip()) if value]
    excerpt = _excerpt_around(text, anchors)
    return status, model_found, manufacturer_found, excerpt


def _excerpt_around(text: str, anchors: list[str], *, radius: int = 160) -> str:
    compact = " ".join(text.split())
    folded = compact.casefold()
    positions = [folded.find(anchor.casefold()) for anchor in anchors if anchor]
    positions = [position for position in positions if position >= 0]
    if not positions:
        return compact[: min(len(compact), radius * 2)]
    center = min(positions)
    start = max(0, center - radius)
    end = min(len(compact), center + radius)
    return compact[start:end]


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("attachment URL must be http(s)")
    host = parsed.hostname.casefold()
    if host in {"localhost", "localhost.localdomain"}:
        raise ValueError("local attachment URL is not allowed")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
        raise ValueError("private attachment address is not allowed")


def inspect_attachment(
    attachment: ResearchAttachment,
    query: ProductQuery,
    *,
    client: httpx.Client | None = None,
    timeout_seconds: float = 10.0,
    max_bytes: int = DEFAULT_MAX_ATTACHMENT_BYTES,
) -> AttachmentIdentityEvidence:
    try:
        _validate_public_url(attachment.url)
    except ValueError as exc:
        return AttachmentIdentityEvidence(
            attachment.name,
            attachment.url,
            AttachmentIdentityStatus.DOWNLOAD_FAILED,
            error_type=type(exc).__name__,
            error_message=_safe_error(exc),
        )

    owns_client = client is None
    active_client = client or httpx.Client(timeout=timeout_seconds, follow_redirects=True)
    try:
        try:
            response = active_client.get(attachment.url)
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > max_bytes:
                raise AttachmentTooLargeError(f"attachment exceeds {max_bytes} bytes")
            data = response.content
            if len(data) > max_bytes:
                raise AttachmentTooLargeError(f"attachment exceeds {max_bytes} bytes")
        except AttachmentTooLargeError as exc:
            return AttachmentIdentityEvidence(
                attachment.name,
                attachment.url,
                AttachmentIdentityStatus.TOO_LARGE,
                error_type=type(exc).__name__,
                error_message=_safe_error(exc),
            )
        except Exception as exc:
            return AttachmentIdentityEvidence(
                attachment.name,
                attachment.url,
                AttachmentIdentityStatus.DOWNLOAD_FAILED,
                error_type=type(exc).__name__,
                error_message=_safe_error(exc),
            )

        try:
            text = extract_attachment_text(name=attachment.name, url=attachment.url, data=data)
        except UnsupportedAttachmentError as exc:
            return AttachmentIdentityEvidence(
                attachment.name,
                attachment.url,
                AttachmentIdentityStatus.UNSUPPORTED,
                error_type=type(exc).__name__,
                error_message=_safe_error(exc),
            )
        except Exception as exc:
            return AttachmentIdentityEvidence(
                attachment.name,
                attachment.url,
                AttachmentIdentityStatus.PARSE_FAILED,
                error_type=type(exc).__name__,
                error_message=_safe_error(exc),
            )

        status, model_found, manufacturer_found, excerpt = classify_attachment_identity(text, query)
        return AttachmentIdentityEvidence(
            attachment.name,
            attachment.url,
            status,
            model_found=model_found,
            manufacturer_found=manufacturer_found,
            excerpt=excerpt,
        )
    finally:
        if owns_client:
            active_client.close()


def inspect_record_attachments(
    record: G2BResearchRecord,
    query: ProductQuery,
    *,
    max_attachments: int = 3,
    timeout_seconds: float = 10.0,
    max_bytes: int = DEFAULT_MAX_ATTACHMENT_BYTES,
) -> tuple[AttachmentIdentityEvidence, ...]:
    if max_attachments < 1:
        raise ValueError("max_attachments must be positive")
    if not record.attachments:
        return ()
    results: list[AttachmentIdentityEvidence] = []
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
        for attachment in record.attachments[:max_attachments]:
            results.append(
                inspect_attachment(
                    attachment,
                    query,
                    client=client,
                    timeout_seconds=timeout_seconds,
                    max_bytes=max_bytes,
                )
            )
    return tuple(results)
