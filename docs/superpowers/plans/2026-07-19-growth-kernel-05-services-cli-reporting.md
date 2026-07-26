# V3 Service Boundaries, Durable Scheduler, CLI, and Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Governance、Publisher、Outcome Finalizer、Auto/BTST Producer、Authorizer、Capital Gateway 和 lifecycle scheduler 落成独立 capability/namespace 的窄服务，让两个现有命令只用无特权客户端编排 `off|shadow`，并从权威投影准确展示资本与生命周期状态。

**Architecture:** privileged worker 使用独立进程、Unix domain socket、OS/storage ACL、服务身份和独立 key reference。CLI 不持有签名材料或 writable DSN。Capital Gateway 是唯一资本/entry authority writer；durable scheduler 是其受限 worker，持续推进 exit/cancel/query/reconcile，不依赖 CLI 每日运行。各服务事务独立，失败分别呈现，禁止把跨服务调用描述为原子。

**Tech Stack:** FastAPI、uvicorn UDS、httpx、Pydantic contracts、Plan 01–04 domain services、pytest。

## Global Constraints

- CLI/Agent/producer 不得读取 Governance/Publisher/Finalizer/Authorizer/Gateway 私钥、broker credential 或 writable DB DSN。
- 同进程类拆分不算隔离；生产配置要求不同 service principal、socket owner/mode 和数据库 owner。
- market、auto-signal、btst-signal、outcome、authorization/governance、capital/gateway 各自 writable namespace；跨 authority 通过签名对象或窄 API。
- `--auto` 的 snapshot、outcome、Auto shadow 是独立提交；不得因后一步失败回填前一步或伪装全成功。
- lifecycle/exit/reconcile 优先于 entry；snapshot/scan/Authorizer 故障仍必须展示并推进已有资本义务。
- 本计划只允许 `off|shadow`；不得执行 migration flip、canary activation 或真实 broker send。

---

## File Structure

- Create `src/screening/offensive/v3/services/common.py`
- Create `src/screening/offensive/v3/services/identity.py`
- Create `src/screening/offensive/v3/services/trusted_clock.py`
- Create `src/screening/offensive/v3/services/clients.py`
- Create `src/screening/offensive/v3/services/market_publisher.py`
- Create `src/screening/offensive/v3/services/outcome_finalizer.py`
- Create `src/screening/offensive/v3/services/authorizer_api.py`
- Create `src/screening/offensive/v3/services/governance_api.py`
- Create `src/screening/offensive/v3/services/capital_gateway_api.py`
- Create `src/screening/offensive/v3/services/lifecycle_scheduler.py`
- Create `src/screening/offensive/v3/services/auto_producer_api.py`
- Create `src/screening/offensive/v3/services/btst_producer_api.py`
- Create `src/screening/offensive/v3/producers/auto.py`
- Create `src/screening/offensive/v3/producers/btst.py`
- Create `src/screening/offensive/v3/orchestration/auto_flow.py`
- Create `src/screening/offensive/v3/orchestration/daily_action_flow.py`
- Create `src/screening/offensive/v3/reporting/projections.py`
- Create `src/screening/offensive/v3/reporting/render.py`
- Modify `src/cli/dispatcher.py`
- Create `config/services/v3/services.example.toml`
- Create `docs/runbooks/v3-shadow-services.md`
- Create tests under `tests/offensive/v3/services/`, `tests/offensive/v3/orchestration/`, and `tests/offensive/v3/reporting/`

### Task 1: Authenticated UDS foundation, process identity, and trusted clock

**Interfaces:** Produces `ServiceIdentity`, health/version endpoints, `ServiceClient`, idempotency headers, signed response verification and `TrustedClock` status.

- [ ] **Step 1: Write failing tests** in `test_service_boundary.py` for wrong server identity/capability, socket owner/mode, schema negotiation, timeout, duplicate/conflicting request, key path readable by CLI, stale process lease and clock rollback/skew.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/services/test_service_boundary.py -v`.
- [ ] **Step 3: Implement UDS-only client/server foundation**. Production startup accepts opaque service-owned key references, never raw key material. Trusted clock reports monotonic sequence, wall time, skew health and source; unhealthy/rollback blocks time-sensitive entry while exit/reconcile remains callable.
- [ ] **Step 4: Add subprocess ACL test** proving the CLI principal can connect but cannot open key/DB paths.
- [ ] **Step 5: Verify and commit** with `git commit -m "feat(v3): establish authenticated service and clock boundaries"`.

### Task 2: Publisher, Finalizer, Authorizer, and Governance services

**Interfaces:** Produces `POST /v1/snapshots/publish`, `POST /v1/outcomes/finalize`, `POST /v1/authorizations/assess-edge` and governance candidate endpoints for Trust/Policy/Stage/Exploration/Recovery/manifests.

- [ ] **Step 1: Write capability-matrix tests** proving each service can write only its own namespace and cannot activate Gateway state, mutate capital, publish another issuer kind or obtain another signer.
- [ ] **Step 2: Add Publisher tests** for PIT cutoff, legal empty, stale fallback, future row, raw payload retention, v2 readiness adaptation and Evidence Store-controlled ingest stamps.
- [ ] **Step 3: Add Authorizer/Governance tests** for inactive candidate output, exact issuer capability, idempotency and partial service outage. Governance endpoints require explicit signed approval input; no permissive environment-variable fallback.
- [ ] **Step 4: Implement API adapters** over Plan 03 services and verify:

```bash
uv run pytest tests/offensive/v3/services/test_{market_publisher,outcome_finalizer,authorizer_api,governance_api}.py -v
```

- [ ] **Step 5: Commit** with `git commit -m "feat(v3): isolate evidence and governance authorities"`.

### Task 3: Capital Gateway API and sole-writer access matrix

**Interfaces:** Produces read-only `GET /v1/capital/risk-snapshot`, authority activation/fence routes, lifecycle routes, shadow publication and gated entry proposal/seal/permit/outbox routes.

- [ ] **Step 1: Write failing tests** proving CLI/producer/Authorizer/Governance cannot open capital DB; shadow rejected by executable route; local policy rejected as activation; runtime `off|shadow` rejects executable entry; exit/reconcile/correction remain available during entry halt.
- [ ] **Step 2: Add route-level tests** for joint policy/envelope CAS, one active envelope, `EntryFenceRaised` durable ACK, economic idempotency, reserve rollback, permit expiry and `SEND_CLAIMED` disabled in this plan.
- [ ] **Step 3: Verify RED** with `uv run pytest tests/offensive/v3/services/test_capital_gateway_api.py -v`.
- [ ] **Step 4: Implement thin API adapter** over Plan 02/04 repository using one Gateway-owned DB/session. Every request is capability/signature verified inside the service; shadow uses a physically separate namespace and endpoint.
- [ ] **Step 5: Verify and commit** with `git commit -m "feat(v3): expose the sole capital authority gateway"`.

### Task 4: Independent durable lifecycle scheduler

**Interfaces:** Produces restartable workers for `derive/claim ExitMandate`, due exit, cancel, query and reconcile with separate work queues/rate budgets.

- [ ] **Step 1: Write failing tests** for CLI absence, Publisher/Authorizer outage, process kill after claim, lease expiry, duplicate worker, entry saturation, independent exit rate budget, unknown sellable quantity and correction-driven lot reopen.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/services/test_lifecycle_scheduler.py -v`.
- [ ] **Step 3: Implement durable leases and bounded work loops**. Scheduler accepts only risk-maintaining/reducing commands; it cannot create entry proposal or broaden permit. Shutdown leaves durable work claim recoverable.
- [ ] **Step 4: Add 24-hour simulated-clock test** proving T+10 exits are generated and retried without either CLI command running.
- [ ] **Step 5: Verify and commit** with `git commit -m "feat(v3): run exits and reconciliation independently"`.

### Task 5: Auto and BTST producer service adapters

**Interfaces:** Produces signed `SignalEvidence` only. Auto remains shadow-only; BTST outputs raw targets/features without regime/streak/composite sizing.

- [ ] **Step 1: Write fixture tests** for full funnel, behavior fingerprint, no cache reopen, no authorization field, OB disabled, correction provenance and producer namespace separation.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/services/test_{auto_producer,btst_producer}.py -v`.
- [ ] **Step 3: Implement adapters** around current scoring and `scan_from_verified_snapshot()` using frozen payloads. Freeze legacy behavior as a named baseline; any semantic change gets new fingerprint/trial generation.
- [ ] **Step 4: Run current scanner regression tests** and prove adapters perform no network I/O after snapshot handoff.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): isolate auto and btst evidence producers"`.

### Task 6: `--auto` independent shadow orchestration

**Interfaces:** Produces `AutoFlowResult(snapshot_status, outcome_status, auto_shadow_status)` while current legacy cache refresh remains an explicit independent step.

- [ ] **Step 1: Write tests** for all 2^3 success/failure combinations, rerun idempotency, unavailable services, snapshot failure, correction pending fence and report `execution_authority=none`.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/orchestration/test_auto_flow.py -v`.
- [ ] **Step 3: Implement sequential independently committed calls** controlled only by the loaded candidate policy plus active mode projection. `off` preserves existing behavior; `shadow` adds v3 evidence without changing v2 plans or capital.
- [ ] **Step 4: Verify with** `uv run pytest tests/offensive/v3/orchestration/test_auto_flow.py tests/test_main_auto_cache_refresh.py -v`.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): orchestrate independent auto evidence steps"`.

### Task 7: `--daily-action` lifecycle-first shadow orchestration

**Interfaces:** Produces `ShadowDecision`, discrepancy report and read-only capital projection; no executable v3 seal in this plan.

- [ ] **Step 1: Write tests** for scheduler/lifecycle call before snapshot/scan, missing snapshot, missed window, stale NAV, no signal, v2 comparison, repeat run and byte-identical production v2/v3 capital paths.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/orchestration/test_daily_action_flow.py -v`.
- [ ] **Step 3: Implement flow**: query lifecycle/scheduler status → read capital projection → load frozen evidence → invoke BTST producer → run Kernel under shadow authority → persist ShadowDecision evidence → compare legacy output. Before Plan 06 flip, v3 never advances authoritative capital.
- [ ] **Step 4: Run current dispatcher/daily-action regression tests**.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): run lifecycle-first daily action shadow"`.

### Task 8: Ledger-derived reporting and operator visibility

**Interfaces:** Produces one `DailyOperatorProjection` rendered as JSON and Chinese terminal text.

- [ ] **Step 1: Write golden tests** for `shadow`, `blocked`, `sealed`, `permitted`, `outbox_durable`, `send_claimed`, `submission_ambiguous`, `proxy_fill`, `manual_fill`, `broker_fill`, `pending_exit`, `reopened_by_correction`, `terminating`, `insolvent`, `risk_halted`, `stage_loss_halted`, `reconciliation_halt`, stale/unknown and partial service failure.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/reporting/ -v`.
- [ ] **Step 3: Implement projections**. Planned entry set equals active executable seals only; Auto recommendation shows `execution_authority=none`; pending/block/halt must prevent misleading sole output “今日无信号”. Account capital total and mode-pure performance are distinct labeled views.
- [ ] **Step 4: Verify JSON/text share the same projection object** and never independently derive status.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): report truthful capital and lifecycle state"`.

### Task 9: Runbook and integrated shadow verification

- [ ] Document service identities, socket/file ACL, key/clock rotation, startup order, scheduler health, backups, correction fence protocol and fail-closed behavior in `docs/runbooks/v3-shadow-services.md`.
- [ ] Add integration test starting all services in a pytest temporary tree and exercising both commands with network disabled and production paths write-monitored.
- [ ] Run:

```bash
uv run pytest tests/offensive/v3/services/ tests/offensive/v3/orchestration/ tests/offensive/v3/reporting/ -v
uv run pytest tests/offensive/ tests/test_main_auto_cache_refresh.py -q
git diff --check
```

Expected: all pass; runtime remains shadow; no executable v3 seal, send claim or v2 mutation exists.

- [ ] Update `AGENTS.md` with verified topology/runbook and exact non-authoritative status, then commit scoped files.

## Completion Gate

- [ ] Capability separation is proven by process/socket/storage ACL tests, not class names.
- [ ] CLI can run both commands with v3 off and cannot access any signing/writable authority material.
- [ ] Durable scheduler advances exit/reconcile without CLI, entry dependencies or shared rate budget.
- [ ] Shadow cannot mutate v2 decisions/capital or create executable seals/send claims.
- [ ] Every partial failure has its own durable status and retry path; reports match authority projections exactly.
