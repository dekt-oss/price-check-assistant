"""Add a read-optimized serving index for R2 Track B delivery-line history.

Revision ID: 0003_track_b_delivery_lines
Revises: 0002_observation_provenance
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_track_b_delivery_lines"
down_revision: str | None = "0002_observation_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "track_b_delivery_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("delivery_request_number", sa.String(120), nullable=False),
        sa.Column("change_order", sa.String(30), nullable=False),
        sa.Column("change_order_number", sa.Integer(), nullable=False),
        sa.Column("product_sequence", sa.String(40), nullable=False),
        sa.Column("item_sha256", sa.String(64), nullable=False),
        sa.Column("raw_object_key", sa.Text(), nullable=False),
        sa.Column("raw_payload_sha256", sa.String(64), nullable=False),
        sa.Column("detail_code", sa.String(10), nullable=False),
        sa.Column("product_id", sa.String(100)),
        sa.Column("product_title", sa.Text()),
        sa.Column("product_class", sa.String(300)),
        sa.Column("class_key", sa.String(300)),
        sa.Column("manufacturer", sa.String(300)),
        sa.Column("manufacturer_qualifier", sa.String(50)),
        sa.Column("model_name", sa.String(300)),
        sa.Column("model_qualifier", sa.String(50)),
        sa.Column("model_qualifier_verified_as_origin", sa.Boolean(), nullable=False),
        sa.Column("model_key", sa.String(300)),
        sa.Column("specification", sa.Text()),
        sa.Column("unit_price", sa.Numeric(18, 2)),
        sa.Column("quantity", sa.Numeric(18, 3)),
        sa.Column("unit", sa.String(50)),
        sa.Column("total_amount", sa.Numeric(20, 2)),
        sa.Column("amount_check", sa.String(30), nullable=False),
        sa.Column("transaction_date", sa.Date()),
        sa.Column("supplier", sa.String(300)),
        sa.Column("demand_institution", sa.String(300)),
        sa.Column("api_params_json", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "delivery_request_number",
            "change_order",
            "product_sequence",
            name="uq_track_b_stable_identity",
        ),
        sa.UniqueConstraint(
            "delivery_request_number",
            "change_order_number",
            "product_sequence",
            name="uq_track_b_numeric_change_order",
        ),
    )
    for column in (
        "delivery_request_number",
        "detail_code",
        "product_id",
        "class_key",
        "model_key",
    ):
        op.create_index(f"ix_track_b_delivery_lines_{column}", "track_b_delivery_lines", [column])


def downgrade() -> None:
    op.drop_table("track_b_delivery_lines")
