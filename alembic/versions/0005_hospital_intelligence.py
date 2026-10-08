"""Add hospital master/financial/metric, news keyword/item and data source log tables.

Revision ID: 0005_hospital_intelligence
Revises: 0004_track_b_delivery_conditions
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005_hospital_intelligence"
down_revision: str | None = "0004_track_b_delivery_conditions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hospital_master",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("hospital_id", sa.String(40), nullable=False, unique=True),
        sa.Column("canonical_name", sa.String(200), nullable=False, unique=True),
        sa.Column("short_name", sa.String(100)),
        sa.Column("aliases_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("foundation", sa.String(200)),
        sa.Column("network", sa.String(200)),
        sa.Column("region", sa.String(50)),
        sa.Column("hospital_type", sa.String(50)),
        sa.Column("ownership", sa.String(50)),
        sa.Column("bed_count", sa.Integer()),
        sa.Column("bed_count_as_of", sa.Date()),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    for column in ("network", "region", "hospital_type"):
        op.create_index(f"ix_hospital_master_{column}", "hospital_master", [column])

    op.create_table(
        "hospital_financial",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "hospital_id",
            sa.String(40),
            sa.ForeignKey("hospital_master.hospital_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_period_start", sa.Date()),
        sa.Column("fiscal_period_end", sa.Date()),
        sa.Column("account_code", sa.String(60), nullable=False),
        sa.Column("account_name", sa.String(200)),
        sa.Column("amount", sa.Numeric(20, 0)),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column(
            "fetched_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "hospital_id",
            "fiscal_year",
            "account_code",
            "source",
            name="uq_hospital_financial_account",
        ),
    )
    op.create_index("ix_hospital_financial_hospital_id", "hospital_financial", ["hospital_id"])
    op.create_index("ix_hospital_financial_fiscal_year", "hospital_financial", ["fiscal_year"])

    op.create_table(
        "hospital_metric",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "hospital_id",
            sa.String(40),
            sa.ForeignKey("hospital_master.hospital_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("metric_key", sa.String(60), nullable=False),
        sa.Column("value", sa.Numeric(24, 6)),
        sa.Column("inputs_json", sa.Text()),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("hospital_id", "fiscal_year", "metric_key", name="uq_hospital_metric"),
    )
    op.create_index("ix_hospital_metric_hospital_id", "hospital_metric", ["hospital_id"])
    op.create_index("ix_hospital_metric_fiscal_year", "hospital_metric", ["fiscal_year"])

    op.create_table(
        "news_keyword",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("text", sa.String(200), nullable=False),
        sa.Column("group_key", sa.String(60), nullable=False),
        sa.Column("group_name", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("alert", sa.String(20), nullable=False, server_default="none"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("group_key", "text", name="uq_news_keyword_group_text"),
    )
    op.create_index("ix_news_keyword_group_key", "news_keyword", ["group_key"])

    op.create_table(
        "news_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("article_id", sa.String(600), nullable=False, unique=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_domain", sa.String(200)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("naver_link", sa.Text()),
        sa.Column("keywords_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="new"),
        sa.Column(
            "detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_news_item_published_at", "news_item", ["published_at"])
    op.create_index("ix_news_item_status", "news_item", ["status"])

    op.create_table(
        "data_source_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_name", sa.String(100), nullable=False),
        sa.Column("query_text", sa.Text()),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
    )
    op.create_index("ix_data_source_log_source_name", "data_source_log", ["source_name"])


def downgrade() -> None:
    for table in (
        "data_source_log",
        "news_item",
        "news_keyword",
        "hospital_metric",
        "hospital_financial",
        "hospital_master",
    ):
        op.drop_table(table)
