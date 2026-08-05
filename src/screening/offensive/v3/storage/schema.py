"""SQLAlchemy Core table definitions for the append-only capital ledger.

One real broker account owns one capital fact stream. Money, prices,
quantities, units, basis, and fees are persisted as integer quanta only
(cents / units / micro-price / numerator-denominator); SQLite REAL is never
used for economic truth. Event and history tables are append-only: database
triggers reject UPDATE and DELETE, and projections are the only mutable
state (they can always be rebuilt from the event stream).
"""

from __future__ import annotations

import sqlalchemy as sa


IMMUTABLE_TABLES: tuple[str, ...] = (
    "account_capital_truth",
    "capital_flow_events",
    "economic_event_legs",
    "economic_events",
    "entry_tombstones",
    "event_revisions",
    "execution_revisions",
    "exit_obligation_reopens",
    "nav_observations",
    "risk_epoch_history",
    "risk_snapshot_seals",
    "session_checkpoints",
    "stage_loss_budget_activations",
    "stage_loss_charges",
)


def _immutability_triggers() -> tuple[tuple[str, str], ...]:
    triggers: list[tuple[str, str]] = []
    for table in IMMUTABLE_TABLES:
        triggers.append(
            (
                f"no_update_{table}",
                "CREATE TRIGGER IF NOT EXISTS "
                f"no_update_{table} BEFORE UPDATE ON {table} "
                "BEGIN SELECT RAISE(ABORT, "
                f"'immutable table: {table} rejects UPDATE'); END;",
            )
        )
        triggers.append(
            (
                f"no_delete_{table}",
                "CREATE TRIGGER IF NOT EXISTS "
                f"no_delete_{table} BEFORE DELETE ON {table} "
                "BEGIN SELECT RAISE(ABORT, "
                f"'immutable table: {table} rejects DELETE'); END;",
            )
        )
    return tuple(triggers)


IMMUTABILITY_TRIGGERS: tuple[tuple[str, str], ...] = _immutability_triggers()

IMMUTABILITY_TRIGGER_DDL: tuple[str, ...] = tuple(
    ddl for _, ddl in IMMUTABILITY_TRIGGERS
)

TRIGGER_DROP_DDL: tuple[str, ...] = tuple(
    f"DROP TRIGGER IF EXISTS {name}" for name, _ in IMMUTABILITY_TRIGGERS
)


def build_metadata() -> sa.MetaData:
    """Build a fresh MetaData with the full Plan 02 Task 1 table set."""

    meta = sa.MetaData()

    sa.Table(
        "account_capital_truth",
        meta,
        sa.Column("portfolio_id", sa.Text, primary_key=True),
        sa.Column("broker_account_id", sa.Text, nullable=True),
        sa.Column("execution_mode", sa.Text, nullable=False),
        sa.Column("base_currency", sa.Text, nullable=False),
        sa.Column("environment_fingerprint", sa.Text, nullable=True),
        sa.Column("binding_content_hash", sa.Text, nullable=False),
        sa.Column("lifecycle_state", sa.Text, nullable=False),
        sa.Column("bound_at", sa.Text, nullable=False),
    )

    sa.Table(
        "economic_events",
        meta,
        sa.Column("economic_event_id", sa.Text, primary_key=True),
        sa.Column("idempotency_key", sa.Text, nullable=False, unique=True),
        sa.Column("stream_version", sa.BigInteger, nullable=False, unique=True),
        sa.Column("event_kind", sa.Text, nullable=False),
        sa.Column(
            "portfolio_id",
            sa.Text,
            sa.ForeignKey("account_capital_truth.portfolio_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("position_lineage_id", sa.Text, nullable=True),
        sa.Column("economic_lot_id", sa.Text, nullable=True),
        sa.Column("execution_mode", sa.Text, nullable=False),
        sa.Column("source_authority", sa.Text, nullable=False),
        sa.Column("effective_at", sa.Text, nullable=False),
        sa.Column("recorded_at", sa.Text, nullable=False),
        sa.Column("correction_of_event_id", sa.Text, nullable=True),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("payload_content_hash", sa.Text, nullable=False, unique=True),
        sa.Column("canonical_event_json", sa.Text, nullable=False),
    )

    sa.Table(
        "economic_event_legs",
        meta,
        sa.Column("leg_id", sa.Text, primary_key=True),
        sa.Column(
            "economic_event_id",
            sa.Text,
            sa.ForeignKey("economic_events.economic_event_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("asset_kind", sa.Text, nullable=False),
        # Valuation-mark legs (Plan 02 Task 3) carry no debit/credit
        # direction, so the column is nullable.
        sa.Column("direction", sa.Text, nullable=True),
        sa.Column("cash_amount_cents", sa.BigInteger, nullable=True),
        sa.Column("security_id", sa.Text, nullable=True),
        sa.Column("quantity_units", sa.BigInteger, nullable=True),
        sa.Column("receivable_id", sa.Text, nullable=True),
        sa.Column("cost_basis_cents", sa.BigInteger, nullable=True),
        sa.Column("mark_price_micros", sa.BigInteger, nullable=True),
        sa.UniqueConstraint("economic_event_id", "sequence", name="uq_legs_event_sequence"),
    )

    sa.Table(
        "event_revisions",
        meta,
        sa.Column(
            "canonical_event_id",
            sa.Text,
            sa.ForeignKey("economic_events.economic_event_id"),
            nullable=False,
        ),
        sa.Column(
            "revision_event_id",
            sa.Text,
            sa.ForeignKey("economic_events.economic_event_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("revision_kind", sa.Text, nullable=False),
        sa.Column("recorded_at", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("canonical_event_id", "revision_event_id"),
    )

    sa.Table(
        "capital_projection",
        meta,
        sa.Column(
            "portfolio_id",
            sa.Text,
            sa.ForeignKey("account_capital_truth.portfolio_id"),
            primary_key=True,
        ),
        sa.Column("available_cash_cents", sa.BigInteger, nullable=False),
        sa.Column("restricted_cash_cents", sa.BigInteger, nullable=False),
        sa.Column("unsettled_cash_cents", sa.BigInteger, nullable=False),
        sa.Column("subscription_suspense_cash_cents", sa.BigInteger, nullable=False),
        sa.Column("redemption_suspense_cash_cents", sa.BigInteger, nullable=False),
        sa.Column("issued_unit_quanta", sa.BigInteger, nullable=False),
        sa.Column("pending_redeemed_unit_quanta", sa.BigInteger, nullable=False),
        sa.Column("as_observed_nav_cents", sa.BigInteger, nullable=False),
        sa.Column("lifetime_high_water_mark_cents", sa.BigInteger, nullable=False),
        sa.Column("active_epoch_high_water_mark_cents", sa.BigInteger, nullable=False),
        sa.Column("lifecycle_state", sa.Text, nullable=False),
        sa.Column("capital_version", sa.BigInteger, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.Column("updated_by_event_id", sa.Text, nullable=True),
    )

    sa.Table(
        "positions",
        meta,
        sa.Column("position_lineage_id", sa.Text, primary_key=True),
        sa.Column("economic_lot_id", sa.Text, primary_key=True),
        sa.Column("security_id", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("settled_quantity_units", sa.BigInteger, nullable=False),
        sa.Column("tradable_quantity_units", sa.BigInteger, nullable=False),
        sa.Column("share_receivable_quantity_units", sa.BigInteger, nullable=False),
        sa.Column("cost_basis_cents", sa.BigInteger, nullable=False),
        sa.Column("producer_namespace", sa.Text, nullable=False),
        sa.Column("research_program_id", sa.Text, nullable=False),
        sa.Column("economic_lineage_id", sa.Text, nullable=False),
        sa.Column("stage_id", sa.Text, nullable=False),
        sa.Column("opened_by_event_id", sa.Text, nullable=False),
        sa.Column("updated_by_event_id", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
    )

    sa.Table(
        "reserves",
        meta,
        sa.Column("reserve_id", sa.Text, primary_key=True),
        sa.Column("source_id", sa.Text, nullable=False, unique=True),
        sa.Column("research_program_id", sa.Text, nullable=False),
        sa.Column("economic_lineage_id", sa.Text, nullable=False),
        sa.Column("stage_id", sa.Text, nullable=False),
        sa.Column("covered_live_order_id", sa.Text, nullable=True),
        sa.Column("reserved_entry_gross_cents", sa.BigInteger, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
    )

    sa.Table(
        "receivables",
        meta,
        sa.Column("receivable_id", sa.Text, primary_key=True),
        sa.Column("receivable_kind", sa.Text, nullable=False),
        sa.Column("security_id", sa.Text, nullable=False),
        sa.Column("position_lineage_id", sa.Text, nullable=True),
        sa.Column("amount_cents", sa.BigInteger, nullable=True),
        sa.Column("quantity_units", sa.BigInteger, nullable=True),
        sa.Column("settled", sa.Integer, nullable=False),
        sa.Column(
            "created_by_event_id",
            sa.Text,
            sa.ForeignKey("economic_events.economic_event_id"),
            nullable=False,
        ),
        sa.Column("settled_by_event_id", sa.Text, nullable=True),
        sa.Column("updated_at", sa.Text, nullable=False),
    )

    sa.Table(
        "payables",
        meta,
        sa.Column("payable_id", sa.Text, primary_key=True),
        sa.Column("payable_kind", sa.Text, nullable=False),
        sa.Column("amount_cents", sa.BigInteger, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("created_by_event_id", sa.Text, nullable=True),
    )

    sa.Table(
        "risk_latches",
        meta,
        sa.Column("latch_kind", sa.Text, primary_key=True),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("set_at", sa.Text, nullable=False),
        sa.Column("set_by_event_id", sa.Text, nullable=True),
    )

    sa.Table(
        "stage_loss_state",
        meta,
        sa.Column("research_program_id", sa.Text, primary_key=True),
        sa.Column("economic_lineage_id", sa.Text, primary_key=True),
        sa.Column("stage_id", sa.Text, primary_key=True),
        sa.Column("stage_loss_budget_id", sa.Text, nullable=False),
        sa.Column("frozen_budget_cents", sa.BigInteger, nullable=False),
        sa.Column("consumed_cents", sa.BigInteger, nullable=False),
        sa.Column("stage_loss_version", sa.BigInteger, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
    )

    sa.Table(
        "execution_revisions",
        meta,
        sa.Column("execution_revision_id", sa.Text, primary_key=True),
        sa.Column("execution_id", sa.Text, nullable=False),
        sa.Column("revision", sa.BigInteger, nullable=False),
        sa.Column("revision_kind", sa.Text, nullable=False),
        sa.Column("order_id", sa.Text, nullable=True),
        sa.Column("payload_content_hash", sa.Text, nullable=False),
        sa.Column("recorded_at", sa.Text, nullable=False),
        sa.UniqueConstraint("execution_id", "revision", name="uq_execution_revision"),
    )

    sa.Table(
        "session_checkpoints",
        meta,
        sa.Column("session", sa.Text, primary_key=True),
        sa.Column("phase", sa.Text, primary_key=True),
        sa.Column("stream_version", sa.BigInteger, nullable=False),
        sa.Column("recorded_at", sa.Text, nullable=False),
    )

    sa.Table(
        "entry_tombstones",
        meta,
        sa.Column("entry_identity", sa.Text, primary_key=True),
        sa.Column("tombstone_reason", sa.Text, nullable=False),
        sa.Column("capital_version", sa.BigInteger, nullable=False),
        sa.Column("stream_version", sa.BigInteger, nullable=False),
        sa.Column("tombstoned_at", sa.Text, nullable=False),
    )

    # -- Plan 02 Task 6: durable reopened exit obligations -----------------
    # Append-only facts: one row per flat/nonpositive-to-positive lot
    # transition caused by an execution bust/correction. Plan 04 consumes
    # them to restore the stable ExitMandate identity at a revision beyond
    # every prior mandate revision of the lot.

    sa.Table(
        "exit_obligation_reopens",
        meta,
        sa.Column("reopen_id", sa.Text, primary_key=True),
        sa.Column("position_lineage_id", sa.Text, nullable=False),
        sa.Column("economic_lot_id", sa.Text, nullable=False),
        sa.Column("security_id", sa.Text, nullable=False),
        sa.Column("producer_namespace", sa.Text, nullable=False),
        sa.Column("research_program_id", sa.Text, nullable=False),
        sa.Column("economic_lineage_id", sa.Text, nullable=False),
        sa.Column("stage_id", sa.Text, nullable=False),
        sa.Column("reopened_quantity_units", sa.BigInteger, nullable=False),
        sa.Column("position_state", sa.Text, nullable=False),
        sa.Column("reopen_reason", sa.Text, nullable=False),
        sa.Column("mandate_revision_floor", sa.BigInteger, nullable=False),
        sa.Column(
            "reopened_by_execution_revision_id", sa.Text, nullable=False
        ),
        sa.Column("reopened_by_event_id", sa.Text, nullable=False),
        sa.Column("capital_version", sa.BigInteger, nullable=False),
        sa.Column("stream_version", sa.BigInteger, nullable=False),
        sa.Column("recorded_at", sa.Text, nullable=False),
    )

    sa.Table(
        "gateway_meta",
        meta,
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
    )

    # -- Plan 02 Task 3: unit NAV, external flows, and lifecycle tables -------

    sa.Table(
        "capital_flow_events",
        meta,
        sa.Column("flow_event_id", sa.Text, primary_key=True),
        sa.Column("idempotency_key", sa.Text, nullable=False, unique=True),
        sa.Column("flow_kind", sa.Text, nullable=False),
        sa.Column(
            "portfolio_id",
            sa.Text,
            sa.ForeignKey("account_capital_truth.portfolio_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("flow_version", sa.BigInteger, nullable=False, unique=True),
        sa.Column("flow_request_id", sa.Text, nullable=True),
        sa.Column("source_authority", sa.Text, nullable=False),
        sa.Column("effective_at", sa.Text, nullable=False),
        sa.Column("recorded_at", sa.Text, nullable=False),
        sa.Column("cash_amount_cents", sa.BigInteger, nullable=True),
        sa.Column("refund_cents", sa.BigInteger, nullable=True),
        sa.Column("reserved_cents", sa.BigInteger, nullable=True),
        sa.Column("issued_unit_quanta", sa.BigInteger, nullable=True),
        sa.Column("cancelled_unit_quanta", sa.BigInteger, nullable=True),
        sa.Column("pending_unit_quanta", sa.BigInteger, nullable=True),
        sa.Column("burnt_unit_quanta", sa.BigInteger, nullable=True),
        sa.Column("unit_price_numerator", sa.BigInteger, nullable=True),
        sa.Column("unit_price_denominator", sa.BigInteger, nullable=True),
        sa.Column("payable_id", sa.Text, nullable=True),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("payload_content_hash", sa.Text, nullable=False, unique=True),
    )

    sa.Table(
        "flow_requests",
        meta,
        sa.Column("flow_request_id", sa.Text, primary_key=True),
        sa.Column("flow_kind", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("cash_amount_cents", sa.BigInteger, nullable=True),
        sa.Column("unit_quanta", sa.BigInteger, nullable=True),
        sa.Column("issued_unit_quanta", sa.BigInteger, nullable=True),
        sa.Column("unit_price_numerator", sa.BigInteger, nullable=True),
        sa.Column("unit_price_denominator", sa.BigInteger, nullable=True),
        sa.Column("v_pre_cents", sa.BigInteger, nullable=True),
        sa.Column("units_pre_quanta", sa.BigInteger, nullable=True),
        sa.Column("frozen_capital_version", sa.BigInteger, nullable=True),
        sa.Column("payable_id", sa.Text, nullable=True),
        sa.Column("source_authority", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
    )

    sa.Table(
        "nav_observations",
        meta,
        sa.Column("nav_observation_id", sa.Text, primary_key=True),
        sa.Column(
            "portfolio_id",
            sa.Text,
            sa.ForeignKey("account_capital_truth.portfolio_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("observation_kind", sa.Text, nullable=False),
        sa.Column("supersedes_observation_id", sa.Text, nullable=True),
        sa.Column("as_of", sa.Text, nullable=False),
        sa.Column("recorded_at", sa.Text, nullable=False),
        sa.Column("capital_version", sa.BigInteger, nullable=False),
        sa.Column("created_by_event_id", sa.Text, nullable=False),
        sa.Column("nav_cents", sa.BigInteger, nullable=False),
        sa.Column("issued_unit_quanta", sa.BigInteger, nullable=False),
        sa.Column("live_unit_quanta", sa.BigInteger, nullable=False),
        sa.Column("unit_price_numerator", sa.BigInteger, nullable=True),
        sa.Column("unit_price_denominator", sa.BigInteger, nullable=True),
        sa.Column("log_growth_kind", sa.Text, nullable=False),
        sa.Column("log_growth_nav_numerator", sa.BigInteger, nullable=True),
        sa.Column("log_growth_nav_denominator", sa.BigInteger, nullable=True),
    )

    sa.Table(
        "risk_epoch_history",
        meta,
        sa.Column("risk_epoch", sa.BigInteger, primary_key=True),
        sa.Column(
            "portfolio_id",
            sa.Text,
            sa.ForeignKey("account_capital_truth.portfolio_id"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.Text, nullable=False, unique=True),
        sa.Column("predecessor_risk_epoch", sa.BigInteger, nullable=False),
        sa.Column("audited_nav_cents", sa.BigInteger, nullable=False),
        sa.Column(
            "active_epoch_baseline_nav_cents", sa.BigInteger, nullable=False
        ),
        sa.Column(
            "lifetime_high_water_mark_cents", sa.BigInteger, nullable=False
        ),
        sa.Column("source_authority", sa.Text, nullable=False),
        sa.Column("authorization_reference", sa.Text, nullable=True),
        sa.Column("started_at", sa.Text, nullable=False),
    )

    # -- Plan 02 Task 4: corporate action fact projection ---------------------
    # Mutable projection (rebuildable from the economic event stream). One
    # row per (action_id, lot); revisions update the row in place while the
    # append-only events/event_revisions history preserves every fact.

    sa.Table(
        "corporate_actions",
        meta,
        sa.Column("action_id", sa.Text, primary_key=True),
        sa.Column("position_lineage_id", sa.Text, primary_key=True),
        sa.Column("economic_lot_id", sa.Text, primary_key=True),
        sa.Column("action_kind", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("source_authority_tier", sa.Text, nullable=False),
        sa.Column("source_authority", sa.Text, nullable=False),
        sa.Column("security_id", sa.Text, nullable=False),
        sa.Column("revision", sa.BigInteger, nullable=False),
        sa.Column("entitlement_numerator", sa.BigInteger, nullable=True),
        sa.Column("entitlement_denominator", sa.BigInteger, nullable=True),
        sa.Column(
            "fractional_remainder_numerator", sa.BigInteger, nullable=True
        ),
        sa.Column(
            "fractional_remainder_denominator", sa.BigInteger, nullable=True
        ),
        sa.Column("cash_in_lieu_cents", sa.BigInteger, nullable=True),
        sa.Column("receivable_id", sa.Text, nullable=True),
        sa.Column("cash_in_lieu_receivable_id", sa.Text, nullable=True),
        sa.Column("ex_effective_at", sa.Text, nullable=False),
        sa.Column("pay_effective_at", sa.Text, nullable=True),
        sa.Column("tradable_effective_at", sa.Text, nullable=True),
        sa.Column("successor_security_id", sa.Text, nullable=True),
        sa.Column("successor_quantity_units", sa.BigInteger, nullable=True),
        sa.Column("successor_receivable_id", sa.Text, nullable=True),
        sa.Column("inherited_position_state", sa.Text, nullable=True),
        sa.Column("opened_by_event_id", sa.Text, nullable=False),
        sa.Column("updated_by_event_id", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
    )

    # -- Plan 02 Task 5: append-only stage-loss and risk-snapshot facts ------
    #
    # Stage-loss budgets freeze at activation and are consumed monotonically;
    # session snapshots seal the complete CapitalRiskSnapshot once per
    # session. Both are append-only facts (immutability triggers apply); the
    # mutable ``stage_loss_state`` projection above them is rebuildable from
    # these rows.

    sa.Table(
        "stage_loss_budget_activations",
        meta,
        sa.Column("stage_loss_budget_id", sa.Text, primary_key=True),
        sa.Column("idempotency_key", sa.Text, nullable=False, unique=True),
        sa.Column("research_program_id", sa.Text, nullable=False),
        sa.Column("economic_lineage_id", sa.Text, nullable=False),
        sa.Column("stage_id", sa.Text, nullable=False),
        sa.Column("frozen_budget_cents", sa.BigInteger, nullable=False),
        sa.Column("source_authority", sa.Text, nullable=False),
        sa.Column("authorization_reference", sa.Text, nullable=False),
        sa.Column("activated_at", sa.Text, nullable=False),
        sa.UniqueConstraint(
            "research_program_id",
            "economic_lineage_id",
            "stage_id",
            name="uq_stage_loss_budget_identity",
        ),
    )

    sa.Table(
        "stage_loss_charges",
        meta,
        sa.Column("stage_loss_charge_id", sa.Text, primary_key=True),
        sa.Column("idempotency_key", sa.Text, nullable=False, unique=True),
        sa.Column(
            "payload_content_fingerprint", sa.Text, nullable=False
        ),
        sa.Column("research_program_id", sa.Text, nullable=False),
        sa.Column("economic_lineage_id", sa.Text, nullable=False),
        sa.Column("stage_id", sa.Text, nullable=False),
        sa.Column("source_authority", sa.Text, nullable=False),
        sa.Column(
            "realized_market_losses_ex_fees_cents",
            sa.BigInteger,
            nullable=False,
        ),
        sa.Column("cumulative_fees_and_taxes_cents", sa.BigInteger, nullable=False),
        sa.Column("marked_unrealized_pnl_cents", sa.BigInteger, nullable=False),
        sa.Column("unrealized_loss_charge_cents", sa.BigInteger, nullable=False),
        sa.Column(
            "incremental_pending_stress_beyond_mark_cents",
            sa.BigInteger,
            nullable=False,
        ),
        sa.Column("instantaneous_charge_cents", sa.BigInteger, nullable=False),
        sa.Column("consumed_before_cents", sa.BigInteger, nullable=False),
        sa.Column("consumed_after_cents", sa.BigInteger, nullable=False),
        sa.Column("frozen_budget_cents", sa.BigInteger, nullable=False),
        sa.Column("stage_loss_version_before", sa.BigInteger, nullable=False),
        sa.Column("stage_loss_version_after", sa.BigInteger, nullable=False),
        sa.Column("latch_state_after", sa.Text, nullable=False),
        sa.Column("capital_version_after", sa.BigInteger, nullable=False),
        sa.Column("recorded_at", sa.Text, nullable=False),
    )

    sa.Table(
        "risk_snapshot_seals",
        meta,
        sa.Column("risk_snapshot_seal_id", sa.Text, primary_key=True),
        sa.Column("portfolio_id", sa.Text, nullable=False),
        sa.Column("session", sa.Text, nullable=False),
        sa.Column("risk_snapshot_id", sa.Text, nullable=False),
        sa.Column("capital_version", sa.BigInteger, nullable=False),
        sa.Column("stream_version", sa.BigInteger, nullable=False),
        sa.Column("snapshot_content_hash", sa.Text, nullable=False),
        sa.Column("snapshot_json", sa.Text, nullable=False),
        sa.Column("entry_scaling_multiplier_ppm", sa.BigInteger, nullable=False),
        sa.Column("as_of", sa.Text, nullable=False),
        sa.Column("sealed_at", sa.Text, nullable=False),
        sa.Column("source_authority", sa.Text, nullable=False),
        sa.UniqueConstraint(
            "portfolio_id", "session", name="uq_risk_snapshot_seal_session"
        ),
    )

    return meta


def configure_sqlite_connection(dbapi_connection, connection_record) -> None:
    """Apply the required SQLite pragmas to every physical connection."""

    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=15000")
    cursor.close()
