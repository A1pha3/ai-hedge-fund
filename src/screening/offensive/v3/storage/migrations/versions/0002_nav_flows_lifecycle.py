"""Unit NAV, external flows, account lifecycle, and insolvency surface.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-04

Plan 02 Task 3. Adds the append-only financing fact stream
(``capital_flow_events``), the subscription/redemption request state machine
(``flow_requests``), the as-observed/restated-final NAV path
(``nav_observations``), the durable risk-epoch chain
(``risk_epoch_history``), and the subscription/redemption suspense cash
columns on ``capital_projection``. The new history tables receive the same
append-only immutability triggers as the Task 1 tables.

The revision is idempotent by inspection: revision 0001 creates tables
through the evolved ``build_metadata()``, so a fresh ``upgrade head`` run
finds the Task 3 surface already present and this revision only verifies
and completes it. A real schema-1 ledger receives the additive changes.

One schema-1 limitation is left as-is by design: ``economic_event_legs
.direction`` was NOT NULL in revision 0001, and SQLite cannot relax column
nullability in place. Valuation-mark legs carry no direction, so a ledger
physically created at schema 1 must be recreated before valuations are
recorded (no production ledger exists at schema 1; Plan 02 is unreleased).
Fresh ``create_all``/``upgrade head`` databases are nullable-correct.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from src.screening.offensive.v3.storage.schema import IMMUTABILITY_TRIGGER_DDL


revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _capital_projection_suspense_columns() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {
        column["name"] for column in inspector.get_columns("capital_projection")
    }
    if "subscription_suspense_cash_cents" not in existing:
        op.add_column(
            "capital_projection",
            sa.Column(
                "subscription_suspense_cash_cents",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            ),
        )
    if "redemption_suspense_cash_cents" not in existing:
        op.add_column(
            "capital_projection",
            sa.Column(
                "redemption_suspense_cash_cents",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            ),
        )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    _capital_projection_suspense_columns()

    if "capital_flow_events" not in existing_tables:
        op.create_table(
            "capital_flow_events",
            sa.Column("flow_event_id", sa.Text(), primary_key=True),
            sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
            sa.Column("flow_kind", sa.Text(), nullable=False),
            sa.Column(
                "portfolio_id",
                sa.Text(),
                sa.ForeignKey("account_capital_truth.portfolio_id"),
                nullable=False,
                index=True,
            ),
            sa.Column("flow_version", sa.BigInteger(), nullable=False, unique=True),
            sa.Column("flow_request_id", sa.Text(), nullable=True),
            sa.Column("source_authority", sa.Text(), nullable=False),
            sa.Column("effective_at", sa.Text(), nullable=False),
            sa.Column("recorded_at", sa.Text(), nullable=False),
            sa.Column("cash_amount_cents", sa.BigInteger(), nullable=True),
            sa.Column("refund_cents", sa.BigInteger(), nullable=True),
            sa.Column("reserved_cents", sa.BigInteger(), nullable=True),
            sa.Column("issued_unit_quanta", sa.BigInteger(), nullable=True),
            sa.Column("cancelled_unit_quanta", sa.BigInteger(), nullable=True),
            sa.Column("pending_unit_quanta", sa.BigInteger(), nullable=True),
            sa.Column("burnt_unit_quanta", sa.BigInteger(), nullable=True),
            sa.Column("unit_price_numerator", sa.BigInteger(), nullable=True),
            sa.Column("unit_price_denominator", sa.BigInteger(), nullable=True),
            sa.Column("payable_id", sa.Text(), nullable=True),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column(
                "payload_content_hash", sa.Text(), nullable=False, unique=True
            ),
        )

    if "flow_requests" not in existing_tables:
        op.create_table(
            "flow_requests",
            sa.Column("flow_request_id", sa.Text(), primary_key=True),
            sa.Column("flow_kind", sa.Text(), nullable=False),
            sa.Column("state", sa.Text(), nullable=False),
            sa.Column("cash_amount_cents", sa.BigInteger(), nullable=True),
            sa.Column("unit_quanta", sa.BigInteger(), nullable=True),
            sa.Column("issued_unit_quanta", sa.BigInteger(), nullable=True),
            sa.Column("unit_price_numerator", sa.BigInteger(), nullable=True),
            sa.Column("unit_price_denominator", sa.BigInteger(), nullable=True),
            sa.Column("v_pre_cents", sa.BigInteger(), nullable=True),
            sa.Column("units_pre_quanta", sa.BigInteger(), nullable=True),
            sa.Column("frozen_capital_version", sa.BigInteger(), nullable=True),
            sa.Column("payable_id", sa.Text(), nullable=True),
            sa.Column("source_authority", sa.Text(), nullable=False),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
        )

    if "nav_observations" not in existing_tables:
        op.create_table(
            "nav_observations",
            sa.Column("nav_observation_id", sa.Text(), primary_key=True),
            sa.Column(
                "portfolio_id",
                sa.Text(),
                sa.ForeignKey("account_capital_truth.portfolio_id"),
                nullable=False,
                index=True,
            ),
            sa.Column("observation_kind", sa.Text(), nullable=False),
            sa.Column("supersedes_observation_id", sa.Text(), nullable=True),
            sa.Column("as_of", sa.Text(), nullable=False),
            sa.Column("recorded_at", sa.Text(), nullable=False),
            sa.Column("capital_version", sa.BigInteger(), nullable=False),
            sa.Column("created_by_event_id", sa.Text(), nullable=False),
            sa.Column("nav_cents", sa.BigInteger(), nullable=False),
            sa.Column("issued_unit_quanta", sa.BigInteger(), nullable=False),
            sa.Column("live_unit_quanta", sa.BigInteger(), nullable=False),
            sa.Column("unit_price_numerator", sa.BigInteger(), nullable=True),
            sa.Column("unit_price_denominator", sa.BigInteger(), nullable=True),
            sa.Column("log_growth_kind", sa.Text(), nullable=False),
            sa.Column("log_growth_nav_numerator", sa.BigInteger(), nullable=True),
            sa.Column(
                "log_growth_nav_denominator", sa.BigInteger(), nullable=True
            ),
        )

    if "risk_epoch_history" not in existing_tables:
        op.create_table(
            "risk_epoch_history",
            sa.Column("risk_epoch", sa.BigInteger(), primary_key=True),
            sa.Column(
                "portfolio_id",
                sa.Text(),
                sa.ForeignKey("account_capital_truth.portfolio_id"),
                nullable=False,
            ),
            sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
            sa.Column("predecessor_risk_epoch", sa.BigInteger(), nullable=False),
            sa.Column("audited_nav_cents", sa.BigInteger(), nullable=False),
            sa.Column(
                "active_epoch_baseline_nav_cents",
                sa.BigInteger(),
                nullable=False,
            ),
            sa.Column(
                "lifetime_high_water_mark_cents", sa.BigInteger(), nullable=False
            ),
            sa.Column("source_authority", sa.Text(), nullable=False),
            sa.Column("authorization_reference", sa.Text(), nullable=True),
            sa.Column("started_at", sa.Text(), nullable=False),
        )

    for ddl in IMMUTABILITY_TRIGGER_DDL:
        bind.exec_driver_sql(ddl)


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        "capital_flow_events",
        "nav_observations",
        "risk_epoch_history",
    ):
        bind.exec_driver_sql(f"DROP TRIGGER IF EXISTS no_update_{table}")
        bind.exec_driver_sql(f"DROP TRIGGER IF EXISTS no_delete_{table}")
    op.drop_table("risk_epoch_history")
    op.drop_table("nav_observations")
    op.drop_table("flow_requests")
    op.drop_table("capital_flow_events")
    op.drop_column("capital_projection", "redemption_suspense_cash_cents")
    op.drop_column("capital_projection", "subscription_suspense_cash_cents")
