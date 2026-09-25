"""Idempotent building blocks for migrations after the baseline.

A preview may already have run newer code under `create_all`, which creates
missing tables but never adds columns. So later revisions create a table only
if it is missing, and add a column or index only if it is missing, and an
upgrade works from any of those partial states.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


def _inspector():
    return sa.inspect(op.get_bind())


def has_table(name: str) -> bool:
    return _inspector().has_table(name)


def has_column(table: str, column: str) -> bool:
    return any(c["name"] == column for c in _inspector().get_columns(table))


def has_index(table: str, name: str) -> bool:
    return any(i["name"] == name for i in _inspector().get_indexes(table))


def create_table(name: str, *columns, **kw) -> bool:
    if has_table(name):
        return False
    op.create_table(name, *columns, **kw)
    return True


def add_column(table: str, column: sa.Column) -> None:
    if not has_column(table, column.name):
        with op.batch_alter_table(table) as batch:
            batch.add_column(column)


def create_index(name: str, table: str, columns: list[str], **kw) -> None:
    if not has_index(table, name):
        op.create_index(name, table, columns, **kw)
