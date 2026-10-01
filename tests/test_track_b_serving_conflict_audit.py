from __future__ import annotations

import sqlite3

import pytest

from purchase_price.scripts.audit_track_b_serving_conflicts import audit_conflict_rows


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE track_b_delivery_lines (
            id INTEGER PRIMARY KEY,
            delivery_request_number TEXT NOT NULL,
            change_order TEXT NOT NULL,
            product_sequence TEXT NOT NULL,
            identity_conflict INTEGER NOT NULL,
            identity_conflict_count INTEGER NOT NULL,
            detail_code TEXT,
            product_id TEXT,
            product_title TEXT,
            unit_price NUMERIC,
            quantity NUMERIC,
            unit TEXT,
            total_amount NUMERIC,
            supplier TEXT,
            demand_institution TEXT,
            transaction_date TEXT,
            contract_delivery_type TEXT,
            contract_type TEXT,
            delivery_condition TEXT,
            raw_object_key TEXT NOT NULL
        )
        """
    )
    return connection


def _insert(
    connection: sqlite3.Connection,
    *,
    request: str,
    conflict: bool,
    conflict_count: int,
    detail_code: str = "4217210101",
    supplier: str = "공급사A",
    unit_price: int | None = 100,
) -> None:
    connection.execute(
        """
        INSERT INTO track_b_delivery_lines (
            delivery_request_number,
            change_order,
            product_sequence,
            identity_conflict,
            identity_conflict_count,
            detail_code,
            product_id,
            product_title,
            unit_price,
            quantity,
            unit,
            total_amount,
            supplier,
            demand_institution,
            transaction_date,
            contract_delivery_type,
            contract_type,
            delivery_condition,
            raw_object_key
        ) VALUES (?, '00', '1', ?, ?, ?, '12345678', ?, ?, 1, '대', ?, ?, '병원A',
                  '2026-08-21', '일반납품', '단가계약', '현장설치도', ?)
        """,
        (
            request,
            int(conflict),
            conflict_count,
            detail_code,
            "심장충격기, Example, MODEL-1",
            unit_price,
            unit_price,
            supplier,
            f"raw/v1/test/{request}.json.gz",
        ),
    )
    connection.commit()


def test_audit_conflict_rows_reports_quarantined_scope() -> None:
    connection = _connection()
    try:
        _insert(connection, request="R1", conflict=True, conflict_count=3)
        _insert(
            connection,
            request="R2",
            conflict=True,
            conflict_count=1,
            detail_code="4217210201",
            supplier="공급사B",
            unit_price=None,
        )
        _insert(connection, request="R3", conflict=False, conflict_count=0)

        report = audit_conflict_rows(connection, sample_limit=10)

        assert report["status"] == "CONFLICTS_PRESENT"
        assert report["conflict_row_count"] == 2
        assert report["conflict_event_count"] == 4
        assert report["max_conflicts_for_one_identity"] == 3
        assert report["priced_conflict_row_count"] == 1
        assert report["top_detail_codes"] == [
            ("4217210101", 1),
            ("4217210201", 1),
        ]
        assert report["samples"][0]["source_record_id"] == "delivery:R1|change:00|line:1"
        assert report["samples"][0]["unit_price"] == "100"
        assert "fail-closed" in report["interpretation"]
    finally:
        connection.close()


def test_audit_conflict_rows_clean_index() -> None:
    connection = _connection()
    try:
        _insert(connection, request="R1", conflict=False, conflict_count=0)

        report = audit_conflict_rows(connection)

        assert report["status"] == "CLEAN"
        assert report["conflict_row_count"] == 0
        assert report["conflict_event_count"] == 0
        assert report["max_conflicts_for_one_identity"] == 0
        assert report["samples"] == []
    finally:
        connection.close()


def test_audit_conflict_rows_requires_positive_sample_limit() -> None:
    connection = _connection()
    try:
        with pytest.raises(ValueError, match="sample_limit"):
            audit_conflict_rows(connection, sample_limit=0)
    finally:
        connection.close()
