"""Alembic environment. Always driven from `holt_server.migrate`, which hands
over an open connection; there is no alembic.ini and no URL in here."""

from alembic import context

from holt_server.db import Base

connection = context.config.attributes["connection"]
context.configure(
    connection=connection,
    target_metadata=Base.metadata,
    # SQLite (tests, local) cannot ALTER most things; batch mode rebuilds the
    # table instead. Postgres ignores it and alters in place.
    render_as_batch=True,
    compare_type=True,
)
with context.begin_transaction():
    context.run_migrations()
