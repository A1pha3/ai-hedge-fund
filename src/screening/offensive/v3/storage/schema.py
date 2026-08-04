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
    "economic_event_legs",
    "economic_events",
    "entry_tombstones",
    "event_revisions",
    "execution_revisions",
    "session_checkpoints",
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
        sa.Column("direction", sa.Text, nullable=False),
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

    sa.Table(
        "gateway_meta",
        meta,
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
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
