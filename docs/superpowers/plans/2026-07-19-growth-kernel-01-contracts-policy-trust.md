# Growth Kernel Revision 2 Contracts, Policy, and Trust Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在已合并的 Plan 01 Revision 1 基线上完成不兼容的 Revision 2 契约升级，冻结控制面、完整组合授权、资本快照、entry/exit、迁移/broker/DR manifest 和可信时间语义，使后续计划只依赖最终接口。

**Architecture:** `v3/contracts` 与 `v3/policy` 保持无存储、无网络、strict/frozen；canonical payload 使用 domain-separated hash。`TrustBundle` 和 `PolicyActivation` 是签名候选，只有未来 Capital Gateway 的单调 activation 才产生权限。旧 `CapitalAuthorization`/`DecisionSeal` 保留时只能作为显式 legacy adapter 输入，不能继续作为稳定 port 返回类型。

**Tech Stack:** Python、Pydantic 2、`Decimal`、Ed25519/cryptography、pytest。

## Global Constraints

- 当前实现事实：Revision 1 contracts/policy/trust/ports 已合并；本计划只完成 Revision 2 delta，不声称资本、Authorizer、Gateway 或 broker 已实现。
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
- Create `src/screening/offensive/v3/contracts/migration.py`
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

- [ ] **Step 3: Implement minimal primitives** in `contracts/base.py`. Canonical serialization sorts keys, rejects NaN/Infinity/float, normalizes Decimal strings and binds domain plus schema major before SHA-256.
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
  - ExitMandate has no entry authorization field and cannot sell unknown/untradable quantity;
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

**Interfaces:** Evidence envelopes add `provider_published_at`; store-controlled records add `ingested_at`, `commit_sequence`, revision links and active-revision identity. Produces root-verified `TrustBundleVerifier`, candidate `load_policy_snapshot()` and `verify_policy_activation()` without activation side effects.

- [ ] **Step 1: Add failing tests** in `test_evidence.py`, `test_trust_registry.py`, and `test_policy.py` for trusted clock ordering, store-controlled fields forbidden on producer input, root signature, registry epoch/predecessor rollback, revoked/expired issuer, policy predecessor/account/epoch mismatch, duplicate JSON key and symlink/non-regular files.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement verification only**. `TrustedRegistry.load()` becomes a compatibility parser; executable verification requires a valid `TrustBundle` chain and explicit `trusted_at`. `policy-v2.json` remains `runtime_mode="off"` and has no activation authority.
- [ ] **Step 4: Run secret/capability scan**.

```bash
uv run pytest tests/offensive/v3/contracts/test_{evidence,trust_registry,policy}.py -v
rg -n "PRIVATE KEY|broker.*secret|authorizer.*secret|def sign\(" src/screening/offensive/v3 config/policies/v3
```

Expected: tests pass; scan has no output.

- [ ] **Step 5: Commit** with `git commit -m "feat(v3): verify trusted evidence policy and registry chains"`.

### Task 5: Publish final ports and block obsolete-interface diffusion

**Interfaces:** Produces Roadmap ports: `CapitalGatewayReadPort`, `EvidenceQueryPort`, `AuthorizationQueryPort`, `GrowthKernelPort`, `CapitalGatewayCommandPort`, and `CapabilityVerifier`.

- [ ] **Step 1: Update** `tests/offensive/v3/contracts/test_ports.py` with fakes for every final method and immutable return type.
- [ ] **Step 2: Update** `test_import_boundaries.py` to forbid storage/network/pandas/v2 imports from contracts/policy and forbid downstream v3 modules from importing old interface aliases.
- [ ] **Step 3: Add repository scan test** that permits old names only in Revision 1 fixture/adapter modules and this historical status documentation.
- [ ] **Step 4: Run complete verification**.

```bash
uv run pytest tests/offensive/v3/contracts/ -v
uv run pytest tests/offensive/test_daily_action_readiness.py tests/offensive/test_daily_action_snapshot_security.py -q
git diff --check
```

Expected: all tests pass; policy remains off; no capital/authority file is created.

- [ ] **Step 5: Update `AGENTS.md` current implementation boundary** to “Revision 2 contracts/policy/trust/ports complete; no capital authority”, then commit scoped files.

## Completion Gate

- [ ] Every Revision 2 schema and canonical hash has an approved snapshot fixture.
- [ ] Unknown schema, extra field, float, empty fingerprint, naive time, wrong mode/account/capability/epoch and invalid predecessor fail closed.
- [ ] `ShadowDecision` cannot parse or sign as `PortfolioDecisionSeal`.
- [ ] `CapitalAuthorizationEnvelope` is the only final entry authorization type and represents one complete target portfolio policy.
- [ ] Trust/policy loading performs no activation; no CLI/producer module contains signing material.
- [ ] Plan 02–07 can compile exclusively against the final ports without importing obsolete aliases.
