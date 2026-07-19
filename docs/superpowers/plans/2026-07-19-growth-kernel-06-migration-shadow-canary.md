# V2-to-V3 Migration, Shadow, and BTST Canary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在资本守恒、单 writer 和可崩溃恢复的前提下完成 v2→v3 原子交接，验证 shadow 差异，并且只有在执行匹配证据和治理门全部通过后才允许 BTST 2% canary。

**Architecture:** 迁移协调器使用持久化状态机、精确 v2 source stream hash、共享 durable inbox 和 CAS authority flip。shadow parity 在独立 namespace 长时间运行；canary activation 读取已签 CapitalAuthorization/StageManifest，绝不由部署脚本自行判断 edge。回滚只收紧 policy 或进入 draining，不能复活旧 writer。

**Tech Stack:** Python、Plan 01–05、SQLite transaction/CAS、pytest fault injection。

## Global Constraints

- 这是首次可能改变资本 authority 的计划，必须由人工审批窗口执行。
- 开始前冻结 v2 新风险；已有退出、公司行动和对账继续。
- 不假设 v2 当前无成交/无持仓；每次迁移都实时盘点。
- authority flip 与 v2 write fence 是同一原子权限操作；共享 inbox 消除无人可记账窗口。
- 2% 是组合/lineage 瞬时 gross cap，不是单票、单日或累计损失额度。
- 未达到 §13.5/§13.6 的证据门时，交付结果是安全的 shadow/no-trade，不是失败。
- 本计划只能激活 `DAILY_BAR_PROXY` 或 `MANUAL_CONFIRMED` 的同模式授权；`BROKER_CONFIRMED` 首次 2% exploration 必须等待 Plan 07 全部验收。

---

## File Structure

- Create `src/screening/offensive/v3/migration/models.py`
- Create `src/screening/offensive/v3/migration/inventory.py`
- Create `src/screening/offensive/v3/migration/repository.py`
- Create `src/screening/offensive/v3/migration/coordinator.py`
- Create `src/screening/offensive/v3/migration/inbox.py`
- Create `src/screening/offensive/v3/migration/conservation.py`
- Modify `src/screening/offensive/ledger_repository.py`
- Create `src/screening/offensive/v3/canary/activation.py`
- Create `src/screening/offensive/v3/canary/loss_budget.py`
- Create `src/screening/offensive/v3/canary/monitor.py`
- Create `scripts/v3_migration.py`
- Create `scripts/v3_shadow_audit.py`
- Create `docs/runbooks/v3-migration-and-canary.md`
- Create tests under `tests/offensive/v3/migration/` and `tests/offensive/v3/canary/`

### Task 1: Read-only v2 inventory and exact state hash

**Interfaces:** Produces `V2Inventory`, `capture_v2_inventory()`, `v2_source_stream_version` and canonical full-state hash.

- [ ] **Step 1: Write failing tests** for plans, positions, cash, marks, reserves, HWM, fees, pending exits, unknown/ambiguous state and file replacement. Include non-empty synthetic v2 ledgers.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/migration/test_inventory.py -v`.
- [ ] **Step 3: Implement secure read-only adapter**. Any unrepresentable v2 fact becomes explicit `UNATTRIBUTED_RISK` or migration blocker; never discard/round silently.
- [ ] **Step 4: Verify GREEN** and prove source files remain byte-identical.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): inventory v2 capital for migration"`.

### Task 2: Persistent migration state machine and conservation import

**Interfaces:** Produces exact states from spec §17, `prepare_import()`, `verify_conservation()` and resumable checkpoints.

- [ ] **Step 1: Write failing transition/idempotency tests** for every legal edge, illegal skip/backtrack, crash after each committed step and same migration ID/different source hash.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement import as non-executable v3 events** tied to source stream/hash. Compare cash, shares, receivable/tradable, reserves, open/pending, live orders, units, HWM and cumulative fees exactly.
- [ ] **Step 4: Verify GREEN** with `uv run pytest tests/offensive/v3/migration/test_{state_machine,conservation}.py -v`.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): prepare resumable conserving migration"`.

### Task 3: Shared inbox, source CAS, and atomic authority flip

**Interfaces:** Produces `DurableCapitalInbox`, `AuthorityWriteLease`, `AuthorityRegistry.compare_and_flip()` and `replay_inbox()`；现有 v2 所有资本 mutator 在迁移窗口内也必须持有同一 lease/fencing token。

- [ ] **Step 1: Write failing concurrency tests** injecting fill, dividend, fee, exit, company-action correction and crash between `CONSERVATION_VERIFIED` and flip；覆盖已通过 authority check 但尚未提交 v2 ledger 的竞态。
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement fixed lock order `authority DB BEGIN IMMEDIATE -> target ledger transaction -> target commit -> authority lease release`**。v2 consumer 从 authority check 到 v2 commit 全程持有 `AuthorityWriteLease`；flip 只有在无 in-flight lease 时才能在 authority DB 同一事务验证 source version/hash、安装 v2 fence 并切换 active writer。崩溃会回滚 target transaction 并释放 authority lock。所有外部事件先进入 durable inbox；pre-flip v2 或 post-flip v3 只在有效 epoch 下幂等消费。

```python
def compare_and_flip(expected: SourceToken, target_epoch: int) -> None:
    with authority_db.begin_immediate() as tx:
        tx.require_active_writer("v2", expected)
        tx.install_fence("v2", expected)
        tx.activate_writer("v3", target_epoch)
```

- [ ] **Step 4: Verify GREEN**: no test observes two active writers or zero durable recipient; stale source token always blocks.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): atomically hand off capital authority"`.

### Task 4: Live-order drain/adopt and v2 read-only finalization

**Interfaces:** Produces `drain_or_adopt()`, `verify_inbox_replayed()` and final `V2_READ_ONLY` marker.

- [ ] **Step 1: Write tests** for terminal drain, stable client/broker ID adoption, duplicate adoption, unknown broker order, late fill and incomplete inbox.
- [ ] **Step 2: Implement adoption without resubmission**; unknown order or broker ambiguity blocks finalization and all new risk.
- [ ] **Step 3: Verify** with `uv run pytest tests/offensive/v3/migration/test_live_orders.py -v`.
- [ ] **Step 4: Add OS/database write-fence test** proving v2 exits before flip and v3 events after flip remain possible, while v2 new capital writes after flip fail.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): finalize single-writer migration"`.

### Task 5: Shadow parity and discrepancy taxonomy

**Interfaces:** Produces `scripts/v3_shadow_audit.py` and daily comparison of inputs/candidates/admission/rank/size/cash/risk/outcomes.

- [ ] **Step 1: Write fixture tests** for expected semantic differences: T+1/T+10, costs, OB disabled, regime/streak sizing removed, Decimal/lot sizing, unknown proxy fills, drawdown curve and pending visibility.
- [ ] **Step 2: Implement comparison** with categories `EXPECTED_POLICY_CHANGE | DATA_MISMATCH | KERNEL_BUG | LEGACY_BUG | UNKNOWN` and exact evidence/seal hashes.
- [ ] **Step 3: Add minimum observation rule** in runbook: no authority flip/canary while any unresolved `KERNEL_BUG`, `DATA_MISMATCH` or `UNKNOWN` affects capital.
- [ ] **Step 4: Verify rerun determinism** and production immutability.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): audit shadow behavior before authority"`.

### Task 6: Stage loss budget and 2% activation guard

**Interfaces:** Produces `StageLossBudget.consume()`, latch `STAGE_LOSS_HALTED`, and `CanaryActivator.activate()`.

- [ ] **Step 1: Write failing tests** for mutually exclusive realized-market-loss/fees/unrealized/pending-stress terms, profits not replenishing budget, family/epoch relabeling, concurrent exploration portfolio cap, inherited/unattributed risk and permanent latch.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement central ceiling checks**. Activation requires signed active authorization, matching mode/policy/stage/sample slot, no unresolved risk, as-observed NAV, all deadlines and portfolio-wide 2% gross room.
- [ ] **Step 4: Verify GREEN** with `uv run pytest tests/offensive/v3/canary/test_{loss_budget,activation}.py -v`.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): guard btst two-percent canary"`.

### Task 7: Canary monitoring, halt, drain, and non-automatic promotion

**Interfaces:** Produces daily `CanaryHealth`, risk/stage/reconciliation halts and assessment-ready package; does not produce 5% authorization itself.

- [ ] **Step 1: Write tests** for 10–15% curve, 15% latch, stage loss latch, edge revalidation, stale NAV, capacity degradation, exit continuity, fixed assessment, unresolved EXIT_PENDING and no auto-promotion.
- [ ] **Step 2: Implement monitor** that can only maintain or reduce authority. A 5% transition requires a new signed StageManifest/EdgeAuthorization from Plan 03 using non-reused future evidence.
- [ ] **Step 3: Verify** with `uv run pytest tests/offensive/v3/canary/test_monitor.py -v`.
- [ ] **Step 4: Add operator alerts and immutable assessment bundle hashes**.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): monitor halt and drain canary risk"`.

### Task 8: Migration rehearsal and approval checklist

- [ ] Implement `scripts/v3_migration.py` commands: `inventory`, `freeze-new-risk`, `prepare`, `verify`, `flip`, `replay-inbox`, `finalize`, `status`; all default to dry-run except explicit approved step.
- [ ] Run a full rehearsal against copies in pytest/workspace-isolated temp paths, including kill/restart and disk-full/transaction-failure injection.
- [ ] Run:

```bash
uv run pytest tests/offensive/v3/migration/ tests/offensive/v3/canary/ -v
uv run pytest tests/offensive/ tests/test_main_auto_cache_refresh.py -q
uv run python scripts/v3_migration.py status --dry-run
git diff --check
```

Expected: tests pass; real status command is read-only and reports current writer/fence/inbox/conservation state.

- [ ] Obtain independent review of conservation report, service ACL, active authorization, Trial/SAP, stage loss budget and rollback/drain plan before real `flip` or `activate`.
- [ ] Update `AGENTS.md` one state at a time; do not claim canary active unless authority and stage records actually prove it.

## Completion Gate

- [ ] Fault injection cannot create double writers, lost inbox events or conservation drift.
- [ ] v2 becomes read-only only after v3 inbox replay and final reconciliation.
- [ ] Shadow discrepancies are classified and capital-impacting unknowns are zero.
- [ ] 2% canary activation is impossible without current signed evidence and governance records.
- [ ] Halt/drain remains available even when every new-entry dependency fails.
