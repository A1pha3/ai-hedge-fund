"""Schema-level guarantees for the v3 AccountCapitalTruth store.

Plan 02 Task 1: append-only table set, WAL + foreign keys, integer quanta
for every monetary/quantity column, unique canonical-event and idempotency
keys, immutability triggers, and the Alembic migration layout.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from src.screening.offensive.v3.capital.repository import CapitalRepository
from src.screening.offensive.v3.storage import metadata


EXPECTED_TABLES = frozenset(
    {
        "account_capital_truth",
        "capital_flow_events",
        "capital_projection",
        "corporate_actions",
        "economic_event_legs",
        "economic_events",
        "entry_tombstones",
        "event_revisions",
        "execution_revisions",
        "flow_requests",
        "gateway_meta",
        "nav_observations",
        "payables",
        "positions",
        "receivables",
        "reserves",
        "risk_epoch_history",
        "risk_latches",
        "session_checkpoints",
        "stage_loss_state",
    }
)

IMMUTABLE_TABLES = frozenset(
    {
        "account_capital_truth",
        "capital_flow_events",
        "economic_event_legs",
        "economic_events",
        "entry_tombstones",
        "event_revisions",
        "execution_revisions",
        "nav_observations",
        "risk_epoch_history",
        "session_checkpoints",
    }
)

INTEGER_QUANTA_COLUMNS = {
    ("capital_projection", "available_cash_cents"),
    ("capital_projection", "restricted_cash_cents"),
    ("capital_projection", "unsettled_cash_cents"),
    ("capital_projection", "subscription_suspense_cash_cents"),
    ("capital_projection", "redemption_suspense_cash_cents"),
    ("capital_projection", "issued_unit_quanta"),
    ("capital_projection", "pending_redeemed_unit_quanta"),
    ("capital_projection", "as_observed_nav_cents"),
    ("capital_projection", "lifetime_high_water_mark_cents"),
    ("capital_projection", "active_epoch_high_water_mark_cents"),
    ("capital_projection", "capital_version"),
    ("capital_flow_events", "flow_version"),
    ("capital_flow_events", "cash_amount_cents"),
    ("capital_flow_events", "refund_cents"),
    ("capital_flow_events", "reserved_cents"),
    ("capital_flow_events", "issued_unit_quanta"),
    ("capital_flow_events", "cancelled_unit_quanta"),
    ("capital_flow_events", "pending_unit_quanta"),
    ("capital_flow_events", "burnt_unit_quanta"),
    ("capital_flow_events", "unit_price_numerator"),
    ("capital_flow_events", "unit_price_denominator"),
    ("flow_requests", "cash_amount_cents"),
    ("flow_requests", "unit_quanta"),
    ("flow_requests", "issued_unit_quanta"),
    ("flow_requests", "unit_price_numerator"),
    ("flow_requests", "unit_price_denominator"),
    ("flow_requests", "v_pre_cents"),
    ("flow_requests", "units_pre_quanta"),
    ("flow_requests", "frozen_capital_version"),
    ("nav_observations", "capital_version"),
    ("nav_observations", "nav_cents"),
    ("nav_observations", "issued_unit_quanta"),
    ("nav_observations", "live_unit_quanta"),
    ("nav_observations", "unit_price_numerator"),
    ("nav_observations", "unit_price_denominator"),
    ("nav_observations", "log_growth_nav_numerator"),
    ("nav_observations", "log_growth_nav_denominator"),
    ("risk_epoch_history", "risk_epoch"),
    ("risk_epoch_history", "predecessor_risk_epoch"),
    ("risk_epoch_history", "audited_nav_cents"),
    ("risk_epoch_history", "active_epoch_baseline_nav_cents"),
    ("risk_epoch_history", "lifetime_high_water_mark_cents"),
    ("economic_event_legs", "cash_amount_cents"),
    ("economic_event_legs", "quantity_units"),
    ("economic_event_legs", "cost_basis_cents"),
    ("economic_event_legs", "mark_price_micros"),
    ("positions", "settled_quantity_units"),
    ("positions", "tradable_quantity_units"),
    ("positions", "share_receivable_quantity_units"),
    ("positions", "cost_basis_cents"),
    ("reserves", "reserved_entry_gross_cents"),
    ("receivables", "amount_cents"),
    ("receivables", "quantity_units"),
    ("payables", "amount_cents"),
    ("stage_loss_state", "frozen_budget_cents"),
    ("stage_loss_state", "consumed_cents"),
    ("corporate_actions", "revision"),
    ("corporate_actions", "entitlement_numerator"),
    ("corporate_actions", "entitlement_denominator"),
    ("corporate_actions", "fractional_remainder_numerator"),
    ("corporate_actions", "fractional_remainder_denominator"),
    ("corporate_actions", "cash_in_lieu_cents"),
    ("corporate_actions", "successor_quantity_units"),
}


@pytest.fixture()
def repository(tmp_path: Path) -> CapitalRepository:
    return CapitalRepository.initialize(tmp_path / "capital.sqlite3")


def _seed_history(conn: sa.engine.Connection) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO account_capital_truth ("
            " portfolio_id, broker_account_id, execution_mode, base_currency,"
            " environment_fingerprint, binding_content_hash, lifecycle_state, bound_at"
            ") VALUES ("
            " 'pf-schema', 'acct-schema', 'manual_confirmed', 'CNY',"
            " :fingerprint, 'seed-hash', 'ACTIVE', '2026-08-03T09:00:00+00:00')"
        ),
        {"fingerprint": "ab" * 32},
    )
    for index in (1, 2):
        conn.execute(
            sa.text(
                "INSERT INTO economic_events ("
                " economic_event_id, idempotency_key, stream_version, event_kind,"
                " portfolio_id, position_lineage_id, economic_lot_id, execution_mode,"
                " source_authority, effective_at, recorded_at, correction_of_event_id,"
                " payload_json, payload_content_hash, canonical_event_json"
                ") VALUES ("
                f" 'eco-seed-{index}', 'seed-key-{index}', {index}, 'FEE_CHARGED',"
                " 'pf-schema', NULL, NULL, 'manual_confirmed',"
                " 'test.seed', '2026-08-03T09:00:00+00:00',"
                f" '2026-08-03T09:00:0{index}+00:00', NULL,"
                f" '{{\"seed\": {index}}}', :payload_hash, :canonical_json)"
            ),
            {
                "payload_hash": f"{index:064x}",
                "canonical_json": f'{{"seed": {index}}}',
            },
        )
    conn.execute(
        sa.text(
            "INSERT INTO economic_event_legs ("
            " leg_id, economic_event_id, sequence, asset_kind, direction,"
            " cash_amount_cents"
            ") VALUES ('leg-seed', 'eco-seed-1', 0, 'CASH', 'DEBIT', 100)"
        )
    )
    conn.execute(
        sa.text(
            "INSERT INTO event_revisions ("
            " canonical_event_id, revision_event_id, revision_kind, recorded_at"
            ") VALUES ('eco-seed-1', 'eco-seed-2', 'LATE_CORRECTION',"
            " '2026-08-03T09:00:02+00:00')"
        )
    )
    conn.execute(
        sa.text(
            "INSERT INTO execution_revisions ("
            " execution_revision_id, execution_id, revision, revision_kind,"
            " order_id, payload_content_hash, recorded_at"
            ") VALUES ('xrev-seed', 'exec-1', 1, 'BUSTED', NULL,"
            " :payload_hash, '2026-08-03T09:00:00+00:00')"
        ),
        {"payload_hash": "c" * 64},
    )
    conn.execute(
        sa.text(
            "INSERT INTO session_checkpoints ("
            " session, phase, stream_version, recorded_at"
            ") VALUES ('2026-08-03', 'PREOPEN_RISK_LOCKED', 1,"
            " '2026-08-03T09:00:00+00:00')"
        )
    )
    conn.execute(
        sa.text(
            "INSERT INTO entry_tombstones ("
            " entry_identity, tombstone_reason, capital_version, stream_version,"
            " tombstoned_at"
            ") VALUES ('entry-seed', 'capital_version_advanced', 1, 1,"
            " '2026-08-03T09:00:00+00:00')"
        )
    )
    conn.execute(
        sa.text(
            "INSERT INTO capital_flow_events ("
            " flow_event_id, idempotency_key, flow_kind, portfolio_id,"
            " flow_version, source_authority, effective_at, recorded_at,"
            " payload_json, payload_content_hash"
            ") VALUES ('flow-seed', 'flow-key-1', 'GENESIS', 'pf-schema', 1,"
            " 'test.seed', '2026-08-03T09:00:00+00:00',"
            " '2026-08-03T09:00:00+00:00', '{}', :payload_hash)"
        ),
        {"payload_hash": "f" * 64},
    )
    conn.execute(
        sa.text(
            "INSERT INTO nav_observations ("
            " nav_observation_id, portfolio_id, observation_kind, as_of,"
            " recorded_at, capital_version, created_by_event_id, nav_cents,"
            " issued_unit_quanta, live_unit_quanta, log_growth_kind"
            ") VALUES ('navobs-seed', 'pf-schema', 'AS_OBSERVED',"
            " '2026-08-03T09:00:00+00:00', '2026-08-03T09:00:00+00:00', 1,"
            " 'flow-seed', 100, 1, 1, 'NO_PRIOR_OBSERVATION')"
        )
    )
    conn.execute(
        sa.text(
            "INSERT INTO risk_epoch_history ("
            " risk_epoch, portfolio_id, idempotency_key, predecessor_risk_epoch,"
            " audited_nav_cents, active_epoch_baseline_nav_cents,"
            " lifetime_high_water_mark_cents, source_authority, started_at"
            ") VALUES (1, 'pf-schema', 'epoch-key-1', 0, 100, 100, 100,"
            " 'test.seed', '2026-08-03T09:00:00+00:00')"
        )
    )


def test_initialize_creates_exact_table_set(repository: CapitalRepository) -> None:
    with repository.engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT name FROM sqlite_master"
                " WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ).all()
    assert {row.name for row in rows} == EXPECTED_TABLES


def test_journal_mode_is_wal_for_new_connections(
    repository: CapitalRepository,
) -> None:
    raw = sqlite3.connect(repository.database_path)
    try:
        mode = raw.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        raw.close()
    assert mode == "wal"


def test_repository_connections_enforce_foreign_keys(
    repository: CapitalRepository,
) -> None:
    with repository.engine.connect() as conn:
        assert conn.execute(sa.text("PRAGMA foreign_keys")).scalar() == 1
        with pytest.raises(IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO economic_event_legs ("
                    " leg_id, economic_event_id, sequence, asset_kind, direction"
                    ") VALUES ('leg-orphan', 'eco-missing', 0, 'CASH', 'DEBIT')"
                )
            )


def test_schema_version_is_exact_and_persisted(
    repository: CapitalRepository,
) -> None:
    assert metadata.SCHEMA_MAJOR == 2
    assert metadata.LEDGER_SCHEMA_VERSION == 3
    assert repository.schema_version() == metadata.LEDGER_SCHEMA_VERSION
    with repository.engine.connect() as conn:
        stored = conn.execute(
            sa.text("SELECT value FROM gateway_meta WHERE key = 'schema_version'")
        ).scalar()
    assert stored == str(metadata.LEDGER_SCHEMA_VERSION)


def test_idempotency_key_is_unique(repository: CapitalRepository) -> None:
    with repository.engine.begin() as conn:
        _seed_history(conn)
        with pytest.raises(IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO economic_events ("
                    " economic_event_id, idempotency_key, stream_version,"
                    " event_kind, portfolio_id, execution_mode, source_authority,"
                    " effective_at, recorded_at, payload_json,"
                    " payload_content_hash, canonical_event_json"
                    ") VALUES ("
                    " 'eco-dup', 'seed-key-1', 3, 'FEE_CHARGED', 'pf-schema',"
                    " 'manual_confirmed', 'test.seed',"
                    " '2026-08-03T09:00:00+00:00', '2026-08-03T09:00:03+00:00',"
                    " '{}', :payload_hash, '{}')"
                ),
                {"payload_hash": "d" * 64},
            )


def test_payload_content_hash_is_unique(repository: CapitalRepository) -> None:
    with repository.engine.begin() as conn:
        _seed_history(conn)
        with pytest.raises(IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO economic_events ("
                    " economic_event_id, idempotency_key, stream_version,"
                    " event_kind, portfolio_id, execution_mode, source_authority,"
                    " effective_at, recorded_at, payload_json,"
                    " payload_content_hash, canonical_event_json"
                    ") VALUES ("
                    " 'eco-dup', 'seed-key-3', 3, 'FEE_CHARGED', 'pf-schema',"
                    " 'manual_confirmed', 'test.seed',"
                    " '2026-08-03T09:00:00+00:00', '2026-08-03T09:00:03+00:00',"
                    " '{}', :payload_hash, '{}')"
                ),
                {"payload_hash": f"{1:064x}"},
            )


def test_stream_version_is_unique(repository: CapitalRepository) -> None:
    with repository.engine.begin() as conn:
        _seed_history(conn)
        with pytest.raises(IntegrityError):
            conn.execute(
                sa.text(
                    "INSERT INTO economic_events ("
                    " economic_event_id, idempotency_key, stream_version,"
                    " event_kind, portfolio_id, execution_mode, source_authority,"
                    " effective_at, recorded_at, payload_json,"
                    " payload_content_hash, canonical_event_json"
                    ") VALUES ("
                    " 'eco-dup', 'seed-key-3', 2, 'FEE_CHARGED', 'pf-schema',"
                    " 'manual_confirmed', 'test.seed',"
                    " '2026-08-03T09:00:00+00:00', '2026-08-03T09:00:03+00:00',"
                    " '{}', :payload_hash, '{}')"
                ),
                {"payload_hash": "e" * 64},
            )


def test_immutable_tables_reject_update_and_delete(
    repository: CapitalRepository,
) -> None:
    with repository.engine.begin() as conn:
        _seed_history(conn)

    updates = {
        "account_capital_truth": "UPDATE account_capital_truth"
        " SET base_currency = 'USD' WHERE portfolio_id = 'pf-schema'",
        "economic_events": "UPDATE economic_events"
        " SET source_authority = 'x' WHERE economic_event_id = 'eco-seed-1'",
        "economic_event_legs": "UPDATE economic_event_legs"
        " SET cash_amount_cents = 999 WHERE leg_id = 'leg-seed'",
        "event_revisions": "UPDATE event_revisions"
        " SET revision_kind = 'X' WHERE canonical_event_id = 'eco-seed-1'",
        "execution_revisions": "UPDATE execution_revisions"
        " SET revision_kind = 'X' WHERE execution_revision_id = 'xrev-seed'",
        "session_checkpoints": "UPDATE session_checkpoints"
        " SET stream_version = 999 WHERE session = '2026-08-03'",
        "entry_tombstones": "UPDATE entry_tombstones"
        " SET tombstone_reason = 'x' WHERE entry_identity = 'entry-seed'",
        "capital_flow_events": "UPDATE capital_flow_events"
        " SET flow_kind = 'X' WHERE flow_event_id = 'flow-seed'",
        "nav_observations": "UPDATE nav_observations"
        " SET nav_cents = 0 WHERE nav_observation_id = 'navobs-seed'",
        "risk_epoch_history": "UPDATE risk_epoch_history"
        " SET audited_nav_cents = 0 WHERE risk_epoch = 1",
    }
    deletes = {
        table: f"DELETE FROM {table}" for table in IMMUTABLE_TABLES
    }

    assert set(updates) == IMMUTABLE_TABLES
    with repository.engine.connect() as conn:
        for table, statement in updates.items():
            with pytest.raises(sa.exc.SQLAlchemyError) as excinfo:
                conn.execute(sa.text(statement))
            assert "immutable" in str(excinfo.value)
            assert table in str(excinfo.value)
        for table, statement in deletes.items():
            with pytest.raises(sa.exc.SQLAlchemyError) as excinfo:
                conn.execute(sa.text(statement))
            assert "immutable" in str(excinfo.value)
            assert table in str(excinfo.value)


def test_monetary_columns_use_integer_quanta_not_real(
    repository: CapitalRepository,
) -> None:
    with repository.engine.connect() as conn:
        tables = conn.execute(
            sa.text(
                "SELECT name FROM sqlite_master"
                " WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ).all()
        declared: dict[tuple[str, str], str] = {}
        for (table,) in tables:
            columns = conn.execute(sa.text(f"PRAGMA table_info({table})")).all()
            for column in columns:
                declared[(table, column.name)] = column.type.upper()

    for table, column in INTEGER_QUANTA_COLUMNS:
        declared_type = declared[(table, column)]
        assert "INT" in declared_type, (table, column, declared_type)
    for (table, column), declared_type in declared.items():
        assert not any(token in declared_type for token in ("REAL", "FLOA", "DOUB")), (
            table,
            column,
            declared_type,
        )


def test_alembic_layout_chains_the_ledger_revisions() -> None:
    from alembic.script import ScriptDirectory
    from alembic.config import Config

    migrations = (
        Path(__file__).resolve().parents[4]
        / "src"
        / "screening"
        / "offensive"
        / "v3"
        / "storage"
        / "migrations"
    )
    config = Config()
    config.set_main_option("script_location", str(migrations))
    script = ScriptDirectory.from_config(config)
    revisions = list(script.walk_revisions())
    assert len(revisions) == 3
    assert script.get_current_head() == metadata.CURRENT_MIGRATION_REVISION
    bases = {revision.revision: revision.down_revision for revision in revisions}
    assert bases[metadata.CURRENT_MIGRATION_REVISION] == (
        metadata.NAV_FLOWS_MIGRATION_REVISION
    )
    assert bases[metadata.NAV_FLOWS_MIGRATION_REVISION] == (
        metadata.INITIAL_MIGRATION_REVISION
    )
    assert bases[metadata.INITIAL_MIGRATION_REVISION] is None


def test_alembic_upgrade_reproduces_create_all_schema(tmp_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    migrations = (
        Path(__file__).resolve().parents[4]
        / "src"
        / "screening"
        / "offensive"
        / "v3"
        / "storage"
        / "migrations"
    )
    database = tmp_path / "alembic_upgrade.sqlite3"
    config = Config()
    config.set_main_option("script_location", str(migrations))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "head")

    raw = sqlite3.connect(database)
    try:
        tables = {
            row[0]
            for row in raw.execute(
                "SELECT name FROM sqlite_master"
                " WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                " AND name != 'alembic_version'"
            )
        }
        triggers = {
            row[0]
            for row in raw.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            )
        }
    finally:
        raw.close()

    assert tables == EXPECTED_TABLES
    for table in IMMUTABLE_TABLES:
        assert f"no_update_{table}" in triggers
        assert f"no_delete_{table}" in triggers
