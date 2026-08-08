"""Plan 06 Task 4 (RED): 单存储 authority CAS 与 handoff cursor.

锁定约束:
1. compare_and_flip() 仅在: 无 in-flight/unresolved lease + preimage (approval/
   adoption/source+target roots/cursor) 与注册表完全一致 时成功.
2. preimage 任一字段漂移 (approval hash、adoption hash、source/target root、
   版本、cursor) 即拒绝, 且不产生任何副作用 (CAS 原子).
3. flip 并发: 两个 flip 只有一个成功; 另一个收到 AUTHORITY_CONFLICT.
4. flip 后: v2 writer fenced; v3 writer 激活于下一 fencing epoch;
   handoff cursor 绑定; 再次 flip 拒绝 (已 flip).
5. flip 后 inbox 重放: v3 消费从 cursor+1 开始; 无事件失去 durable 接收者;
   final reconciliation 前 entry 保持 fenced.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import threading
from pathlib import Path

import pytest

from src.screening.offensive.v3.migration.authority import (
    AUTHORITY_CONFLICT,
    AuthorityError,
    AuthorityRegistry,
    AuthorityState,
    PREIMAGE_MISMATCH,
    UNRESOLVED_LEASE,
)
from src.screening.offensive.v3.migration.compat_writer import CompatibilityWriter
from src.screening.offensive.v3.migration.inbox import (
    DurableCapitalInbox,
    ExternalEventKind,
)

from tests.offensive.v3.migration.helpers import build_populated_ledger

UTC = timezone.utc
NOW = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _clock():  # type: ignore[no-untyped-def]
    current = {"value": NOW}

    def _now() -> datetime:
        current["value"] += timedelta(seconds=1)
        return current["value"]

    return _now


def _registry(tmp_path: Path) -> AuthorityRegistry:
    return AuthorityRegistry(tmp_path / "authority.sqlite3", clock=_clock())


def _preimage(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "approval_hash": HASH_A,
        "adoption_hash": HASH_B,
        "source_root": HASH_C,
        "target_root": "d" * 64,
        "source_stream_version": 20,
        "target_import_version": 1,
        "source_writer": "v2-writer",
        "target_writer": "v3-writer",
        "next_fencing_epoch": 9,
        "handoff_cursor": 7,
    }
    values.update(overrides)
    return values


def _bound_registry(tmp_path: Path, **overrides: object) -> AuthorityRegistry:
    registry = _registry(tmp_path)
    registry.bind_preimage(_preimage(**overrides))
    return registry


def _inbox(tmp_path: Path) -> DurableCapitalInbox:
    return DurableCapitalInbox(tmp_path / "inbox.sqlite3", clock=_clock())


# ---------------------------------------------------------------------------
# flip 前置条件
# ---------------------------------------------------------------------------


def test_flip_succeeds_with_exact_preimage_and_no_lease(tmp_path: Path) -> None:
    registry = _bound_registry(tmp_path)
    receipt = registry.compare_and_flip(_preimage())
    assert receipt.state is AuthorityState.FLIPPED
    assert receipt.active_writer == "v3-writer"
    assert receipt.fencing_epoch == 9
    assert receipt.handoff_cursor == 7


def test_flip_rejects_any_preimage_drift(tmp_path: Path) -> None:
    registry = _bound_registry(tmp_path)
    for field, bad in (
        ("approval_hash", HASH_C),
        ("adoption_hash", HASH_C),
        ("source_root", HASH_A),
        ("target_root", HASH_A),
        ("handoff_cursor", 8),
        ("next_fencing_epoch", 10),
    ):
        drifted = _preimage(**{field: bad})
        with pytest.raises(AuthorityError) as excinfo:
            registry.compare_and_flip(drifted)
        assert excinfo.value.code == PREIMAGE_MISMATCH, field
    # 无副作用: 仍可正常 flip
    registry.compare_and_flip(_preimage())


def test_flip_rejects_unresolved_writer_lease(tmp_path: Path) -> None:
    registry = _bound_registry(tmp_path)
    inbox = _inbox(tmp_path)
    registry.attach_inbox(inbox)
    inbox.force_unresolved_lease_for_test()
    with pytest.raises(AuthorityError) as excinfo:
        registry.compare_and_flip(_preimage())
    assert excinfo.value.code == UNRESOLVED_LEASE


def test_flip_rejects_unacked_projection(tmp_path: Path) -> None:
    registry = _bound_registry(tmp_path)
    inbox = _inbox(tmp_path)
    registry.attach_inbox(inbox)
    inbox.append(
        kind=ExternalEventKind.BROKER_FILL,
        source="broker",
        external_id="f-1",
        occurred_at=NOW,
        payload={"trade_id": "t"},
    )
    inbox.mark_projected(1)
    with pytest.raises(AuthorityError) as excinfo:
        registry.compare_and_flip(_preimage())
    assert excinfo.value.code == UNRESOLVED_LEASE


def test_concurrent_flips_exactly_one_succeeds(tmp_path: Path) -> None:
    registry = _bound_registry(tmp_path)
    outcomes: list[str] = []

    def _flip() -> None:
        try:
            registry.compare_and_flip(_preimage())
            outcomes.append("ok")
        except AuthorityError as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=_flip) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("ok") == 1
    assert outcomes.count(AUTHORITY_CONFLICT) == 3


def test_second_flip_after_success_rejected(tmp_path: Path) -> None:
    registry = _bound_registry(tmp_path)
    registry.compare_and_flip(_preimage())
    with pytest.raises(AuthorityError) as excinfo:
        registry.compare_and_flip(_preimage())
    assert excinfo.value.code == AUTHORITY_CONFLICT


# ---------------------------------------------------------------------------
# flip 后状态
# ---------------------------------------------------------------------------


def test_flip_fences_v2_writer(tmp_path: Path) -> None:
    registry = _bound_registry(tmp_path, source_writer="compat-writer:test")
    inbox = _inbox(tmp_path)
    registry.attach_inbox(inbox)
    ledger_path, _ = build_populated_ledger(tmp_path / "v2")
    writer = CompatibilityWriter(
        ledger_path=ledger_path,
        inbox=inbox,
        ledger_id="test",
        initial_cash=100_000,
        clock=_clock(),
    )
    registry.compare_and_flip(_preimage(source_writer="compat-writer:test"))
    from src.screening.offensive.v3.migration.compat_writer import (
        COMPAT_WRITER_FENCED,
        CompatWriterError,
    )

    inbox.append(
        kind=ExternalEventKind.BROKER_FILL,
        source="broker",
        external_id="post-flip",
        occurred_at=NOW,
        payload={"trade_id": "trade-pending", "exit_date": "2026-07-22",
                 "raw_fill_price": "11.0", "commission": "5.0", "tax": "0.0",
                 "slippage_cost": "3.0"},
    )
    with pytest.raises(CompatWriterError) as excinfo:
        writer.apply_next()
    assert excinfo.value.code == COMPAT_WRITER_FENCED


def test_flip_binds_handoff_cursor_for_v3_replay(tmp_path: Path) -> None:
    registry = _bound_registry(tmp_path, handoff_cursor=3)
    receipt = registry.compare_and_flip(_preimage(handoff_cursor=3))
    assert receipt.replay_from == 4  # v3 消费从 cursor+1 开始


def test_entry_stays_fenced_until_final_reconciliation(tmp_path: Path) -> None:
    registry = _bound_registry(tmp_path)
    registry.compare_and_flip(_preimage())
    assert registry.entry_permitted() is False
    registry.complete_final_reconciliation()
    assert registry.entry_permitted() is True


def test_replay_tracks_consumed_revisions(tmp_path: Path) -> None:
    registry = _bound_registry(tmp_path, handoff_cursor=0)
    inbox = _inbox(tmp_path)
    registry.attach_inbox(inbox)
    registry.compare_and_flip(_preimage(handoff_cursor=0))
    inbox.append(
        kind=ExternalEventKind.BROKER_FILL,
        source="broker",
        external_id="post-flip-1",
        occurred_at=NOW,
        payload={"trade_id": "t"},
    )
    consumed = registry.replay_inbox()
    assert consumed == (1,)
    assert registry.replay_inbox() == ()
