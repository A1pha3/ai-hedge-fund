# Plan 08: Broker Runtime Composition + Fence Send-Path Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close Plan 07 review finding M1 by introducing `BrokerRuntime`, a composition layer that forces the fencing-epoch/writer fence into the dispatcher send path so a stale epoch / non-authority writer / incomplete disaster recovery is fail-closed before any command reaches the broker.

**Architecture:** `BrokerRuntime` (new `src/screening/offensive/v3/broker/runtime.py`) is a thin shell wrapping `BrokerDispatcher` + `WriterHandoff` (+ optional `DisasterRecoveryCoordinator`). It exposes the single entry/resend entry point and calls `fence_send` (and the DR entry gate) before any dispatcher call; the fencing epoch is read live from the fence authority at send time, never snapshotted. Offline only: `DeterministicFakeBroker` provides the test anchor; the production adapter stays disabled.

**Tech Stack:** Python 3.12, dataclasses, pytest, existing v3 broker/gateway primitives.

## Global Constraints

- **Offline primitive only.** Adapter stays disabled (`BROKER_ADAPTER_NOT_CERTIFIED`); in-process; tests use `tmp_path`; no real credential/DSN/endpoint/capital. This plan proves the fence *code invariant* in the send path — it is not a broker authorization.
- **Fail-closed.** A fence failure must leave zero side effects: the dispatcher is never invoked (no gateway claim, no broker command, no inbox receipt).
- **No placeholder steps.** Every test/impl step below is concrete and runnable.
- **Test basename uniqueness.** `tests/offensive/v3/` has no `__init__.py`; new test file basename must be unique in that tree (`test_runtime.py` is unique).
- **Reuse existing fixtures.** `drive_to_outbox`, `Clock` from `tests/offensive/v3/broker/helpers.py`; `_full_restore` etc. from `tests/offensive/v3/broker/test_disaster_recovery.py`. Do NOT rebuild gateway/DR fixtures by hand.
- **Do not modify dispatcher/handoff/DR internals.** The runtime composes them; it does not change their logic. (`BrokerDispatcher.run_once`/`resend`, `WriterHandoff.fence_send`, `DisasterRecoveryCoordinator.fence_send`/`entry_permitted`/`fencing_epoch` are consumed as-is.)
- Run tests with the worktree/venv interpreter: `.venv/bin/python -m pytest ...`.

---

### Task 1: `BrokerRuntime` composition layer + send-path fence

**Files:**
- Create: `src/screening/offensive/v3/broker/runtime.py`
- Test: `tests/offensive/v3/broker/test_runtime.py`

**Interfaces:**
- Consumes (all pre-existing, unchanged):
  - `BrokerDispatcher.run_once(permit, expected_versions, *, context) -> DispatchOutcome`
  - `BrokerDispatcher.resend(permit, *, context, broker_cutoff=None, certified_idempotent=None, now=None) -> DispatchOutcome`
  - `WriterHandoff.fence_send(*, writer_id: str, epoch: int) -> None` (raises `HandoffError` with `.code` ∈ `ENTRY_FENCED`/`WRITER_NOT_AUTHORITY`/`EPOCH_SUPERSEDED`)
  - `WriterHandoff.fencing_epoch -> int`
  - `DisasterRecoveryCoordinator.entry_permitted -> bool`, `.fencing_epoch -> int`
- Produces:
  - `BrokerRuntimeError(RuntimeError)` with `.code: str`; the only new code is `ENTRY_FENCED_DURING_RECOVERY`.
  - `@dataclass BrokerRuntime(dispatcher, handoff, writer_id, recovery=None)` with:
    - `current_fencing_epoch() -> int` — DR epoch if `recovery is not None` else `handoff.fencing_epoch`.
    - `submit_entry(permit, expected_versions, *, context) -> DispatchOutcome`
    - `submit_resend(permit, *, context, broker_cutoff=None, certified_idempotent=None, now=None) -> DispatchOutcome`

- [ ] **Step 1: Write the failing tests** (all 8 in one file)

```python
"""Plan 08 Task 1 (RED): BrokerRuntime send-path fence wiring.

锁定约束:
1. submit_entry/submit_resend 在触 dispatcher 前强制 fence: 非 live
   writer / stale epoch / DR 未完成 → fail-closed, fake broker 收不到任何
   命令 (dispatcher 完全不被调用, 无 claim/无 receipt).
2. fencing_epoch 从 fence 权威即时读取 (DR 存在时取 DR, 否则 handoff),
   不作构造期快照 — handoff/DR 完成后 epoch 自动跟进.
3. 正路径: live writer + live epoch + ACTIVE → 正常发送 (不破坏 dispatcher).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.screening.offensive.v3.broker.dispatcher import BrokerDispatcher
from src.screening.offensive.v3.broker.fake import (
    DeterministicFakeBroker,
    FakeAction,
    FakeScript,
)
from src.screening.offensive.v3.broker.handoff import (
    CursorCheckpoint,
    FenceProof,
    HandoffError,
    WriterHandoff,
)
from src.screening.offensive.v3.broker.ports import BrokerAccountBinding
from src.screening.offensive.v3.broker.raw_inbox import BrokerRawInbox
from src.screening.offensive.v3.broker.runtime import (
    BrokerRuntime,
    BrokerRuntimeError,
)
from src.screening.offensive.v3.gateway.decisions import DeliveryOutcome

from tests.offensive.v3.broker.helpers import Clock, drive_to_outbox
from tests.offensive.v3.broker.test_disaster_recovery import _full_restore

FINGERPRINT = "a" * 64

# drive_to_outbox 的默认 permit 产 2 条 order line → 正路径须脚本 2 个 ack
# (与 test_dispatcher.py 的 ACKS 一致), 否则第二条 FakeScriptExhausted.
ACKS = [FakeAction.ack(broker_order_id="B-1"), FakeAction.ack(broker_order_id="B-2")]


def _account() -> BrokerAccountBinding:
    return BrokerAccountBinding(
        account_id="broker-account-v3",
        environment="sandbox",
        currency="CNY",
        endpoint_fingerprint=FINGERPRINT,
    )


def _broker(*actions: FakeAction) -> DeterministicFakeBroker:
    return DeterministicFakeBroker(FakeScript(account=_account(), actions=tuple(actions)))


def _runtime(
    tmp_path: Path,
    broker: DeterministicFakeBroker,
    *,
    writer_id: str = "writer-1",
    handoff: WriterHandoff | None = None,
    recovery=None,
    name: str = "gw",
):
    """真实 gateway driven to outbox + runtime 包裹的 dispatcher."""

    rig = drive_to_outbox(tmp_path / f"{name}.sqlite3", Clock())
    inbox = BrokerRawInbox(str(tmp_path / f"raw-{name}.sqlite3"))
    dispatcher = BrokerDispatcher(
        gateway=rig.gateway, broker=broker, inbox=inbox, account=_account()
    )
    rt = BrokerRuntime(
        dispatcher=dispatcher,
        handoff=handoff if handoff is not None else WriterHandoff(),
        writer_id=writer_id,
        recovery=recovery,
    )
    return rt, rig, inbox, broker


def _sent(broker: DeterministicFakeBroker) -> int:
    """已派发到 fake broker 的命令数 (fail-closed 可观测锚点)."""

    return broker._cursor


# -- 正路径 -----------------------------------------------------------------


def test_submit_entry_live_writer_sends(tmp_path) -> None:
    rt, rig, inbox, broker = _runtime(tmp_path, _broker(*ACKS))
    outcome = rt.submit_entry(
        rig.permit, rig.permit.send_claim_expected_versions, context=rig.claim_context
    )
    assert outcome.delivery is DeliveryOutcome.BROKER_ACK
    assert _sent(broker) == 2  # 2 条 order line 全发出


# -- handoff fence ----------------------------------------------------------


def test_submit_entry_fenced_when_not_active(tmp_path) -> None:
    broker = _broker(FakeAction.ack(broker_order_id="B-1"))
    handoff = WriterHandoff()
    handoff.begin_drain(live_orders=0, ambiguous_orders=0)  # ACTIVE -> DRAINING
    rt, rig, inbox, _ = _runtime(tmp_path, broker, handoff=handoff)
    with pytest.raises(HandoffError) as exc:
        rt.submit_entry(
            rig.permit, rig.permit.send_claim_expected_versions, context=rig.claim_context
        )
    assert exc.value.code == "ENTRY_FENCED"
    assert _sent(broker) == 0  # dispatcher 未被触达


def test_submit_entry_rejects_non_authority_writer(tmp_path) -> None:
    broker = _broker(FakeAction.ack(broker_order_id="B-1"))
    rt, rig, inbox, _ = _runtime(tmp_path, broker, writer_id="intruder")
    with pytest.raises(HandoffError) as exc:
        rt.submit_entry(
            rig.permit, rig.permit.send_claim_expected_versions, context=rig.claim_context
        )
    assert exc.value.code == "WRITER_NOT_AUTHORITY"
    assert _sent(broker) == 0


def test_submit_entry_stale_writer_after_handoff_fenced(tmp_path) -> None:
    """M1 核心回归: handoff 完成并 re-arm writer-2 (epoch 2, ACTIVE) 后, 旧
    writer-1 的 runtime 在 send path 被实际判为非 authority, fake broker 收不到
    命令 — 而非仅靠进程内不变式."""

    broker = _broker(*ACKS)
    handoff = WriterHandoff()
    handoff.begin_drain(live_orders=0, ambiguous_orders=0)
    handoff.report_drained(remaining_live=0, remaining_ambiguous=0)
    handoff.mark_reconciled()
    handoff.present_fence_proof(
        FenceProof(
            credential_revoked=True,
            session_revoked=True,
            network_egress_removed=True,
            proven_at=Clock()(),
        )
    )
    ck = CursorCheckpoint(
        inbox_cursor="i1", outbox_cursor="o1", broker_cursor="b1",
        fencing_epoch=handoff.fencing_epoch,
    )
    new_epoch = handoff.complete(new_writer_id="writer-2", checkpoint=ck)
    assert new_epoch == 2
    # re-arm 新 writer 使状态回 ACTIVE → fence 判定走到 writer 检查.
    handoff.activate_new_writer(writer_id="writer-2", epoch=new_epoch)
    # 旧 writer runtime: writer-1 已不是 authority.
    rt, rig, inbox, _ = _runtime(tmp_path, broker, writer_id="writer-1", handoff=handoff)
    with pytest.raises(HandoffError) as exc:
        rt.submit_entry(
            rig.permit, rig.permit.send_claim_expected_versions, context=rig.claim_context
        )
    assert exc.value.code == "WRITER_NOT_AUTHORITY"
    assert _sent(broker) == 0


# -- DR 门 -------------------------------------------------------------------


def test_submit_entry_fenced_during_incomplete_recovery(tmp_path) -> None:
    from src.screening.offensive.v3.broker.disaster_recovery import (
        DisasterRecoveryCoordinator,
    )

    broker = _broker(FakeAction.ack(broker_order_id="B-1"))
    rt, rig, inbox, _ = _runtime(
        tmp_path, broker, recovery=DisasterRecoveryCoordinator()  # PRE_RESTORE
    )
    with pytest.raises(BrokerRuntimeError) as exc:
        rt.submit_entry(
            rig.permit, rig.permit.send_claim_expected_versions, context=rig.claim_context
        )
    assert exc.value.code == "ENTRY_FENCED_DURING_RECOVERY"
    assert _sent(broker) == 0


def test_submit_entry_after_recovery_uses_raised_epoch(tmp_path) -> None:
    broker = _broker(*ACKS)
    recovery = _full_restore()  # RECOVERY_COMPLETE, fencing_epoch 3, writer-2
    assert recovery.entry_permitted and recovery.fencing_epoch == 3
    rt, rig, inbox, _ = _runtime(tmp_path, broker, recovery=recovery)
    assert rt.current_fencing_epoch() == 3  # epoch 取自 DR, 非 handoff 快照
    outcome = rt.submit_entry(
        rig.permit, rig.permit.send_claim_expected_versions, context=rig.claim_context
    )
    assert outcome.delivery is DeliveryOutcome.BROKER_ACK
    assert _sent(broker) == 2


# -- resend 同样被 fence -----------------------------------------------------


def test_submit_resend_fenced_for_non_authority_writer(tmp_path) -> None:
    broker = _broker()  # 无脚本: 若 dispatcher 被触达会 FakeScriptExhausted
    rt, rig, inbox, _ = _runtime(tmp_path, broker, writer_id="intruder")
    with pytest.raises(HandoffError) as exc:
        rt.submit_resend(rig.permit, context=rig.claim_context)
    assert exc.value.code == "WRITER_NOT_AUTHORITY"
    assert _sent(broker) == 0


# -- fence 失败零副作用 ------------------------------------------------------


def test_fence_failure_leaves_no_claim_no_receipt(tmp_path) -> None:
    broker = _broker(FakeAction.ack(broker_order_id="B-1"))
    rt, rig, inbox, _ = _runtime(tmp_path, broker, writer_id="intruder")
    with pytest.raises(HandoffError):
        rt.submit_entry(
            rig.permit, rig.permit.send_claim_expected_versions, context=rig.claim_context
        )
    assert _sent(broker) == 0
    # dispatcher 未被触达: inbox 无 receipt, gateway entry 无 delivery 记录.
    assert len(list(inbox.iter_all())) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/offensive/v3/broker/test_runtime.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named '...broker.runtime'` (collection error).

- [ ] **Step 3: Write the minimal implementation**

Create `src/screening/offensive/v3/broker/runtime.py`:

```python
"""Plan 08: production composition layer wiring the fence into the send path.

``BrokerRuntime`` is the single entry point that couples the broker
dispatcher to the fencing authorities. Every entry/resend passes the
WriterHandoff fence (and the disaster-recovery entry gate) BEFORE the
dispatcher is touched, so a stale fencing epoch, a non-authority writer,
or an incomplete recovery is fail-closed before any command reaches the
broker — closing Plan 07 review finding M1 (the fence previously ran only
as an in-process invariant, not on the send path).

The fencing epoch is read live from the fence authority at send time (the
DR epoch when a recovery coordinator is present, else the handoff epoch),
never snapshotted at construction, so a completed handoff/DR that raised
the epoch is honored immediately.

Offline primitive: the adapter stays disabled, no real credential/DSN/
capital is touched. This proves the fence code invariant, not a broker
authorization.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.screening.offensive.v3.broker.disaster_recovery import (
    DisasterRecoveryCoordinator,
)
from src.screening.offensive.v3.broker.dispatcher import (
    BrokerDispatcher,
    DispatchOutcome,
)
from src.screening.offensive.v3.broker.handoff import WriterHandoff


class BrokerRuntimeError(RuntimeError):
    """Runtime composition failure with a stable machine-readable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass
class BrokerRuntime:
    """Couples the broker dispatcher to the fencing authorities.

    The single send-path entry point: every submit passes the fence before
    the dispatcher is invoked. The runtime holds no authorization, seal,
    reserve, or capital logic — it only adds the send-path fence.
    """

    dispatcher: BrokerDispatcher
    handoff: WriterHandoff
    writer_id: str
    recovery: DisasterRecoveryCoordinator | None = None

    def current_fencing_epoch(self) -> int:
        """The live fencing epoch from the fence authority (DR wins)."""

        if self.recovery is not None:
            return self.recovery.fencing_epoch
        return self.handoff.fencing_epoch

    def _fence(self) -> None:
        """Fail-closed fence before any dispatcher call (zero side effects)."""

        if self.recovery is not None and not self.recovery.entry_permitted:
            raise BrokerRuntimeError(
                "ENTRY_FENCED_DURING_RECOVERY",
                "disaster recovery not complete; entry stays fenced",
            )
        self.handoff.fence_send(
            writer_id=self.writer_id, epoch=self.current_fencing_epoch()
        )

    def submit_entry(self, permit, expected_versions, *, context) -> DispatchOutcome:
        """Fence, then dispatch one claimed entry."""

        self._fence()
        return self.dispatcher.run_once(permit, expected_versions, context=context)

    def submit_resend(
        self,
        permit,
        *,
        context,
        broker_cutoff: datetime | None = None,
        certified_idempotent: bool | None = None,
        now: datetime | None = None,
    ) -> DispatchOutcome:
        """Fence, then resend exact claimed client ids (dispatcher keeps its
        cutoff/idempotency pre-guards; the runtime only adds the fence)."""

        self._fence()
        return self.dispatcher.resend(
            permit,
            context=context,
            broker_cutoff=broker_cutoff,
            certified_idempotent=certified_idempotent,
            now=now,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/offensive/v3/broker/test_runtime.py -v`
Expected: 8 passed.

- [ ] **Step 5: Run the broker + v3 suites for regressions**

Run: `.venv/bin/python -m pytest tests/offensive/v3/broker/ -q && .venv/bin/python -m pytest tests/offensive/v3/ -q`
Expected: broker suite green (178 + 8 = 186); v3 suite green (2551 + 8 = 2559).

- [ ] **Step 6: Commit**

```bash
git add src/screening/offensive/v3/broker/runtime.py tests/offensive/v3/broker/test_runtime.py
git commit -m "feat(v3): wire fence into broker send path via BrokerRuntime (M1)"
```

---

### Task 2: Documentation + acceptance

**Files:**
- Modify: `AGENTS.md` (当前 v3 已实现范围 → Plan 07 段, the sentence noting the fence is "尚未 wire 进 dispatcher send path（留生产组合层）")

**Interfaces:**
- Consumes: Task 1 `BrokerRuntime`.
- Produces: updated AGENTS.md scope note; acceptance run log.

- [ ] **Step 1: Update the AGENTS.md fence caveat**

In `AGENTS.md`, in the paragraph that currently says the fencing-epoch/writer fence "尚未 wire 进 dispatcher send path（留生产组合层）", replace that clause to record that Plan 08 wired it: the fence is now enforced on the send path by `BrokerRuntime` (composition layer), which reads the live fencing epoch from the fence authority and fails closed before the dispatcher on stale epoch / non-authority writer / incomplete recovery. Keep the surrounding caveats intact — the production adapter is still disabled, no real broker connection / authority flip / capital activation has occurred; this is an offline composition primitive proving the code invariant, not a broker authorization.

- [ ] **Step 2: Run the acceptance gate**

Run:
```bash
.venv/bin/python -m pytest tests/offensive/v3/broker/test_runtime.py -v
.venv/bin/python -m pytest tests/offensive/v3/ -q
git diff --check
```
Expected: test_runtime 8 passed; v3 suite 2559 green; `git diff --check` no output.

- [ ] **Step 3: Commit**

```bash
git add AGENTS.md
git commit -m "docs(v3): record Plan 08 fence send-path wiring in AGENTS.md scope"
```

---

## Self-Review notes (coverage / consistency)

- Spec §4.1/§4.2 sequences → Task 1 `_fence` + `submit_entry`/`submit_resend` (Steps 1–4).
- Spec §3.2 live-epoch (no snapshot) → `current_fencing_epoch()` + tests `test_submit_entry_after_recovery_uses_raised_epoch`.
- Spec §5 error model → `BrokerRuntimeError(ENTRY_FENCED_DURING_RECOVERY)` + HandoffError pass-through.
- Spec §6 all 8 test anchors → Task 1 Step 1 (8 tests, incl. fail-closed `_sent(broker)==0` observation).
- Spec §7 exploration checklist → intentionally not implemented (operational gate), not a plan task.
- Spec §8 acceptance → Task 2 Step 2.
- Type consistency: `submit_entry(permit, expected_versions, *, context)` matches `run_once(permit, expected_versions, *, context)`; `submit_resend(permit, *, context, ...)` matches `resend(permit, *, context, ...)`. `expected_versions` passed as `rig.permit.send_claim_expected_versions` (matches dispatcher test usage). `context` = `rig.claim_context`.
