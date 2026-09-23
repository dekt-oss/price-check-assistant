from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from purchase_price.services.matching import normalize_text

MFDS_PRODUCT_INFO_BASE_URL = "https://apis.data.go.kr/1471000/MdeqStdCdPrdtInfoService03"
MFDS_PRODUCT_INFO_OPERATION = "getMdeqStdCdPrdtInfoInq03"
MFDS_PRODUCT_INFO_RAW_OPERATION = "mfds-product-info-page"
MFDS_IDENTITY_SCHEMA = "mfds-identity-sqlite-v1"


@dataclass(frozen=True)
class MfdsIdentityRecord:
    udi_di: str | None
    product_name: str | None
    classification_no: str | None
    grade: str | None
    permit_number: str | None
    permit_date: str | None
    model_name: str | None
    trade_name: str | None
    registered_company: str | None
    source_payload_sha256: str | None = None

    @property
    def permit_key(self) -> str:
        return normalize_text(self.permit_number)

    @property
    def model_key(self) -> str:
        return normalize_text(self.model_name)

    @property
    def company_key(self) -> str:
        return normalize_text(self.registered_company)

    @property
    def product_key(self) -> str:
        return normalize_text(self.product_name)


@dataclass(frozen=True)
class MfdsIdentityLookup:
    status: str
    query: str
    match_type: str | None
    records: tuple[MfdsIdentityRecord, ...]

    @property
    def permit_numbers(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    item.permit_number.strip()
                    for item in self.records
                    if item.permit_number and item.permit_number.strip()
                }
            )
        )

    @property
    def model_names(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    item.model_name.strip()
                    for item in self.records
                    if item.model_name and item.model_name.strip()
                }
            )
        )

    @property
    def companies(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    item.registered_company.strip()
                    for item in self.records
                    if item.registered_company and item.registered_company.strip()
                }
            )
        )

    @property
    def product_names(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    item.product_name.strip()
                    for item in self.records
                    if item.product_name and item.product_name.strip()
                }
            )
        )


def _text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def parse_mfds_product_info_record(
    item: Mapping[str, Any],
    *,
    source_payload_sha256: str | None = None,
) -> MfdsIdentityRecord:
    return MfdsIdentityRecord(
        udi_di=_text(item.get("UDIDI_CD")),
        product_name=_text(item.get("PRDLST_NM")),
        classification_no=_text(item.get("MDEQ_CLSF_NO")),
        grade=_text(item.get("CLSF_NO_GRAD_CD")),
        permit_number=_text(item.get("PERMIT_NO")),
        permit_date=_text(item.get("PRMSN_YMD")),
        model_name=_text(item.get("FOML_INFO")),
        trade_name=_text(item.get("PRDT_NM_INFO")),
        registered_company=_text(item.get("MNFT_IPRT_ENTP_NM")),
        source_payload_sha256=source_payload_sha256,
    )


def create_identity_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS mfds_identity (
            row_key TEXT PRIMARY KEY,
            udi_di TEXT,
            product_name TEXT,
            product_key TEXT NOT NULL,
            classification_no TEXT,
            grade TEXT,
            permit_number TEXT,
            permit_key TEXT NOT NULL,
            permit_date TEXT,
            model_name TEXT,
            model_key TEXT NOT NULL,
            trade_name TEXT,
            registered_company TEXT,
            company_key TEXT NOT NULL,
            source_payload_sha256 TEXT,
            last_seen_cycle INTEGER NOT NULL DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_mfds_identity_permit
            ON mfds_identity(permit_key);
        CREATE INDEX IF NOT EXISTS idx_mfds_identity_model
            ON mfds_identity(model_key);
        CREATE INDEX IF NOT EXISTS idx_mfds_identity_company
            ON mfds_identity(company_key);
        CREATE INDEX IF NOT EXISTS idx_mfds_identity_product
            ON mfds_identity(product_key);
        CREATE INDEX IF NOT EXISTS idx_mfds_identity_udi
            ON mfds_identity(udi_di);
        """
    )
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(mfds_identity)").fetchall()
    }
    if "last_seen_cycle" not in columns:
        connection.execute(
            "ALTER TABLE mfds_identity ADD COLUMN last_seen_cycle INTEGER NOT NULL DEFAULT 1"
        )


def _row_key(record: MfdsIdentityRecord) -> str:
    parts = (
        normalize_text(record.udi_di),
        record.permit_key,
        record.model_key,
        record.company_key,
        record.product_key,
    )
    return "|".join(parts)


def upsert_identity_records(
    connection: sqlite3.Connection,
    records: Iterable[MfdsIdentityRecord],
    *,
    cycle: int = 1,
) -> int:
    if cycle < 1:
        raise ValueError("cycle must be positive")
    create_identity_schema(connection)
    count = 0
    for record in records:
        if not any((record.udi_di, record.permit_number, record.model_name, record.product_name)):
            continue
        connection.execute(
            """
            INSERT INTO mfds_identity (
                row_key, udi_di, product_name, product_key, classification_no, grade,
                permit_number, permit_key, permit_date, model_name, model_key, trade_name,
                registered_company, company_key, source_payload_sha256, last_seen_cycle
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(row_key) DO UPDATE SET
                udi_di=excluded.udi_di,
                product_name=excluded.product_name,
                classification_no=excluded.classification_no,
                grade=excluded.grade,
                permit_number=excluded.permit_number,
                permit_date=excluded.permit_date,
                model_name=excluded.model_name,
                trade_name=excluded.trade_name,
                registered_company=excluded.registered_company,
                source_payload_sha256=excluded.source_payload_sha256,
                last_seen_cycle=excluded.last_seen_cycle
            """,
            (
                _row_key(record),
                record.udi_di,
                record.product_name,
                record.product_key,
                record.classification_no,
                record.grade,
                record.permit_number,
                record.permit_key,
                record.permit_date,
                record.model_name,
                record.model_key,
                record.trade_name,
                record.registered_company,
                record.company_key,
                record.source_payload_sha256,
                cycle,
            ),
        )
        count += 1
    return count


def purge_identity_records_not_seen_in_cycle(
    connection: sqlite3.Connection,
    cycle: int,
) -> int:
    if cycle < 1:
        raise ValueError("cycle must be positive")
    create_identity_schema(connection)
    cursor = connection.execute(
        "DELETE FROM mfds_identity WHERE last_seen_cycle <> ?",
        (cycle,),
    )
    return max(int(cursor.rowcount or 0), 0)


def _records_from_rows(rows: Iterable[sqlite3.Row]) -> tuple[MfdsIdentityRecord, ...]:
    return tuple(
        MfdsIdentityRecord(
            udi_di=row["udi_di"],
            product_name=row["product_name"],
            classification_no=row["classification_no"],
            grade=row["grade"],
            permit_number=row["permit_number"],
            permit_date=row["permit_date"],
            model_name=row["model_name"],
            trade_name=row["trade_name"],
            registered_company=row["registered_company"],
            source_payload_sha256=row["source_payload_sha256"],
        )
        for row in rows
    )


def lookup_identity(
    connection: sqlite3.Connection,
    query: str,
    *,
    limit: int = 200,
) -> MfdsIdentityLookup:
    cleaned = query.strip()
    if not cleaned:
        return MfdsIdentityLookup("empty", cleaned, None, ())
    key = normalize_text(cleaned)
    connection.row_factory = sqlite3.Row
    create_identity_schema(connection)

    for match_type, column, value in (
        ("permit", "permit_key", key),
        ("udi", "udi_di", cleaned),
        ("model", "model_key", key),
        ("company", "company_key", key),
        ("product", "product_key", key),
    ):
        if not value:
            continue
        rows = connection.execute(
            f"""
            SELECT udi_di, product_name, classification_no, grade, permit_number,
                   permit_date, model_name, trade_name, registered_company,
                   source_payload_sha256
            FROM mfds_identity
            WHERE {column} = ?
            ORDER BY permit_number, model_name, registered_company, udi_di
            LIMIT ?
            """,
            (value, limit),
        ).fetchall()
        if rows:
            return MfdsIdentityLookup(
                "success",
                cleaned,
                match_type,
                _records_from_rows(rows),
            )
    return MfdsIdentityLookup("success_0", cleaned, None, ())


def lookup_same_product(
    connection: sqlite3.Connection,
    product_name: str,
    *,
    limit: int = 500,
) -> tuple[MfdsIdentityRecord, ...]:
    key = normalize_text(product_name)
    if not key:
        return ()
    connection.row_factory = sqlite3.Row
    create_identity_schema(connection)
    rows = connection.execute(
        """
        SELECT udi_di, product_name, classification_no, grade, permit_number,
               permit_date, model_name, trade_name, registered_company,
               source_payload_sha256
        FROM mfds_identity
        WHERE product_key = ?
        ORDER BY permit_number, model_name, registered_company, udi_di
        LIMIT ?
        """,
        (key, limit),
    ).fetchall()
    return _records_from_rows(rows)


def open_identity_index(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    create_identity_schema(connection)
    return connection
