"""Schema migrations: fresh databases, pre-migration databases, and drift.

Runs on SQLite, or on the Postgres in HOLT_TEST_DATABASE_URL (as CI does).
"""

from __future__ import annotations

import asyncio
import os

import pytest
from holt_server import migrate
from holt_server.db import Base, Database
from sqlalchemy import inspect, text


@pytest.fixture
def db(tmp_path, drop_everything):
    url = os.environ.get("HOLT_TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{tmp_path / 'm.db'}"
    database = Database(url)

    async def reset():
        await drop_everything(database.engine)
        await database.dispose()

    asyncio.run(reset())
    return database


# Each asyncio.run is its own event loop, and asyncpg connections can't move
# between loops: every step closes the pool it used.
def run(db: Database, fn):
    async def go():
        try:
            async with db.engine.begin() as conn:
                return await conn.run_sync(fn)
        finally:
            await db.dispose()
    return asyncio.run(go())


def upgrade(db: Database) -> None:
    async def go():
        try:
            await db.migrate()
        finally:
            await db.dispose()
    asyncio.run(go())


def revision(conn) -> str | None:
    return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()


def head() -> str:
    from alembic.script import ScriptDirectory

    return ScriptDirectory.from_config(migrate.config()).get_current_head()


def test_fresh_database_migrates_to_head_matching_the_models(db):
    upgrade(db)
    assert run(db, revision) == head()
    assert run(db, migrate.differences) == []
    upgrade(db)  # a second run changes nothing
    assert run(db, revision) == head()


def baseline_schema(conn) -> None:
    """What `create_all` made in production before migrations: the 0001
    schema with no alembic_version table."""
    from alembic import command

    command.upgrade(migrate.config(conn), migrate.BASELINE)
    conn.execute(text("DROP TABLE alembic_version"))


def test_create_all_database_is_stamped_and_keeps_its_rows(db):
    run(db, baseline_schema)
    run(db, lambda c: c.execute(text(
        "INSERT INTO users (id, plan, ai_used, ai_period, created_at) "
        "VALUES ('u1', 'free', 2, '2026-09', CURRENT_TIMESTAMP)")))
    upgrade(db)
    assert run(db, revision) == head()
    assert run(db, lambda c: c.execute(text("SELECT ai_used FROM users")).scalar()) == 2
    assert run(db, migrate.differences) == []


def test_ai_credits_migration_deletes_saved_keys_and_keeps_users(db):
    from alembic import command

    run(db, lambda c: command.upgrade(migrate.config(c), "0002"))
    run(db, lambda c: c.execute(text(
        "INSERT INTO users (id, plan, ai_used, ai_period, byok_provider, byok_model, "
        "byok_cipher, created_at) VALUES "
        "('keyed', 'free', 1, '2026-09', 'openai', 'gpt-5-mini', 'AQID-sealed', CURRENT_TIMESTAMP), "
        "('plain', 'pro', 0, '', NULL, NULL, NULL, CURRENT_TIMESTAMP)")))
    run(db, lambda c: command.upgrade(migrate.config(c), "0003"))

    got = run(db, lambda c: c.execute(text(
        "SELECT id, plan, byok_provider, byok_model, byok_cipher, ai_credits, "
        "credits_granted_at, last_claim_at FROM users ORDER BY id")).all())
    assert [tuple(r) for r in got] == [
        ("keyed", "free", None, None, None, 0, None, None),
        ("plain", "pro", None, None, None, 0, None, None),
    ]
    # The release before this one still inserts users without the new columns.
    run(db, lambda c: c.execute(text(
        "INSERT INTO users (id, plan, ai_used, ai_period, created_at) "
        "VALUES ('older', 'free', 0, '2026-09', CURRENT_TIMESTAMP)")))
    assert run(db, lambda c: c.execute(text(
        "SELECT ai_credits FROM users WHERE id = 'older'")).scalar()) == 0
    # Later migrations add their own tables: compare the models at head.
    run(db, lambda c: command.upgrade(migrate.config(c), "head"))
    assert run(db, migrate.differences) == []

    run(db, lambda c: command.downgrade(migrate.config(c), "0002"))
    tables = run(db, lambda c: inspect(c).get_table_names())
    assert "credit_events" not in tables
    cols = {col["name"] for col in run(db, lambda c: inspect(c).get_columns("users"))}
    assert "ai_credits" not in cols and "byok_cipher" in cols


def test_partial_schema_without_history_is_refused(db):
    run(db, lambda c: Base.metadata.tables["users"].create(c))
    with pytest.raises(RuntimeError, match="some of the baseline tables"):
        upgrade(db)
    assert "alembic_version" not in run(db, lambda c: inspect(c).get_table_names())


def test_baseline_tables_are_the_models_tables():
    # A new model needs a new migration, not a bigger baseline.
    assert migrate.BASELINE_TABLES <= set(Base.metadata.tables)


def test_entitlements_migration_keeps_the_ledger_as_free_credits(db):
    from alembic import command

    run(db, lambda c: command.upgrade(migrate.config(c), "0005"))
    run(db, lambda c: c.execute(text(
        "INSERT INTO users (id, plan, ai_used, ai_period, ai_credits, created_at) "
        "VALUES ('u1', 'free', 0, '', 2, CURRENT_TIMESTAMP)")))
    run(db, lambda c: c.execute(text(
        "INSERT INTO credit_events (user_id, kind, amount, job_id, created_at) VALUES "
        "('u1', 'grant', 3, NULL, CURRENT_TIMESTAMP), "
        "('u1', 'spend', -1, 'j1', CURRENT_TIMESTAMP)")))
    run(db, lambda c: command.upgrade(migrate.config(c), "0006"))

    got = run(db, lambda c: c.execute(text(
        "SELECT kind, amount, source, feature, lot_id FROM credit_events ORDER BY id")).all())
    assert [tuple(r) for r in got] == [("grant", 3, "free", None, None),
                                       ("spend", -1, "free", "ai_report", None)]
    assert run(db, lambda c: c.execute(text(
        "SELECT plan, plan_expires_at, ai_credits FROM users")).one()) == ("free", None, 2)
    # The release before this one still writes ledger rows without a source.
    run(db, lambda c: c.execute(text(
        "INSERT INTO credit_events (user_id, kind, amount, job_id, created_at) "
        "VALUES ('u1', 'claim', 1, NULL, CURRENT_TIMESTAMP)")))
    assert run(db, lambda c: c.execute(text(
        "SELECT source FROM credit_events WHERE kind = 'claim'")).scalar()) == "free"
    run(db, lambda c: command.upgrade(migrate.config(c), "head"))
    assert run(db, migrate.differences) == []

    run(db, lambda c: command.downgrade(migrate.config(c), "0005"))
    tables = run(db, lambda c: inspect(c).get_table_names())
    assert not {"credit_lots", "plan_events", "plan_usage"} & set(tables)
    assert run(db, lambda c: c.execute(text("SELECT count(*) FROM credit_events")).scalar()) == 3


def test_contribution_state_migration_is_idempotent(db):
    """Staging got 0026's columns under an earlier revision number: upgrading
    over them, and downgrading when they're gone, both work."""
    from alembic import command

    state = {"node_id", "turn", "turn_at", "first_reply_at", "last_activity_at",
             "review_decision"}
    columns = lambda c: {x["name"] for x in inspect(c).get_columns("contributions")}  # noqa: E731
    run(db, lambda c: command.upgrade(migrate.config(c), "0026"))
    assert state <= run(db, columns)
    run(db, lambda c: command.stamp(migrate.config(c), "0025"))  # columns there, version behind
    run(db, lambda c: command.upgrade(migrate.config(c), "head"))
    assert run(db, revision) == head()
    assert run(db, migrate.differences) == []

    run(db, lambda c: command.downgrade(migrate.config(c), "0025"))
    assert not state & run(db, columns)
    run(db, lambda c: command.stamp(migrate.config(c), "0026"))  # version ahead, columns gone
    run(db, lambda c: command.downgrade(migrate.config(c), "0025"))
    assert run(db, revision) == "0025"


def test_warm_failures_migration_starts_from_the_failures_already_in_the_jobs_table(db):
    # The seeds the warm pass kept failing on are known before the first pass
    # on the new release, so it doesn't start with all of them once more.
    from datetime import UTC, datetime, timedelta

    import sqlalchemy as sa
    from alembic import command

    run(db, lambda c: command.upgrade(migrate.config(c), "0030"))
    t0 = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)

    def job(repo, code, minutes, priority=10):
        return {"id": f"{repo}-{minutes}"[:32], "kind": "analysis", "repo": repo,
                "repo_key": repo.lower(), "mode": "rules", "days": 7, "params": {},
                "charged": False, "priority": priority, "status": "error", "stage": "Failed",
                "progress": 0.0, "error": {"code": code, "message": "m"},
                "created_at": t0, "finished_at": t0 + timedelta(minutes=minutes)}

    def fill(c):
        meta = sa.MetaData()
        jobs = sa.Table("jobs", meta, autoload_with=c)
        reports = sa.Table("reports", meta, autoload_with=c)
        c.execute(sa.insert(jobs), [
            *[job("Big/Repo", "upstream", m) for m in (0, 30, 60, 90)],
            job("gone/away", "not_found", 10),
            job("octo/fixed", "upstream", 10),       # a report was made since
            job("octo/limited", "rate_limited", 10),  # GitHub's doing, not the repository's
            job("octo/person", "upstream", 10, priority=0),  # a person's check, not a warm report
        ])
        c.execute(sa.insert(reports), [{
            "repo": "octo/fixed", "repo_key": "octo/fixed", "mode": "rules", "days": 7,
            "report": {}, "created_at": t0 + timedelta(minutes=20)}])

    run(db, fill)
    run(db, lambda c: command.upgrade(migrate.config(c), "0031"))
    got = run(db, lambda c: c.execute(text(
        "SELECT repo_key, repo, code, failures, last_failed_at, retry_at FROM warm_failures "
        "ORDER BY repo_key")).all())

    def at(value):  # SQLite hands back text; Postgres, a datetime
        when = value if isinstance(value, datetime) else datetime.fromisoformat(value)
        return when.replace(tzinfo=None)

    naive = t0.replace(tzinfo=None)
    assert [(r[0], r[1], r[2], r[3]) for r in got] == [
        ("big/repo", "Big/Repo", "upstream", 3), ("gone/away", "gone/away", "not_found", 1)]
    # Three or more failures in a row: a day from the last one. Not there: a month.
    assert at(got[0][4]) == naive + timedelta(minutes=90)
    assert at(got[0][5]) == naive + timedelta(minutes=90, hours=24)
    assert at(got[1][5]) == naive + timedelta(minutes=10, days=30)
    run(db, lambda c: command.upgrade(migrate.config(c), "head"))
    assert run(db, migrate.differences) == []
