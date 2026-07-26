# Optional Broker Gateway, Reconciliation, and Disaster Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Plan 01–06 全部验收且获得独立批准后，实现唯一持有 broker credential/network egress 的 adapter worker，证明账户/协议完整性，正确处理 `SEND_CLAIMED`、同 ID 重试、累计成交、部分成交、撤单、乱序/截断、费用、bust/correction、对账、writer handoff 和灾备；首次真实资本只通过新的 BROKER_CONFIRMED 2% exploration 启动。

**Architecture:** Capital Gateway 继续是 entry/capital 唯一权威；broker adapter 不修改授权、seal、reserve 或资本，只发送已经在 Gateway 取得 `SEND_CLAIMED` 的不可变命令，并把所有 authenticated raw response 先写 durable broker inbox。Normalizer 把外部状态映射为 execution revisions，Plan 02 再幂等入账。Gateway-owned lifecycle scheduler 对 entry/exit/cancel/query/reconcile 使用独立队列与限流预算。无法证明的 broker 语义保持 unknown/no-entry。

**Tech Stack:** FastAPI/UDS、httpx、Plan 01–06、SQLite outbox/inbox、选定券商的固定 SDK/API 版本、pytest stateful/fault injection。

## Global Constraints

- 默认生产 adapter 为 disabled；在选定券商、账户环境、API 版本、合规和 sandbox/小额实测完成前，`BROKER_CONFIRMED` startup 必须失败。
- CLI/Agent/producer/Governance/Authorizer 不持有 broker credential、adapter key、network egress 或 Capital Gateway writable DSN。
- broker account ID、环境、币种、endpoint/certificate fingerprint 必须与 portfolio binding 精确相等。
- 没有 authenticated broker receipt/ACK 不能称 broker accepted/fill；本地 outbox/send time 不是 broker time。
- 只有经能力测试证明账户/交易日作用域内 client ID 幂等，才允许截止前同 `client_order_id` 重试；绝不生成新 ID 猜测重发。
- 查询必须证明分页完整、cursor 连续和历史 retention 覆盖；截断/回退/最近 N 条响应都是 unknown。
- 累计成交只按 `new_cumulative - last_cumulative` 入账；非显式 bust 的回退锁存 reconciliation halt。
- broker-live 不复用 proxy/manual fill 或晋级样本；真实但未关联事实先入 AccountCapitalTruth 并 halt，不得丢弃。

---

## File Structure

- Create `src/screening/offensive/v3/broker/ports.py`
- Create `src/screening/offensive/v3/broker/capabilities.py`
- Create `src/screening/offensive/v3/broker/raw_inbox.py`
- Create `src/screening/offensive/v3/broker/dispatcher.py`
- Create `src/screening/offensive/v3/broker/normalizer.py`
- Create `src/screening/offensive/v3/broker/reconcile.py`
- Create `src/screening/offensive/v3/broker/handoff.py`
- Create `src/screening/offensive/v3/broker/disaster_recovery.py`
- Create `src/screening/offensive/v3/broker/adapters/production.py`
- Create `scripts/v3_broker_certify.py`
- Create `config/services/v3/broker-gateway.example.toml`
- Create `docs/runbooks/v3-broker-gateway.md`
- Create tests under `tests/offensive/v3/broker/`

### Task 1: Broker-neutral port, authenticated envelopes, and deterministic fake

**Interfaces:** Produces `BrokerPort.submit/cancel/query_*`, `BrokerRawEnvelope`, stable order/execution/fee revision contracts and `DeterministicFakeBroker`.

- [ ] **Step 1: Write failing contract tests** in `test_ports.py` for client/broker order IDs, execution IDs/revisions, broker/source/received timestamps, cumulative fields, partial/cancel/reject/expire, fee revisions, unknown status and malformed authentication metadata.
- [ ] **Step 2: Add raw-inbox tests** for content-addressed authenticated payload, source sequence, parser version, duplicate/conflict, durable-before-normalize and encrypted/redacted secret fields.
- [ ] **Step 3: Verify RED** with `uv run pytest tests/offensive/v3/broker/test_{ports,raw_inbox}.py -v`.
- [ ] **Step 4: Implement broker-neutral port/fake and a disabled `production.py`** that raises `BROKER_ADAPTER_NOT_CERTIFIED`; no vendor SDK or credential is added yet.
- [ ] **Step 5: Verify and commit** with `git commit -m "feat(v3): define authenticated broker protocol boundary"`.

### Task 2: Capability certification and BrokerEnablementManifest gate

**Interfaces:** Produces signed `BrokerCapabilityProfile`, certification report/hash and `verify_broker_enablement()`.

- [ ] **Step 1: Write failing tests** for account/environment/currency/endpoint mismatch; unproven client-ID scope; duplicate create behavior; unsupported auction order type/TIF; ambiguous cutoff; partial/cancel/expiry/late-fill semantics; pagination/cursor/retention gaps and clock skew.
- [ ] **Step 2: Implement** `scripts/v3_broker_certify.py` with read-only capability probes by default and an explicit signed approval requirement for any sandbox/order mutation. Store redacted raw envelopes and exact API/SDK/docs version hashes.
- [ ] **Step 3: Make `production.py` load only one frozen capability profile** whose hash is bound by a valid `BrokerEnablementManifest`; any missing/unknown field keeps startup disabled.
- [ ] **Step 4: Verify with** `uv run pytest tests/offensive/v3/broker/test_capabilities.py -v`.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): certify broker semantics before enablement"`.

### Task 3: SEND_CLAIMED dispatcher and ambiguous submission handling

**Interfaces:** Produces `BrokerDispatcher.run_once()` consuming immutable Gateway commands after Plan 04 `claim_send()`.

- [ ] **Step 1: Write adversarial tests** for shadow/proxy/manual input, stale seal/envelope/capital/risk/stage/fence, wrong account/env, expired permit/send/broker cutoff, duplicate dispatcher, crash before/after claim, network timeout and ACK persistence failure.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/broker/test_dispatcher.py -v`.
- [ ] **Step 3: Implement sequence**: request Gateway `SEND_CLAIMED` transition → send exact immutable payload with exact client ID → durably append raw receipt/timeout → report status to Gateway. No adapter-side precheck substitutes for Gateway transaction.
- [ ] **Step 4: Recovery rule**: a claimed command without durable authenticated ACK becomes `SUBMISSION_AMBIGUOUS`. If certified idempotency and both send/cutoff deadlines remain valid, retry exact same ID/payload; otherwise query/cancel/reconcile only. New ID is forbidden.
- [ ] **Step 5: Verify and commit** with `git commit -m "feat(v3): dispatch only claimed broker commands"`.

### Task 4: Push/poll normalization and execution revisions

**Interfaces:** Produces `normalize_order_update()`, `apply_cumulative_execution()`, `apply_bust()` and `apply_correction()`.

- [ ] **Step 1: Write stateful tests** permuting duplicate/late/out-of-order push and poll, cancel-late-fill, equal/increasing/decreasing cumulative quantity, partial fee, bust, corrected quantity/price and unlinked execution.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/broker/test_normalizer.py -v`.
- [ ] **Step 3: Implement delta normalization**. Explicit bust appends inverse economics; correction appends bust-old then apply-new with increasing revision. Historical order state remains terminal while active economic projection may reopen position/ExitMandate.
- [ ] **Step 4: Prove every message permutation** with the same canonical source revisions converges to identical capital/event count; negative impossible shares produce reconciliation halt, not clamp.
- [ ] **Step 5: Verify and commit** with `git commit -m "feat(v3): normalize broker revisions exactly once"`.

### Task 5: Complete paginated reconciliation of orders, fills, cash, positions, fees, and actions

**Interfaces:** Produces `Reconciler.capture_complete_snapshot()`, `compare()` and typed break/severity/action.

- [ ] **Step 1: Write tests** for multi-page exact match, repeated/missing page, cursor rollback, retention too short, stale snapshot, timing-tolerant pending fee, unexplained cash/share, provisional action, manual link, unknown order and missing execution.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/broker/test_reconcile.py -v`.
- [ ] **Step 3: Implement completeness proof** binding query parameters, page count, cursors, broker as-of/received times and raw envelope roots. Tolerance is versioned per fact type; no generic monetary epsilon.
- [ ] **Step 4: Material/unknown break** latches no-entry but persists external fact first. Confirmation links existing canonical fact or posts only delta; it never duplicates capital.
- [ ] **Step 5: Verify and commit** with `git commit -m "feat(v3): reconcile complete broker history and capital"`.

### Task 6: Durable entry/exit/cancel/query scheduling and rate isolation

**Interfaces:** Extends Plan 05 scheduler with broker work queues and certified auction timings.

- [ ] **Step 1: Write tests** for entry queue saturation, separate exit/query budget, CLI/process outage, restart leases, broker throttle, cutoff, partial exit, unknown sellable shares, suspend/limit, cancel race and correction-driven exit reopen.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/broker/test_scheduler.py -v`.
- [ ] **Step 3: Implement independent queues/rate buckets**. Exit cannot consume entry authorization and entry cannot exhaust exit/query capacity. Unknown quantity triggers query/reconcile and zero additional sell.
- [ ] **Step 4: Run long simulated lifecycle** through T+1 entry and T+10 delayed exits with adapter restarts and rate-limit responses.
- [ ] **Step 5: Verify and commit** with `git commit -m "feat(v3): schedule broker lifecycle without orphan exits"`.

### Task 7: Credential/session/network fencing and writer handoff

**Interfaces:** Produces `ACTIVE -> DRAINING -> BROKER_RECONCILED -> HANDOFF_COMPLETE` with monotonic authority/fencing epoch and external fence proof.

- [ ] **Step 1: Write failure tests** for live/ambiguous/cancel-pending order, late fill, stale old writer, rotated key, cached session, old socket/fd, retained network route and new writer early send.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/broker/test_handoff.py -v`.
- [ ] **Step 3: Implement handoff**: old worker stops entry and drains/reconciles; external credential/session is revoked; network policy removes old egress; new worker receives next fencing epoch only after proofs and cursor checkpoint. Old epoch remains permanently invalid.
- [ ] **Step 4: If broker cannot revoke an old session**, require termination proof for the process/host holding it plus network-policy proof; otherwise handoff cannot complete and entry stays fenced.
- [ ] **Step 5: Verify and commit** with `git commit -m "feat(v3): fence broker credentials sessions and writers"`.

### Task 8: Disaster recovery and first BROKER_CONFIRMED exploration

**Interfaces:** Produces `DisasterRecoveryCoordinator.restore()` and a guarded broker activation checklist.

- [ ] **Step 1: Write DR tests** for stale/tampered backup, wrong account, missing outbox/inbox cursor, live/ambiguous order, lost credential, recovery epoch race and old writer resurrection.
- [ ] **Step 2: Implement restore** requiring signed `DisasterRecoveryManifest`; verify backup root, raise recovery/fencing epoch, restore durable stores/cursors, query complete broker state, replay/reconcile and re-prove conservation. Before completion only exit/tightening is allowed.
- [ ] **Step 3: Run production-readiness fault campaign**: process kill, network partition, duplicate webhook, delayed/truncated poll, DB busy/full, clock skew, key rotation, broker restart, handoff and DR.
- [ ] **Step 4: Run complete checks**.

```bash
uv run pytest tests/offensive/v3/broker/ -v
uv run pytest tests/offensive/v3/ tests/offensive/ -q
git diff --check
```

Expected: all pass; disabled adapter remains default; every ambiguity halts entry while exit/reconcile continues.

- [ ] **Step 5: Obtain independent security/compliance/reconciliation/DR approval**, then start a new BROKER_CONFIRMED Trial/Stage using a signed one-shot `EXPLORATION` envelope: exploration aggregate <=2%, and when no existing broker EDGE grant exists total portfolio gross <=2%. Expiry/assessment 后只 drain；任何未决 exploration 风险或法律 finality 缺口阻断重发，后续尝试必须重新消耗 Attempt/multiplicity/exploration budget，不能续期或改写为 edge。Proxy/manual evidence is prior only. Update `AGENTS.md` only after a real broker-confirmed round trip and reconciliation prove the mode.

## Completion Gate

- [ ] Exactly one valid adapter epoch can send; every order has one durable Gateway claim and one immutable client ID.
- [ ] Broker capability profile proves account binding, idempotency, auction TIF/cutoff, pagination/cursor/retention and clock semantics.
- [ ] Duplicate/late/out-of-order/bust/correction never duplicates or hides capital; reopened risk recreates exit duty.
- [ ] Old credential/session/process/network path cannot submit after handoff or DR.
- [ ] Durable scheduler preserves exits under CLI/entry/service failure and independent rate limits.
- [ ] First broker risk uses new broker-mode evidence and a complete 2% exploration envelope; no proxy/manual authorization is relabeled.
