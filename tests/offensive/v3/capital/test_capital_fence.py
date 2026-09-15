"""Capital-local writer fencing epoch: re-enable gate items 1-3.

The withdrawal migration
(``docs/superpowers/migrations/2026-08-13-shadow-capital-mutation-withdrawal.md``)
names the re-enable preconditions: a monotone fencing epoch per arm
database, atomic claim/renew/expiry/takeover bound to a writer identity, and
same-transaction consumption for every economic write. These tests pin the
primitive against real SQLite files, including trigger-level rejection of
direct-write bypasses.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from src.screening.offensive.v3.capital.fence import (
    CapitalFence,
    CapitalFenceError,
    FenceTicket,
)
from src.screening.offensive.v3.capital.repository import CapitalRepository

T0 = datetime(2026, 9, 15, 6, 0, 0, tzinfo=timezone.utc)


def _at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


@pytest.fixture()
def fresh_repo(tmp_path: Path):
    path = tmp_path / "fence.sqlite3"
    repository = CapitalRepository.initialize(path)
    yield repository
    repository.engine.dispose()


def _attach(repository) -> CapitalFence:
    return CapitalFence.attach(repository)


def _tamper_ticket(ticket: FenceTicket, **changes) -> FenceTicket:
    fields = ticket.model_dump()
    fields.update(changes)
    return FenceTicket.model_validate(fields)


# -- attach: fresh-namespace discipline (gate item 7) -------------------------


def test_attach_on_fresh_ledger_is_idempotent(fresh_repo) -> None:
    fence = _attach(fresh_repo)
    again = _attach(fresh_repo)
    assert again.repository is fresh_repo
    with fresh_repo.engine.connect() as conn:
        columns = {
            row[1]
            for row in conn.execute(
                sa.text("PRAGMA table_info(capital_fence_epochs)")
            ).all()
        }
        assert "epoch" in columns and "superseded_by_epoch" in columns
        triggers = {
            row[0]
            for row in conn.execute(
                sa.text(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                    " AND name LIKE 'fence_%'"
                )
            ).all()
        }
        assert {
            "fence_epoch_monotone",
            "fence_identity_immutable",
            "fence_terminal_irreversible",
            "fence_no_delete",
        } <= triggers
    assert fence is not None


def test_attach_rejects_uninitialized_file(tmp_path: Path) -> None:
    import hashlib

    path = tmp_path / "foreign.sqlite3"
    path.write_bytes(b"not a capital ledger")
    before = hashlib.sha256(path.read_bytes()).hexdigest()

    class _Foreign:  # duck repository: only the engine is consulted
        engine = sa.create_engine(f"sqlite:///{path}")

    with pytest.raises(CapitalFenceError) as excinfo:
        CapitalFence.attach(_Foreign())
    assert excinfo.value.code == "fence_requires_initialized_ledger"
    _Foreign.engine.dispose()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_attach_rejects_ledger_with_economic_history(
    fresh_repo, tmp_path: Path
) -> None:
    # A synthetic legacy world: one account binding and one economic event,
    # written directly. The guard must reject adoption of any history.
    legacy_path = tmp_path / "legacy.sqlite3"
    import shutil

    # Checkpoint the WAL into the main file before copying (R35 discipline:
    # a cold file copy of a live WAL database loses the schema writes).
    fresh_repo.engine.dispose()
    shutil.copyfile(
        fresh_repo.database_path, legacy_path
    )
    conn = sqlite3.connect(legacy_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "INSERT INTO account_capital_truth (portfolio_id, broker_account_id,"
        " execution_mode, base_currency, binding_content_hash,"
        " lifecycle_state, bound_at) VALUES ('pf-legacy', NULL,"
        " 'DAILY_BAR_PROXY', 'CNY', 'deadbeef', 'ACTIVE',"
        " '2026-09-15T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO economic_events (economic_event_id, idempotency_key,"
        " stream_version, event_kind, portfolio_id, execution_mode,"
        " source_authority, effective_at, recorded_at, payload_json,"
        " payload_content_hash, canonical_event_json)"
        " VALUES ('evt-legacy', 'ik-legacy', 1, 'GENESIS', 'pf-legacy',"
        " 'DAILY_BAR_PROXY', 'test', '2026-09-15T00:00:00+00:00',"
        " '2026-09-15T00:00:00+00:00', '{}', 'deadbeef', '{}')"
    )
    conn.commit()
    conn.close()

    repository = CapitalRepository.open(legacy_path)
    try:
        with pytest.raises(CapitalFenceError) as excinfo:
            CapitalFence.attach(repository)
        assert excinfo.value.code == "fence_namespace_not_fresh"
        assert excinfo.value.details["economic_events"] == 1
        with repository.engine.connect() as conn2:
            assert (
                conn2.execute(
                    sa.text(
                        "SELECT COUNT(*) FROM sqlite_master WHERE"
                        " name = 'capital_fence_epochs'"
                    )
                ).scalar_one()
                == 0
            )
    finally:
        repository.engine.dispose()


# -- claim: monotone epochs and quiet-fence requirement ------------------------


def test_claim_mints_strictly_increasing_epochs(fresh_repo) -> None:
    fence = _attach(fresh_repo)
    first = fence.claim("writer-a", now=_at(0), lease_seconds=60)
    fence.release(first, now=_at(1))
    second = fence.claim("writer-a", now=_at(2), lease_seconds=60)
    assert (first.epoch, second.epoch) == (1, 2)
    assert second.expires_wall_ms == int(_at(62).timestamp() * 1000)


def test_claim_refuses_unexpired_active_lease_even_for_same_writer(
    fresh_repo,
) -> None:
    fence = _attach(fresh_repo)
    ticket = fence.claim("writer-a", now=_at(0), lease_seconds=60)
    with pytest.raises(CapitalFenceError) as excinfo:
        fence.claim("writer-a", now=_at(1), lease_seconds=60)
    assert excinfo.value.code == "fence_already_active"
    assert excinfo.value.details["active_epoch"] == ticket.epoch
    with pytest.raises(CapitalFenceError) as excinfo:
        fence.claim("writer-b", now=_at(1), lease_seconds=60)
    assert excinfo.value.code == "fence_already_active"


def test_claim_allowed_once_active_lease_expired(fresh_repo) -> None:
    fence = _attach(fresh_repo)
    expired = fence.claim("writer-a", now=_at(0), lease_seconds=60)
    later = fence.claim(
        "writer-b",
        now=datetime.fromtimestamp(
            expired.expires_wall_ms / 1000, tz=timezone.utc
        )
        + timedelta(seconds=1),
        lease_seconds=60,
    )
    assert later.epoch == expired.epoch + 1


def test_takeover_supersedes_expired_active_rows(fresh_repo) -> None:
    fence = _attach(fresh_repo)
    expired = fence.claim("writer-a", now=_at(0), lease_seconds=60)
    after_expiry = datetime.fromtimestamp(
        expired.expires_wall_ms / 1000, tz=timezone.utc
    )
    ticket = fence.takeover("writer-b", now=after_expiry, lease_seconds=60)
    assert ticket.epoch == expired.epoch + 1
    with fresh_repo.engine.connect() as conn:
        states = {
            int(row.epoch): (str(row.state), row.superseded_by_epoch)
            for row in conn.execute(
                sa.text(
                    "SELECT epoch, state, superseded_by_epoch FROM"
                    " capital_fence_epochs ORDER BY epoch"
                )
            ).all()
        }
    assert states[expired.epoch] == ("SUPERSEDED", ticket.epoch)
    assert states[ticket.epoch] == ("ACTIVE", None)


def test_invalid_inputs_fail_closed(fresh_repo) -> None:
    fence = _attach(fresh_repo)
    with pytest.raises(CapitalFenceError) as excinfo:
        fence.claim("", now=_at(0), lease_seconds=60)
    assert excinfo.value.code == "fence_invalid_writer"
    with pytest.raises(CapitalFenceError) as excinfo:
        fence.claim("w", now=_at(0), lease_seconds=0)
    assert excinfo.value.code == "fence_invalid_lease"
    with pytest.raises(CapitalFenceError) as excinfo:
        fence.claim("w", now=_at(0), lease_seconds=True)
    assert excinfo.value.code == "fence_invalid_lease"
    with pytest.raises(CapitalFenceError) as excinfo:
        fence.claim("w", now=datetime(2026, 9, 15, 6, 0, 0), lease_seconds=60)
    assert excinfo.value.code == "fence_now_naive"


# -- renew / release: writer-bound lease maintenance ---------------------------


def test_renew_extends_expiry_for_current_owner(fresh_repo) -> None:
    fence = _attach(fresh_repo)
    ticket = fence.claim("writer-a", now=_at(0), lease_seconds=60)
    renewed = fence.renew(ticket, now=_at(30), lease_seconds=60)
    assert renewed.epoch == ticket.epoch
    assert renewed.expires_wall_ms == int(_at(90).timestamp() * 1000)
    assert renewed.expires_wall_ms > ticket.expires_wall_ms


def test_renew_rejects_wrong_writer(fresh_repo) -> None:
    fence = _attach(fresh_repo)
    ticket = fence.claim("writer-a", now=_at(0), lease_seconds=60)
    forged = _tamper_ticket(ticket, writer_id="writer-b")
    with pytest.raises(CapitalFenceError) as excinfo:
        fence.renew(forged, now=_at(1), lease_seconds=60)
    # A3: 错 writer 与已过期/已 superseded 同族 fail-closed 为 fence_lost，
    # 归因细节放 reason/details，不另立顶层码。
    assert excinfo.value.code == "fence_lost"
    assert excinfo.value.details["reason"] == "writer_mismatch"


def test_renew_rejects_expired_lease(fresh_repo) -> None:
    fence = _attach(fresh_repo)
    ticket = fence.claim("writer-a", now=_at(0), lease_seconds=60)
    with pytest.raises(CapitalFenceError) as excinfo:
        fence.renew(ticket, now=_at(61), lease_seconds=60)
    assert excinfo.value.code == "fence_lost"
    assert excinfo.value.details["reason"] == "expired"


def test_renew_after_takeover_reports_supersession(fresh_repo) -> None:
    fence = _attach(fresh_repo)
    old = fence.claim("writer-a", now=_at(0), lease_seconds=60)
    new = fence.takeover("writer-b", now=_at(1), lease_seconds=60)
    assert new.epoch == old.epoch + 1
    with pytest.raises(CapitalFenceError) as excinfo:
        fence.renew(old, now=_at(2), lease_seconds=60)
    assert excinfo.value.code == "fence_lost"
    assert excinfo.value.details["reason"] == "superseded"
    assert excinfo.value.details["superseded_by_epoch"] == new.epoch


def test_release_then_renew_is_terminal(fresh_repo) -> None:
    fence = _attach(fresh_repo)
    ticket = fence.claim("writer-a", now=_at(0), lease_seconds=60)
    fence.release(ticket, now=_at(1))
    with pytest.raises(CapitalFenceError) as excinfo:
        fence.renew(ticket, now=_at(2), lease_seconds=60)
    assert excinfo.value.code == "fence_lost"
    assert excinfo.value.details["reason"] == "released"
    with pytest.raises(CapitalFenceError) as excinfo:
        fence.release(ticket, now=_at(3))
    assert excinfo.value.code == "fence_lost"


# -- same-transaction consumption (gate item 3) --------------------------------


def test_assert_current_passes_inside_caller_transaction(
    fresh_repo,
) -> None:
    fence = _attach(fresh_repo)
    ticket = fence.claim("writer-a", now=_at(0), lease_seconds=60)
    conn = fresh_repo.engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    )
    try:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        fence.assert_current(conn, ticket, now=_at(1))
        conn.exec_driver_sql("ROLLBACK")
    finally:
        conn.close()


def test_assert_current_fails_after_committed_takeover(
    fresh_repo,
) -> None:
    """The takeover-window closure: a writer displaced before its economic
    transaction began cannot pass the consumption check inside that
    transaction, so its economic write dies with the assertion."""

    fence = _attach(fresh_repo)
    old = fence.claim("writer-a", now=_at(0), lease_seconds=60)
    fence.takeover("writer-b", now=_at(1), lease_seconds=60)
    conn = fresh_repo.engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    )
    try:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        with pytest.raises(CapitalFenceError) as excinfo:
            fence.assert_current(conn, old, now=_at(2))
        assert excinfo.value.code == "fence_lost"
        assert excinfo.value.details["reason"] == "superseded"
        conn.exec_driver_sql("ROLLBACK")
    finally:
        conn.close()


def test_assert_current_rejects_expired_ticket(fresh_repo) -> None:
    fence = _attach(fresh_repo)
    ticket = fence.claim("writer-a", now=_at(0), lease_seconds=60)
    conn = fresh_repo.engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    )
    try:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        with pytest.raises(CapitalFenceError) as excinfo:
            fence.assert_current(conn, ticket, now=_at(60))
        assert excinfo.value.code == "fence_lost"
        assert excinfo.value.details["reason"] == "expired"
        conn.exec_driver_sql("ROLLBACK")
    finally:
        conn.close()


def test_assert_current_requires_caller_connection(fresh_repo) -> None:
    fence = _attach(fresh_repo)
    ticket = fence.claim("writer-a", now=_at(0), lease_seconds=60)
    with pytest.raises(TypeError):
        fence.assert_current(fresh_repo.engine, ticket, now=_at(1))


def test_assert_current_never_mutates_fence_rows(fresh_repo) -> None:
    fence = _attach(fresh_repo)
    ticket = fence.claim("writer-a", now=_at(0), lease_seconds=60)
    conn = _open_autocommit(fresh_repo)
    try:
        fence.assert_current(conn, ticket, now=_at(1))
    finally:
        conn.close()
    with fresh_repo.engine.connect() as conn2:
        row = conn2.execute(
            sa.text(
                "SELECT expires_wall_ms, state FROM capital_fence_epochs"
                " WHERE epoch = :epoch"
            ),
            {"epoch": ticket.epoch},
        ).one()
    assert int(row.expires_wall_ms) == ticket.expires_wall_ms
    assert str(row.state) == "ACTIVE"


def _open_autocommit(repository):
    return repository.engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    )


# -- trigger-level enforcement: direct-write bypasses --------------------------


def test_triggers_reject_monotonicity_and_identity_bypasses(
    fresh_repo,
) -> None:
    fence = _attach(fresh_repo)
    ticket = fence.claim("writer-a", now=_at(0), lease_seconds=60)
    raw = sqlite3.connect(fresh_repo.database_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                "INSERT INTO capital_fence_epochs (epoch, writer_id, state,"
                " claimed_wall_ms, expires_wall_ms, superseded_by_epoch)"
                " VALUES (1, 'attacker', 'ACTIVE', 1, 2, NULL)"
            )
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                "INSERT INTO capital_fence_epochs (epoch, writer_id, state,"
                " claimed_wall_ms, expires_wall_ms, superseded_by_epoch)"
                " VALUES (?, 'attacker', 'ACTIVE', 1, 2, NULL)",
                (ticket.epoch,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                "UPDATE capital_fence_epochs SET writer_id = 'attacker'"
                " WHERE epoch = ?",
                (ticket.epoch,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                "UPDATE capital_fence_epochs SET claimed_wall_ms = 0"
                " WHERE epoch = ?",
                (ticket.epoch,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                "DELETE FROM capital_fence_epochs WHERE epoch = ?",
                (ticket.epoch,),
            )
        raw.commit()
    finally:
        raw.close()
    with fresh_repo.engine.connect() as conn:
        row = conn.execute(
            sa.text(
                "SELECT writer_id FROM capital_fence_epochs"
                " WHERE epoch = :epoch"
            ),
            {"epoch": ticket.epoch},
        ).one()
    assert str(row.writer_id) == "writer-a"


def test_terminal_states_are_irreversible(fresh_repo) -> None:
    fence = _attach(fresh_repo)
    old = fence.claim("writer-a", now=_at(0), lease_seconds=60)
    fence.takeover("writer-b", now=_at(1), lease_seconds=60)
    raw = sqlite3.connect(fresh_repo.database_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                "UPDATE capital_fence_epochs SET state = 'ACTIVE'"
                " WHERE epoch = ?",
                (old.epoch,),
            )
        raw.commit()
    finally:
        raw.close()


def test_takeover_records_full_chains_across_multiple_epochs(
    fresh_repo,
) -> None:
    fence = _attach(fresh_repo)
    first = fence.claim("w1", now=_at(0), lease_seconds=60)
    second = fence.takeover("w2", now=_at(1), lease_seconds=60)
    third = fence.takeover("w3", now=_at(2), lease_seconds=60)
    assert (first.epoch, second.epoch, third.epoch) == (1, 2, 3)
    with pytest.raises(CapitalFenceError) as excinfo:
        fence.assert_current(
            _open_autocommit(fresh_repo), first, now=_at(3)
        )
    assert excinfo.value.details["superseded_by_epoch"] == 2
    with fresh_repo.engine.connect() as conn:
        rows = {
            int(row.epoch): (str(row.state), row.superseded_by_epoch)
            for row in conn.execute(
                sa.text(
                    "SELECT epoch, state, superseded_by_epoch FROM"
                    " capital_fence_epochs ORDER BY epoch"
                )
            ).all()
        }
    assert rows[1] == ("SUPERSEDED", 2)
    assert rows[2] == ("SUPERSEDED", 3)
    assert rows[3] == ("ACTIVE", None)


# -- A1: schema-shape drift is fail-closed, never self-healed ------------------


def test_attach_rejects_drifted_fence_shape_with_zero_side_effects(
    fresh_repo,
) -> None:
    # A pre-existing drifted capital_fence_epochs table on an otherwise fresh
    # ledger must be rejected before any DDL runs: attach never "fixes" a
    # shape it does not recognize.
    with fresh_repo.engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE capital_fence_epochs (epoch INTEGER,"
                " writer_id TEXT)"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO capital_fence_epochs (epoch, writer_id)"
                " VALUES (1, 'legacy-shape')"
            )
        )
    with pytest.raises(CapitalFenceError) as excinfo:
        _attach(fresh_repo)
    assert excinfo.value.code == "fence_schema_drift"
    with fresh_repo.engine.connect() as conn:
        columns = [
            str(row[1])
            for row in conn.execute(
                sa.text("PRAGMA table_info(capital_fence_epochs)")
            ).all()
        ]
        count = conn.execute(
            sa.text("SELECT COUNT(*) FROM capital_fence_epochs")
        ).scalar_one()
        triggers = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'trigger'"
                " AND name LIKE 'fence_%'"
            )
        ).scalar_one()
    assert columns == ["epoch", "writer_id"]
    assert int(count) == 1
    assert int(triggers) == 0


def test_attach_rejects_missing_enforcement_triggers(fresh_repo) -> None:
    # A fence table whose enforcement triggers were dropped (tampered or
    # partially migrated) is not silently repaired: epoch monotonicity is a
    # database-enforced contract, and its absence is drift.
    _attach(fresh_repo)
    raw = sqlite3.connect(fresh_repo.database_path)
    try:
        raw.execute("DROP TRIGGER fence_epoch_monotone")
        raw.commit()
    finally:
        raw.close()
    with pytest.raises(CapitalFenceError) as excinfo:
        CapitalFence.attach(fresh_repo)
    assert excinfo.value.code == "fence_schema_drift"
    with fresh_repo.engine.connect() as conn:
        triggers = {
            str(row[0])
            for row in conn.execute(
                sa.text(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                    " AND name LIKE 'fence_%'"
                )
            ).all()
        }
    assert "fence_epoch_monotone" not in triggers


# -- A2: BEGIN IMMEDIATE serialization under concurrency -----------------------


def test_concurrent_takeovers_mint_distinct_monotone_epochs(fresh_repo):
    fence = _attach(fresh_repo)
    writers = [f"contended-{i}" for i in range(6)]
    results: list = []
    errors: list = []
    barrier = threading.Barrier(len(writers))

    def _takeover(writer: str) -> None:
        barrier.wait()
        try:
            results.append(
                fence.takeover(writer, now=_at(1), lease_seconds=600).epoch
            )
        except CapitalFenceError as exc:  # pragma: no cover - takeover never loses
            errors.append(exc)

    threads = [
        threading.Thread(target=_takeover, args=(writer,))
        for writer in writers
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert sorted(results) == [1, 2, 3, 4, 5, 6]


def test_concurrent_claims_elect_exactly_one_winner(fresh_repo):
    fence = _attach(fresh_repo)
    winners: list = []
    losers: list = []
    barrier = threading.Barrier(6)

    def _claim(index: int) -> None:
        barrier.wait()
        try:
            winners.append(
                fence.claim(f"racer-{index}", now=_at(0), lease_seconds=600)
            )
        except CapitalFenceError as exc:
            losers.append(exc)

    threads = [
        threading.Thread(target=_claim, args=(index,)) for index in range(6)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # BEGIN IMMEDIATE serializes the quiet-fence check with the insert, so
    # exactly one unexpired lease can ever exist — no duplicated epochs.
    assert len(winners) == 1
    assert len(losers) == 5
    assert {exc.code for exc in losers} == {"fence_already_active"}
    assert {exc.details["active_epoch"] for exc in losers} == {
        winners[0].epoch
    }
    fence.release(winners[0], now=_at(1))
    follower = fence.claim("racer-follower", now=_at(2), lease_seconds=60)
    assert follower.epoch == winners[0].epoch + 1


# -- A4: the consumption point shares the economic transaction -----------------


def _bind_account(conn: sa.Connection, portfolio_id: str) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO account_capital_truth (portfolio_id,"
            " broker_account_id, execution_mode, base_currency,"
            " binding_content_hash, lifecycle_state, bound_at)"
            " VALUES (:pid, NULL, 'DAILY_BAR_PROXY', 'CNY', 'deadbeef',"
            " 'ACTIVE', '2026-09-15T00:00:00+00:00')"
        ),
        {"pid": portfolio_id},
    )


def _insert_economic_event(
    conn: sa.Connection, portfolio_id: str, event_id: str
) -> None:
    conn.execute(
        sa.text(
            "INSERT INTO economic_events (economic_event_id, idempotency_key,"
            " stream_version, event_kind, portfolio_id, execution_mode,"
            " source_authority, effective_at, recorded_at, payload_json,"
            " payload_content_hash, canonical_event_json)"
            " VALUES (:eid, :ik, 1, 'GENESIS', :pid, 'DAILY_BAR_PROXY',"
            " 'test', '2026-09-15T00:00:00+00:00',"
            " '2026-09-15T00:00:00+00:00', '{}', :hash, '{}')"
        ),
        {"eid": event_id, "ik": f"ik-{event_id}", "pid": portfolio_id,
         "hash": f"hash-{event_id}"},
    )


def test_assert_then_economic_write_rolls_back_atomically(fresh_repo) -> None:
    fence = _attach(fresh_repo)
    ticket = fence.claim("writer-a", now=_at(0), lease_seconds=600)
    conn = _open_autocommit(fresh_repo)
    try:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        _bind_account(conn, "pf-fence")
        fence.assert_current(conn, ticket, now=_at(1))
        _insert_economic_event(conn, "pf-fence", "evt-tx")
        conn.exec_driver_sql("ROLLBACK")
    finally:
        conn.close()
    # The assertion and the economic write lived and died in one transaction:
    # after ROLLBACK neither left a trace.
    with fresh_repo.engine.connect() as conn2:
        assert (
            conn2.execute(
                sa.text("SELECT COUNT(*) FROM economic_events")
            ).scalar_one()
            == 0
        )
        state = conn2.execute(
            sa.text(
                "SELECT state FROM capital_fence_epochs WHERE epoch = :epoch"
            ),
            {"epoch": ticket.epoch},
        ).scalar_one()
    assert str(state) == "ACTIVE"


def test_uncommitted_state_invisible_to_independent_connection(
    fresh_repo,
) -> None:
    fence = _attach(fresh_repo)
    ticket = fence.claim("writer-a", now=_at(0), lease_seconds=600)
    writer_conn = _open_autocommit(fresh_repo)
    outside_conn = _open_autocommit(fresh_repo)
    try:
        writer_conn.exec_driver_sql("BEGIN IMMEDIATE")
        _bind_account(writer_conn, "pf-fence")
        fence.assert_current(writer_conn, ticket, now=_at(1))
        _insert_economic_event(writer_conn, "pf-fence", "evt-uncommitted")
        # An independent connection must not observe the writer's uncommitted
        # economic event — which is exactly why the consumption check has to
        # run on the economic transaction's own connection: a check through
        # any other connection validates a snapshot, never this transaction.
        assert (
            outside_conn.execute(
                sa.text("SELECT COUNT(*) FROM economic_events")
            ).scalar_one()
            == 0
        )
        writer_conn.exec_driver_sql("ROLLBACK")
        assert (
            outside_conn.execute(
                sa.text("SELECT COUNT(*) FROM economic_events")
            ).scalar_one()
            == 0
        )
    finally:
        writer_conn.close()
        outside_conn.close()
