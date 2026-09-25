"""Baseline: the schema of main as of PR #6 (users, jobs, reports).

Databases created by `create_all` before migrations existed are stamped at
this revision (see holt_server.migrate) instead of running it.

Revision ID: 0001
Revises:
Create Date: 2026-09-26
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

ACTIVE = sa.text("status IN ('queued', 'running')")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=200), nullable=False),
        sa.Column("plan", sa.String(length=40), nullable=False),
        sa.Column("ai_used", sa.Integer(), nullable=False),
        sa.Column("ai_period", sa.String(length=7), nullable=False),
        sa.Column("byok_provider", sa.String(length=40), nullable=True),
        sa.Column("byok_model", sa.String(length=200), nullable=True),
        sa.Column("byok_cipher", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("repo", sa.String(length=200), nullable=True),
        sa.Column("repo_key", sa.String(length=200), nullable=True),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("user_id", sa.String(length=200), nullable=True),
        sa.Column("key_source", sa.String(length=10), nullable=True),
        sa.Column("charged", sa.Boolean(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=260), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=40), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("stage", sa.String(length=80), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_jobs_status_priority", "jobs", ["status", "priority", "created_at"])
    op.create_index("ix_jobs_user_created", "jobs", ["user_id", "created_at"])
    op.create_index("ux_jobs_active_dedupe", "jobs", ["dedupe_key"], unique=True,
                    postgresql_where=ACTIVE, sqlite_where=ACTIVE)
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("repo", sa.String(length=200), nullable=False),
        sa.Column("repo_key", sa.String(length=200), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reports_lookup", "reports", ["repo_key", "mode", "days", "created_at"])


def downgrade() -> None:
    op.drop_table("reports")
    op.drop_table("jobs")
    op.drop_table("users")
