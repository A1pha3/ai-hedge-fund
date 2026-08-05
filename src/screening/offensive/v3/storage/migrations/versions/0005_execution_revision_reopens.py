"""Reopened exit obligations for execution bust/correction.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-04

Plan 02 Task 6. Adds one append-only fact table:

- ``exit_obligation_reopens``: one durable row per economic lot that a
  bust/correction transitions from a flat or nonpositive projection back
  to a positive holding. Carries the stable lot identity, its full risk
  attribution, the restored ``EXIT_PENDING`` position state, the
  ``REOPENED_BY_CORRECTION`` reason, the execution revision provenance,
  and the kernel's mandate revision floor (revision 1 belongs to INITIAL
  mandates only). Plan 04's ExitMandate projection consumes these rows.

The table is an immutable fact (UPDATE/DELETE triggers apply). The
revision is idempotent by inspection: revision 0001 creates tables
through the evolved ``build_metadata()``, so a fresh ``upgrade head``
run finds the Task 6 surface already present and this revision only
verifies it. A real schema-4 ledger receives the additive table and
triggers.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from src.screening.offensive.v3.storage.schema import (
    IMMUTABILITY_TRIGGER_DDL,
)


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "exit_obligation_reopens" not in existing_tables:
        op.create_table(
            "exit_obligation_reopens",
            sa.Column("reopen_id", sa.Text(), primary_key=True),
            sa.Column("position_lineage_id", sa.Text(), nullable=False),
            sa.Column("economic_lot_id", sa.Text(), nullable=False),
            sa.Column("security_id", sa.Text(), nullable=False),
            sa.Column("producer_namespace", sa.Text(), nullable=False),
            sa.Column("research_program_id", sa.Text(), nullable=False),
            sa.Column("economic_lineage_id", sa.Text(), nullable=False),
            sa.Column("stage_id", sa.Text(), nullable=False),
            sa.Column(
                "reopened_quantity_units", sa.BigInteger(), nullable=False
            ),
            sa.Column("position_state", sa.Text(), nullable=False),
            sa.Column("reopen_reason", sa.Text(), nullable=False),
            sa.Column(
                "mandate_revision_floor", sa.BigInteger(), nullable=False
            ),
            sa.Column(
                "reopened_by_execution_revision_id",
                sa.Text(),
                nullable=False,
            ),
            sa.Column("reopened_by_event_id", sa.Text(), nullable=False),
            sa.Column("capital_version", sa.BigInteger(), nullable=False),
            sa.Column("stream_version", sa.BigInteger(), nullable=False),
            sa.Column("recorded_at", sa.Text(), nullable=False),
        )

    # Immutability triggers for the append-only fact tables (idempotent).
    for ddl in IMMUTABILITY_TRIGGER_DDL:
        bind.exec_driver_sql(ddl)


def downgrade() -> None:
    # Dropping the table also drops its append-only immutability triggers.
    op.drop_table("exit_obligation_reopens")
