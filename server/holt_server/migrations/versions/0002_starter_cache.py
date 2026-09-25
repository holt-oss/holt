"""starter_cache (PR #30).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-26
"""

import sqlalchemy as sa
from alembic import op

from holt_server.migrations._util import create_table

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table(
        "starter_cache",
        sa.Column("repo_key", sa.String(length=200), nullable=False),
        sa.Column("repo", sa.String(length=200), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("repo_key"),
    )


def downgrade() -> None:
    op.drop_table("starter_cache")
