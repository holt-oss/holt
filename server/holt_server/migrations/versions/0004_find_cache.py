"""find_cache (PR #35).

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-26
"""

import sqlalchemy as sa
from alembic import op

from holt_server.migrations._util import create_table

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Main created this with create_all before migrations; only if missing.
    create_table(
        "find_cache",
        sa.Column("key", sa.String(length=300), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("find_cache")
