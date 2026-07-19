# Growth Kernel and Proxy Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现确定、可回放、无网络副作用的 Growth Kernel，以及严格分离的 shadow、日线代理和人工确认执行状态机；producer 候选只有经授权、风险、容量和资本检查后才可能成为 seal。

**Architecture:** 内核是纯函数，输入冻结的 PolicySnapshot、PIT snapshot、raw candidates、CapitalSnapshot 和已验证 CapitalAuthorization，输出 `NoTradeDecision`、`ShadowDecision` 或 `PublishDecisionCommand`。Seal repository 与执行服务负责事务幂等；proxy/manual 使用不同 namespace/issuer，均不能伪装 broker fill。

**Tech Stack:** Python、Decimal/整数、Plan 01 contracts、Plan 02/03 ports、pytest/Hypothesis。

## Global Constraints

- 内核不得 import pandas、requests/httpx、SQLite repository、v2 service 或环境变量。
- producer 不做组合 risk multiplier；BTST 初始禁用 streak/regime/composite sizing，OB disabled。
- drawdown multiplier 只应用一次；15% 是新增风险 halt，不是强制平仓。
- `DecisionSeal` 只能由 executable path 产生；shadow namespace 永远不能被 gateway 接受。
- 日线一字板或无法证明开盘成交时为 UNKNOWN/cash；禁止事后 raw close 补 fill。
- T+10 退出数量按当时权威可卖数量生成；risk halt 不阻止退出。

---

## File Structure

- Create `src/screening/offensive/v3/kernel/models.py`
- Create `src/screening/offensive/v3/kernel/risk.py`
- Create `src/screening/offensive/v3/kernel/capacity.py`
- Create `src/screening/offensive/v3/kernel/sizing.py`
- Create `src/screening/offensive/v3/kernel/decide.py`
- Create `src/screening/offensive/v3/decision/repository.py`
- Create `src/screening/offensive/v3/execution/order_state.py`
- Create `src/screening/offensive/v3/execution/proxy.py`
- Create `src/screening/offensive/v3/execution/manual.py`
- Create `src/screening/offensive/v3/execution/lifecycle.py`
- Create tests under `tests/offensive/v3/kernel/` and `tests/offensive/v3/execution/`

### Task 1: Raw candidate contract and single-pass risk

**Interfaces:** Produces `RawCandidate`, `KernelInput`, `RiskDecision`, `drawdown_multiplier()` and `apply_portfolio_risk_once()`.

- [ ] **Step 1: Write failing tests** for drawdown 9.99/10/14.99/15%, negative/stale NAV, existing exposure above target, lineage/program/global caps, stage-loss latch, unattributed migration risk and double-scaling rejection.

```python
def test_risk_multiplier_is_applied_once() -> None:
    candidate = raw_candidate(target=Decimal("0.10"), risk_adjusted=False)
    first = apply_portfolio_risk_once(candidate, Decimal("0.125"))
    assert first.target_weight == Decimal("0.05")
    with pytest.raises(KernelContractError, match="already risk adjusted"):
        apply_portfolio_risk_once(first, Decimal("0.125"))
```

- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/kernel/test_risk.py -v`.
- [ ] **Step 3: Implement pure risk module** with `risk_adjustment_count: Literal[0,1]`; inherited open/pending/live/reserve and unattributed risk count toward all caps.
- [ ] **Step 4: Verify GREEN**.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): apply portfolio risk exactly once"`.

### Task 2: Admission, ranking, ADV capacity, and integer sizing

**Interfaces:** Produces `admit_candidates()`, `rank_candidates()`, `capacity_limit()`, `size_orders()` and structured `BlockReason`.

- [ ] **Step 1: Write failing tests** for authorization/mode/lineage/version mismatch, BTST-only allowlist, OB disabled, Auto shadow-only, industry/day/ticker/gross caps, missing ADV, price boundary, 100-share lot, high-price zero lot, worst-case fees and deterministic tie-break.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement ordering**: validate → admit → deterministic rank → min(cash, risk, ADV, stock/industry/gross caps) → integer lot floor → worst-case reserve. Remaining cash is not reallocated after observed fills.

```python
quantity = floor_to_lot(
    min(risk_notional, cash_notional, adv_notional),
    worst_case_price_micros,
    lot_size=policy.lot_size,
)
```

- [ ] **Step 4: Verify GREEN** with `uv run pytest tests/offensive/v3/kernel/test_{admission,capacity,sizing}.py -v`.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): size authorized capacity-safe orders"`.

### Task 3: Pure decision orchestration and deadlines

**Interfaces:** Produces `GrowthKernel.decide(input) -> NoTradeDecision | ShadowDecision | PublishDecisionCommand`.

- [ ] **Step 1: Write table-driven tests** for snapshot cutoff, close-finalized ordering, seal/permit/send/broker deadlines, stale capital/authorization, kill override, no-signal, missed entry window and deterministic replay.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement six-step kernel only**. The function returns complete structured reasons and never writes or calls clock/network; all timestamps are explicit inputs.
- [ ] **Step 4: Verify GREEN** and property `same canonical input => same canonical output hash`.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): decide with a deterministic growth kernel"`.

### Task 4: Immutable seal repository and supersede protocol

**Interfaces:** Produces `DecisionRepository.publish()`, `supersede()`, `issue_permit()`, `active_seal()` and `planned_projection()`。Decision tables 与 Plan 02 capital tables 位于同一个 gateway-owned DB，并共用一个 transaction/session，保证 seal 指针与 reserve 原子变化。

- [ ] **Step 1: Write failing tests** for logical key `(portfolio, session, authority_epoch)`, identical rerun, payload conflict, revision monotonicity, reserve swap rollback, permit/fence preventing supersede, expired authorization and old permit replay.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement atomic active-seal pointer** and reserve operations through Plan 02 transaction port. Same-key/different-payload is zero-write unless explicit legal supersede before any permit/fence/live order.
- [ ] **Step 4: Verify GREEN** with multi-process race and injected failure between release/reserve/pointer switch.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): seal idempotent executable decisions"`.

### Task 5: Order/plan/position state machines and T+10 lifecycle

**Interfaces:** Produces legal transitions from spec §15, `prepare_entry_intents()`, `prepare_due_exits()` and `reconcile_execution_event()`.

- [ ] **Step 1: Write failing transition tests** for all legal/illegal plan and order edges, partial fill revisions, cancel-request late fill, terminal correction, T+10 session ordinal, EXIT_PENDING and legal terminal events.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement explicit transition maps**. Exit quantity is `tradable_quantity - live_exit_leaves`; unknown/suspended/limit state keeps pending position and reserve, never stale-close settlement.
- [ ] **Step 4: Verify GREEN** with `uv run pytest tests/offensive/v3/execution/test_{state,lifecycle}.py -v`.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): govern entry exit and pending lifecycle"`.

### Task 6: DAILY_BAR_PROXY execution

**Interfaces:** Produces `DailyBarProxy.execute_open()` and proxy fill/unknown/reject events.

- [ ] **Step 1: Write failing tests** for T+1 open, favorable one-price limit ambiguity, ordinary limit touch, suspension, missing bar, late command, partial portfolio cash, fixed slippage/cost policy and mode tagging.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement conservative proxy**. Only a pre-sealed proxy intent with known, executable open produces a synthetic fill; otherwise plan expires or remains pending according to entry/exit semantics.
- [ ] **Step 4: Verify GREEN** with `uv run pytest tests/offensive/v3/execution/test_proxy.py -v`.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): simulate conservative daily-bar execution"`.

### Task 7: MANUAL_CONFIRMED ingestion and corrections

**Interfaces:** Produces `ManualExecutionService.record()`, `correct()` and attachment/reconciliation status projections.

- [ ] **Step 1: Write failing tests** requiring operator, source, observed_at, attachment hash, exact quantity/price/fees; reject broker namespace, duplicate economics, missing provenance and direct history rewrite。另测真实但未关联 plan 的人工成交：必须记入资本真相、归为 `UNATTRIBUTED_RISK` 并锁存 reconciliation halt，不能因模型不认识而丢弃事实。
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement manual-only issuer path**. A later broker reconciliation links the manual event but cannot copy it; differences create explicit correction after human review. Unplanned confirmed economics are recorded first, then block new risk until attributed/reconciled.
- [ ] **Step 4: Verify GREEN**.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): ingest auditable manual executions"`.

### Task 8: Integrated kernel/execution verification

- [ ] Run:

```bash
uv run pytest tests/offensive/v3/kernel/ tests/offensive/v3/execution/ -v
uv run pytest tests/offensive/test_execution_adjuster.py tests/offensive/test_trade_lifecycle.py tests/offensive/test_daily_action_service.py -q
git diff --check
```

Expected: all pass.

- [ ] Add a test that asserts kernel imports contain no storage/network/v2 modules.
- [ ] Add a projection test: planned BUY set equals active executable seals exactly; shadow/blocked/pending are excluded and separately visible.
- [ ] Update `AGENTS.md`: kernel/proxy/manual implemented, runtime remains off/shadow, no broker capability.
- [ ] Commit verification files and documentation.

## Completion Gate

- [ ] Pure kernel replay is byte-for-byte deterministic.
- [ ] Risk/capacity/cash limits cannot be applied twice or bypassed by producer fields.
- [ ] Shadow cannot be submitted; proxy/manual cannot be labeled broker.
- [ ] T+10 and cancel-late-fill paths preserve real positions until actual/legal terminal facts.
- [ ] Every planned report row maps to one active executable seal.
