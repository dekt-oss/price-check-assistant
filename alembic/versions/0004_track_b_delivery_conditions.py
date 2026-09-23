"""Add Track B delivery and contract condition fields.

Revision ID: 0004_track_b_delivery_conditions
Revises: 0003_track_b_delivery_lines
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_track_b_delivery_conditions"
down_revision: str | None = "0003_track_b_delivery_lines"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("track_b_delivery_lines", sa.Column("contract_delivery_type", sa.Text()))
    op.add_column("track_b_delivery_lines", sa.Column("contract_type", sa.Text()))
    op.add_column("track_b_delivery_lines", sa.Column("delivery_condition", sa.Text()))


def downgrade() -> None:
    op.drop_column("track_b_delivery_lines", "delivery_condition")
    op.drop_column("track_b_delivery_lines", "contract_type")
    op.drop_column("track_b_delivery_lines", "contract_delivery_type")
