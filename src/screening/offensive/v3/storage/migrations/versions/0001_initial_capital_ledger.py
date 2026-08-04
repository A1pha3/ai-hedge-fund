"""Initial append-only AccountCapitalTruth ledger schema.

Revision ID: 0001
Revises:
Create Date: 2026-08-04

Single source of truth for the DDL is ``storage/schema.py``; this revision
applies the same table set plus the append-only immutability triggers.
"""

from __future__ import annotations

from alembic import op

from src.screening.offensive.v3.storage.schema import (
    IMMUTABILITY_TRIGGER_DDL,
    TRIGGER_DROP_DDL,
    build_metadata,
)


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    build_metadata().create_all(bind)
    for ddl in IMMUTABILITY_TRIGGER_DDL:
        bind.exec_driver_sql(ddl)


def downgrade() -> None:
    bind = op.get_bind()
    for ddl in TRIGGER_DROP_DDL:
        bind.exec_driver_sql(ddl)
    build_metadata().drop_all(bind)
