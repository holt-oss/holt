"""Database migrations (Alembic), run at startup and as a one-shot command.

    python -m holt_server.migrate            # upgrade to the latest schema
    python -m holt_server.migrate --check    # exit 1 if not up to date

A database made before migrations existed (by `create_all`, i.e. main as of
PR #6) has tables but no `alembic_version`. It is stamped at the baseline
revision, which is exactly that schema, and then upgraded in place. Later
revisions check what already exists, because a preview may have run newer
code under `create_all` and gained some tables but none of the new columns.

On Postgres the whole upgrade holds an advisory lock, so several processes
starting at once (API replicas, a migrate job) take turns instead of racing.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

MIGRATIONS = Path(__file__).with_name("migrations")
BASELINE = "0001"
LOCK_ID = 7_406_110  # arbitrary, fixed: "holt" migrations


def config(connection=None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.attributes["connection"] = connection
    return cfg


def head() -> str:
    return ScriptDirectory.from_config(config()).get_current_head()


def current(connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


def upgrade_sync(connection, target: str = "head") -> None:
    """Upgrade on an open (sync) connection. The caller owns the transaction."""
    cfg = config(connection)
    tables = inspect(connection)
    if not tables.has_table("alembic_version") and tables.has_table("users"):
        command.stamp(cfg, BASELINE)  # made by create_all before migrations
    command.upgrade(cfg, target)


async def migrate(engine: AsyncEngine, target: str = "head") -> None:
    async with engine.begin() as conn:
        if conn.dialect.name == "postgresql":
            # Released when this transaction ends.
            await conn.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": LOCK_ID})
        await conn.run_sync(upgrade_sync, target)


async def is_current(engine: AsyncEngine) -> bool:
    async with engine.connect() as conn:
        return await conn.run_sync(current) == head()


def main(argv: list[str] | None = None) -> int:
    from holt_server.db import Database
    from holt_server.settings import get_settings

    parser = argparse.ArgumentParser(prog="python -m holt_server.migrate",
                                     description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="only check; exit 1 if the database is not up to date")
    args = parser.parse_args(argv)

    async def run() -> int:
        db = Database(get_settings().database_url, pooled=False)
        try:
            if args.check:
                ok = await is_current(db.engine)
                print("up to date" if ok else "needs migrating")
                return 0 if ok else 1
            await migrate(db.engine)
            print(f"database at {head()}")
            return 0
        finally:
            await db.dispose()

    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main())
