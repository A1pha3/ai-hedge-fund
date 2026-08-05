"""Append-only stage-loss facts and risk-snapshot seals.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-04

Plan 02 Task 5. Adds three append-only fact tables:

- ``stage_loss_budget_activations``: one frozen integer-cent budget per
  (program, lineage, stage) identity, sealed at activation;
- ``stage_loss_charges``: every instantaneous stage-loss measurement with
  its mutually exclusive components, the monotone consumption before/after,
  and the latch state it produced;
- ``risk_snapshot_seals``: one sealed complete ``CapitalRiskSnapshot`` per
  (portfolio, session), with the content-hash fingerprint and the drawdown
  entry-scaling multiplier in effect at the seal.

All three are immutable facts (UPDATE/DELETE triggers apply); the mutable
``stage_loss_state`` projection is rebuildable from the activation and
charge rows. The revision is idempotent by inspection: revision 0001
creates tables through the evolved ``build_metadata()``, so a fresh
``upgrade head`` run finds the Task 5 surface already present and this
revision only verifies it. A real schema-3 ledger receives the additive
tables and triggers.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from src.screening.offensive.v3.storage.schema import (
    IMMUTABILITY_TRIGGER_DDL,
)


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "stage_loss_budget_activations" not in existing_tables:
        op.create_table(
            "stage_loss_budget_activations",
            sa.Column("stage_loss_budget_id", sa.Text(), primary_key=True),
            sa.Column(
                "idempotency_key", sa.Text(), nullable=False, unique=True
            ),
            sa.Column("research_program_id", sa.Text(), nullable=False),
            sa.Column("economic_lineage_id", sa.Text(), nullable=False),
            sa.Column("stage_id", sa.Text(), nullable=False),
            sa.Column("frozen_budget_cents", sa.BigInteger(), nullable=False),
            sa.Column("source_authority", sa.Text(), nullable=False),
            sa.Column("authorization_reference", sa.Text(), nullable=False),
            sa.Column("activated_at", sa.Text(), nullable=False),
            sa.UniqueConstraint(
                "research_program_id",
                "economic_lineage_id",
                "stage_id",
                name="uq_stage_loss_budget_identity",
            ),
        )

    if "stage_loss_charges" not in existing_tables:
        op.create_table(
            "stage_loss_charges",
            sa.Column("stage_loss_charge_id", sa.Text(), primary_key=True),
            sa.Column(
                "idempotency_key", sa.Text(), nullable=False, unique=True
            ),
            sa.Column(
                "payload_content_fingerprint", sa.Text(), nullable=False
            ),
            sa.Column("research_program_id", sa.Text(), nullable=False),
            sa.Column("economic_lineage_id", sa.Text(), nullable=False),
            sa.Column("stage_id", sa.Text(), nullable=False),
            sa.Column("source_authority", sa.Text(), nullable=False),
            sa.Column(
                "realized_market_losses_ex_fees_cents",
                sa.BigInteger(),
                nullable=False,
            ),
            sa.Column(
                "cumulative_fees_and_taxes_cents",
                sa.BigInteger(),
                nullable=False,
            ),
            sa.Column(
                "marked_unrealized_pnl_cents", sa.BigInteger(), nullable=False
            ),
            sa.Column(
                "unrealized_loss_charge_cents",
                sa.BigInteger(),
                nullable=False,
            ),
            sa.Column(
                "incremental_pending_stress_beyond_mark_cents",
                sa.BigInteger(),
                nullable=False,
            ),
            sa.Column(
                "instantaneous_charge_cents", sa.BigInteger(), nullable=False
            ),
            sa.Column(
                "consumed_before_cents", sa.BigInteger(), nullable=False
            ),
            sa.Column(
                "consumed_after_cents", sa.BigInteger(), nullable=False
            ),
            sa.Column("frozen_budget_cents", sa.BigInteger(), nullable=False),
            sa.Column(
                "stage_loss_version_before", sa.BigInteger(), nullable=False
            ),
            sa.Column(
                "stage_loss_version_after", sa.BigInteger(), nullable=False
            ),
            sa.Column("latch_state_after", sa.Text(), nullable=False),
            sa.Column("capital_version_after", sa.BigInteger(), nullable=False),
            sa.Column("recorded_at", sa.Text(), nullable=False),
        )

    if "risk_snapshot_seals" not in existing_tables:
        op.create_table(
            "risk_snapshot_seals",
            sa.Column("risk_snapshot_seal_id", sa.Text(), primary_key=True),
            sa.Column("portfolio_id", sa.Text(), nullable=False),
            sa.Column("session", sa.Text(), nullable=False),
            sa.Column("risk_snapshot_id", sa.Text(), nullable=False),
            sa.Column("capital_version", sa.BigInteger(), nullable=False),
            sa.Column("stream_version", sa.BigInteger(), nullable=False),
            sa.Column("snapshot_content_hash", sa.Text(), nullable=False),
            sa.Column("snapshot_json", sa.Text(), nullable=False),
            sa.Column(
                "entry_scaling_multiplier_ppm",
                sa.BigInteger(),
                nullable=False,
            ),
            sa.Column("as_of", sa.Text(), nullable=False),
            sa.Column("sealed_at", sa.Text(), nullable=False),
            sa.Column("source_authority", sa.Text(), nullable=False),
            sa.UniqueConstraint(
                "portfolio_id",
                "session",
                name="uq_risk_snapshot_seal_session",
            ),
        )

    # Immutability triggers for the append-only fact tables (idempotent).
    for ddl in IMMUTABILITY_TRIGGER_DDL:
        bind.exec_driver_sql(ddl)


def downgrade() -> None:
    # Dropping each table also drops its append-only immutability triggers.
    op.drop_table("risk_snapshot_seals")
    op.drop_table("stage_loss_charges")
    op.drop_table("stage_loss_budget_activations")
