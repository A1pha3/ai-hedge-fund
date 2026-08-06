# Growth Kernel, Capital Gateway Admission, and Proxy Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现确定、可回放、无 I/O 的 Growth Kernel；在 Plan 02 Gateway Authority Store 中实现唯一的 policy/envelope activation、entry seal/reserve/permit/send-claim 状态机；并交付与 broker 永久分离的 proxy/manual 执行及独立 ExitMandate lane。

**Architecture:** Kernel 输入冻结的 active policy、PIT evidence、raw candidates、`CapitalRiskSnapshot` 和完整 `CapitalAuthorizationEnvelope`，只输出 `NoTradeDecision | ShadowDecision | PortfolioDecision`。Capital Gateway 在同一数据库事务完成联合 activation、entry admission、reserve、`PortfolioDecisionSeal`、permit 与 `SEND_CLAIMED` 线性化。ExitMandate 从 AccountCapitalTruth 派生，不消费 entry authorization；Plan 05 将其运行成独立 durable scheduler。

**Tech Stack:** Python、整数/Decimal、Plan 01–03 ports、SQLAlchemy Gateway transaction、Hypothesis、pytest。

## Global Constraints

- Kernel 禁止 import pandas、network、SQLite、v2、environment 或 clock；相同 canonical input 必须产生相同 hash。
- producer 不应用 portfolio risk multiplier；BTST 初始禁用 regime/streak/composite sizing，OB disabled，Auto executable admission 为零。
- drawdown multiplier 同时作用于未缩放 lineage target 与未缩放 portfolio gross ceiling，且只作用一次。
- shadow schema/namespace/capability 必须让 Gateway executable endpoint 无法解析。
- 每个 portfolio 同时最多一个 active envelope；PolicyActivation 与行为变化 envelope 必须联合 CAS。
- `SEND_CLAIMED` 前可以 tombstone/cancel，之后按已在途风险处理；本计划不调用真实 broker。
- entry halt 不得阻断 ExitMandate、公司行动、reconcile 或 execution correction。

---

## File Structure

- Create `src/screening/offensive/v3/kernel/models.py`
- Create `src/screening/offensive/v3/kernel/risk.py`
- Create `src/screening/offensive/v3/kernel/capacity.py`
- Create `src/screening/offensive/v3/kernel/sizing.py`
- Create `src/screening/offensive/v3/kernel/decide.py`
- Create `src/screening/offensive/v3/gateway/authority.py`
- Create `src/screening/offensive/v3/gateway/decisions.py`
- Create `src/screening/offensive/v3/gateway/admission.py`
- Create `src/screening/offensive/v3/gateway/entry_state.py`
- Create `src/screening/offensive/v3/gateway/exits.py`
- Create `src/screening/offensive/v3/execution/proxy.py`
- Create `src/screening/offensive/v3/execution/manual.py`
- Create `src/screening/offensive/v3/execution/lifecycle.py`
- Create tests under `tests/offensive/v3/kernel/`, `tests/offensive/v3/gateway/`, and `tests/offensive/v3/execution/`

### Task 1: Complete KernelInput and single-pass portfolio risk

**Interfaces:** Produces `RawCandidate`, `KernelInput`, `RiskDecision`, `drawdown_multiplier()` and `apply_portfolio_risk_once()`.

- [x] **Step 1: Write failing tests** in `test_risk.py` for 9.99/10/12.5/14.99/15% drawdown, stale/negative NAV, open/pending/live/reserved/ambiguous/exit-pending/unattributed exposure, program/lineage/stage/global caps and mixed capital versions.
- [x] **Step 2: Add double-scaling tests** and prove the same multiplier scales both each unscaled lineage target and the unscaled portfolio gross ceiling before capacity/lot rounding.

```python
adjusted = apply_portfolio_risk_once(
    unscaled_lineage_targets=input.unscaled_targets,
    unscaled_portfolio_gross_cap=input.envelope.portfolio_gross_cap,
    drawdown=input.capital.drawdown,
)
assert adjusted.risk_adjustment_count == 1
```

- [x] **Step 3: Verify RED** with `uv run pytest tests/offensive/v3/kernel/test_risk.py -v`.
- [x] **Step 4: Implement pure risk module**; any unknown component returns a typed block, never zero/default exposure.
- [x] **Step 5: Verify and commit** with `git commit -m "feat(v3): apply complete portfolio risk once"`.

### Task 2: Admission, ranking, capacity, and integer sizing

**Interfaces:** Produces `admit_candidates()`, `rank_candidates()`, `capacity_limit()`, `size_portfolio()` and structured `BlockReason`.

- [ ] **Step 1: Write failing tests** for policy/envelope/mode/account/producer/lineage/behavior/cost/stage mismatch, BTST allowlist, OB disabled, Auto shadow-only, exploration aggregate cap, industry/day/ticker/gross caps, missing ADV, board price boundary, 100-share lot, high-price zero lot, worst-case fee/reserve and deterministic tie-break.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/kernel/test_{admission,capacity,sizing}.py -v`.
- [ ] **Step 3: Implement order**: validate complete frozen input → admit → deterministic rank → apply risk once → constrain by cash/risk/ADV/ticker/industry/portfolio → integer-lot floor → worst-case reserve. Remaining cash is not reallocated after observed T+1 fills.
- [ ] **Step 4: Add invariance tests** proving producer-supplied weights/risk labels cannot bypass central limits and input permutation does not change selected orders.
- [ ] **Step 5: Verify and commit** with `git commit -m "feat(v3): size authorized portfolio entries deterministically"`.

### Task 3: Pure portfolio decision and explicit deadline contract

**Interfaces:** Produces `GrowthKernel.decide(KernelInput)` and complete `PortfolioDecision` proposal.

- [ ] **Step 1: Write table-driven tests** for trusted evidence cutoff, close finalization, `seal_creation_deadline`, `permit_issue_deadline`, `permit_expires_at`, `gateway_send_deadline`, broker cutoff, no-signal, missed window, stale capital and deterministic replay.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/kernel/test_decide.py -v`.
- [ ] **Step 3: Implement pure orchestration**. Proposal contains all lines, quantities, limit bounds, worst-case reserve, versions and reasons; no repository ID, active status or signature is self-assigned by Kernel.
- [ ] **Step 4: Verify property** `same canonical input => same canonical output bytes/hash` across process and candidate input order.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): propose deterministic portfolio decisions"`.

### Task 4: Trust/policy/envelope activation and entry fences

**Interfaces:** Produces `GatewayAuthorityRepository.activate_trust_bundle()`, `activate_policy_and_envelope()`, `replace_envelope()`, `raise_entry_fence()` and read-only active-state projection.

- [x] **Step 1: Write failing tests** for invalid root/capability/predecessor, epoch rollback, wrong account/mode, policy/envelope fingerprint mismatch, two active envelopes, concurrent replacement, pure tightening and a fake “tightening” that adds behavior.
- [x] **Step 2: Add correction-fence tests** using Plan 03 protocol: signed `EntryFenceRaised` persists idempotently, increments fencing/authorization status, tombstones unclaimed entry, ACKs only after commit and never affects ExitMandate.
- [x] **Step 3: Verify RED** with `uv run pytest tests/offensive/v3/gateway/test_authority.py -v`.
- [x] **Step 4: Implement monotonic CAS**. Behavior-changing `PolicyActivation` and its complete envelope activate in one Gateway transaction; pure tightening may activate alone only when a mechanical subset check proves no new behavior/quantity/window/cap.
- [x] **Step 5: Verify and commit** with `git commit -m "feat(v3): activate governed policy and entry authority"`.

### Task 5: Atomic reserve and PortfolioDecisionSeal idempotency

**Interfaces:** Produces `CapitalGateway.publish_entry()` and `active_seal()`.

- [x] **Step 1: Write failing tests** for economic key `(portfolio_id, signal_session, decision_cycle_id)`, identical rerun, same-key/different-payload, epoch change with same key, stale expected versions, reserve failure and two-process race.
- [x] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/gateway/test_decisions.py -v`.
- [x] **Step 3: Implement one immediate transaction**: reverify active trust/policy/envelope/capital/risk/stage/fence; insert decision; reserve exact worst-case cash/exposure; publish active `PortfolioDecisionSeal`. Any failure rolls back all three.
- [x] **Step 4: Add supersede tests**. Before permit, an explicit legal shrink/cancel may replace active seal under the same economic key/revision chain; after permit or outbox state, no quantity increase or key escape is allowed.
- [x] **Step 5: Verify and commit** with `git commit -m "feat(v3): seal and reserve portfolio entries atomically"`.

### Task 6: Permit, durable outbox, and SEND_CLAIMED linearization

**Interfaces:** Produces `issue_permit()`, `make_outbox_durable()`, `claim_send()` and entry states through `SUBMISSION_AMBIGUOUS | BROKER_ACK` without network delivery.

- [ ] **Step 1: Write adversarial tests** for old active seal, wrong permit nonce, quantity increase, expired issue/permit/send deadlines, stale envelope/capital/risk/stage/fence versions, halt, duplicate claim and two competing dispatchers.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/gateway/test_entry_state.py -v`.
- [ ] **Step 3: Implement final send-right transaction**:

```python
with gateway.begin_immediate() as tx:
    tx.require_outbox_durable(command_id)
    tx.revalidate_active_seal_policy_envelope_capital_risk_stage_fence()
    tx.consume_permit_nonce_before_expiry()
    tx.require_before_gateway_send_deadline()
    tx.mark_send_claimed(client_order_id)
```

No network call occurs inside the DB transaction. After commit the owner either sends the exact immutable payload with the same client ID or records ambiguous/receipt state.

- [ ] **Step 4: Add crash matrix** before/after each state and prove an unclaimed outbox can be tombstoned while claimed state always remains worst-case live exposure.
- [ ] **Step 5: Verify and commit** with `git commit -m "feat(v3): linearize final entry send rights"`.

### Task 7: ExitMandate and economic-lot lifecycle

**Interfaces:** Produces `derive_exit_mandates()`, `claim_due_exit_work()`, `record_exit_attempt()`, `reconcile_exit()` and correction-driven reopen.

- [ ] **Step 1: Write transition tests** for T+10 ordinal, partial exit, suspension/limit state, unknown tradable quantity, existing live exit leaves, cancel-late-fill, terminal legal event, successor security and fill bust reopening a closed lot.
- [ ] **Step 2: Add dependency-outage tests** proving exits continue when policy/envelope/Authorizer/Publisher/entry endpoints are unavailable or risk/stage halt is active.
- [ ] **Step 3: Verify RED** with `uv run pytest tests/offensive/v3/gateway/test_exits.py -v`.
- [ ] **Step 4: Implement mandate quantity** as verified tradable quantity minus proven live exit leaves. Unknown quantity schedules query/reconcile and sends zero new sell quantity; it never guesses or oversells. Mandates and leases are durable/restartable.
- [ ] **Step 5: Verify and commit** with `git commit -m "feat(v3): persist independent exit obligations"`.

### Task 8: DAILY_BAR_PROXY and MANUAL_CONFIRMED execution

**Interfaces:** Produces `DailyBarProxy.execute_open()` and `ManualExecutionService.record/correct()` with permanent mode provenance.

- [ ] **Step 1: Write proxy tests** for pre-sealed T+1 open, one-price limit ambiguity, ordinary limit touch, suspension, missing bar, late command, partial cash and fixed slippage/cost version. No known executable open means unknown/cash, never a stale-close fill.
- [ ] **Step 2: Write manual tests** requiring pre-sealed plan for official OOS, operator/source/observed/attachment hash/exact price/quantity/fees; reject broker namespace. An out-of-protocol real trade is first recorded in AccountCapitalTruth, marked `UNATTRIBUTED_RISK`, excluded from official OOS and latches no-entry until reconciled.
- [ ] **Step 3: Verify RED** with `uv run pytest tests/offensive/v3/execution/test_{proxy,manual}.py -v`.
- [ ] **Step 4: Implement mode-specific adapters**; later broker matching links the same economic fact or posts delta correction, never copies it into another mode.
- [ ] **Step 5: Verify and commit** with `git commit -m "feat(v3): execute auditable proxy and manual modes"`.

### Task 9: Integrated Kernel/Gateway/Exit verification

- [ ] Add import-boundary test: Kernel has no storage/network/v2 imports.
- [ ] Add projection test: planned entry rows equal active executable seals; shadow/blocked/tombstoned/ambiguous are separately visible.
- [ ] Run:

```bash
uv run pytest tests/offensive/v3/kernel/ tests/offensive/v3/gateway/ tests/offensive/v3/execution/ -v
uv run pytest tests/offensive/test_execution_adjuster.py tests/offensive/test_trade_lifecycle.py tests/offensive/test_daily_action_service.py -q
git diff --check
```

Expected: all pass; no broker network adapter exists and runtime remains off.

- [ ] Update `AGENTS.md` to the exact implemented boundary and commit verification files.

## Completion Gate

- [ ] Kernel replay is byte-for-byte deterministic and all risk/capacity scaling occurs once.
- [ ] One transaction owns active policy/envelope, seal/reserve and final `SEND_CLAIMED` version checks.
- [ ] Economic idempotency cannot be bypassed by changing epoch or retry ID.
- [ ] Entry dependency failures cannot block, erase or oversell exits.
- [ ] Proxy/manual cannot be labeled broker; out-of-protocol facts preserve capital and halt new risk.
- [ ] No real broker call or production capital activation is enabled by this plan.
