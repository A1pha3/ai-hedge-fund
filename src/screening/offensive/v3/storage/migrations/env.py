"""Minimal self-contained Alembic environment for the capital ledger.

The ledger schema lives in ``schema.py``; this environment only wires the
migration machinery to that metadata. Plan 02 Task 1 ships the single
initial revision, later tasks append forward-only revisions.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from src.screening.offensive.v3.storage.schema import build_metadata


target_metadata = build_metadata()


def run_migrations_offline() -> None:
    url = context.config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        context.config.get_section(context.config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
