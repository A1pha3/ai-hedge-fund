# V2-to-V3 Signed Migration, Shadow, and Mode-Specific BTST Canary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在资本逐项守恒、单 writer、外部事件不丢失且可崩溃恢复的前提下完成 v2→v3 authority 交接；验证 shadow 差异；只有同执行模式证据和治理门全部通过后才激活 BTST 2% canary。

**Architecture:** 先把所有 legacy capital mutator 收敛到受 ACL 保护的 compatibility writer，并让 broker/公司行动等外部事实先进入共享 durable inbox。迁移协调器使用签名 `MigrationApprovalManifest`、live-order adoption manifest、精确 source/target roots、handoff cursor 和 authority-store CAS。跨数据库不声称原子：持久 write lease 在 v2 commit 与 source-token ACK 之间保持 flip 阻塞；崩溃留下 unresolved lease，必须重新盘点后才能清除。Canary 只激活既有完整 envelope 和 StageManifest，不自行判断 edge。

**Tech Stack:** Python、Plan 01–05、SQLite CAS/leases、OS/UDS ACL、pytest concurrency/fault injection。

## Global Constraints

- 这是首次可能改变资本 authority 的计划；真实 freeze/flip/activate 都需要独立、短时、签名批准窗口。
- 开始前停止 v2 新风险；退出、公司行动、外部回报和对账必须继续进入 durable inbox。
- 不假设 v2 无持仓/订单/应收/保留；每次执行实时盘点且 unknown 阻断。
- 不能用跨两个 SQLite connection 的嵌套 `with` 声称原子提交；安全性来自 durable inbox、lease、prepared root 和单库 CAS。
- 任何旧写入口、旧 fd、旧 credential/session、缓存连接或网络路径在 flip 后都必须失去写/发送能力。
- 2% 是同 mode portfolio aggregate gross cap；不是单票、单日、lineage 各自额度或累计亏损预算。
- stage loss 由 Plan 02 同一资本事务计算；本计划只验证冻结 budget、activation 和 latch/monitor。
- 本计划只能激活 `DAILY_BAR_PROXY` 或有完整来源的 `MANUAL_CONFIRMED`；首次 `BROKER_CONFIRMED` 2% 等待 Plan 07。

---

## File Structure

- Create `src/screening/offensive/v3/migration/models.py`
- Create `src/screening/offensive/v3/migration/inventory.py`
- Create `src/screening/offensive/v3/migration/repository.py`
- Create `src/screening/offensive/v3/migration/coordinator.py`
- Create `src/screening/offensive/v3/migration/inbox.py`
- Create `src/screening/offensive/v3/migration/compat_writer.py`
- Create `src/screening/offensive/v3/migration/conservation.py`
- Create `src/screening/offensive/v3/migration/adoption.py`
- Modify `src/screening/offensive/ledger_repository.py`
- Create `src/screening/offensive/v3/canary/activation.py`
- Create `src/screening/offensive/v3/canary/monitor.py`
- Create `scripts/v3_migration.py`
- Create `scripts/v3_shadow_audit.py`
- Create `docs/runbooks/v3-migration-and-canary.md`
- Create tests under `tests/offensive/v3/migration/` and `tests/offensive/v3/canary/`

### Task 1: Signed approval, read-only inventory, and exact state roots

**Interfaces:** Produces `verify_migration_approval()`, `V2Inventory`, `capture_v2_inventory()`, `SourceToken` and canonical source root.

- [ ] **Step 1: Write failing tests** in `test_inventory.py` for cash, positions, tradable/receivable, plans, reserves, live/ambiguous/cancel-pending orders, marks, units, lifetime/active HWM, fees, stage loss, pending exits, unknown state, symlink/file replacement and non-empty ledgers.
- [ ] **Step 2: Add manifest tests** binding source/target portfolio/account, schema/writer IDs, migration program hash, time window, conservation formula version, order rules, credential/session fence, rollback/DR and two distinct approvers.
- [ ] **Step 3: Verify RED** with `uv run pytest tests/offensive/v3/migration/test_{inventory,approval}.py -v`.
- [ ] **Step 4: Implement secure read-only capture**. Unrepresentable facts become `UNATTRIBUTED_RISK`/blocker; no rounding/default. Prove source files byte-identical.
- [ ] **Step 5: Verify and commit** with `git commit -m "feat(v3): approve and inventory capital migration"`.

### Task 2: Durable external inbox and legacy writer convergence

**Interfaces:** Produces `DurableCapitalInbox`, `CompatibilityWriter`, `AuthorityWriteLease`, source-token ACK and canonical external event/revision deduplication.

- [ ] **Step 1: Write failing tests** for broker fill/fee, company action, exit, correction and manual facts arriving before/during/after freeze; duplicate/out-of-order revisions; crash before v2 commit, after v2 commit before ACK and while lease held.
- [ ] **Step 2: Modify every v2 capital mutator** to call the compatibility writer/lease path. Add an AST/import/call-site inventory test so a newly added direct v2 mutator fails CI.
- [ ] **Step 3: Implement protocol**: external ingress durably appends first; current writer acquires an authority lease, projects exactly one inbox revision, commits its own DB, ACKs resulting source token/cursor, then releases lease. A crash leaves durable inbox plus unresolved lease and blocks flip until read-only reconciliation proves the actual source state.
- [ ] **Step 4: Add OS/DB ACL tests** proving application/CLI principals cannot open the v2 DB writable; only compatibility-writer principal can. Retain an old client connection/fd in a test, fence/terminate the writer, then prove subsequent mutation fails.
- [ ] **Step 5: Verify and commit** with `git commit -m "feat(v3): converge legacy writes through durable ingress"`.

### Task 3: Prepared v3 import, live-order adoption, and itemized conservation

**Interfaces:** Produces migration states through `CONSERVATION_VERIFIED`, `prepare_import()`, signed `OrderAdoptionManifest` and `verify_conservation()`.

```text
DISCOVERED
  -> V2_NEW_RISK_FROZEN
  -> ORDERS_DRAINED_OR_ADOPTED
  -> CAPITAL_RECONCILED
  -> V3_IMPORT_PREPARED
  -> CONSERVATION_VERIFIED
  -> V2_CAPITAL_WRITE_FENCED_AND_AUTHORITY_FLIPPED
  -> V3_INBOX_REPLAYED
  -> V2_READ_ONLY
```

- [ ] **Step 1: Write state/idempotency tests** for legal transitions, illegal skip/backtrack, crash after each commit and same migration ID/different root.
- [ ] **Step 2: Write adoption tests** for terminal drain and each live/ambiguous/cancel-pending order binding stable client/broker ID, cumulative fill, leaves, reserve, last broker sequence and responsible writer. Adoption never resubmits.
- [ ] **Step 3: Implement non-executable import** tied to approval/source cursor/root. Produce source projection, target projection and itemized proof for every cash/currency, shares, tradable/receivable, reserve, open/exit-pending, live/ambiguous order, units, HWM, stage loss/latch and cumulative fee field; comparing only total NAV is insufficient.
- [ ] **Step 4: Verify RED/GREEN** with `uv run pytest tests/offensive/v3/migration/test_{state_machine,adoption,conservation}.py -v`.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): prepare conserving migration and order adoption"`.

### Task 4: Single-store authority CAS and handoff cursor

**Interfaces:** Produces `AuthorityRegistry.compare_and_flip()` and post-flip inbox replay/finalization.

- [ ] **Step 1: Write concurrency tests** injecting fill/dividend/fee/exit/correction, new lease request and crash between verification and flip. Cover source/token/cursor/target root changes and unresolved lease.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/migration/test_authority_flip.py -v`.
- [ ] **Step 3: Implement one authority-store CAS** whose preimage binds approval hash, adoption hash, source/target roots, source stream/capital version, target import version, active writer/fencing epoch and `handoff_inbox_cursor`. It succeeds only with zero in-flight/unresolved lease. The prepared target is immutable/non-executable before CAS; do not open a target transaction inside the authority transaction.

```python
with authority_store.begin_immediate() as tx:
    tx.require_no_writer_lease()
    tx.require_preimage(expected_manifest_and_roots)
    tx.fence_writer("v2")
    tx.activate_writer("v3", next_fencing_epoch)
    tx.bind_handoff_cursor(cursor)
```

- [ ] **Step 4: After CAS**, terminate compatibility writer, revoke its service credential/session/network path, start v3 consumer at `cursor + 1`, replay to durable head and complete final reconciliation before permitting entry. Tests prove no two writers and no event without a durable recipient.
- [ ] **Step 5: Verify and commit** with `git commit -m "feat(v3): hand off capital authority with a bound cursor"`.

### Task 5: Shadow parity and discrepancy taxonomy

**Interfaces:** Produces `scripts/v3_shadow_audit.py` comparing inputs, candidates, admission, rank, size, cash, reserve, risk, exit and outcomes.

- [ ] **Step 1: Write fixture tests** for expected T+1/T+10, cost, OB, regime/streak, integer-lot, unknown proxy, drawdown and pending differences.
- [ ] **Step 2: Implement categories** `EXPECTED_POLICY_CHANGE | DATA_MISMATCH | KERNEL_BUG | LEGACY_BUG | UNKNOWN`, binding evidence/proposal/seal/capital roots.
- [ ] **Step 3: Encode runbook gate**: no flip/canary while unresolved `DATA_MISMATCH | KERNEL_BUG | UNKNOWN` can affect capital, exit or sample attribution.
- [ ] **Step 4: Verify rerun determinism** and production immutability.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): audit shadow capital and decision parity"`.

### Task 6: Mode-specific 2% activation guard

**Interfaces:** Produces `CanaryActivator.activate()`; consumes Plan 02 stage-loss state and Plan 03 signed policy/envelope/Trial/SAP/Stage candidates.

- [ ] **Step 1: Write failing tests** for wrong mode/account/policy/stage/sample, expired candidate, inactive trust, unresolved risk, stale as-observed NAV, inherited/unattributed exposure, an `EXPLORATION` kind incorrectly used outside broker mode, gross cap >2%, missing fixed integer loss budget and attempted proxy-to-broker reuse.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/canary/test_activation.py -v`.
- [ ] **Step 3: Implement activation through Plan 04 joint Gateway CAS**. Activator never signs or assesses edge. Proxy/manual canary 必须使用同模式 `EDGE` envelope 的完整 target policy，2% 是该 Stage 的 portfolio/lineage 较小上限；`EXPLORATION` 在本计划中一律拒绝。
- [ ] **Step 4: Add stage tests**: expiry drains；2% stage 的证据不得用于 5% stage；新的 stage 必须有新的 Trial/SAP/Stage、evaluation units、primary evidence 和完整 envelope。
- [ ] **Step 5: Verify and commit** with `git commit -m "feat(v3): activate mode-specific two-percent canary"`.

### Task 7: Monitoring, halt, drain, and non-automatic promotion

**Interfaces:** Produces `CanaryHealth`, operator alerts and immutable assessment package; never produces a 5%/10% envelope.

- [ ] **Step 1: Write tests** for drawdown curve/latch, stage loss latch, envelope revalidation, stale NAV, capacity degradation, fixed assessment, unresolved ExitMandate and all entry dependencies offline.
- [ ] **Step 2: Implement monitor** that can only maintain, tighten, fence or drain. Plan 02 transaction owns stage loss consumption; monitor only observes versions/latches and requests entry fence.
- [ ] **Step 3: Prove exits continue** through all halts/outages and reopened corrections reappear in monitoring.
- [ ] **Step 4: Add recovery tests**: 15% latch 后只有新的 `RiskEpochStarted`、更高 epoch `PolicyActivation` 和 `RECOVERY` envelope 可恢复；完整 portfolio/各 lineage cap 均不高于 2%，继承的 open/pending/live/reserved/ambiguous/unattributed 风险和既有 stage/program loss consumption 全部计入，生命周期 NAV/HWM 不重置。再要求每个 5% 然后 <=10% transition 使用新的同模式 StageManifest、evaluation units、primary evidence 和完整 envelope。
- [ ] **Step 5: Verify and commit** with `git commit -m "feat(v3): monitor and drain canary without auto-promotion"`.

### Task 8: Migration/DR rehearsal and approval checklist

- [ ] Implement `scripts/v3_migration.py` commands `inventory`, `freeze-new-risk`, `prepare`, `verify`, `adopt-orders`, `flip`, `replay-inbox`, `finalize`, `status`; all mutation commands require a verified manifest and otherwise default to dry-run.
- [ ] Add backup recovery rehearsal using a signed test `DisasterRecoveryManifest`: verify backup root/cursors, raise recovery/fencing epoch, replay inbox/outbox, reconcile live/ambiguous state and keep entry fenced until conservation passes.
- [ ] Run:

```bash
uv run pytest tests/offensive/v3/migration/ tests/offensive/v3/canary/ -v
uv run pytest tests/offensive/ tests/test_main_auto_cache_refresh.py -q
uv run python scripts/v3_migration.py status --dry-run
git diff --check
```

Expected: all pass; status is read-only and reports approval/root/writer/fence/lease/inbox/cursor/conservation state.

- [ ] Obtain independent approval of itemized conservation, ACL old fd test, active envelope, Trial/SAP/Stage, stage-loss budget, drain and DR proof before a real flip/activation.
- [ ] Update `AGENTS.md` one persisted state at a time; never claim canary active from plan completion alone.

## Completion Gate

- [ ] Fault injection cannot produce two active writers, lost durable events, cursor gaps or conservation drift.
- [ ] No cross-database sequence is mislabeled atomic; every ambiguous crash state blocks flip until reconciliation.
- [ ] Old process/fd/credential/session/network path is proven unable to write or send after flip.
- [ ] v2 becomes read-only only after v3 replay and final itemized reconciliation.
- [ ] Proxy/manual 2% activation is impossible without matching evidence and cannot confer broker authority.
- [ ] Halt/drain/DR remain available while all new-entry dependencies fail.
