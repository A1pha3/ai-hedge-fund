# V3 Service Boundaries, CLI, and Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 Publisher、Outcome Finalizer、Auto/BTST Producer、Authorizer 和 Capital Gateway 落成独立 capability/namespace 的窄服务边界，并让现有两个命令在不持有高权限凭据的情况下编排 v3 shadow 与只读报告。

**Architecture:** 每个 privileged worker 使用独立进程、Unix domain socket、socket/storage OS ACL、签名服务身份和独立 signing key reference；CLI 只持有无特权 client 与只读公钥注册表。各步骤独立提交，失败互不伪装。报告只从 sealed ledger/evidence projection 读取，显式区分 shadow、blocked、planned、各 fill mode、pending、halt 和 conflict。

**Tech Stack:** FastAPI、uvicorn UDS、httpx、Pydantic contracts、Plan 01–04 services、pytest。

## Global Constraints

- CLI/Agent/producer 进程不得读取 Publisher、Finalizer、Authorizer 或 Gateway 私钥和数据库写 DSN。
- 同进程 Python 类拆分不算权限隔离；生产配置必须指定不同 service principal/UDS 权限。
- SQLite 权限按文件隔离：market、auto-signal、btst-signal、outcome、authorization、capital 各有独立 owner/DB；任何服务都不能获得另一个 authority 的可写 DB 文件。
- `--auto` 的 snapshot、outcome、Auto shadow 是三个独立事务和状态。
- lifecycle/exit 先于新仓；snapshot/scan 失败仍必须展示已有资本状态。
- 本计划仅启用 `off|shadow`；不得 authority flip 或开启 BTST canary。

---

## File Structure

- Create `src/screening/offensive/v3/services/common.py`
- Create `src/screening/offensive/v3/services/clients.py`
- Create `src/screening/offensive/v3/services/market_publisher.py`
- Create `src/screening/offensive/v3/services/outcome_finalizer.py`
- Create `src/screening/offensive/v3/services/authorizer_api.py`
- Create `src/screening/offensive/v3/services/capital_gateway_api.py`
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
- Create tests under `tests/offensive/v3/services/` and `tests/offensive/v3/orchestration/`

### Task 1: Authenticated Unix-socket service foundation

**Interfaces:** Produces health/version endpoints, `ServiceClient`, request idempotency headers, socket ACL/server signature checks and structured error envelope.

- [ ] **Step 1: Write failing tests** for wrong signed server identity, socket owner/mode, schema negotiation, timeout, duplicate request, conflicting request and secret path readable by CLI user.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/services/test_service_boundary.py -v`.
- [ ] **Step 3: Implement UDS-only clients/servers**. Test signers are injected fakes; production service startup accepts key reference from a root/service-owned path and refuses group/world-readable material. Do not add fallback in-process signing.

```python
class ServiceClient:
    def __init__(self, socket_path: Path, expected_service_id: str) -> None:
        self._client = httpx.Client(transport=httpx.HTTPTransport(uds=str(socket_path)))
        self._expected = expected_service_id
```

- [ ] **Step 4: Verify GREEN and privilege scan**.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): establish isolated service boundaries"`.

### Task 2: Market Publisher service and v2 readiness adapter

**Interfaces:** Produces `POST /v1/snapshots/publish`, signed `SnapshotEvidence`, retained payload blobs and typed per-source state.

- [ ] **Step 1: Write failing tests** for cutoff, legal empty, failed source, stale fallback, future row, symlink/file replacement, duplicate publish and v2 manifest adaptation without treating readiness as edge.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement publisher** by reusing verified snapshot parsing logic through an adapter, not by weakening v2 validation. Capture raw consumed payloads and parser/policy versions.
- [ ] **Step 4: Verify GREEN** with v2 readiness security regression suite.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): publish reproducible market snapshots"`.

### Task 3: Outcome Finalizer and Authorizer services

**Interfaces:** Produces `POST /v1/outcomes/finalize` and `POST /v1/authorizations/assess`; CLI receives status/result IDs, not signing material.

- [ ] **Step 1: Write tests** proving Finalizer cannot publish snapshot/sign authorization, Authorizer cannot mutate capital/outcome, assessment idempotency and partial service outage isolation.
- [ ] **Step 2: Implement API adapters** over Plan 03 domain services; storage ACL fixtures grant only required tables/namespaces.
- [ ] **Step 3: Verify** with `uv run pytest tests/offensive/v3/services/test_{outcome_finalizer,authorizer_api}.py -v`.
- [ ] **Step 4: Add contract test** that the CLI process configuration contains socket endpoints and public registry only.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): isolate outcome and authorization services"`.

### Task 4: Capital Gateway API and writer access matrix

**Interfaces:** Produces read-only `GET /v1/capital/snapshot`, lifecycle `POST /v1/sessions/advance`, shadow publication and gated `POST /v1/decisions/publish`; only this service owns capital/decision DB write access.

- [ ] **Step 1: Write failing tests** proving CLI/producer/Authorizer cannot open or write capital DB, shadow payload is rejected by executable endpoint, runtime `off|shadow` rejects executable publication, exit/reconcile commands remain allowed during new-risk halt, and repeated commands are idempotent.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/services/test_capital_gateway_api.py -v`; expected failures are missing API/routes, not fixture errors.
- [ ] **Step 3: Implement the API adapter** over Plan 02/04 ports. Every executable request is signature/capability verified again inside the gateway; filesystem tests assign the DB and socket to the gateway principal only. Shadow decisions use a separate issuer-scoped DB and route.
- [ ] **Step 4: Verify GREEN** with `uv run pytest tests/offensive/v3/services/test_capital_gateway_api.py -v`.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): isolate the sole capital writer gateway"`.

### Task 5: Auto and BTST producer adapters

**Interfaces:** Produces signed `SignalEvidence` only. Auto output is shadow-only; BTST outputs raw target and feature diagnostics without regime/streak/composite sizing。两个 producer 分别运行在自己的 UDS service/OS principal 下，并各自只拥有对应 signal namespace DB。

- [ ] **Step 1: Write failing tests** using frozen SnapshotEvidence fixtures. Assert full funnel, behavior fingerprint, no cache reopen, no authorization field, OB disabled, and current scanner discrepancy reasons.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement adapters and UDS service apps** around current `scan_from_verified_snapshot()` and Auto scoring outputs. Freeze legacy behavior as an explicit baseline adapter; any changed candidate/rank/size starts a new behavior fingerprint.
- [ ] **Step 4: Verify GREEN** and current scanner regression tests.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): adapt auto and btst as evidence producers"`.

### Task 6: `--auto` independent orchestration

**Interfaces:** Produces `AutoFlowResult(snapshot_status, outcome_status, auto_shadow_status)` and preserves current cache refresh under an explicit legacy step during shadow.

- [ ] **Step 1: Write failing orchestration tests** for each of 2³ success/failure combinations, rerun idempotency, unavailable service, snapshot failure without false outcome success and Auto report `execution_authority=none`.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement sequential, independently committed calls**. 运行模式只读取版本化 `PolicySnapshot.runtime_mode=off|shadow`；不得由 `V3_RUNTIME_MODE` 等环境变量放宽。`off` preserves current behavior; `shadow` adds v3 evidence but never changes v2 plans.
- [ ] **Step 4: Verify GREEN** with `uv run pytest tests/offensive/v3/orchestration/test_auto_flow.py tests/test_main_auto_cache_refresh.py -v`.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): orchestrate independent auto evidence steps"`.

### Task 7: `--daily-action` lifecycle-first shadow orchestration

**Interfaces:** Produces v3 `ShadowDecision`, discrepancy report, and read-only capital projection; does not publish executable seal in this plan。authority flip 前，现有 v2 lifecycle 仍先按当前路径结算；v3 只从冻结的 v2 capital snapshot 建立 counterfactual shadow state，绝不推进或改写权威资本。

- [ ] **Step 1: Write failing tests** for lifecycle-first ordering, missing snapshot, missed window, stale NAV, no signal, current v2 plan comparison, repeat run and production v2/v3 path immutability.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement shadow flow**: request capital lifecycle projection, load frozen evidence, run BTST producer, invoke pure kernel in shadow authority, persist ShadowDecision evidence, compare against legacy output with structured reasons.
- [ ] **Step 4: Verify GREEN** with current dispatcher/daily-action tests.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): run daily action shadow lifecycle"`.

### Task 8: Ledger-derived reporting and operator visibility

**Interfaces:** Produces JSON and Chinese terminal views from a single `DailyOperatorProjection`.

- [ ] **Step 1: Write golden tests** for all statuses: `shadow`, `blocked`, `planned`, `simulated_fill`, `manual_fill`, `broker_fill`, `pending_exit`, `risk_halted`, `stage_loss_halted`, `conflict`, stale/unknown and service partial failure.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement renderer**. Planned set comes only from active executable seals. Auto BUY-like recommendations display `execution_authority=none`. Pending/block/halt prevents the misleading sole message “今日无信号”.
- [ ] **Step 4: Verify GREEN** with `uv run pytest tests/offensive/v3/reporting/ -v`.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): render truthful ledger-derived status"`.

### Task 9: Process/ACL runbook and integrated shadow verification

- [ ] Create `docs/runbooks/v3-shadow-services.md` with service identities, socket ownership/mode, key rotation, start/stop order, backups, health checks and fail-closed behavior.
- [ ] Add integration test that starts isolated UDS services under a temporary directory and exercises both commands without network or production data.
- [ ] Run:

```bash
uv run pytest tests/offensive/v3/services/ tests/offensive/v3/orchestration/ tests/offensive/v3/reporting/ -v
uv run pytest tests/offensive/ tests/test_main_auto_cache_refresh.py -q
git diff --check
```

Expected: all pass; mode remains shadow and no executable v3 seal exists.

- [ ] Update `AGENTS.md` with service topology and shadow runbook link.
- [ ] Commit exact service, CLI, test, config and documentation files.

## Completion Gate

- [ ] OS/process and storage tests prove capability separation, not merely class separation.
- [ ] 每个 authority 只有自己的 writable SQLite 文件；跨 authority 数据均经签名复制或窄 API。
- [ ] Existing commands remain usable when v3 services are off.
- [ ] Shadow mode cannot alter v2 decisions or write executable v3 seals.
- [ ] Every partial failure is separately visible and retryable.
- [ ] Reports are exact projections of ledger/evidence states.
