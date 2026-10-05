"""Item-level MFDS registration status built from the full 형명 (model-info) dataset.

The product-info dataset behind the identity index has item number, model and company but no
cancellation status. The model-info dataset (`MdeqModlInfoService01`, ~7.4M model rows) has
the status (`RTRCN_DSCTN_DIVS_CD`, `DSCTN_RTRCN_YMD`, `EXPORT_YN`) but no company. Its per-
product-name queries take 10-60 s, while unfiltered 500-row pages take 2-8 s and parallelise,
so the whole dataset is collected once per cycle and reduced to one row per item number
(MEDDEV_ITEM_NO). Joined with the identity index on the permit number, this gives instant
"국내 정상 / 취소·취하 / 수출용" status without calling the slow API during a search.

An item counts as domestically active when at least one of its model rows is neither cancelled
nor export-only (`MedicalDeviceModelRecord.active_for_domestic_candidate`).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from purchase_price.services.mfds_device_intelligence import MedicalDeviceModelRecord

MFDS_ITEM_STATUS_SCHEMA = "mfds-item-status-sqlite-v1"
MFDS_ITEM_STATUS_PREFIX = "derived/v1/mfds-item-status"


def item_key(value: str | None) -> str:
    return "".join((value or "").split())


@dataclass(frozen=True)
class MfdsItemStatus:
    item_number: str
    product_name: str | None
    permission_type: str | None
    permit_date: str | None
    domestic_active: bool
    cancellation_status: str | None
    cancellation_date: str | None
    export_only: bool | None

    @property
    def status_label(self) -> str:
        if self.domestic_active:
            return "국내 정상"
        if self.cancellation_status:
            return "취소·취하"
        if self.export_only:
            return "수출용"
        return "상태 미확인"


def create_item_status_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS mfds_item_status (
            item_key TEXT PRIMARY KEY,
            item_number TEXT NOT NULL,
            product_name TEXT,
            permission_type TEXT,
            permit_date TEXT,
            domestic_active INTEGER NOT NULL,
            cancellation_status TEXT,
            cancellation_date TEXT,
            export_only INTEGER,
            last_seen_cycle INTEGER NOT NULL
        );
        """
    )


def upsert_item_status(
    connection: sqlite3.Connection,
    records: Iterable[MedicalDeviceModelRecord],
    *,
    cycle: int,
) -> int:
    """Fold model rows into item rows; replaying a page within a cycle is idempotent."""

    if cycle < 1:
        raise ValueError("cycle must be positive")
    create_item_status_schema(connection)
    count = 0
    for record in records:
        key = item_key(record.permit_number)
        if not key:
            continue
        connection.execute(
            """
            INSERT INTO mfds_item_status (
                item_key, item_number, product_name, permission_type, permit_date,
                domestic_active, cancellation_status, cancellation_date, export_only,
                last_seen_cycle
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_key) DO UPDATE SET
                item_number=excluded.item_number,
                product_name=CASE WHEN last_seen_cycle = excluded.last_seen_cycle THEN COALESCE(excluded.product_name, product_name) ELSE excluded.product_name END,
                permission_type=CASE WHEN last_seen_cycle = excluded.last_seen_cycle THEN COALESCE(excluded.permission_type, permission_type) ELSE excluded.permission_type END,
                permit_date=CASE WHEN last_seen_cycle = excluded.last_seen_cycle THEN COALESCE(excluded.permit_date, permit_date) ELSE excluded.permit_date END,
                domestic_active=CASE
                    WHEN last_seen_cycle = excluded.last_seen_cycle
                        THEN MAX(domestic_active, excluded.domestic_active)
                    ELSE excluded.domestic_active
                END,
                cancellation_status=CASE WHEN last_seen_cycle = excluded.last_seen_cycle THEN COALESCE(excluded.cancellation_status, cancellation_status) ELSE excluded.cancellation_status END,
                cancellation_date=CASE WHEN last_seen_cycle = excluded.last_seen_cycle THEN COALESCE(excluded.cancellation_date, cancellation_date) ELSE excluded.cancellation_date END,
                export_only=CASE WHEN last_seen_cycle = excluded.last_seen_cycle THEN COALESCE(excluded.export_only, export_only) ELSE excluded.export_only END,
                last_seen_cycle=excluded.last_seen_cycle
            """,
            (
                key,
                record.permit_number,
                record.product_name,
                record.permission_type,
                record.permit_date.isoformat() if record.permit_date else None,
                1 if record.active_for_domestic_candidate else 0,
                record.cancellation_status,
                record.cancellation_date.isoformat() if record.cancellation_date else None,
                None if record.export_only is None else int(record.export_only),
                cycle,
            ),
        )
        count += 1
    return count


def purge_items_not_seen_in_cycle(connection: sqlite3.Connection, cycle: int) -> int:
    create_item_status_schema(connection)
    cursor = connection.execute("DELETE FROM mfds_item_status WHERE last_seen_cycle <> ?", (cycle,))
    return max(int(cursor.rowcount or 0), 0)


def lookup_item_status(
    connection: sqlite3.Connection,
    item_numbers: Sequence[str | None],
) -> dict[str, MfdsItemStatus]:
    """Status keyed by whitespace-free item number; unknown items are simply absent."""

    keys = tuple(dict.fromkeys(item_key(number) for number in item_numbers if item_key(number)))
    if not keys:
        return {}
    create_item_status_schema(connection)
    placeholders = ",".join("?" for _ in keys)
    rows = connection.execute(
        f"""
        SELECT item_key, item_number, product_name, permission_type, permit_date,
               domestic_active, cancellation_status, cancellation_date, export_only
        FROM mfds_item_status WHERE item_key IN ({placeholders})
        """,
        keys,
    ).fetchall()
    return {
        row[0]: MfdsItemStatus(
            item_number=row[1],
            product_name=row[2],
            permission_type=row[3],
            permit_date=row[4],
            domestic_active=bool(row[5]),
            cancellation_status=row[6],
            cancellation_date=row[7],
            export_only=None if row[8] is None else bool(row[8]),
        )
        for row in rows
    }
