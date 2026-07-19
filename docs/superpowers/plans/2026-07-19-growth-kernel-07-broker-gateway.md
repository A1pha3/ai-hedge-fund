# Optional Broker Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在前六个子项目已稳定且获得单独批准后，实现唯一持有 broker credential 的权威 gateway，正确处理 permit/fencing、transactional outbox、累计成交、部分成交、撤单、乱序回报、费用、bust/correction、对账和 writer handoff。

**Architecture:** Gateway 是独立 service principal 和唯一 broker writer。它在提交前原子重验 active seal、authorization revision、capital/risk version、permit nonce 和 fencing epoch，再把 order intent 与 outbox 同事务持久化。Adapter 只翻译 broker 协议；所有回报先规范化成稳定 execution revision，再由资本台账幂等消费。

**Tech Stack:** FastAPI/UDS、httpx、Plan 01–06、broker-specific SDK（选定券商后才加入）、SQLite outbox/inbox、pytest stateful/fault injection。

## Global Constraints

- 本计划默认不执行；选择券商、账户类型、API sandbox 与合规要求后必须补充 adapter-specific threat model。
- CLI/Agent/producer 不持有 broker credential、gateway signing key 或 ledger write DSN。
- 没有完整 broker receipt/ACK 就不能称 broker fill；本地 outbox 时间不等于 broker 接收时间。
- `client_order_id`、`broker_order_id`、`broker_execution_id` 和 `(execution_id, revision)` 分别唯一。
- 累计成交只按 `new_cum - last_cum` 入账；未解释回退立即 `RECONCILIATION_HALT`。
- broker-live 不能复用 proxy/manual fill；人工事件只能关联和差额更正，不能搬运。

---

## File Structure

- Create `src/screening/offensive/v3/broker/ports.py`
- Create `src/screening/offensive/v3/broker/gateway.py`
- Create `src/screening/offensive/v3/broker/outbox.py`
- Create `src/screening/offensive/v3/broker/normalizer.py`
- Create `src/screening/offensive/v3/broker/reconcile.py`
- Create `src/screening/offensive/v3/broker/handoff.py`
- Create `src/screening/offensive/v3/broker/adapters/production.py` only after broker selection; this stable module implements the selected vendor port
- Create `config/services/v3/broker-gateway.example.toml`
- Create `docs/runbooks/v3-broker-gateway.md`
- Create tests under `tests/offensive/v3/broker/`

### Task 1: Broker-neutral port and protocol fixtures

**Interfaces:** Produces `BrokerPort.submit/cancel/query_orders/query_executions/query_cash_positions`, receipt/event models and deterministic fake broker.

- [ ] **Step 1: Write failing contract tests** for unique IDs, timestamps, cumulative fields, partial/cancel/reject states, fee revisions and malformed/unknown broker payload.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/broker/test_ports.py -v`.
- [ ] **Step 3: Implement broker-neutral Protocol and fake**; no production SDK dependency yet.
- [ ] **Step 4: Verify GREEN**.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): define broker-neutral gateway port"`.

### Task 2: Final permit, fencing, and submission gate

**Interfaces:** Produces `Gateway.submit_permitted_entry()` and `submit_due_exit()`.

- [ ] **Step 1: Write adversarial tests** for shadow/manual/proxy seal, stale authorization revision, old active seal, wrong nonce, expired deadline, stale capital version, old fencing epoch, risk halt entry vs allowed exit and duplicate submit.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement one immediate transaction** validating `active_seal_id + revision + permit_nonce + fencing_epoch + authorization/version/Merkle root + capital_version`; persist order intent/client ID/outbox before any network send.
- [ ] **Step 4: Verify GREEN** with two competing gateway processes; only current fencing epoch can create an outbox row.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): fence and persist broker submissions"`.

### Task 3: Transactional outbox delivery and broker receipt deadlines

**Interfaces:** Produces `OutboxDispatcher.run_once()`, retry/backoff, broker receipt persistence and ambiguous-submission halt.

- [ ] **Step 1: Write tests** for crash before send, after send before ACK commit, network timeout, duplicate client ID, broker accepted after local timeout, cutoff missed and retry after restart.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement at-least-once delivery with broker idempotency key**. If broker cannot guarantee idempotent create/query by client ID, ambiguous submission stops new risk until reconciliation; never submit a second fresh ID automatically.
- [ ] **Step 4: Verify GREEN**.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): deliver broker orders through durable outbox"`.

### Task 4: Push/poll normalization and execution revisions

**Interfaces:** Produces `normalize_order_update()`, `apply_cumulative_execution()`, `apply_bust()` and `apply_correction()`.

- [ ] **Step 1: Write stateful tests** permuting push/poll duplicate/late/out-of-order messages, cancel-late-fill, cumulative equal/increase/decrease, partial fee arrival, bust and corrected quantity/price。真实但无法关联本地 order 的 fill 必须先作为 `UNATTRIBUTED_RISK` 入账并 halt，不能丢弃。
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement delta normalization**. `BUSTED` appends inverse economics; `CORRECTED` appends bust-old then apply-new under increasing revision; no history deletion/state rollback. Unlinked broker economics use a stable broker execution ID, enter capital truth exactly once, and remain unattributed until reconciliation resolves them.

```python
delta = update.cumulative_quantity - last.cumulative_quantity
if delta < 0 and not update.is_explicit_bust:
    raise ReconciliationHalt("unexplained cumulative execution rollback")
```

- [ ] **Step 4: Verify GREEN**: every event permutation yields identical final capital and event count after deduplication.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): normalize broker executions exactly once"`.

### Task 5: Cash, position, fee, and corporate-action reconciliation

**Interfaces:** Produces `Reconciler.compare()` and typed breaks with severity/action.

- [ ] **Step 1: Write tests** for exact match, timing-tolerant pending fee, unexplained cash/share, provisional corporate action, manual link, unknown order and stale broker snapshot.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement explicit tolerance policy** versioned by fact type, not generic monetary epsilon. Material/unknown mismatch latches halt; confirmation never duplicates economic event.
- [ ] **Step 4: Verify GREEN**.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): reconcile broker and capital truth"`.

### Task 6: Gateway writer handoff

**Interfaces:** Produces `ACTIVE -> DRAINING -> BROKER_RECONCILED -> HANDOFF_COMPLETE` with monotonic authority epoch.

- [ ] **Step 1: Write concurrency/failure tests** for live order, pending cancel, late fill, stale old writer, crash at each state and new writer early submission.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement handoff**. Old writer drains/reconciles; new writer receives new fencing epoch only after terminal/reconciled checkpoint. Old tokens remain permanently invalid.
- [ ] **Step 4: Verify GREEN**.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): hand off broker writer without overlap"`.

### Task 7: Selected broker adapter and sandbox certification

- [ ] Freeze vendor docs/version, auction cutoff semantics, rate limits, idempotency behavior, cumulative fill semantics, fees, corporate-action source and sandbox limitations in `docs/runbooks/v3-broker-gateway.md`.
- [ ] Implement adapter mapping every vendor status to a typed broker-neutral state; unknown status must raise and halt, not map to filled/cancelled.
- [ ] Add recorded, redacted protocol fixtures for partial fills, cancel races, rejects, corrections and reconnect.
- [ ] Run broker sandbox certification; compare submitted/received timestamps and reject any path that cannot prove auction receipt before cutoff.
- [ ] Commit adapter only after security review; do not include credentials or account identifiers.

### Task 8: Production-readiness fault campaign and enablement

- [ ] Run process kill, network partition, duplicate webhook, delayed poll, DB busy/full, clock skew, key rotation, broker restart and handoff tests.
- [ ] Run:

```bash
uv run pytest tests/offensive/v3/broker/ -v
uv run pytest tests/offensive/v3/ tests/offensive/ -q
git diff --check
```

Expected: all pass; no unexplained capital difference and every ambiguous case halts new risk while exits/reconciliation continue.

- [ ] Obtain independent security, compliance, reconciliation and disaster-recovery approval.
- [ ] Start with a separately signed one-shot `ExplorationAuthorization` at portfolio-wide 2%, never relabel proxy evidence as broker evidence.
- [ ] Update `AGENTS.md` only after a real broker-confirmed end-to-end event and reconciliation prove the mode; until then retain “broker gateway not authoritative”.

## Completion Gate

- [ ] Exactly one gateway epoch can send, and every broker order has one durable local intent.
- [ ] Duplicate/late/out-of-order reports never duplicate capital.
- [ ] Cumulative rollback, unknown status or unexplained reconciliation break halts new risk.
- [ ] Bust/correction and company-action confirmation preserve append-only economics.
- [ ] Broker 2% exploration uses new, non-reused evidence and an independent authorization.
