# V3 Account Capital Truth and Gateway Authority Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立独立、append-only、精确、可崩溃恢复的 `AccountCapitalTruth` 与 Capital Gateway Authority Store，覆盖现金、头寸、reserve、订单经济投影、单位 NAV、外部 flow、公司行动、execution revision、stage loss、risk latch 和完整 `CapitalRiskSnapshot`。

**Architecture:** 一个真实 broker account 对应一个资本事实流；mode-pure 业绩是只读子投影，不能拆分经济事实。Gateway-owned SQLite 在同一事务追加 canonical economic event、更新资本/risk/stage 投影、递增版本并 tombstone 尚未取得 send claim 的 entry。历史只追加 revision/补偿事件，禁止 UPDATE/DELETE；Plan 04 再在同一 DB 上实现 active policy/envelope、seal/reserve 与 admission。

**Tech Stack:** Python、SQLAlchemy 2 Core、Alembic、SQLite WAL、整数 money/quantity/unit quanta、Hypothesis、pytest。

## Global Constraints

- Depends on Plan 01 Revision 2 contracts/ports；本计划不读取 producer/evidence DB，不创建 broker order。
- 所有数据库位于 pytest `tmp_path` 或显式 v3 dev path；不得迁移或修改 v2/production 数据。
- money、price、quantity、units、basis、fee 禁止 SQLite `REAL`；有理权益存 numerator/denominator，所有舍入策略由版本化 policy 冻结。
- 每个经济事实只有一个 canonical event；projection 可重建，事件历史技术上禁止 UPDATE/DELETE。
- `AccountCapitalTruth` 汇集账户全部真实模式事实；performance projection 仍按 execution provenance 分池。
- unknown/negative-impossible/reconciliation break 锁存 no-entry；不得 clamp、丢弃或用估值事件修正持仓。
- 所有会影响可入场额度的 capital correction、stage loss 和 risk latch 与资本事实同一事务提交。

---

## File Structure

- Create `src/screening/offensive/v3/storage/metadata.py`
- Create `src/screening/offensive/v3/storage/schema.py`
- Create `src/screening/offensive/v3/storage/migrations/`
- Create `src/screening/offensive/v3/capital/repository.py`
- Create `src/screening/offensive/v3/capital/projector.py`
- Create `src/screening/offensive/v3/capital/account_truth.py`
- Create `src/screening/offensive/v3/capital/nav.py`
- Create `src/screening/offensive/v3/capital/corporate_actions.py`
- Create `src/screening/offensive/v3/capital/risk_snapshot.py`
- Create `src/screening/offensive/v3/capital/stage_loss.py`
- Create `src/screening/offensive/v3/capital/execution_revisions.py`
- Create `src/screening/offensive/v3/capital/checkpoints.py`
- Create `src/screening/offensive/v3/capital/verify.py`
- Create tests under `tests/offensive/v3/capital/`

### Task 1: Append-only schema, account identity, and transaction kernel

**Interfaces:** Produces `CapitalRepository.initialize()`, `append_atomic()`, `events()`, `stream_version()`, `capital_version()`, `AccountBinding`, `CapitalConflict` and a Gateway transaction context reusable by Plan 04.

- [ ] **Step 1: Write failing tests** in `test_schema.py` and `test_repository.py` for exact schema version, WAL/foreign keys, unique canonical/idempotency keys, account/environment/currency binding, stream CAS, payload conflict, rollback on projector failure and two-process contention.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/capital/test_{schema,repository}.py -v`.
- [ ] **Step 3: Implement** `account_capital_truth`, `economic_events`, `economic_event_legs`, `event_revisions`, `capital_projection`, `positions`, `reserves`, `receivables`, `payables`, `risk_latches`, `stage_loss_state`, `execution_revisions`, `session_checkpoints`, `entry_tombstones` and `gateway_meta`. Add triggers rejecting UPDATE/DELETE on immutable tables.

```python
def append_atomic(self, command: CapitalCommand) -> CapitalRiskSnapshot:
    with self._db.begin_immediate() as tx:
        tx.require_account_binding(command.account_binding)
        tx.require_stream_version(command.expected_stream_version)
        event = tx.insert_idempotent_event(command)
        tx.apply_legs_and_projection(event)
        tx.recompute_risk_and_stage_loss(command.as_of)
        tx.tombstone_unclaimed_entries_if_versions_changed()
        return tx.read_capital_risk_snapshot()
```

- [ ] **Step 4: Verify GREEN**, including injected crash after event insert and before projection update; transaction rollback leaves zero partial write.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): create account capital authority store"`.

### Task 2: Fills, fees, reserves, positions, and exact conservation

**Interfaces:** Produces `reserve_entry()`, `release_reserve()`, `record_fill_revision()`, `record_fee_revision()`, `capital_risk_snapshot()` and `assert_conservation()`.

- [ ] **Step 1: Write property tests** for partial entry/exit fills, minimum commission per order, transfer/stamp tax versions, live/cancel-pending reserve, late fill, duplicate revision, unattributed fill and exact round-half-even policy.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/capital/test_fills_and_conservation.py -v`.
- [ ] **Step 3: Implement one fact/one event semantics**. A fill has integer price micros and quantity; gross cash and security legs are atomic. Fee revision is linked but distinct. `SUBMISSION_AMBIGUOUS` leaves worst-case reserve/live exposure in risk.
- [ ] **Step 4: Verify GREEN**. Every generated sequence satisfies opening capital + external flows + economic P&L = closing assets − liabilities, with zero unexplained cents/shares/units.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): conserve fills fees reserves and positions"`.

### Task 3: Genesis units, external flows, NAV lifecycle, and insolvency

**Interfaces:** Produces `initialize_genesis()`, `close_valuation()`, `request/price/settle_subscription()`, `request/price/settle_redemption()`, `start_risk_epoch()` and as-observed/restated-final projections.

- [ ] **Step 1: Write failing tests** for one-time genesis, flow-before-price ordering, suspense cash, partial/full redemption, `pending_redeemed_units`, `ACTIVE -> TERMINATING -> TERMINATED`, cancellation rules, lifetime/active HWM, restatement links and NAV <= 0.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/capital/test_nav_and_flows.py -v`.
- [ ] **Step 3: Implement exact unit accounting**. Full redemption cannot erase units before liabilities/receivables/positions settle. Confirmed NAV <= 0 sets `INSOLVENT`; lifecycle log growth is represented by typed `NEGATIVE_INFINITY`, not float `-inf` persisted in SQLite. `RiskEpochStarted` never resets lifetime HWM/history.
- [ ] **Step 4: Verify GREEN**, including deposits/redemptions that leave unit return unchanged at the pricing instant.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): account units flows termination and insolvency"`.

### Task 4: Corporate actions and successor lot/exit continuity

**Interfaces:** Produces `record_entitlement()`, `settle_cash_in_lieu()`, `make_shares_tradable()`, `apply_split_merge()`, `convert_security()`, `settle_terminal_cash()` and `legal_write_off()`.

- [ ] **Step 1: Write failing tests** for ex/pay/tradable dates, fractional rational entitlements, cash-in-lieu, split/merge basis, dividend correction, merger/conversion, delisting and successor security inheriting economic lot plus due exit.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/capital/test_corporate_actions.py -v`.
- [ ] **Step 3: Implement source-authority matrix** and stable economic fact/revision IDs. Confirmation changes only the unresolved delta; successor mapping never closes risk merely because the old ticker disappears.
- [ ] **Step 4: Verify GREEN** with conservation before/after every generated corporate-action chain.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): preserve corporate action and lot continuity"`.

### Task 5: Complete CapitalRiskSnapshot, drawdown latch, and non-replenishable stage loss

**Interfaces:** Produces `CapitalRiskSnapshotBuilder`, `StageLossEngine.charge()`, `RiskLatchService.evaluate()` and versioned program/lineage/stage/global exposure views.

- [ ] **Step 1: Write failing tests** covering cash, reserve, open, pending, live leaves, exit pending, ambiguous, unattributed and inherited risk; per-lineage/program/stage/global sums; units/NAV/HWM/drawdown; mixed mode/account/currency; stale/unknown mark; 9.99/10/14.99/15% boundaries.
- [ ] **Step 2: Add stage-loss tests** for fixed activation budget cents, mutually exclusive realized market loss/fees/unrealized/pending-stress charge, concurrent fills/marks, profits/rebounds not replenishing, relabel/epoch changes not resetting and permanent `STAGE_LOSS_HALTED`.

```python
instantaneous_charge_cents = (
    realized_market_losses_ex_fees_cents
    + cumulative_fees_and_taxes_cents
    + max(0, -marked_unrealized_pnl_cents)
    + incremental_pending_stress_beyond_mark_cents
)
stage_loss_consumed_cents_t = max(
    stage_loss_consumed_cents_previous,
    instantaneous_charge_cents,
)
if stage_loss_consumed_cents_t >= frozen_budget_cents:
    latch = StageLossState.HALTED
```

四项必须互斥：realized loss 不含 fee/tax，pending stress 只含 mark 之外的增量逆风；无法归属的 charge 同时进入 `UNATTRIBUTED_RISK` 与最保守的 program/global budget。

- [ ] **Step 3: Verify RED** with `uv run pytest tests/offensive/v3/capital/test_{risk_snapshot,stage_loss}.py -v`.
- [ ] **Step 4: Implement in the capital transaction** used by fills/fees/marks/reserves; a version change atomically tombstones unclaimed entry. Missing exposure component returns typed unknown and blocks new risk.
- [ ] **Step 5: Verify and commit** with `git commit -m "feat(v3): snapshot complete risk and latch stage loss"`.

### Task 6: Execution bust/correction, reopen, and negative-position halt

**Interfaces:** Produces `apply_execution_revision()`, `apply_bust()`, `apply_correction()` and `ReopenedEconomicLot` notification for Plan 04 ExitMandate projection.

- [ ] **Step 1: Write stateful tests** for fill -> exit -> closed -> bust, corrected quantity/price/fee, duplicate/out-of-order revisions, cancel-late-fill, unknown order and a correction that would create negative shares.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/capital/test_execution_revisions.py -v`.
- [ ] **Step 3: Implement compensating revisions**: never delete or rewrite terminal order/fill history; recompute active economic projection. A reopened positive lot emits durable reopen state; impossible negative quantity latches `RECONCILIATION_HALT` and preserves the discrepancy without clamping.
- [ ] **Step 4: Verify GREEN**: all permutations with the same canonical revisions converge to identical capital and active lot state.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): revise executions and reopen economic risk"`.

### Task 7: Checkpoints, backups, rebuild, and full verification

**Interfaces:** Produces `CheckpointService.advance()`, consistent backup manifest, `rebuild_projections()` and `verify_ledger()`.

- [ ] **Step 1: Write tests** for monotonic session phases, restart, earlier `as_of`, late correction, backup root/cursor metadata, projection tampering, unknown event, disk-full and restore-to-new-path.
- [ ] **Step 2: Implement checkpoint and backup** without advancing watermark on partial failure. Backup manifest binds account, schema, stream/capital/risk/stage versions, last durable inbox/outbox cursor and content root.
- [ ] **Step 3: Run full checks**.

```bash
uv run pytest tests/offensive/v3/capital/ -v
uv run pytest tests/offensive/test_ledger_repository.py tests/offensive/test_daily_action_service.py -q
uv run python -m src.screening.offensive.v3.capital.verify --help
git diff --check
```

Expected: all pass; help exits 0; fixture verifier reports `capital_conservation=PASS projection_rebuild=PASS`.

- [ ] **Step 4: Update `AGENTS.md`** to “v3 capital/authority store primitives implemented; not authoritative, no active policy/envelope/seal”.
- [ ] **Step 5: Commit** scoped capital, migration, test and documentation files.

## Completion Gate

- [ ] Every cent/share/unit/entitlement change has one canonical source fact and append-only revision history.
- [ ] `CapitalRiskSnapshot` includes every risk-bearing state and fails closed on any unknown component.
- [ ] Stage loss, capital version, risk latch and unclaimed-entry tombstone update atomically.
- [ ] Full redemption and insolvency preserve economic/legal obligations and lifetime history.
- [ ] Bust/correction can reopen positions and downstream exit obligations; negative impossible state is never hidden.
- [ ] No Plan 02 path accepts producer candidates, activates authorization, creates executable seal or sends orders.
