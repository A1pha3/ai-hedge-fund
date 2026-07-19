# Growth Kernel Contracts, Policy, and Trust Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立 v3 的不可变领域契约、规范化序列化、版本化 PolicySnapshot 和只读发行者信任验证，使后续台账、证据、内核与服务共享同一种严格语义。

**Architecture:** 新建无 I/O 的 `v3/contracts` 与 `v3/policy`，使用 strict/frozen Pydantic models 和 canonical JSON；签名验证只依赖只读 trusted registry，CLI 与 producer 不包含私钥或签发方法。所有未知 schema major、额外字段、空 fingerprint 和模式错配均 fail closed。

**Tech Stack:** Python、Pydantic 2、`Decimal`、cryptography Ed25519、pytest。

## Global Constraints

- 本计划只定义契约、验证和只读 policy；不写交易、资本或 evidence 数据库。
- `execution_authorized` 禁止出现在 Snapshot/Signal/Outcome schema。
- 四种执行模式和 shadow/executable 类型永久分离，不能靠布尔字段切换。
- `family_id` 不能替代 `economic_lineage_id`；GLOBAL scope 使用 typed `family_id=None`。
- PolicySnapshot 只能收紧当前运行；放宽配置必须进入新的 authority/risk epoch。
- 私钥、MAC secret、broker credential 不进入仓库、CLI 环境或测试 fixture。

---

## File Structure

- Create `src/screening/offensive/v3/__init__.py`
- Create `src/screening/offensive/v3/contracts/base.py`
- Create `src/screening/offensive/v3/contracts/evidence.py`
- Create `src/screening/offensive/v3/contracts/authorization.py`
- Create `src/screening/offensive/v3/contracts/decision.py`
- Create `src/screening/offensive/v3/contracts/capital.py`
- Create `src/screening/offensive/v3/contracts/ports.py`
- Create `src/screening/offensive/v3/policy/models.py`
- Create `src/screening/offensive/v3/policy/loader.py`
- Create `src/screening/offensive/v3/trust/registry.py`
- Create `config/policies/v3/policy-v1.json`
- Create tests under `tests/offensive/v3/contracts/`

### Task 1: Strict base types and canonical payloads

**Interfaces:** Produces `ExecutionMode`, `EvidenceScope`, `SignalStage`, `Sha256`, `UtcInstant`, `CanonicalModel`, `canonical_json_bytes()` and `content_hash()`。所有 evidence contract 显式携带 `effective_at`、`observed_at`、`available_at`，派生证据的 `available_at` 取全部依赖的最大值。

- [ ] **Step 1: Write failing tests** in `tests/offensive/v3/contracts/test_base.py` proving strict booleans, timezone-aware UTC, forbidden extra fields, normalized decimal strings and order-independent hashes.

```python
def test_canonical_hash_is_stable() -> None:
    left = canonical_json_bytes({"b": Decimal("1.00"), "a": 2})
    right = canonical_json_bytes({"a": 2, "b": Decimal("1")})
    assert left == right == b'{"a":2,"b":"1"}'

def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValidationError):
        UtcInstantAdapter.validate_python(datetime(2026, 7, 19, 16, 0))
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/offensive/v3/contracts/test_base.py -v`

Expected: import fails because `v3.contracts.base` does not exist.

- [ ] **Step 3: Implement the base contract** with `ConfigDict(strict=True, frozen=True, extra="forbid")`, UTC validator, finite `Decimal`, and JSON encoder that sorts keys, rejects NaN/Infinity and renders normalized decimals without exponent drift.

```python
class ExecutionMode(StrEnum):
    RESEARCH_RECONSTRUCTION = "research_reconstruction"
    DAILY_BAR_PROXY = "daily_bar_proxy"
    MANUAL_CONFIRMED = "manual_confirmed"
    BROKER_CONFIRMED = "broker_confirmed"

class CanonicalModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="python", exclude_none=False))

    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()
```

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/offensive/v3/contracts/test_base.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/screening/offensive/v3 tests/offensive/v3/contracts/test_base.py
git commit -m "feat(v3): define strict canonical contract primitives"
```

### Task 2: Evidence, authorization, decision, and capital schemas

**Interfaces:** Consumes Task 1. Produces the six evidence contracts, `CapitalAuthorization` discriminated union, `ShadowDecision`, `DecisionSeal`, `ExecutionPermit`, capital snapshots/events and legal state enums.

- [ ] **Step 1: Write contract tests** in `test_evidence.py`, `test_authorization.py`, `test_decision.py`, and `test_capital.py` for exact keys, typed scope, execution-mode equality, timestamps, permit shrink-only fields and state-transition tables.

```python
@pytest.mark.parametrize("model", [SnapshotEvidence, SignalEvidence, OutcomeEvidence])
def test_producer_evidence_cannot_claim_execution_authority(model) -> None:
    raw = valid_payload(model) | {"execution_authorized": True}
    with pytest.raises(ValidationError, match="extra_forbidden"):
        model.model_validate(raw)

def test_shadow_cannot_parse_as_decision_seal(shadow_payload: dict) -> None:
    with pytest.raises(ValidationError):
        DecisionSeal.model_validate(shadow_payload)
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/offensive/v3/contracts/test_{evidence,authorization,decision,capital}.py -v`

Expected: imports fail.

- [ ] **Step 3: Implement exact models**. `EvidenceEnvelope` contains all §6.2 fields; `EdgeAuthorization` contains evidence Merkle root, Trial/SAP hashes, attempt checkpoint, sample consumption and version; `ExplorationAuthorization` enforces broker mode and 2% max; `DecisionSeal` contains integer quantity, price/cost reserves, authority/risk epoch and active revision.

```python
AuthorizationUnion = Annotated[
    EdgeAuthorization | ExplorationAuthorization,
    Field(discriminator="authorization_kind"),
]

class CapitalAuthorization(RootModel[AuthorizationUnion]):
    pass

class ExecutionPermit(CanonicalModel):
    permit_id: str
    active_seal_id: str
    seal_revision: int
    permitted_quantity: int
    sealed_quantity: int
    capital_version: int
    fencing_epoch: int
    permit_nonce: str
    deadline: UtcInstant

    @model_validator(mode="after")
    def shrink_only(self) -> Self:
        if not 0 <= self.permitted_quantity <= self.sealed_quantity:
            raise ValueError("permit may only shrink sealed quantity")
        return self
```

- [ ] **Step 4: Verify GREEN and schema snapshots**

Run: `uv run pytest tests/offensive/v3/contracts/ -v`

Expected: pass; serialized fixture hashes are stable across two processes.

- [ ] **Step 5: Commit**

```bash
git add src/screening/offensive/v3/contracts tests/offensive/v3/contracts
git commit -m "feat(v3): codify evidence decision and capital schemas"
```

### Task 3: Versioned PolicySnapshot and behavior fingerprint

**Interfaces:** Produces `PolicySnapshot`, `load_policy_snapshot(path)`, `behavior_fingerprint(producer, policy)` and initial off-by-default `config/policies/v3/policy-v1.json`.

- [ ] **Step 1: Write failing tests** in `tests/offensive/v3/contracts/test_policy.py` for the exact drawdown function, 2/5/10% tiers, ADV policy, cost/board/calendar versions, disabled OB/regime sizing/streak sizing and `runtime_mode="off"`.

```python
@pytest.mark.parametrize(
    ("drawdown", "expected"),
    [(Decimal("0.0999"), Decimal("1")), (Decimal("0.10"), Decimal("1")),
     (Decimal("0.125"), Decimal("0.5")), (Decimal("0.1499"), Decimal("0.002")),
     (Decimal("0.15"), Decimal("0"))],
)
def test_drawdown_multiplier_boundaries(drawdown, expected) -> None:
    assert PolicySnapshot.drawdown_multiplier(drawdown) == expected
```

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/offensive/v3/contracts/test_policy.py -v`

Expected: import fails.

- [ ] **Step 3: Implement strict loader**. Reject symlinks/non-regular files, unknown major, duplicate JSON keys, environment-based risk relaxation and missing governance fields. Compute `policy_fingerprint` over the complete canonical payload.

- [ ] **Step 4: Verify GREEN**

Run: `uv run pytest tests/offensive/v3/contracts/test_policy.py -v`

Expected: pass; initial policy remains non-executable.

- [ ] **Step 5: Commit**

```bash
git add src/screening/offensive/v3/policy config/policies/v3 tests/offensive/v3/contracts/test_policy.py
git commit -m "feat(v3): freeze fail-closed policy snapshots"
```

### Task 4: Capability registry and signature verification

**Interfaces:** Produces `Capability`, `TrustedIssuer`, `SignedEnvelope`, `TrustedRegistry.load()`, `CapabilityVerifier.verify()`; never produces `sign()` in CLI-facing modules.

- [ ] **Step 1: Write adversarial tests** in `test_trust_registry.py`: unknown issuer/key, wrong capability/scope/version, expired key, payload mutation, issuer self-claim, shadow issuer signing seal, manual issuer writing broker mode and unknown schema all fail.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/offensive/v3/contracts/test_trust_registry.py -v`

Expected: import fails.

- [ ] **Step 3: Implement read-only Ed25519 verification**. Registry contains public keys and capability scopes only; service-specific signing adapters live outside this package and arrive in Plan 05/07 via injected ports.

```python
class CapabilityVerifier:
    def verify(self, signed: SignedEnvelope, required: Capability) -> VerifiedIssuer:
        issuer = self.registry.require(signed.issuer_id, signed.key_id)
        issuer.require_capability(required, signed.schema_major)
        Ed25519PublicKey.from_public_bytes(issuer.public_key).verify(
            b64decode(signed.signature), signed.payload
        )
        return VerifiedIssuer(issuer_id=issuer.issuer_id, capability=required)
```

- [ ] **Step 4: Verify GREEN and secret scan**

Run: `uv run pytest tests/offensive/v3/contracts/test_trust_registry.py -v`

Run: `rg -n "PRIVATE KEY|broker.*secret|authorizer.*secret" src/screening/offensive/v3 config/policies/v3`

Expected: tests pass; secret scan has no output.

- [ ] **Step 5: Commit**

```bash
git add src/screening/offensive/v3/trust tests/offensive/v3/contracts/test_trust_registry.py
git commit -m "feat(v3): verify issuer capabilities at trust boundary"
```

### Task 5: Ports, import boundaries, and plan-level verification

**Interfaces:** Produces Protocols listed in the roadmap and enforces contracts do not import storage, pandas, network, CLI or v2 modules.

- [ ] **Step 1: Add** `tests/offensive/v3/contracts/test_import_boundaries.py` and `test_ports.py` using AST import checks and small fakes that satisfy each Protocol.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/contracts/test_{ports,import_boundaries}.py -v`.
- [ ] **Step 3: Implement** `contracts/ports.py`; expose only immutable return types and command objects, never raw SQL connections or mutable mappings.
- [ ] **Step 4: Run verification**:

```bash
uv run pytest tests/offensive/v3/contracts/ -v
uv run pytest tests/offensive/test_daily_action_readiness.py tests/offensive/test_daily_action_snapshot_security.py -q
git diff --check
```

Expected: all pass; v2 security regressions unchanged.

- [ ] **Step 5: Update implementation status** in `AGENTS.md` to “v3 contracts/policy/trust verifier implemented; no capital authority”, then commit only relevant files.

```bash
git add AGENTS.md src/screening/offensive/v3 config/policies/v3 tests/offensive/v3/contracts
git commit -m "test(v3): enforce contract and trust boundaries"
```

## Completion Gate

- [ ] All contract JSON schemas and fixture hashes are reviewed and versioned.
- [ ] No model silently coerces strings into bool/int/date/Decimal.
- [ ] No executable type can be constructed from shadow payload without a validation error.
- [ ] No producer/CLI module has a signing primitive or private credential.
- [ ] Policy default is `off`; enabling later requires a new versioned policy file and authority epoch.
