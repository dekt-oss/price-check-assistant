"""Require evidence-backed price observations and persist derivation metadata.

Revision ID: 0002_observation_provenance
Revises: 0001_phase0_foundation
"""

import hashlib
import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_observation_provenance"
down_revision: str | None = "0001_phase0_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_BACKFILL_VERSION = "legacy-observation-backfill-v1"


def _backfill_missing_evidence() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT id, source_name, source_record_id, source_url, original_title,
                   price, currency, evidence_type, collected_at
            FROM price_observations
            WHERE evidence_id IS NULL
            ORDER BY id
            """
        )
    ).mappings()

    for row in rows:
        payload = {
            "legacy_price_observation_id": row["id"],
            "source_name": row["source_name"],
            "source_record_id": row["source_record_id"],
            "source_url": row["source_url"],
            "original_title": row["original_title"],
            "price": str(row["price"]),
            "currency": row["currency"],
            "evidence_type": row["evidence_type"],
            "collected_at": str(row["collected_at"]),
            "provenance_warning": "original raw payload unavailable; synthetic migration backfill",
        }
        payload_text = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        payload_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest()
        source_name = row["source_name"] or "legacy-observation"

        evidence_id = bind.execute(
            sa.text(
                """
                SELECT id FROM raw_evidence
                WHERE source_name = :source_name AND payload_hash = :payload_hash
                """
            ),
            {"source_name": source_name, "payload_hash": payload_hash},
        ).scalar_one_or_none()

        if evidence_id is None:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO raw_evidence (
                        run_id, source_name, source_record_id, source_url, original_title,
                        payload_text, payload_hash, parser_version
                    ) VALUES (
                        NULL, :source_name, :source_record_id, :source_url, :original_title,
                        :payload_text, :payload_hash, :parser_version
                    )
                    """
                ),
                {
                    "source_name": source_name,
                    "source_record_id": row["source_record_id"],
                    "source_url": row["source_url"],
                    "original_title": row["original_title"],
                    "payload_text": payload_text,
                    "payload_hash": payload_hash,
                    "parser_version": LEGACY_BACKFILL_VERSION,
                },
            )
            evidence_id = bind.execute(
                sa.text(
                    """
                    SELECT id FROM raw_evidence
                    WHERE source_name = :source_name AND payload_hash = :payload_hash
                    """
                ),
                {"source_name": source_name, "payload_hash": payload_hash},
            ).scalar_one()

        bind.execute(
            sa.text(
                "UPDATE price_observations SET evidence_id = :evidence_id WHERE id = :observation_id"
            ),
            {"evidence_id": evidence_id, "observation_id": row["id"]},
        )


def upgrade() -> None:
    comparison_scope = sa.Enum(
        "OBSERVED_ONLY",
        "QUOTE_COMPARABLE",
        "REFERENCE_ONLY",
        "EXCLUDE",
        name="comparisonscope",
        native_enum=False,
    )

    op.add_column(
        "price_observations",
        sa.Column(
            "derivation_version",
            sa.String(length=80),
            nullable=False,
            server_default="legacy-v1",
        ),
    )
    op.add_column(
        "price_observations",
        sa.Column(
            "comparison_scope",
            comparison_scope,
            nullable=False,
            server_default="OBSERVED_ONLY",
        ),
    )
    op.add_column(
        "price_observations",
        sa.Column("comparison_note", sa.Text(), nullable=True),
    )

    _backfill_missing_evidence()

    with op.batch_alter_table("price_observations") as batch_op:
        batch_op.alter_column("evidence_id", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column(
            "derivation_version",
            existing_type=sa.String(length=80),
            existing_nullable=False,
            server_default=None,
        )
        batch_op.alter_column(
            "comparison_scope",
            existing_type=comparison_scope,
            existing_nullable=False,
            server_default=None,
        )
        batch_op.create_unique_constraint(
            "uq_price_observation_derivation",
            ["evidence_id", "product_id", "derivation_version", "evidence_type"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("price_observations") as batch_op:
        batch_op.drop_constraint("uq_price_observation_derivation", type_="unique")
        batch_op.alter_column("evidence_id", existing_type=sa.Integer(), nullable=True)

    legacy_ids = [
        row[0]
        for row in bind.execute(
            sa.text("SELECT id FROM raw_evidence WHERE parser_version = :version"),
            {"version": LEGACY_BACKFILL_VERSION},
        ).all()
    ]
    for evidence_id in legacy_ids:
        bind.execute(
            sa.text("UPDATE price_observations SET evidence_id = NULL WHERE evidence_id = :evidence_id"),
            {"evidence_id": evidence_id},
        )
        bind.execute(
            sa.text("DELETE FROM raw_evidence WHERE id = :evidence_id"),
            {"evidence_id": evidence_id},
        )

    op.drop_column("price_observations", "comparison_note")
    op.drop_column("price_observations", "comparison_scope")
    op.drop_column("price_observations", "derivation_version")
