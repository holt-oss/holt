"""Migrations: the models match the latest revision, and an existing database
from main (built by create_all, no alembic_version) upgrades in place.

Set HOLT_TEST_DATABASE_URL to run these against Postgres as well.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from holt_server import migrate as mig
from holt_server.db import Base, Database, Job, User
from sqlalchemy import inspect, text


@pytest.fixture
def db(tmp_path):
    url = os.environ.get("HOLT_TEST_DATABASE_URL") or \
        f"sqlite+aiosqlite:///{tmp_path / 'm.db'}"
    database = Database(url, pooled=False)

    async def wipe():
        async with database.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))

    asyncio.run(wipe())
    yield database
    asyncio.run(database.engine.dispose())


def run(database, fn, *args):
    async def go():
        async with database.engine.begin() as conn:
            return await conn.run_sync(fn, *args)
    return asyncio.run(go())


def to(revision):
    def step(conn):
        command.upgrade(mig.config(conn), revision)
    return step


def sql(statement, params=None):
    def step(conn):
        return conn.execute(text(statement), params or {})
    return step


def columns(table):
    return lambda conn: {c["name"] for c in inspect(conn).get_columns(table)}


def main_schema_without_alembic(database):
    """What staging has: main's tables, made by create_all, no alembic_version."""
    run(database, to("0002"))
    run(database, sql("DROP TABLE alembic_version"))
    now = datetime.now(UTC)
    run(database, sql(
        "INSERT INTO users (id, plan, ai_used, ai_period, created_at) "
        "VALUES ('old-user', 'free', 2, '2026-09', :now)", {"now": now}))
    run(database, sql(
        "INSERT INTO jobs (id, kind, repo, repo_key, mode, days, params, charged, priority, "
        "status, stage, progress, created_at) VALUES ('oldjob', 'analysis', 'o/r', 'o/r', "
        "'rules', 7, '{}', false, 0, 'done', 'Done', 1.0, :now)", {"now": now}))


def test_models_match_the_latest_migration(db):
    asyncio.run(mig.migrate(db.engine))

    def diff(conn):
        return compare_metadata(MigrationContext.configure(conn), Base.metadata)

    assert run(db, diff) == []


def test_existing_main_database_upgrades_in_place(db):
    main_schema_without_alembic(db)
    asyncio.run(mig.migrate(db.engine))
    assert asyncio.run(mig.is_current(db.engine))
    assert {"quota_pool"} <= run(db, columns("jobs"))
    assert {"pack_credits", "plan_until", "plan_subscription_id"} <= run(db, columns("users"))

    async def use():
        async with db.session() as s:
            user = await s.get(User, "old-user")
            assert (user.ai_used, user.pack_credits, user.packs_frozen) == (2, 0, False)
            # The insert that broke on staging.
            s.add(Job(kind="analysis", repo="o/r2", repo_key="o/r2", mode="ai", days=7,
                      params={}, user_id="old-user", charged=True, quota_pool="plan"))
            await s.commit()
            assert await s.get(Job, "oldjob") is not None

    asyncio.run(use())


def test_preview_with_some_billing_tables_from_create_all(db):
    """Newer code once ran under create_all: new tables exist, new columns don't."""
    main_schema_without_alembic(db)

    def partial(conn):
        for name in ("subscriptions", "payments", "webhook_events"):
            Base.metadata.tables[name].create(conn)

    run(db, partial)
    asyncio.run(mig.migrate(db.engine))
    assert asyncio.run(mig.is_current(db.engine))
    assert "pack_credits" in run(db, columns("users"))
    assert "refunds" in run(db, lambda conn: set(inspect(conn).get_table_names()))


def test_fresh_database_and_rerun_are_fine(db):
    asyncio.run(mig.migrate(db.engine))
    asyncio.run(mig.migrate(db.engine))  # nothing to do the second time
    assert asyncio.run(mig.is_current(db.engine))


def test_downgrade_and_upgrade_again(db):
    asyncio.run(mig.migrate(db.engine))

    def down(conn):
        command.downgrade(mig.config(conn), "0002")

    run(db, down)
    assert "pack_credits" not in run(db, columns("users"))
    asyncio.run(mig.migrate(db.engine))
    assert asyncio.run(mig.is_current(db.engine))


def test_check_command(db, monkeypatch, capsys):
    from holt_server import settings

    monkeypatch.setenv("DATABASE_URL", str(db.engine.url.render_as_string(hide_password=False)))
    settings.get_settings.cache_clear()
    try:
        assert mig.main(["--check"]) == 1
        assert mig.main([]) == 0
        assert mig.main(["--check"]) == 0
    finally:
        settings.get_settings.cache_clear()
    assert "up to date" in capsys.readouterr().out


def test_staging_as_it_is_now_upgrades(db):
    """main with #30 and #35 under create_all: starter_cache and find_cache
    exist, alembic_version does not."""
    main_schema_without_alembic(db)  # users, jobs, reports, starter_cache
    run(db, lambda conn: Base.metadata.tables["find_cache"].create(conn))
    run(db, sql("INSERT INTO find_cache (key, params, results, created_at) "
                "VALUES ('k', '{}', '[]', :now)", {"now": datetime.now(UTC)}))
    asyncio.run(mig.migrate(db.engine))
    assert asyncio.run(mig.is_current(db.engine))
    assert run(db, sql("SELECT count(*) FROM find_cache")).scalar() == 1
