# V3 Sealed Capital Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立独立、append-only、精确货币、可崩溃恢复的 v3 资本真相，覆盖现金、头寸、订单预留、费用、单位净值、外部资金流、公司行动、late correction 和 session checkpoint。

**Architecture:** SQLAlchemy Core + Alembic 管理独立 SQLite 数据库。`economic_events` 是不可变事件头，`economic_event_legs` 保存同一事实的多现金/证券/应收/应付/单位份额腿，二者共同构成唯一写入事实；当前状态由同事务投影表加速读取。任何更正追加新 revision/补偿事件，禁止 UPDATE/DELETE 经济历史。所有写命令带 idempotency key、expected stream version、issuer capability 与 authority epoch。

**Tech Stack:** Python、SQLAlchemy 2 Core、Alembic、SQLite WAL、整数分/整数股、Hypothesis、pytest。

## Global Constraints

- Depends on Plan 01 contracts and ports.
- 不迁移、不修改 v2；本计划数据库只建在 `tmp_path` 或显式 v3 dev path。
- SQLite `REAL` 不得出现在 money、quantity、units、cost-basis 真相列；金额用整数分，证券数量用整数股，单位份额用 PolicySnapshot 冻结精度的整数 quanta。
- 估值事件不能改变 cash/shares；头寸只能因 fill 或法律生效公司行动改变。
- 所有外部 flow 使用 flow 前同一时点 unit NAV；无法定价时进入 suspense/memo。
- 早于 session watermark 的普通生产写入失败；late correction 以当前 `recorded_at` 追加。

---

## File Structure

- Create `src/screening/offensive/v3/storage/metadata.py`
- Create `src/screening/offensive/v3/storage/schema.py`
- Create `src/screening/offensive/v3/storage/migrations/`
- Create `src/screening/offensive/v3/capital/repository.py`
- Create `src/screening/offensive/v3/capital/projector.py`
- Create `src/screening/offensive/v3/capital/nav.py`
- Create `src/screening/offensive/v3/capital/corporate_actions.py`
- Create `src/screening/offensive/v3/capital/checkpoints.py`
- Create tests under `tests/offensive/v3/capital/`

### Task 1: Append-only schema and transaction kernel

**Interfaces:** Consumes Plan 01 `CapitalEvent`, `EconomicLeg`, `CapabilityVerifier`. Produces `CapitalRepository.initialize()`, `append(command)`, `events()`, `stream_version()` and `CapitalConflict`.

- [ ] **Step 1: Write failing schema/repository tests** proving exact schema version, WAL/foreign keys, unique `(portfolio_id, idempotency_key)`, stream compare-and-swap, immutable event rows and rollback on projector failure.

```python
def test_same_key_different_payload_is_zero_write(repo) -> None:
    repo.append(command("k1", cash_delta_cents=100))
    with pytest.raises(CapitalConflict):
        repo.append(command("k1", cash_delta_cents=101))
    assert repo.stream_version("p1") == 1
    assert len(repo.events("p1")) == 1
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/offensive/v3/capital/test_{schema,repository}.py -v`

Expected: imports fail.

- [ ] **Step 3: Implement schema** with `ledger_meta`, `economic_events`, `event_revisions`, `capital_projection`, `positions`, `reserves`, `receivables`, `payables`, `session_checkpoints` and an SQLite trigger rejecting UPDATE/DELETE on event tables.

```python
economic_events = Table(
    "economic_events", metadata,
    Column("portfolio_id", String, nullable=False),
    Column("stream_version", Integer, nullable=False),
    Column("economic_event_id", String, nullable=False),
    Column("idempotency_key", String, nullable=False),
    Column("payload_hash", String(64), nullable=False),
    PrimaryKeyConstraint("portfolio_id", "stream_version"),
    UniqueConstraint("portfolio_id", "economic_event_id"),
    UniqueConstraint("portfolio_id", "idempotency_key"),
)

economic_event_legs = Table(
    "economic_event_legs", metadata,
    Column("economic_event_id", String, nullable=False),
    Column("leg_index", Integer, nullable=False),
    Column("asset_kind", String, nullable=False),
    Column("asset_id", String, nullable=False),
    Column("amount_cents", Integer),
    Column("quantity", Integer),
    PrimaryKeyConstraint("economic_event_id", "leg_index"),
)
```

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/offensive/v3/capital/test_{schema,repository}.py -v`

Expected: pass, including two-process contention test.

- [ ] **Step 5: Commit**

```bash
git add src/screening/offensive/v3/storage src/screening/offensive/v3/capital/repository.py tests/offensive/v3/capital
git commit -m "feat(v3): create append-only capital event store"
```

### Task 2: Fills, fees, reserves, positions, and conservation

**Interfaces:** Produces `record_fill()`, `record_fee()`, `reserve_cash()`, `release_reserve()`, `capital_snapshot()` and `assert_conservation()`.

- [ ] **Step 1: Write failing property tests** for partial entry/exit fills, minimum commission per order, transfer/stamp tax effective dates, slippage diagnosis, live cancel reserve, late fill after cancel request and duplicate execution revisions.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/capital/test_fills_and_conservation.py -v`.
- [ ] **Step 3: Implement one transaction per canonical fact**. A fill creates one gross cash event and one position delta; each fee creates a linked but distinct economic event. `record_fill` accepts integer `price_micros`, `quantity`, and exact fee cents; derived decimal display values are projections only.

```python
def record_fill(self, command: RecordFill) -> CapitalSnapshot:
    gross_cents = round_half_even(command.price_micros * command.quantity, 10_000)
    direction = 1 if command.side is Side.BUY else -1
    legs = (
        EconomicLeg.cash(amount_cents=-direction * gross_cents),
        EconomicLeg.security(command.ticker, quantity=direction * command.quantity),
    )
    return self._append_atomic(command, legs)
```

- [ ] **Step 4: Verify GREEN and invariants**

Run: `uv run pytest tests/offensive/v3/capital/test_fills_and_conservation.py -v`

Expected: for every generated event sequence, opening capital + external flows + P&L equals closing assets/liabilities with zero unexplained cents or shares.

- [ ] **Step 5: Commit**

```bash
git add src/screening/offensive/v3/capital tests/offensive/v3/capital/test_fills_and_conservation.py
git commit -m "feat(v3): conserve fills fees reserves and positions"
```

### Task 3: Unit NAV, external flows, HWM, and drawdown epochs

**Interfaces:** Produces `NavProjector.close_valuation()`, `request_subscription()`, `price_subscription()`, `request_redemption()`, `price_redemption()`, `settle_redemption()` and `start_risk_epoch()`.

- [ ] **Step 1: Write failing tests** for flow-before-price ordering, suspense cash, memo withdrawal cancellation, payable settlement, lifetime vs active-epoch HWM and as-observed vs restated NAV.

```python
def test_deposit_does_not_create_return(repo) -> None:
    before = repo.close_valuation(nav_cents=1_000_000, units_micros=1_000_000)
    repo.apply_external_flow(SubscriptionPriced(cash_cents=500_000, unit_price_micros=1_000_000))
    after = repo.capital_snapshot()
    assert after.unit_price_micros == before.unit_price_micros
    assert after.units_micros == 1_500_000
```

- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement exact flow ordering** and append-only restatement links; `RiskEpochStarted` records audited starting NAV but never changes lifetime HWM/history.
- [ ] **Step 4: Verify GREEN** with `uv run pytest tests/offensive/v3/capital/test_nav_and_flows.py -v`.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): account unit nav flows and risk epochs"`.

### Task 4: Corporate actions and economic-lot finality

**Interfaces:** Produces `apply_dividend_receivable()`, `settle_dividend()`, `apply_share_receivable()`, `make_shares_tradable()`, `apply_split_merge()`, `convert_security()`, `settle_terminal_cash()` and `legal_write_off()`.

- [ ] **Step 1: Write failing tests** for ex-date/pay-date separation, fractional entitlements, share receivable vs tradable quantity, split/merge basis, merger conversion, delisting cash, provisional→confirmed and correction without duplicate cash/shares.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement source-authority matrix and stable `economic_event_id`**. Confirmation links to provisional fact; only delta correction changes capital.
- [ ] **Step 4: Verify GREEN** with `uv run pytest tests/offensive/v3/capital/test_corporate_actions.py -v`.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): model auditable corporate actions"`.

### Task 5: Session checkpoints, late correction, and permit invalidation

**Interfaces:** Produces `CheckpointService.advance()`, `append_late_correction()` and transactional `capital_version` increment callback.

- [ ] **Step 1: Write failing tests** for all six phases, idempotent restart, phase regression, earlier `as_of`, same-phase stream version, late fee/dividend, and old permit invalidation.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement monotonic checkpoint state machine**. Late correction does not reopen old phase; it appends at current stream version, increments capital version, and emits an outbox notification consumed later by gateway/authorizer.

```python
PHASES = (
    "CORPORATE_ACTIONS_APPLIED", "PREOPEN_RISK_LOCKED",
    "ORDER_INTENTS_DURABLE", "OPEN_RECONCILED",
    "CLOSE_VALUED", "SESSION_FINALIZED",
)
```

- [ ] **Step 4: Verify GREEN** with `uv run pytest tests/offensive/v3/capital/test_checkpoints.py -v`.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): checkpoint sessions and invalidate stale permits"`.

### Task 6: Read models, backups, and full ledger verification

**Interfaces:** Produces immutable `CapitalSnapshot`, daily NAV projection, position/order/reserve views, `verify_ledger()` and consistent SQLite backup.

- [ ] **Step 1: Write failing tests** that rebuild projections from events, compare backup hashes, detect projection tampering, reject unknown events and prove v2 paths unchanged.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement projector rebuild and verifier**; projection discrepancies halt new risk but never mutate event history automatically.
- [ ] **Step 4: Run full checks**:

```bash
uv run pytest tests/offensive/v3/capital/ -v
uv run pytest tests/offensive/test_ledger_repository.py tests/offensive/test_daily_action_service.py -q
uv run python -m src.screening.offensive.v3.capital.verify --help
git diff --check
```

Expected: all pass; verifier prints `capital_conservation=PASS projection_rebuild=PASS`.

- [ ] **Step 5: Update `AGENTS.md`** to state “v3 capital ledger implemented but not authoritative/not migrated”, then commit exact files.

## Completion Gate

- [ ] Every cent/share change has one canonical event and one source authority.
- [ ] UPDATE/DELETE of economic history is technically blocked.
- [ ] Corporate action and external flow tests preserve NAV and capital conservation.
- [ ] Checkpoint restart and late correction are deterministic.
- [ ] No Plan 02 code accepts producer candidates or creates orders.
