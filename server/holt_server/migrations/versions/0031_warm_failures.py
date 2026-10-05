"""Warm pass (warm.py): the seeds whose report failed, and when each may be
tried again, so a failing seed goes to the back instead of first every pass.

One new table: the release before this one neither reads nor writes it. It
starts with the seeds the warm pass has already failed on (the failed warm
jobs in `jobs` with no report since), so the first pass on this release does
not ask GitHub for every one of them once more.

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-05
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import timedelta

import sqlalchemy as sa
from alembic import op

revision: str = '0031'
down_revision: str | Sequence[str] | None = '0030'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


log = logging.getLogger("holt_server.migrations")

# As warm.py had them when this was written: a failed seed waits six hours,
# doubling with each failure in a row; one that isn't on GitHub, a month.
# However often a seed has failed so far, it starts at three in a row (a day).
RETRY_HOURS = 6
NOT_FOUND_RETRY_HOURS = 30 * 24
START_AT_MOST = 3
# The repository's own failures. A rate limit or a full queue is nobody's.
CODES = ("upstream", "not_found", "internal")
BADGE_PRIORITY = 10


def known_failures(bind) -> list[dict]:
    jobs = sa.table(
        "jobs", sa.column("repo"), sa.column("repo_key"), sa.column("kind"), sa.column("mode"),
        sa.column("days"), sa.column("status"), sa.column("priority"),
        sa.column("error", sa.JSON), sa.column("finished_at", sa.DateTime(timezone=True)))
    reports = sa.table(
        "reports", sa.column("repo_key"), sa.column("mode"), sa.column("days"),
        sa.column("created_at", sa.DateTime(timezone=True)))
    failed = bind.execute(
        sa.select(jobs.c.repo, jobs.c.repo_key, jobs.c.error, jobs.c.finished_at)
        .where(jobs.c.status == "error", jobs.c.kind == "analysis", jobs.c.mode == "rules",
               jobs.c.days == 7, jobs.c.priority >= BADGE_PRIORITY,
               jobs.c.repo_key.isnot(None), jobs.c.finished_at.isnot(None))
        .order_by(jobs.c.finished_at)).all()
    if not failed:
        return []
    reported = dict(bind.execute(
        sa.select(reports.c.repo_key, sa.func.max(reports.c.created_at))
        .where(reports.c.mode == "rules", reports.c.days == 7)
        .group_by(reports.c.repo_key)).all())
    rows: dict[str, dict] = {}
    for repo, key, error, at in failed:
        code = (error or {}).get("code") if isinstance(error, dict) else None
        if code not in CODES or (key in reported and reported[key] >= at):
            continue
        row = rows.setdefault(key, {"repo_key": key, "failures": 0, "first_failed_at": at})
        row.update(repo=repo, code=code, last_failed_at=at,
                   failures=min(row["failures"] + 1, START_AT_MOST))
    for row in rows.values():
        hours = (NOT_FOUND_RETRY_HOURS if row["code"] == "not_found"
                 else RETRY_HOURS * 2 ** (row["failures"] - 1))
        row["retry_at"] = row["last_failed_at"] + timedelta(hours=hours)
    return list(rows.values())


def upgrade() -> None:
    table = op.create_table('warm_failures',
    sa.Column('repo_key', sa.String(length=200), nullable=False),
    sa.Column('repo', sa.String(length=200), nullable=False),
    sa.Column('code', sa.String(length=20), nullable=False),
    sa.Column('failures', sa.Integer(), nullable=False),
    sa.Column('first_failed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_failed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('retry_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('repo_key')
    )
    # A head start, not something the release needs: if the old rows can't be
    # read, the table starts empty and the deploy goes on.
    bind = op.get_bind()
    try:
        with bind.begin_nested():
            rows = known_failures(bind)
            if rows:
                op.bulk_insert(table, rows)
        log.info("warm_failures starts with %d seeds that have failed before", len(rows))
    except Exception:  # noqa: BLE001
        log.exception("warm_failures starts empty: reading the failed jobs failed")


def downgrade() -> None:
    op.drop_table('warm_failures')
