"""Divergent replay latch across takeover: re-enable gate item 4.

The withdrawal migration's re-enable gate requires stable operation ids and
divergent replay latching across takeover: a writer resuming a window after
another writer's takeover must re-drive the same stable operation ids, and a
byte-different replay must latch durably instead of overwriting, passing, or
recomputing a more favorable proposal.  These tests pin the primitive against
real SQLite files, including trigger-level rejection of direct-write
bypasses and the fence-first same-transaction consumption discipline.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa

from src.screening.offensive.v3.capital.fence import (
    CapitalFence,
    CapitalFenceError,
)
from src.screening.offensive.v3.capital.replay_latch import (
    ReplayLatch,
    ReplayLatchError,
)
from src.screening.offensive.v3.capital.repository import CapitalRepository

T0 = datetime(2026, 9, 15, 6, 0, 0, tzinfo=timezone.utc)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


def _at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


@pytest.fixture()
def latch_repo(tmp_path: Path):
    path = tmp_path / "replay_latch.sqlite3"
    repository = CapitalRepository.initialize(path)
    fence = CapitalFence.attach(repository)
    latch = ReplayLatch.attach(fence)
    yield repository, fence, latch
    repository.engine.dispose()


def _open_autocommit(repository):
    return repository.engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    )


def _rows(repository) -> dict:
    with repository.engine.connect() as conn:
        return {
            str(row.operation_id): (
                int(row.epoch),
                str(row.payload_content_hash),
                str(row.state),
                row.diverged_epoch,
                row.diverged_payload_content_hash,
            )
            for row in conn.execute(
                sa.text(
                    "SELECT operation_id, epoch, payload_content_hash, state,"
                    " diverged_epoch, diverged_payload_content_hash FROM"
                    " capital_replay_latches"
                )
            ).all()
        }


def _economic_event_count(repository) -> int:
    with repository.engine.connect() as conn:
        return int(
            conn.execute(
                sa.text("SELECT COUNT(*) FROM economic_events")
            ).scalar_one()
        )


def _bind_account_and_event(
    conn: sa.Connection, portfolio_id: str, event_id: str
) -> None:
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


# -- A1: attach discipline -----------------------------------------------------


def test_attach_requires_fenced_ledger(tmp_path: Path) -> None:
    repository = CapitalRepository.initialize(tmp_path / "unfenced.sqlite3")
    try:
        with pytest.raises(ReplayLatchError) as excinfo:
            ReplayLatch.attach(CapitalFence(repository))
        assert excinfo.value.code == "replay_latch_requires_fenced_ledger"
        with repository.engine.connect() as conn:
            present = conn.execute(
                sa.text(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
                    " AND name = 'capital_replay_latches'"
                )
            ).scalar_one()
        assert int(present) == 0
    finally:
        repository.engine.dispose()


def test_attach_requires_fresh_namespace(latch_repo, tmp_path: Path) -> None:
    repository, _, _ = latch_repo
    legacy_path = tmp_path / "legacy.sqlite3"
    repository.engine.dispose()
    import shutil

    shutil.copyfile(repository.database_path, legacy_path)
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
        " VALUES ('evt-legacy', 'ik-legacy', 7, 'GENESIS', 'pf-legacy',"
        " 'DAILY_BAR_PROXY', 'test', '2026-09-15T00:00:00+00:00',"
        " '2026-09-15T00:00:00+00:00', '{}', 'deadbeef2', '{}')"
    )
    conn.commit()
    conn.close()

    legacy = CapitalRepository.open(legacy_path)
    try:
        with pytest.raises(ReplayLatchError) as excinfo:
            ReplayLatch.attach(CapitalFence(legacy))
        assert excinfo.value.code == "replay_latch_requires_fresh_namespace"
        assert excinfo.value.details["economic_events"] == 1
        with legacy.engine.connect() as conn2:
            # The copied ledger already carries the latch schema (the copy was
            # taken after attach); the rejection must have written nothing.
            latch_rows = conn2.execute(
                sa.text("SELECT COUNT(*) FROM capital_replay_latches")
            ).scalar_one()
        assert int(latch_rows) == 0
    finally:
        legacy.engine.dispose()


def test_attach_is_idempotent(latch_repo) -> None:
    repository, fence, _ = latch_repo
    again = ReplayLatch.attach(fence)
    assert again.repository is repository
    assert again.fence is fence


def test_attach_rejects_drifted_latch_shape(latch_repo) -> None:
    repository, fence, _ = latch_repo
    with repository.engine.begin() as conn:
        conn.execute(sa.text("DROP TABLE capital_replay_latches"))
        conn.execute(
            sa.text(
                "CREATE TABLE capital_replay_latches (operation_id TEXT"
                " PRIMARY KEY, epoch INTEGER)"
            )
        )
    with pytest.raises(ReplayLatchError) as excinfo:
        ReplayLatch.attach(fence)
    assert excinfo.value.code == "replay_latch_schema_drift"
    with repository.engine.connect() as conn:
        columns = [
            str(row[1])
            for row in conn.execute(
                sa.text("PRAGMA table_info(capital_replay_latches)")
            ).all()
        ]
    assert columns == ["operation_id", "epoch"]


def test_attach_rejects_missing_enforcement_triggers(latch_repo) -> None:
    repository, fence, _ = latch_repo
    raw = sqlite3.connect(repository.database_path)
    try:
        raw.execute("DROP TRIGGER replay_latch_no_delete")
        raw.commit()
    finally:
        raw.close()
    with pytest.raises(ReplayLatchError) as excinfo:
        ReplayLatch.attach(fence)
    assert excinfo.value.code == "replay_latch_schema_drift"
    with repository.engine.connect() as conn:
        triggers = {
            str(row[0])
            for row in conn.execute(
                sa.text(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                    " AND name LIKE 'replay_latch_%'"
                )
            ).all()
        }
    assert "replay_latch_no_delete" not in triggers


# -- A2: record semantics ------------------------------------------------------


def test_record_inserts_then_converges_idempotently(latch_repo) -> None:
    repository, _, latch = latch_repo
    ticket = latch.fence.claim("writer-a", now=_at(0), lease_seconds=600)
    conn = _open_autocommit(repository)
    try:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        first = latch.record(
            conn, ticket, "pair-x:reserve", DIGEST_A, now=_at(1)
        )
        conn.exec_driver_sql("COMMIT")
    finally:
        conn.close()
    assert (first.epoch, first.state) == (ticket.epoch, "COMMITTED")
    second = latch.record(
        _open_autocommit(repository),
        ticket,
        "pair-x:reserve",
        DIGEST_A,
        now=_at(2),
    )
    assert second.payload_content_hash == DIGEST_A
    rows = _rows(repository)
    assert rows == {"pair-x:reserve": (ticket.epoch, DIGEST_A, "COMMITTED",
                                       None, None)}


def test_record_rejects_digest_mismatch_and_leaves_row(latch_repo) -> None:
    repository, _, latch = latch_repo
    ticket = latch.fence.claim("writer-a", now=_at(0), lease_seconds=600)
    conn = _open_autocommit(repository)
    try:
        latch.record(conn, ticket, "pair-x:reserve", DIGEST_A, now=_at(1))
        with pytest.raises(ReplayLatchError) as excinfo:
            latch.record(conn, ticket, "pair-x:reserve", DIGEST_B, now=_at(2))
        assert excinfo.value.code == "replay_divergence"
        assert (
            excinfo.value.details["committed_payload_content_hash"] == DIGEST_A
        )
        assert excinfo.value.details["observed_payload_content_hash"] == DIGEST_B
    finally:
        conn.close()
    rows = _rows(repository)
    assert rows["pair-x:reserve"][1] == DIGEST_A
    assert rows["pair-x:reserve"][2] == "COMMITTED"


def test_record_shape_checks_fail_closed(latch_repo) -> None:
    repository, _, latch = latch_repo
    ticket = latch.fence.claim("writer-a", now=_at(0), lease_seconds=600)
    conn = _open_autocommit(repository)
    try:
        with pytest.raises(ReplayLatchError) as excinfo:
            latch.record(conn, ticket, "pair-x", "deadbeef", now=_at(1))
        assert excinfo.value.code == "replay_latch_invalid_digest"
        with pytest.raises(ReplayLatchError) as excinfo:
            latch.record(conn, ticket, "  ", DIGEST_A, now=_at(1))
        assert excinfo.value.code == "replay_latch_invalid_operation"
        with pytest.raises(TypeError):
            latch.record(repository.engine, ticket, "pair-x", DIGEST_A,
                         now=_at(1))
        with pytest.raises(ReplayLatchError) as excinfo:
            latch.record(
                conn,
                ticket,
                "pair-x",
                DIGEST_A,
                now=datetime(2026, 9, 15, 6, 0, 0),
            )
        assert excinfo.value.code == "replay_latch_now_naive"
    finally:
        conn.close()
    assert _rows(repository) == {}


# -- A3: latch semantics -------------------------------------------------------


def test_latch_divergence_is_one_way_and_terminal(latch_repo) -> None:
    repository, _, latch = latch_repo
    ticket = latch.fence.claim("writer-a", now=_at(0), lease_seconds=600)
    conn = _open_autocommit(repository)
    try:
        latch.record(conn, ticket, "pair-x:fill", DIGEST_A, now=_at(1))
        latched = latch.latch_divergence(
            conn, ticket, "pair-x:fill", DIGEST_B, now=_at(2)
        )
        assert latched.state == "DIVERGED"
        assert latched.diverged_epoch == ticket.epoch
        assert latched.diverged_payload_content_hash == DIGEST_B
        with pytest.raises(ReplayLatchError) as excinfo:
            latch.latch_divergence(
                conn, ticket, "pair-x:fill", DIGEST_B, now=_at(3)
            )
        assert excinfo.value.code == "replay_latch_already_latched"
        for digest in (DIGEST_A, DIGEST_B):
            with pytest.raises(ReplayLatchError) as excinfo:
                latch.record(conn, ticket, "pair-x:fill", digest, now=_at(4))
            assert excinfo.value.code == "replay_latch_latched"
    finally:
        conn.close()
    rows = _rows(repository)
    assert rows["pair-x:fill"] == (
        ticket.epoch,
        DIGEST_A,
        "DIVERGED",
        ticket.epoch,
        DIGEST_B,
    )


def test_latch_refuses_unknown_operation_and_equality(latch_repo) -> None:
    repository, _, latch = latch_repo
    ticket = latch.fence.claim("writer-a", now=_at(0), lease_seconds=600)
    conn = _open_autocommit(repository)
    try:
        with pytest.raises(ReplayLatchError) as excinfo:
            latch.latch_divergence(
                conn, ticket, "pair-unknown", DIGEST_B, now=_at(1)
            )
        assert excinfo.value.code == "replay_latch_unknown_operation"
        latch.record(conn, ticket, "pair-x", DIGEST_A, now=_at(1))
        with pytest.raises(ReplayLatchError) as excinfo:
            latch.latch_divergence(
                conn, ticket, "pair-x", DIGEST_A, now=_at(2)
            )
        assert excinfo.value.code == "replay_latch_not_divergent"
    finally:
        conn.close()
    rows = _rows(repository)
    assert rows["pair-x"][2] == "COMMITTED"


# -- A4: takeover convergence and fence-first consumption ----------------------


def test_takeover_converges_by_digest_not_epoch(latch_repo) -> None:
    repository, _, latch = latch_repo
    old = latch.fence.claim("writer-a", now=_at(0), lease_seconds=600)
    conn = _open_autocommit(repository)
    try:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        latch.record(conn, old, "pair-x", DIGEST_A, now=_at(1))
        conn.exec_driver_sql("COMMIT")
    finally:
        conn.close()
    new = latch.fence.takeover("writer-b", now=_at(2), lease_seconds=600)
    assert new.epoch == old.epoch + 1
    conn = _open_autocommit(repository)
    try:
        # Same stable operation id, byte-identical payload: the replay of the
        # displaced writer's commit converges on the original record.
        entry = latch.record(conn, new, "pair-x", DIGEST_A, now=_at(3))
        assert entry.epoch == old.epoch
        assert entry.state == "COMMITTED"
        # Byte-different replay of the same stable id: typed divergence.
        with pytest.raises(ReplayLatchError) as excinfo:
            latch.record(conn, new, "pair-x", DIGEST_B, now=_at(4))
        assert excinfo.value.code == "replay_divergence"
        assert excinfo.value.details["committed_epoch"] == old.epoch
    finally:
        conn.close()
    rows = _rows(repository)
    assert rows["pair-x"] == (old.epoch, DIGEST_A, "COMMITTED", None, None)


def test_lost_fence_records_nothing(latch_repo) -> None:
    repository, fence, latch = latch_repo
    old = fence.claim("writer-a", now=_at(0), lease_seconds=60)
    fence.takeover("writer-b", now=_at(1), lease_seconds=600)
    conn = _open_autocommit(repository)
    try:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        for ticket in (old,):
            with pytest.raises(CapitalFenceError) as excinfo:
                latch.record(conn, ticket, "pair-x", DIGEST_A, now=_at(2))
            assert excinfo.value.code == "fence_lost"
            assert excinfo.value.details["reason"] == "superseded"
            with pytest.raises(CapitalFenceError):
                latch.latch_divergence(
                    conn, ticket, "pair-x", DIGEST_B, now=_at(2)
                )
        conn.exec_driver_sql("ROLLBACK")
    finally:
        conn.close()
    assert _rows(repository) == {}


def test_assert_record_and_economic_write_rollback_atomically(
    latch_repo,
) -> None:
    repository, _, latch = latch_repo
    ticket = latch.fence.claim("writer-a", now=_at(0), lease_seconds=600)
    conn = _open_autocommit(repository)
    try:
        conn.exec_driver_sql("BEGIN IMMEDIATE")
        _bind_account_and_event(conn, "pf-latch", "evt-genesis")
        latch.record(conn, ticket, "pair-x", DIGEST_A, now=_at(1))
        conn.exec_driver_sql("ROLLBACK")
    finally:
        conn.close()
    assert _rows(repository) == {}
    assert _economic_event_count(repository) == 0


def test_uncommitted_latch_invisible_to_independent_connection(
    latch_repo,
) -> None:
    repository, _, latch = latch_repo
    ticket = latch.fence.claim("writer-a", now=_at(0), lease_seconds=600)
    writer_conn = _open_autocommit(repository)
    outside_conn = _open_autocommit(repository)
    try:
        writer_conn.exec_driver_sql("BEGIN IMMEDIATE")
        latch.record(writer_conn, ticket, "pair-x", DIGEST_A, now=_at(1))
        assert _rows(repository) == {}
        writer_conn.exec_driver_sql("COMMIT")
        assert "pair-x" in _rows(repository)
    finally:
        writer_conn.close()
        outside_conn.close()


# -- A5: trigger-level enforcement ----------------------------------------------


def test_triggers_reject_direct_write_bypasses(latch_repo) -> None:
    repository, _, latch = latch_repo
    ticket = latch.fence.claim("writer-a", now=_at(0), lease_seconds=600)
    conn = _open_autocommit(repository)
    try:
        latch.record(conn, ticket, "pair-x", DIGEST_A, now=_at(1))
    finally:
        conn.close()
    raw = sqlite3.connect(repository.database_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                "UPDATE capital_replay_latches SET operation_id = 'pair-y'"
                " WHERE operation_id = 'pair-x'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                "UPDATE capital_replay_latches SET payload_content_hash = ?"
                " WHERE operation_id = 'pair-x'",
                (DIGEST_B,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                "UPDATE capital_replay_latches SET epoch = 99"
                " WHERE operation_id = 'pair-x'"
            )
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute("DELETE FROM capital_replay_latches")
    finally:
        raw.close()
    rows = _rows(repository)
    assert rows["pair-x"][0] == ticket.epoch
    assert rows["pair-x"][1] == DIGEST_A


def test_latched_row_is_irreversible_even_to_direct_writes(latch_repo) -> None:
    repository, _, latch = latch_repo
    ticket = latch.fence.claim("writer-a", now=_at(0), lease_seconds=600)
    conn = _open_autocommit(repository)
    try:
        latch.record(conn, ticket, "pair-x", DIGEST_A, now=_at(1))
        latch.latch_divergence(conn, ticket, "pair-x", DIGEST_B, now=_at(2))
    finally:
        conn.close()
    raw = sqlite3.connect(repository.database_path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                "UPDATE capital_replay_latches SET state = 'COMMITTED',"
                " diverged_epoch = NULL,"
                " diverged_payload_content_hash = NULL,"
                " diverged_wall_ms = NULL WHERE operation_id = 'pair-x'"
            )
    finally:
        raw.close()
    rows = _rows(repository)
    assert rows["pair-x"][2] == "DIVERGED"
    assert rows["pair-x"][4] == DIGEST_B


def test_foreign_key_rejects_epoch_without_fence_row(latch_repo) -> None:
    repository, _, _ = latch_repo
    raw = sqlite3.connect(repository.database_path)
    raw.execute("PRAGMA foreign_keys=ON")
    try:
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                "INSERT INTO capital_replay_latches (operation_id, epoch,"
                " payload_content_hash, state, recorded_wall_ms,"
                " diverged_epoch, diverged_payload_content_hash,"
                " diverged_wall_ms)"
                " VALUES ('pair-x', 999, ?, 'COMMITTED', 1, NULL, NULL, NULL)",
                (DIGEST_A,),
            )
    finally:
        raw.close()


# -- A6: zero production disturbance --------------------------------------------


def test_latch_operations_never_create_economic_events(latch_repo) -> None:
    repository, _, latch = latch_repo
    ticket = latch.fence.claim("writer-a", now=_at(0), lease_seconds=600)
    conn = _open_autocommit(repository)
    try:
        latch.record(conn, ticket, "pair-x", DIGEST_A, now=_at(1))
        latch.latch_divergence(conn, ticket, "pair-x", DIGEST_B, now=_at(2))
    finally:
        conn.close()
    assert _rows(repository)["pair-x"][2] == "DIVERGED"
    assert _economic_event_count(repository) == 0


def test_concurrent_replay_writers_serialize_without_duplicate_ids(
    latch_repo,
) -> None:
    repository, _, latch = latch_repo
    fence = latch.fence
    first = fence.claim("writer-a", now=_at(0), lease_seconds=600)
    conn = _open_autocommit(repository)
    try:
        latch.record(conn, first, "pair-x", DIGEST_A, now=_at(1))
    finally:
        conn.close()
    second = fence.takeover("writer-b", now=_at(2), lease_seconds=600)
    results: list = []
    barrier = threading.Barrier(6)

    def _replay(digest: str) -> None:
        barrier.wait()
        conn = _open_autocommit(repository)
        try:
            results.append(
                latch.record(conn, second, "pair-x", digest, now=_at(3))
            )
        except ReplayLatchError as exc:
            results.append(exc)
        finally:
            conn.close()

    threads = [
        threading.Thread(target=_replay, args=(digest,))
        for digest in [DIGEST_A] * 3 + [DIGEST_B] * 3
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    converged = [r for r in results if not isinstance(r, ReplayLatchError)]
    diverged = [r for r in results if isinstance(r, ReplayLatchError)]
    # BEGIN IMMEDIATE serializes record's read-modify-write: the byte-identical
    # replays converge on the original row, every byte-different replay fails
    # closed, and the durable row still binds the original committing epoch.
    assert len(converged) == 3
    assert all(r.epoch == first.epoch for r in converged)
    assert {exc.code for exc in diverged} == {"replay_divergence"}
    rows = _rows(repository)
    assert rows["pair-x"] == (first.epoch, DIGEST_A, "COMMITTED", None, None)
