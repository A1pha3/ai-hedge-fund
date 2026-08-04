"""Corporate action fact projection.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-04

Plan 02 Task 4. Adds the ``corporate_actions`` projection table: one
rebuildable row per (action_id, lot) carrying the entitlement rational,
fractional remainder, source-authority tier, ex/pay/tradable instants,
and the successor lot mapping (successor security, quantity, and the
inherited position state that keeps due exit obligations alive across
conversions). The table is a mutable projection: it is never part of the
append-only immutability trigger set, and it can always be rebuilt from
the economic event stream plus ``event_revisions``.

The revision is idempotent by inspection: revision 0001 creates tables
through the evolved ``build_metadata()``, so a fresh ``upgrade head``
run finds the Task 4 surface already present and this revision only
verifies it. A real schema-2 ledger receives the additive table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "corporate_actions" not in existing_tables:
        op.create_table(
            "corporate_actions",
            sa.Column("action_id", sa.Text(), primary_key=True),
            sa.Column(
                "position_lineage_id", sa.Text(), primary_key=True
            ),
            sa.Column("economic_lot_id", sa.Text(), primary_key=True),
            sa.Column("action_kind", sa.Text(), nullable=False),
            sa.Column("state", sa.Text(), nullable=False),
            sa.Column("source_authority_tier", sa.Text(), nullable=False),
            sa.Column("source_authority", sa.Text(), nullable=False),
            sa.Column("security_id", sa.Text(), nullable=False),
            sa.Column("revision", sa.BigInteger(), nullable=False),
            sa.Column(
                "entitlement_numerator", sa.BigInteger(), nullable=True
            ),
            sa.Column(
                "entitlement_denominator", sa.BigInteger(), nullable=True
            ),
            sa.Column(
                "fractional_remainder_numerator",
                sa.BigInteger(),
                nullable=True,
            ),
            sa.Column(
                "fractional_remainder_denominator",
                sa.BigInteger(),
                nullable=True,
            ),
            sa.Column("cash_in_lieu_cents", sa.BigInteger(), nullable=True),
            sa.Column("receivable_id", sa.Text(), nullable=True),
            sa.Column(
                "cash_in_lieu_receivable_id", sa.Text(), nullable=True
            ),
            sa.Column("ex_effective_at", sa.Text(), nullable=False),
            sa.Column("pay_effective_at", sa.Text(), nullable=True),
            sa.Column("tradable_effective_at", sa.Text(), nullable=True),
            sa.Column("successor_security_id", sa.Text(), nullable=True),
            sa.Column(
                "successor_quantity_units", sa.BigInteger(), nullable=True
            ),
            sa.Column("successor_receivable_id", sa.Text(), nullable=True),
            sa.Column(
                "inherited_position_state", sa.Text(), nullable=True
            ),
            sa.Column("opened_by_event_id", sa.Text(), nullable=False),
            sa.Column("updated_by_event_id", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("corporate_actions")
