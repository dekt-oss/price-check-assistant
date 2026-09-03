"""Create Phase 0 evidence foundation.

Revision ID: 0001_phase0_foundation
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_phase0_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("manufacturer", sa.String(length=200), nullable=True),
        sa.Column("product_name", sa.String(length=300), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=True),
        sa.Column("specification", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("aliases", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_products_manufacturer", "products", ["manufacturer"])
    op.create_index("ix_products_product_name", "products", ["product_name"])
    op.create_index("ix_products_model_name", "products", ["model_name"])
    op.create_index("ix_products_category", "products", ["category"])

    op.create_table(
        "collection_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_name", sa.String(length=100), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_collection_runs_source_name", "collection_runs", ["source_name"])
    op.create_index("ix_collection_runs_status", "collection_runs", ["status"])

    op.create_table(
        "raw_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("source_name", sa.String(length=100), nullable=False),
        sa.Column("source_record_id", sa.String(length=300), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("original_title", sa.Text(), nullable=True),
        sa.Column("payload_text", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=50), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["collection_runs.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("source_name", "payload_hash", name="uq_evidence_source_hash"),
    )
    op.create_index("ix_raw_evidence_run_id", "raw_evidence", ["run_id"])
    op.create_index("ix_raw_evidence_source_name", "raw_evidence", ["source_name"])
    op.create_index("ix_raw_evidence_source_record_id", "raw_evidence", ["source_record_id"])
    op.create_index("ix_raw_evidence_payload_hash", "raw_evidence", ["payload_hash"])

    evidence_type = sa.Enum(
        "CONTRACT_UNIT_PRICE",
        "SHOPPING_CONTRACT_UNIT_PRICE",
        "DELIVERY_ORDER_UNIT_PRICE",
        "PUBLIC_SALE_PRICE",
        "BID_BASE_AMOUNT",
        "BUDGET_AMOUNT",
        "QUOTE_SAMPLE",
        "UNKNOWN",
        name="evidencetype",
        native_enum=False,
    )
    source_type = sa.Enum(
        "PUBLIC_CONTRACT",
        "PROCUREMENT",
        "MANUFACTURER",
        "B2B",
        "RETAIL",
        "OTHER",
        name="sourcetype",
        native_enum=False,
    )
    match_grade = sa.Enum("A", "B", "C", "D", "X", name="matchgrade", native_enum=False)

    op.create_table(
        "price_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("evidence_id", sa.Integer(), nullable=True),
        sa.Column("price", sa.Numeric(18, 2), nullable=False),
        sa.Column("evidence_type", evidence_type, nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 3), nullable=True),
        sa.Column("unit", sa.String(length=50), nullable=True),
        sa.Column("total_amount", sa.Numeric(20, 2), nullable=True),
        sa.Column("vat_status", sa.String(length=50), nullable=True),
        sa.Column("conditions", sa.Text(), nullable=True),
        sa.Column("source_type", source_type, nullable=False),
        sa.Column("source_name", sa.String(length=300), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_record_id", sa.String(length=300), nullable=True),
        sa.Column("original_title", sa.Text(), nullable=True),
        sa.Column("collected_at", sa.Date(), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=True),
        sa.Column("match_grade", match_grade, nullable=False),
        sa.Column("match_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_id"], ["raw_evidence.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_price_observations_product_id", "price_observations", ["product_id"])
    op.create_index("ix_price_observations_evidence_id", "price_observations", ["evidence_id"])
    op.create_index("ix_price_observations_evidence_type", "price_observations", ["evidence_type"])
    op.create_index("ix_price_observations_source_record_id", "price_observations", ["source_record_id"])


def downgrade() -> None:
    op.drop_table("price_observations")
    op.drop_table("raw_evidence")
    op.drop_table("collection_runs")
    op.drop_table("products")
