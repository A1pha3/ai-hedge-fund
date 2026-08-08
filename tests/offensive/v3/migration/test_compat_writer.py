"""Plan 06 Task 2 (RED): durable 外部收件箱与 legacy writer 收敛.

锁定约束:
1. 外部事实 (broker fill/fee、公司行动、exit、correction、manual) 先 durable
   落 inbox, 再投影进 v2 — freeze 前/中/后到达都不丢.
2. 幂等去重: 同 (source, external_id) 重放不得产生第二个 revision;
   out-of-order 修订按接受序持久化, 不乱序丢弃.
3. CompatibilityWriter 协议: acquire lease -> 投影恰好一个 revision -> commit
   v2 -> ACK source token -> release; 每个写返回 SourceToken.
4. 崩溃语义: v2 commit 前崩溃 = lease 无 ACK 可重放; commit 后 ACK 前崩溃 =
   unresolved lease 阻断 flip; lease 持有期间第二写者拒绝.
5. AST 守卫: 新增任何绕过 compat 层的直接 v2 mutator 调用必须失败.
6. writer fence 后, 保留的旧句柄/连接再写必须失败 (FENCED).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import sqlite3
import threading
from pathlib import Path

import pytest

from src.screening.offensive.ledger_repository import LedgerRepository
from src.screening.offensive.v3.migration.compat_writer import (
    ACK_PENDING,
    COMPAT_WRITER_FENCED,
    CompatWriterError,
    CompatibilityWriter,
    LEASE_HELD,
    UNRESOLVED_LEASE,
)
from src.screening.offensive.v3.migration.inbox import (
    DurableCapitalInbox,
    ExternalEventKind,
)
from src.screening.offensive.v3.migration.inventory import capture_v2_inventory

from tests.offensive.v3.migration.helpers import build_populated_ledger

UTC = timezone.utc
NOW = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)


def _clock(start: datetime = NOW):  # type: ignore[no-untyped-def]
    current = {"value": start}

    def _now() -> datetime:
        current["value"] += timedelta(seconds=1)
        return current["value"]

    return _now


def _make_stack(tmp_path: Path):  # type: ignore[no-untyped-def]
    ledger_path, _ = build_populated_ledger(tmp_path / "v2")
    inbox_path = tmp_path / "inbox.sqlite3"
    inbox = DurableCapitalInbox(inbox_path, clock=_clock())
    writer = CompatibilityWriter(
        ledger_path=ledger_path,
        inbox=inbox,
        ledger_id="test",
        initial_cash=100_000,
        clock=_clock(),
    )
    return ledger_path, inbox, writer


def _broker_fill(external_id: str = "fill-1", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "kind": ExternalEventKind.BROKER_FILL,
        "source": "broker-adapter",
        "external_id": external_id,
        "occurred_at": NOW,
        "payload": {
            "trade_id": "trade-pending",
            "exit_date": "2026-07-22",
            "raw_fill_price": "11.0",
            "commission": "5.0",
            "tax": "0.0",
            "slippage_cost": "3.0",
        },
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# inbox 持久化与去重
# ---------------------------------------------------------------------------


def test_external_fact_durably_appended_before_projection(tmp_path: Path) -> None:
    _ledger_path, inbox, _writer = _make_stack(tmp_path)
    receipt = inbox.append(**_broker_fill())
    assert receipt.revision == 1
    pending = inbox.pending()
    assert len(pending) == 1
    assert pending[0].external_id == "fill-1"
    assert pending[0].kind == ExternalEventKind.BROKER_FILL


def test_duplicate_external_id_is_idempotent(tmp_path: Path) -> None:
    _ledger_path, inbox, _writer = _make_stack(tmp_path)
    first = inbox.append(**_broker_fill())
    second = inbox.append(**_broker_fill())
    assert second.revision == first.revision
    assert len(inbox.pending()) == 1


def test_out_of_order_revisions_persist_in_arrival_order(tmp_path: Path) -> None:
    _ledger_path, inbox, _writer = _make_stack(tmp_path)
    later = inbox.append(**_broker_fill("fill-2", occurred_at=NOW + timedelta(hours=2)))
    earlier = inbox.append(**_broker_fill("fill-1", occurred_at=NOW))
    assert earlier.revision > later.revision
    ordered = [row.external_id for row in inbox.pending()]
    assert ordered == ["fill-2", "fill-1"]


def test_revision_payload_is_exactly_round_tripped(tmp_path: Path) -> None:
    _ledger_path, inbox, _writer = _make_stack(tmp_path)
    payload = _broker_fill()["payload"]
    inbox.append(**_broker_fill())
    row = inbox.pending()[0]
    assert row.payload == payload


# ---------------------------------------------------------------------------
# CompatibilityWriter 协议
# ---------------------------------------------------------------------------


def test_writer_projects_one_revision_and_returns_source_token(tmp_path: Path) -> None:
    ledger_path, inbox, writer = _make_stack(tmp_path)
    inbox.append(**_broker_fill())
    result = writer.apply_next()
    assert result.applied is True
    assert result.source_token.ledger_id == "test"
    assert result.source_token.root
    assert inbox.pending() == ()
    inventory = capture_v2_inventory(ledger_path, ledger_id="test")
    trade = inventory.cash  # cash reflects EXIT_FILLED proceeds
    # -18070 (两笔 entry) + 9892 (900*11.0 - 5 - 0 - 3 的 exit proceeds) = -8178
    assert trade.event_cash_delta_sum == Decimal("-8178")


def test_writer_with_empty_inbox_is_noop(tmp_path: Path) -> None:
    _ledger_path, _inbox, writer = _make_stack(tmp_path)
    result = writer.apply_next()
    assert result.applied is False


def test_lease_excludes_concurrent_writer(tmp_path: Path) -> None:
    _ledger_path, inbox, writer = _make_stack(tmp_path)
    inbox.append(**_broker_fill("fill-a"))
    inbox.append(**_broker_fill("fill-b"))
    with writer.lease():
        rival = CompatibilityWriter(
            ledger_path=tmp_path / "v2" / "ledger.sqlite3",
            inbox=inbox,
            ledger_id="other-ledger",
            initial_cash=100_000,
            clock=_clock(),
        )
        with pytest.raises(CompatWriterError) as excinfo:
            rival.apply_next()
        assert excinfo.value.code == LEASE_HELD


def test_lease_released_after_successful_write(tmp_path: Path) -> None:
    _ledger_path, inbox, writer = _make_stack(tmp_path)
    inbox.append(**_broker_fill())
    writer.apply_next()
    with writer.lease():
        pass  # second lease acquisition succeeds once released


def test_unacked_revision_is_replayed_not_duplicated(tmp_path: Path) -> None:
    """ACK 前崩溃: revision 重放时 v2 幂等, 不产生第二笔现金变化."""

    ledger_path, inbox, writer = _make_stack(tmp_path)
    inbox.append(**_broker_fill())
    writer.apply_next()
    # 模拟 ACK 丢失: 直接清掉 ACK, 保留 v2 commit
    inbox._force_unack_for_test(inbox.history()[0].revision)  # type: ignore[attr-defined]
    before = capture_v2_inventory(ledger_path, ledger_id="test")
    result = writer.apply_next()
    assert result.applied is True  # 重放完成 ACK
    after = capture_v2_inventory(ledger_path, ledger_id="test")
    assert after.cash == before.cash
    assert after.event_count == before.event_count


def test_crash_after_commit_before_ack_leaves_unresolved_lease(tmp_path: Path) -> None:
    ledger_path, inbox, writer = _make_stack(tmp_path)
    inbox.append(**_broker_fill())
    writer.apply_next()
    inbox.force_unresolved_lease_for_test()
    inbox2 = DurableCapitalInbox(tmp_path / "inbox.sqlite3", clock=_clock())
    assert inbox2.has_unresolved_lease() is True


def test_unresolved_lease_blocks_flip_gate(tmp_path: Path) -> None:
    _ledger_path, inbox, writer = _make_stack(tmp_path)
    inbox.append(**_broker_fill())
    writer.apply_next()
    inbox.force_unresolved_lease_for_test()
    with pytest.raises(CompatWriterError) as excinfo:
        writer.assert_flip_ready()
    assert excinfo.value.code == UNRESOLVED_LEASE


def test_unacked_projection_blocks_flip_gate(tmp_path: Path) -> None:
    _ledger_path, inbox, writer = _make_stack(tmp_path)
    inbox.append(**_broker_fill())
    writer.apply_next()
    inbox._force_unack_for_test(inbox.history()[0].revision)  # type: ignore[attr-defined]
    with pytest.raises(CompatWriterError) as excinfo:
        writer.assert_flip_ready()
    assert excinfo.value.code == UNRESOLVED_LEASE


def test_flip_ready_when_inbox_drained_and_no_lease(tmp_path: Path) -> None:
    _ledger_path, inbox, writer = _make_stack(tmp_path)
    inbox.append(**_broker_fill())
    writer.apply_next()
    writer.assert_flip_ready()


# ---------------------------------------------------------------------------
# fence: 旧句柄/连接失效
# ---------------------------------------------------------------------------


def test_fenced_writer_rejects_new_writes_and_lease(tmp_path: Path) -> None:
    _ledger_path, inbox, writer = _make_stack(tmp_path)
    inbox.append(**_broker_fill())
    writer.fence()
    with pytest.raises(CompatWriterError) as excinfo:
        writer.apply_next()
    assert excinfo.value.code == COMPAT_WRITER_FENCED
    with pytest.raises(CompatWriterError):
        with writer.lease():
            pass


def test_fence_is_durable_across_process_restart(tmp_path: Path) -> None:
    ledger_path, inbox, writer = _make_stack(tmp_path)
    writer.fence()
    restarted = CompatibilityWriter(
        ledger_path=ledger_path,
        inbox=DurableCapitalInbox(tmp_path / "inbox.sqlite3", clock=_clock()),
        ledger_id="test",
        initial_cash=100_000,
        clock=_clock(),
    )
    inbox.append(**_broker_fill("fill-after-fence"))
    with pytest.raises(CompatWriterError) as excinfo:
        restarted.apply_next()
    assert excinfo.value.code == COMPAT_WRITER_FENCED


def test_stale_held_lease_handle_fails_after_fence(tmp_path: Path) -> None:
    """flip 时仍持有旧 lease 句柄的 writer 不得再完成 ACK/写."""

    _ledger_path, inbox, writer = _make_stack(tmp_path)
    inbox.append(**_broker_fill())
    lease = writer.lease()
    lease.__enter__()
    writer.fence()
    with pytest.raises(CompatWriterError) as excinfo:
        writer.apply_next(lease=lease)
    assert excinfo.value.code == COMPAT_WRITER_FENCED
    with pytest.raises(CompatWriterError):
        lease.__exit__(None, None, None)
