# Growth Kernel Revision 2 Contracts, Policy, and Trust Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在已合并的 Plan 01 Revision 1 基线上完成不兼容的 Revision 2 契约升级，冻结控制面、完整组合授权、资本快照、entry/exit、迁移/broker/DR manifest 和可信时间语义，使后续计划只依赖最终接口。

**Architecture:** `v3/contracts` 与 `v3/policy` 保持无存储、无网络、strict/frozen；canonical payload 使用 domain-separated hash。`TrustBundle` 和 `PolicyActivation` 是签名候选，只有未来 Capital Gateway 的单调 activation 才产生权限。旧 `CapitalAuthorization`/`DecisionSeal` 保留时只能作为显式 legacy adapter 输入，不能继续作为稳定 port 返回类型。

**Tech Stack:** Python、Pydantic 2、`Decimal`、Ed25519/cryptography、pytest。

## Global Constraints

- 当前实现事实：Plan 01 Revision 2 Tasks 1–5 contracts/policy/trust/final structural ports 已完成；仍无 store、activation、签发、资本 authority、Authorizer、Kernel、Gateway、broker 或可执行路径。
- Tasks 1–3 中未勾选的步骤保留为当时的历史计划记录，不据此否定已经落库并验证的实现；当前完成度只由 Completion Gate 的可重验验收项陈述。
- 本计划不写任何 evidence、capital、authority 或 broker 数据库，也不提供 `activate()`、`sign()`、`send()`。
- Snapshot/Signal/Outcome schema 禁止 `execution_authorized`；shadow 与 executable 必须是不同 discriminant、issuer capability 和 namespace。
- 所有授权都是 portfolio 完整政策的 `CapitalAuthorizationEnvelope`；不得恢复多个独立 lineage authorization 相加的旧语义。
- 时间字段由类型区分；`permit_expires_at` 不能继续叫含混的 `deadline`。
- 本地 registry/policy 文件只是候选；接口和文档不得暗示“读取成功即 active”。
- 私钥、MAC secret、broker credential、真实账户 ID 不进入仓库、CLI 环境或测试 fixture。

---

## Existing Baseline and File Structure

已实现基线位于：

- Modify `src/screening/offensive/v3/contracts/base.py`
- Modify `src/screening/offensive/v3/contracts/evidence.py`
- Modify `src/screening/offensive/v3/contracts/authorization.py`
- Modify `src/screening/offensive/v3/contracts/decision.py`
- Modify `src/screening/offensive/v3/contracts/capital.py`
- Modify `src/screening/offensive/v3/contracts/ports.py`
- Create `src/screening/offensive/v3/contracts/governance.py`
- Create `src/screening/offensive/v3/contracts/execution.py`
- （历史注记：原计划列了独立 `contracts/migration.py`；三个迁移/broker/DR manifest 实际并入 `contracts/governance.py`，无独立模块）
- Modify `src/screening/offensive/v3/contracts/trust.py`
- Modify `src/screening/offensive/v3/policy/models.py`
- Modify `src/screening/offensive/v3/policy/loader.py`
- Modify `src/screening/offensive/v3/trust/registry.py`
- Create `config/policies/v3/policy-v2.json`
- Modify/create tests under `tests/offensive/v3/contracts/`

### Task 1: Freeze Revision 1 and add domain-separated canonical primitives

**Interfaces:** Produces `SchemaVersion`, `UtcInstant`, `MoneyCents`, `QuantityUnits`, `UnitQuanta`, `RationalQuantity`, `CanonicalModel`, `canonical_json_bytes()` and `domain_hash(domain, schema_major, payload)`.

- [ ] **Step 1: Add failing tests** to `tests/offensive/v3/contracts/test_revision2_base.py` for persisted float rejection, finite normalized decimals, timezone-aware UTC, rational denominator > 0, unknown schema major and cross-domain hash separation.

```python
def test_same_payload_has_different_domain_hashes() -> None:
    payload = {"portfolio_id": "p1", "version": 1}
    assert domain_hash("policy-activation", 2, payload) != domain_hash(
        "capital-authorization", 2, payload
    )
```

- [ ] **Step 2: Verify RED**.

Run: `uv run pytest tests/offensive/v3/contracts/test_revision2_base.py -v`

Expected: collection succeeds; tests fail because `domain_hash` and exact integer aliases are absent.

- [ ] **Step 3: Implement minimal primitives** in `contracts/base.py`. Canonical serialization sorts keys, rejects NaN/Infinity/float, normalizes Decimal strings and binds domain plus schema major before SHA-256. Revision 1 imports none of these evolving R2 primitives: its used `ExecutionMode`/`EvidenceScope`/UTC/SHA-256/canonical serializer/content hash/`CanonicalModel` are copied from `dccb76c5` into a self-contained local primitive module, including the R1-only acceptance of finite float values.
- [ ] **Step 4: Add frozen Revision 1 schema/hash fixtures** in `tests/offensive/v3/contracts/fixtures/revision1/` so import adapters can distinguish old payloads without silently reinterpreting them.
- [ ] **Step 5: Verify and commit**.

```bash
uv run pytest tests/offensive/v3/contracts/test_base.py tests/offensive/v3/contracts/test_revision2_base.py -v
git add src/screening/offensive/v3/contracts/base.py tests/offensive/v3/contracts
git commit -m "feat(v3): domain-separate revision two contracts"
```

### Task 2: Define Governance Control Plane and complete authorization envelope

**Interfaces:** Produces `TrustBundle`, `PolicyActivation`, `RiskEpochStarted`, `TrialManifest`, `StatisticalAnalysisPlan`, `StageManifest`, `LineageGrant`, `CapitalAuthorizationEnvelope`, `AuthorizationStatus`, `EntryFenceRaised`, `MigrationApprovalManifest`, `BrokerEnablementManifest` and `DisasterRecoveryManifest`.

- [ ] **Step 1: Add failing exact-schema tests** in `test_governance.py` and replace old authorization expectations in `test_authorization.py`. Cover issuer capability, predecessor/root hash, monotonic epoch fields, portfolio/account/mode binding, `EDGE | EXPLORATION | RECOVERY`, complete target policy, grants, fixed integer loss budgets and expiry.
- [ ] **Step 2: Add adversarial tests** proving:
  - multiple top-level lineage authorizations cannot parse as an active portfolio policy;
  - `EXPLORATION` outside `BROKER_CONFIRMED` fails;
  - exploration aggregate cap over 2% fails;
  - first broker exploration without EDGE also enforces portfolio gross <= 2%;
  - `RECOVERY` cannot create an exploration/edge grant and must bind inherited risk/loss versions;
  - local `PolicySnapshot` or registry cannot parse as an activation object;
  - migration/broker/DR manifests require the exact distinct capability.
- [ ] **Step 3: Verify RED**.

Run: `uv run pytest tests/offensive/v3/contracts/test_{authorization,governance}.py -v`

Expected: failures name missing Revision 2 classes or rejected field sets; no fixture/setup error.

- [ ] **Step 4: Implement strict models** in `contracts/authorization.py` and `contracts/governance.py`.

```python
class AuthorizationKind(StrEnum):
    EDGE = "EDGE"
    EXPLORATION = "EXPLORATION"
    RECOVERY = "RECOVERY"

class CapitalAuthorizationEnvelope(CanonicalModel):
    authorization_kind: AuthorizationKind
    portfolio_id: str
    mode: ExecutionMode
    policy_activation_hash: Sha256
    trust_bundle_hash: Sha256
    authority_epoch: PositiveInt
    risk_epoch: PositiveInt
    portfolio_gross_cap: DecimalFraction
    exploration_aggregate_gross_cap: DecimalFraction
    lineage_grants: tuple[LineageGrant, ...]
    program_loss_budget_bindings: tuple[ProgramLossBudgetBinding, ...]
```

- [ ] **Step 5: Verify, snapshot schemas and commit**.

```bash
uv run pytest tests/offensive/v3/contracts/test_{authorization,governance}.py -v
git add src/screening/offensive/v3/contracts tests/offensive/v3/contracts
git commit -m "feat(v3): define governed portfolio authorization envelopes"
```

### Task 3: Replace decision/capital contracts with portfolio, lifecycle, and trusted-time semantics

**Interfaces:** Produces `PortfolioDecision`, `PortfolioDecisionSeal`, `ShadowDecision`, `ExecutionPermit`, `GatewayExpectedVersions`, `CapitalRiskSnapshot`, `ExitMandate`, entry/order states and exact deadline fields.

- [ ] **Step 1: Update failing tests** in `test_decision.py`, `test_capital.py` and new `test_execution.py`. Cover full portfolio proposal, immutable quantities/limits/worst-case reserve, economic key `(portfolio_id, signal_session, decision_cycle_id)`, exact version bundle, account binding and exposure aggregation at portfolio/program/lineage/stage/global levels.
- [ ] **Step 2: Add transition/deadline tests** for:
  - `SEALED -> PERMITTED -> OUTBOX_DURABLE -> SEND_CLAIMED -> SUBMISSION_AMBIGUOUS | BROKER_ACK`;
  - `close_finalized < seal_creation_deadline < permit_issue_deadline < permit_expires_at <= gateway_send_deadline < broker_auction_cutoff`;
  - `permitted_quantity <= sealed_quantity` and T+1 cannot increase;
  - seal-owned post-admission capital/stream/snapshot anchors, exact same-version revalidation and bidirectionally unique stage/budget bindings;
  - mutually exclusive all-line mechanical-zero versus portfolio-witness `CANCEL`, plus post-permit receipts that preserve exact prior permit/nonce ownership while cancelling monotonic authority/capital/fact drift or current durable-outbox drift;
  - stable reservation allocation identities with monotonic shrink, positive-release capital/snapshot advance, and zero-release capital/snapshot quietness;
  - healthy trusted-time future-snapshot rejection and unhealthy-clock monotonic fact-integrity cancellation;
  - issuer revalidation against `current_registry_epoch >= issuance_registry_epoch`, rejecting same-epoch TrustBundle forks;
  - flat/nonpositive-to-positive correction reopening a stable ExitMandate ID at a revision above all prior revisions;
  - ExitMandate has no entry authorization field, names `entry_plan_evidence_artifact_hash` as the current `EvidenceRecord[PlanEvidence].artifact_hash()` binding, and cannot sell unknown/untradable quantity;
  - order lifecycle terminal history may receive a higher execution revision.
- [ ] **Step 3: Verify RED** with `uv run pytest tests/offensive/v3/contracts -v` so every checkpoint/adversarial contract is included.
- [ ] **Step 4: Implement exact models** in `decision.py`, `capital.py`, and `execution.py`; remove final-interface exports of the old generic names from `contracts/__init__.py`.
- [ ] **Step 5: Verify stable serialization and commit**.

```bash
uv run pytest tests/offensive/v3/contracts -v
git add src/screening/offensive/v3/contracts tests/offensive/v3/contracts
git commit -m "feat(v3): freeze portfolio decision and lifecycle contracts"
```

### Task 4: Upgrade PIT evidence and root-signed trust/policy candidates

**Interfaces:** Evidence envelopes add `provider_published_at`; store-controlled records add `ingested_at`, `commit_sequence`, revision links, active-revision identity and a schema-major domain-separated artifact hash. Produces root-verified `TrustBundleVerifier`, complete schema-major-2 signed control-artifact role routes, and candidate `load_policy_snapshot()` / `verify_policy_activation()` without activation side effects. Revision 1 trust, authorization, capital dependencies and ports remain locally frozen at the `dccb76c5` surface.

**Implemented boundary (2026-08-01):** This task is implemented as storage-free candidate contracts and pure verification only. A raw `TrustedRegistry`, locally loaded policy, constructible `VerifiedTrustBundle`/`VerifiedIssuer`, or typed witness cannot confer authority. `TrustBundleVerifier` only exposes full root-signed chain verification; every executable capability check also consumes a future Authority-Store `CurrentTrustHeadWitness` and exact-matches the signed head. Policy successors consume a typed active-predecessor witness, never raw activation DTOs; each witness enforces `effective_from <= observed_at`, including strict revalidation plus a defensive verification check for unchecked instances. `verify_policy_activation()` accepts only the exact current `CapabilityVerifier`, not a subclass override, and calls `CapabilityVerifier.verify(verifier, ...)` through explicit base-class dispatch so an exact verifier instance cannot shadow `verify()` to bypass an invalid signature or wrong current head. The nested `CapabilityVerifier` constructor likewise accepts only the exact `TrustBundleVerifier`, and root-chain verification/helpers use explicit base-class dispatch so an inner subclass is rejected before its override can run and instance-level method shadowing cannot bypass root-signature verification. These are in-process type/dispatch boundaries and do not claim protection from malicious same-process class monkeypatching or verifier internal-state mutation. Current evidence is schema major 2 and executable plans bind active store-owned records with known provider publication time; `ExitMandate.entry_plan_evidence_artifact_hash` denotes the current plan record's domain-separated `artifact_hash()`. Revision 1 stays locally frozen at major 1, including its `dccb76c5` canonical primitives and finite-float behavior, without weakening current R2 float rejection. Per design §11.2, the behavior fingerprint binds `policy_epoch` but excludes the operational `authority_epoch` and `risk_epoch` fencing counters. `policy-v2.json` remains `off`. Evidence/Trust/Policy Store persistence, source-policy qualification of `NOT_APPLICABLE`, activation CAS, signing, capital authority, and all Task 5 final ports remain outside this task.

- [x] **Step 1: Add failing tests** in `test_evidence.py`, `test_trust_registry.py`, and `test_policy.py` for trusted clock ordering, store-controlled fields forbidden on producer input, root signature, registry epoch/predecessor rollback, revoked/expired issuer, policy predecessor/account/epoch mismatch, duplicate JSON key and symlink/non-regular files.
- [x] **Step 2: Verify RED**.
- [x] **Step 3: Implement verification only**. `TrustedRegistry.load()` becomes a compatibility parser; executable verification requires a complete valid `TrustBundle` chain, exact current-head witness and explicit `trusted_at`. Policy successor verification requires an exact active-predecessor witness. `policy-v2.json` remains `runtime_mode="off"` and has no activation authority.
- [x] **Step 4: Run secret/capability scan** and adversarial checks for superseded/forked trust heads, raw policy predecessors, schema routing, and executable UNKNOWN/NOT_APPLICABLE/historical evidence rejection.

```bash
uv run pytest tests/offensive/v3/contracts/test_{evidence,trust_registry,policy}.py -v
rg -n "PRIVATE KEY|broker.*secret|authorizer.*secret|def sign\(" src/screening/offensive/v3 config/policies/v3
```

Expected: tests pass; scan has no output.

- [x] **Step 5: Prepare the verified Task 4 change set** for the parent session's approved commit workflow with message `feat(v3): verify trusted evidence policy and registry chains`.

### Task 5: Publish final ports and block obsolete-interface diffusion

**Interfaces:** Produces Roadmap ports: `CapitalGatewayReadPort`, `EvidenceQueryPort`, `AuthorizationQueryPort`, `GrowthKernelPort`, `CapitalGatewayCommandPort`, and `CapabilityVerifier`.

**Implemented boundary (2026-08-01):** Published six runtime-checkable structural ports with explicit Revision 2 domain annotations. `EvidenceQueryPort.active_revision()` uses the closed four-record `ActiveEvidenceRecord` union, and `CapabilityVerifier` requires the Authority-Store current-head witness plus trusted time. Plan 04 前实行 fail-closed source boundary: production `src` `*.py` and `*.pyi` must have zero static `GrowthKernelPort` references, with only the exact top-level Protocol definition and exact top-level list/tuple `__all__` element in `screening/offensive/v3/contracts/ports.py`, plus the exact top-level `.ports` import and exact top-level list/tuple `__all__` element in `screening/offensive/v3/contracts/__init__.py`. There is no downstream typing or runtime exception: identifiers, imports, attributes, aliases, annotations, runtime checks, quoted exact tokens, exact-string reflective access, `.pyi` uses, and contracts/ports star imports all fail repository acceptance. Plan 04 may introduce concrete consumers only after an independently reviewed replacement boundary lands with its strict/frozen DTO and entry-point tests; Task 5 does not pre-authorize that change. Current top-level exports contain no Revision 1 port/decision aliases. The separate obsolete-interface AST scan covers the whole production `src` tree and excludes only `screening/offensive/v3/contracts/revision1.py` and `screening/offensive/v3/contracts/revision1_primitives.py`; tests are fixtures outside that production scan. Contracts/policy imports remain explicit allowlists, and control-document old-name checks remain lexical rather than semantic proof. These ports have no implementation or side effects: no storage, activation, signing, capital authority, Kernel, Gateway, send or executable path exists, and `policy-v2` remains `off`.

Dynamic or fragmented string construction is outside this static proof. Plan 04 must keep default-deny and use new RED-to-GREEN TDD to allow only an exact consumer module and the exact `GrowthKernelPort[KernelInput, NoTradeDecision]` signature; alias, runtime-check, and star-import exceptions remain forbidden.

- [x] **Step 1: Update** `tests/offensive/v3/contracts/test_ports.py` with fakes for every final method and immutable return type.
- [x] **Step 2: Update** `test_import_boundaries.py` to forbid storage/network/pandas/v2 imports from contracts/policy and forbid downstream v3 modules from importing old interface aliases.
- [x] **Step 3: Add repository scan test** that permits old names only in Revision 1 fixture/adapter modules and this historical status documentation.
- [x] **Step 4: Run complete verification**.

```bash
uv run pytest tests/offensive/v3/contracts/ -v
uv run pytest tests/offensive/test_daily_action_readiness.py tests/offensive/test_daily_action_snapshot_security.py -q
git diff --check
```

Expected: all tests pass; policy remains off; no capital/authority file is created.

- [x] **Step 5: Update `AGENTS.md` current implementation boundary** to “Revision 2 contracts/policy/trust/ports complete; no capital authority”, then prepare the scoped change set for the parent session's approved commit workflow.

## Completion Gate

- [x] Every Revision 2 schema has strict validation, canonical serialization, hash, and snapshot tests. The checked-in snapshot matrix (`tests/offensive/v3/contracts/test_revision2_snapshot_matrix.py` + `fixtures/revision2/`) covers all 99 public decision/capital/execution/evidence/trust/policy model schema goldens, strict JSON round-trip and canonical hashes, independently recomputed artifact hashes, protected domain preimages, public enum/alias types and port signatures; runtime discovery only alarms on new, removed, or misclassified public contracts.
- [x] Unknown schema, extra field, float, empty fingerprint, naive time, wrong mode/account/capability/epoch and invalid predecessor fail closed.
- [x] `ShadowDecision` cannot parse or sign as `PortfolioDecisionSeal`.
- [x] `CapitalAuthorizationEnvelope` is the only final entry authorization type and represents one complete target portfolio policy.
- [x] Trust/policy loading performs no activation; no CLI/producer module contains signing material.
- [x] Plan 02–07 can compile exclusively against the final ports without importing obsolete aliases.
