# BTST Regime Forward Paired Shadow Trial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a causally correct, durable, shadow-only forward paired trial that compares BTST `regime_admission_mode=IGNORE` (Champion) with `NORMAL_ONLY` (Challenger) on two isolated `DAILY_BAR_PROXY` capital paths, without creating executable authority or reusing the invalid legacy court as promotion evidence.

**Architecture:** One PIT Evidence Store supplies the shared candidate/regime/market spine; a pure shadow-kernel boundary maps two strictly bound policies into the existing shared decision core; one append-only pair store atomically commits both arm decisions before capital mutation; two isolated `AccountCapitalTruth` ledgers consume those decisions through a shared proxy execution/settlement core; a deterministic replay engine rebuilds current-cost and 2x-slippage paths from genesis; a pure frozen evaluator computes `Challenger - Champion` over the complete market-session NAV path. Formal authorization objects, permits, outbox, broker modules, and activation endpoints remain unreachable.

**Tech Stack:** Python 3.12, Pydantic v2 strict/frozen canonical models, SQLAlchemy + SQLite WAL/FK/immutable triggers, existing v3 Evidence/Governance/Capital/ExitLane primitives, SciPy, Hypothesis, pytest.

## Global Constraints

- **Shadow only.** Every Trial policy must use `RuntimeMode.SHADOW` and `ExecutionMode.DAILY_BAR_PROXY`; no task may activate a `PolicyActivation`, create a `CapitalAuthorizationEnvelope`, issue an `ExecutionPermit`, publish an outbox command, import broker runtime/dispatcher, or call a real endpoint.
- **No legacy headline reuse.** Commit `055c3a0d`, its `+44.9%`, and all legacy journal/court artifacts remain `RESEARCH_RECONSTRUCTION`; they cannot enter this Trial's enrollment, `PRIMARY_PROMOTION`, genesis, or assessment.
- **One semantic delta.** The only allowed arm behavior difference is `ProducerPolicy.btst_regime_admission_mode`: Champion `IGNORE`, Challenger `NORMAL_ONLY`. A second behavioral delta rejects Trial registration before enrollment.
- **Schema honesty.** Adding regime admission is PolicySnapshot schema major 2. Replacing `ShadowDecision.policy_activation_hash` is ShadowDecision schema major 3 / namespace v2. Historical policy/shadow artifacts remain audit-readable; no implicit default upgrades or hash rewriting.
- **Unknown is typed.** A canonical `RegimeObservation(state=UNKNOWN)` is a valid shared fact: Champion may proceed and Challenger blocks. Absence of the canonical observation by cutoff is operational `NO_RUN`, never `UNKNOWN` or `NORMAL`.
- **Pair before capital.** Both arm decisions, including `NoTradeDecision`, commit in one SQLite transaction before either arm reserve/fill/fee mutation. Exact retries converge; same key with different bytes latches a protocol breach.
- **Capital is continuous.** Cash, reserves, integer lots, fees, marks, UnitNAV, drawdown, pending exits, company actions, and corrections carry across sessions. No daily reset, additive realized-P&L NAV, future bar lookup, or tail-position omission is permitted.
- **Execution contract.** T0 after-close decision/reserve, mechanically shrink-only T+1 open entry, complete costs, and T+10 open exit. Missing/suspended/late/one-price-lock observations never invent a fill; unknown exits retain their mandate.
- **Causal provenance.** Decision-derived reserve/trade/fee/correction facts bind `DAILY_BAR_PROXY + SHADOW_DECISION`; valuation facts bind their actual `SnapshotEvidence`. Fingerprints prove identity, not permission.
- **Stress is a replay.** Current-cost and 2x-slippage assessment each start from the sealed genesis archives and replay decisions, cash, risk, fills, exits, and marks. Subtracting a constant from final returns is forbidden.
- **ITT and sign.** Every non-cancelled expected market session is present. The primary paired delta is always `log-growth(Challenger) - log-growth(Champion)`, and equality passes an MEE threshold only where the charter says `>=`.
- **No duplicate truth.** Do not add persisted `PairedDayFact`, `PairedDecisionRecord`, `PairedSessionDisposition`, paired hash chain, or assessment projection. Decisions, evidence, capital, and SessionSpine remain the only durable truth.
- **Test file basenames remain unique.** `tests/offensive/v3/` has no package `__init__.py`; use the exact new filenames named below.
- **Use the repository interpreter.** Run tests with `.venv/bin/python -m pytest ...`; run formatting/lint only after tests are green.
- **Preserve user data.** Never stage or modify `data/paper_trading/journal.jsonl`, `data/paper_trading_backtest/journal.jsonl`, or `data/paper_trading_backtest/portfolio_state.json`.

---

### Task 1: Regime contracts and PolicySnapshot schema major 2

**Files:**
- Create: `src/screening/offensive/v3/contracts/regime.py`
- Modify: `src/screening/offensive/v3/contracts/__init__.py`
- Modify: `src/screening/offensive/v3/policy/models.py`
- Modify: `src/screening/offensive/v3/policy/__init__.py`
- Modify: `src/screening/offensive/v3/policy/loader.py`
- Modify: `config/policies/v3/policy-v1.json`
- Modify: `config/policies/v3/policy-v2.json`
- Create: `scripts/v3_refresh_contract_snapshots.py`
- Create: `tests/offensive/v3/contracts/test_regime_contracts.py`
- Modify: `tests/offensive/v3/contracts/test_policy.py`
- Modify: `tests/offensive/v3/contracts/revision2_snapshot_registry.py`
- Modify: `tests/offensive/v3/contracts/revision2_snapshot_exemplars.py`
- Modify: `tests/offensive/v3/contracts/test_revision2_snapshot_matrix.py`
- Regenerate: `tests/offensive/v3/contracts/fixtures/revision2/*.json`

**Interfaces:**
- `RegimeState = NORMAL | RISK_OFF | CRISIS | UNKNOWN`
- `RegimeObservationReason = CLASSIFIED | MISSING_REQUIRED_INPUT | STALE_REQUIRED_INPUT | UNRECOGNIZED_RAW_STATE | INSUFFICIENT_INPUT`
- `RegimeSourceRevision` and canonical `RegimeObservation`
- `normalize_regime_state(raw_state: str | None, *, reason_if_missing: RegimeObservationReason) -> tuple[RegimeState, RegimeObservationReason]`
- `RegimeAdmissionMode = IGNORE | NORMAL_ONLY`
- Required `ProducerPolicy.btst_regime_admission_mode`
- `SUPPORTED_POLICY_SCHEMA_MAJOR = 2`; schema-major-1 files fail current loading and remain raw audit material only

- [ ] **Step 1: Write RED contract tests** for exact enum values, strict unknown normalization, source-revision canonical ordering/root, timestamp order, missing policy field, schema-major-1 rejection, and `ProducerPolicy.any_enabled()` ignoring the enum while still detecting enabled producers.

```python
def test_unrecognized_raw_regime_normalizes_to_unknown() -> None:
    state, reason = normalize_regime_state(
        "euphoria",
        reason_if_missing=RegimeObservationReason.MISSING_REQUIRED_INPUT,
    )
    assert state is RegimeState.UNKNOWN
    assert reason is RegimeObservationReason.UNRECOGNIZED_RAW_STATE


def test_off_policy_enum_does_not_count_as_enabled() -> None:
    policy = ProducerPolicy(
        btst_enabled=False,
        oversold_bounce_enabled=False,
        btst_regime_admission_mode=RegimeAdmissionMode.IGNORE,
        regime_sizing_enabled=False,
        streak_sizing_enabled=False,
        trigger_strength_sizing_enabled=False,
        composite_sizing_enabled=False,
    )
    assert not policy.any_enabled()
```

- [ ] **Step 2: Verify RED.**

Run:

```bash
.venv/bin/python -m pytest tests/offensive/v3/contracts/test_regime_contracts.py tests/offensive/v3/contracts/test_policy.py -q
```

Expected: collection/import fails because the regime types and required policy field do not exist.

- [ ] **Step 3: Implement strict contracts and schema migration.** `RegimeObservation` recomputes `source_evidence_root` from sorted `RegimeSourceRevision.artifact_hash` values, requires `CLASSIFIED` only for canonical non-unknown states, and rejects mutable/unordered/duplicate source bindings. `ProducerPolicy.any_enabled()` explicitly checks the six boolean switches rather than applying `any()` to `model_dump()`.

```python
class RegimeAdmissionMode(StrEnum):
    IGNORE = "IGNORE"
    NORMAL_ONLY = "NORMAL_ONLY"


class ProducerPolicy(CanonicalModel):
    btst_enabled: bool
    oversold_bounce_enabled: bool
    btst_regime_admission_mode: RegimeAdmissionMode
    regime_sizing_enabled: bool
    streak_sizing_enabled: bool
    trigger_strength_sizing_enabled: bool
    composite_sizing_enabled: bool

    def any_enabled(self) -> bool:
        return any((
            self.btst_enabled,
            self.oversold_bounce_enabled,
            self.regime_sizing_enabled,
            self.streak_sizing_enabled,
            self.trigger_strength_sizing_enabled,
            self.composite_sizing_enabled,
        ))
```

- [ ] **Step 4: Update both checked-in policy candidates** to schema major 2 with explicit `"btst_regime_admission_mode":"IGNORE"`; do not change runtime mode, caps, or activation state. Add a deterministic snapshot tool with `--check` and `--accept-contract-change`; it must derive every fixture from the checked-in registries/exemplars, refuse an unclean fixture diff in `--check`, and never touch keys/private material.

- [ ] **Step 5: Register the new public models/enums and regenerate literal fixtures.** Review the diff for exact fields, hashes, cardinalities, and protected policy/behavior preimages before accepting it.

Run:

```bash
.venv/bin/python scripts/v3_refresh_contract_snapshots.py --accept-contract-change
.venv/bin/python scripts/v3_refresh_contract_snapshots.py --check
.venv/bin/python -m pytest tests/offensive/v3/contracts/test_regime_contracts.py tests/offensive/v3/contracts/test_policy.py tests/offensive/v3/contracts/test_revision2_snapshot_matrix.py -q
```

Expected: all pass; both config policies load only as schema major 2; snapshot `--check` emits no diff.

- [ ] **Step 6: Commit.**

```bash
git add src/screening/offensive/v3/contracts/regime.py src/screening/offensive/v3/contracts/__init__.py src/screening/offensive/v3/policy config/policies/v3 scripts/v3_refresh_contract_snapshots.py tests/offensive/v3/contracts
git commit -m "feat(v3): freeze regime admission policy contracts"
```

---

### Task 2: Seal and validate the exact Trial/SAP/Stage policy bundle

**Files:**
- Modify: `src/screening/offensive/v3/governance/repository.py`
- Create: `src/screening/offensive/v3/governance/regime_trial.py`
- Modify: `src/screening/offensive/v3/governance/__init__.py`
- Modify: `tests/offensive/v3/governance/test_trials.py`
- Create: `tests/offensive/v3/governance/test_regime_trial_governance.py`

**Interfaces:**
- `target_policy_registration_hash(policy: PolicySnapshot) -> str`
- `GovernanceArtifactVerifierPort.verify(signed, required, current_head, trusted_at) -> VerifiedIssuer`
- Typed `TrialSealRequest` carrying signed Trial/SAP/baseline-activation envelopes, their exact payloads, matching baseline `PolicySnapshot`, and target `PolicySnapshot` rather than unvalidated JSON strings
- `GovernanceRepository.seal_stage(signed_stage, stage_payload, *, trusted_at) -> str`
- `GovernanceRepository.regime_trial_bundle(trial_id: str) -> SealedRegimeTrialBundle`
- Pure `validate_regime_trial_bundle(bundle, *, trusted_at) -> ValidatedRegimeTrialBundle`
- `policy_semantic_delta_paths(baseline, target) -> tuple[str, ...]`

- [ ] **Step 1: Write RED governance tests** proving capability/trust verification of signed Trial/SAP/baseline activation/Stage payloads, atomic attempt/Trial/SAP/target registration, strict baseline activation→snapshot hash binding, target registration hash recomputation, Stage hash/date binding, `DAILY_BAR_PROXY + SHADOW`, BTST family, and exactly one semantic delta.

```python
def test_regime_trial_allows_only_the_admission_mode_delta(bundle) -> None:
    assert policy_semantic_delta_paths(
        bundle.baseline_policy, bundle.target_policy
    ) == ("producers.btst_regime_admission_mode",)
    checked = validate_regime_trial_bundle(bundle, trusted_at=ENROLLMENT_START)
    assert checked.champion_policy.producers.btst_regime_admission_mode is RegimeAdmissionMode.IGNORE
    assert checked.challenger_policy.producers.btst_regime_admission_mode is RegimeAdmissionMode.NORMAL_ONLY


def test_second_behavior_delta_rejects_trial(bundle) -> None:
    changed = bundle.model_copy(update={
        "target_policy": bundle.target_policy.model_copy(update={
            "capital": bundle.target_policy.capital.model_copy(update={
                "daily_entry_gross_cap": Decimal("0.01")
            })
        })
    })
    with pytest.raises(RegimeTrialGovernanceError, match="policy_delta_mismatch"):
        validate_regime_trial_bundle(changed, trusted_at=ENROLLMENT_START)
```

- [ ] **Step 2: Verify RED.**

```bash
.venv/bin/python -m pytest tests/offensive/v3/governance/test_trials.py tests/offensive/v3/governance/test_regime_trial_governance.py -q
```

Expected: new typed seal/bundle APIs are missing.

- [ ] **Step 3: Extend the GovernanceRepository schema** with immutable signed-envelope/payload columns for Trial, SAP, baseline activation, baseline/target policies, and a `sealed_stages` table whose `trial_id` is an FK to `sealed_trials`. Verify signatures/capability/current trust head before opening the database transaction; hash the exact verified payloads inside it. Strictly decode stored JSON back to exact Pydantic types on every read. A paired Trial uses the literal role `paired` and rejects the legacy one-row-per-arm interpretation because one TrialManifest already binds both policies. Existing `sealed_trial()`/`target_policy()` dict reads may remain for audit callers, but the official runner consumes only `regime_trial_bundle()`.

```python
def target_policy_registration_hash(policy: PolicySnapshot) -> str:
    return domain_hash(
        "ai-hedge-fund.v3.governance.target-policy-registration.v1",
        policy.schema_major,
        {
            "policy_snapshot_hash": policy.content_hash(),
            "policy_fingerprint": policy.policy_fingerprint,
            "executable": False,
        },
    )
```

- [ ] **Step 4: Implement semantic-delta validation.** Compare behavior projections after removing only policy identity/epoch provenance (`policy_id`, `policy_version`, `policy_epoch`, `authority_epoch`, `risk_epoch`). All capital/risk/ADV/execution/version/evidence fields and every producer switch remain semantic. Require baseline `IGNORE`, target `NORMAL_ONLY`, both BTST enabled, OB disabled, all regime/streak/trigger/composite sizing switches disabled, and identical execution/cost versions.

- [ ] **Step 5: Add immutability and rollback tests** for duplicate/conflicting Stage, target registration conflicts, bad baseline hash, wrong mode, expired enrollment, and a failure after attempt insertion. Confirm every failure leaves no partial attempt/trial/stage row.

Run:

```bash
.venv/bin/python -m pytest tests/offensive/v3/governance/test_trials.py tests/offensive/v3/governance/test_regime_trial_governance.py -q
```

Expected: all pass; no activation/envelope table is touched.

- [ ] **Step 6: Commit.**

```bash
git add src/screening/offensive/v3/governance tests/offensive/v3/governance
git commit -m "feat(v3): seal exact paired regime trial bundles"
```

---

### Task 3: Publish and read canonical RegimeObservation through SnapshotEvidence

**Files:**
- Create: `src/screening/offensive/v3/evidence/regime.py`
- Modify: `src/screening/offensive/v3/evidence/__init__.py`
- Create: `tests/offensive/v3/evidence/test_regime_observation_store.py`
- Modify: `tests/offensive/v3/evidence/test_evidence_repository.py`

**Interfaces:**
- `RegimeSnapshotSignerPort.sign_snapshot(snapshot: SnapshotEvidence, payload: bytes) -> SignedEnvelope`
- `RegimeObservationPublisher.publish(observation, snapshot, signer) -> EvidenceRecord[SnapshotEvidence]`
- `RegimeObservationReader.active(evidence_id, cutoff) -> ActiveRegimeObservation`
- `ActiveRegimeObservation(record, observation, observation_hash)`

- [ ] **Step 1: Write RED tests** for NORMAL and UNKNOWN publication, blob-before-envelope durability, strict cutoff reads, revision activation, content-hash mismatch, wrong evidence kind/scope, and operational failure before publication.

```python
def test_unknown_is_a_committed_policy_fact_not_a_no_run(rig) -> None:
    observation = rig.observation(
        state=RegimeState.UNKNOWN,
        reason=RegimeObservationReason.MISSING_REQUIRED_INPUT,
        raw_state=None,
    )
    record = rig.publisher.publish(observation, rig.snapshot(observation), rig.signer)
    loaded = rig.reader.active(record.evidence.evidence_id, rig.cutoff)
    assert loaded.observation.state is RegimeState.UNKNOWN
    assert loaded.record.commit_sequence == record.commit_sequence
```

- [ ] **Step 2: Verify RED.**

```bash
.venv/bin/python -m pytest tests/offensive/v3/evidence/test_regime_observation_store.py tests/offensive/v3/evidence/test_evidence_repository.py -q
```

Expected: regime publisher/reader imports fail.

- [ ] **Step 3: Implement publication without a fifth evidence kind.** Serialize `RegimeObservation` canonically, call `BlobStore.put_durable()` for that payload, require the resulting digest to equal `SnapshotEvidence.payload_content_hash`, sign the SnapshotEvidence JSON, and then call `EvidenceRepository.publish()`. A fault after the first blob write may leave an orphan blob; it may not leave an envelope pointing to a missing blob.

```python
observation_bytes = observation.canonical_bytes()
observation_hash = self._blobs.put_durable(observation_bytes)
if snapshot.payload_content_hash != observation_hash:
    raise RegimeEvidenceError("observation_hash_mismatch", "snapshot binds other bytes")
snapshot_bytes = snapshot.model_dump_json().encode("utf-8")
return self._repository.publish(
    signer.sign_snapshot(snapshot, snapshot_bytes), snapshot_bytes
)
```

- [ ] **Step 4: Implement PIT read validation.** `active()` must use the Evidence Store's active revision strictly before cutoff, fetch the observation blob by its bound hash, strict-decode `RegimeObservation`, verify timestamps/source root/session, and return both hashes. It must never read `regime_history.json`, current caches, or call `detect_market_state()` during historical assessment.

- [ ] **Step 5: Verify deterministic revision behavior and commit.** A later correction is visible only after activation and only to later cutoffs; it never overwrites the earlier record.

```bash
.venv/bin/python -m pytest tests/offensive/v3/evidence/test_regime_observation_store.py tests/offensive/v3/evidence/test_evidence_repository.py -q
git add src/screening/offensive/v3/evidence tests/offensive/v3/evidence
git commit -m "feat(v3): persist causal regime observations"
```

---

### Task 4: ShadowDecision schema major 3 and policy provenance cutover

**Files:**
- Modify: `src/screening/offensive/v3/contracts/decision.py`
- Create: `src/screening/offensive/v3/contracts/trial.py`
- Create: `src/screening/offensive/v3/contracts/compatibility.py`
- Modify: `src/screening/offensive/v3/contracts/__init__.py`
- Modify: `src/screening/offensive/v3/orchestration/daily_action_flow.py`
- Modify: `src/screening/offensive/v3/reporting/shadow_store.py`
- Create: `tests/offensive/v3/contracts/test_shadow_decision_v3.py`
- Modify: `tests/offensive/v3/contracts/test_decision_checkpoint2_shadow.py`
- Modify: `tests/offensive/v3/orchestration/test_daily_action_flow.py`
- Modify: `tests/offensive/v3/reporting/test_shadow_store.py`
- Modify: `tests/offensive/v3/contracts/revision2_snapshot_registry.py`
- Modify: `tests/offensive/v3/contracts/revision2_snapshot_exemplars.py`
- Modify: `tests/offensive/v3/contracts/test_revision2_snapshot_matrix.py`
- Regenerate: `tests/offensive/v3/contracts/fixtures/revision2/*.json`

**Interfaces:**
- Single shared `TrialArm = CHAMPION | CHALLENGER` owned by `contracts/trial.py`
- `ShadowPolicySourceKind = BASELINE_POLICY_ACTIVATION | TARGET_POLICY_REGISTRATION`
- Discriminated `BaselineShadowPolicyBinding | TargetShadowPolicyBinding` exposed as `ShadowPolicyBinding`
- Current `ShadowDecision`: `schema_major: Literal[3]`, namespace `growth-kernel.shadow.v2`, hash domain v2, `shadow_policy_binding` replacing `policy_activation_hash`
- `ShadowOrderLine.target_exit_session`
- `LegacyShadowDecisionV2` and `read_shadow_decision_json(payload, *, official_trial)` in compatibility module
- Official writers accept only current `ShadowDecision`; compatibility is read-only

- [ ] **Step 1: Write RED schema tests** for the two exact binding variants, arm/source mismatch, policy epoch/hash mismatch, target exit date, rejection of `policy_activation_hash`, literal `execution_authority="NONE"`, and official rejection of legacy JSON.

```python
def test_current_shadow_decision_cannot_claim_activation_hash(valid_payload) -> None:
    valid_payload["policy_activation_hash"] = "a" * 64
    with pytest.raises(ValidationError):
        ShadowDecision.model_validate(valid_payload, strict=True)


def test_legacy_shadow_is_read_only(legacy_json: bytes) -> None:
    parsed = read_shadow_decision_json(legacy_json, official_trial=False)
    assert isinstance(parsed, LegacyShadowDecisionV2)
    with pytest.raises(ShadowCompatibilityError, match="legacy_shadow_not_official"):
        read_shadow_decision_json(legacy_json, official_trial=True)
```

- [ ] **Step 2: Verify RED.**

```bash
.venv/bin/python -m pytest tests/offensive/v3/contracts/test_shadow_decision_v3.py tests/offensive/v3/contracts/test_decision_checkpoint2_shadow.py -q
```

Expected: current contract still exposes schema-v2 activation provenance.

- [ ] **Step 3: Move the old shape unchanged into compatibility** so historical bytes/hash remain readable, then make the current exported name schema major 3. Do not provide an upgrader: callers must supply a real Trial-bound policy binding.

```python
ShadowPolicyBinding = Annotated[
    BaselineShadowPolicyBinding | TargetShadowPolicyBinding,
    Field(discriminator="source_kind"),
]


class ShadowDecision(CanonicalModel):
    HASH_DOMAIN = "ai-hedge-fund.v3.decision.shadow-decision.v2"
    artifact_kind: Literal[ArtifactKind.SHADOW_DECISION]
    artifact_namespace: Literal["growth-kernel.shadow.v2"]
    schema_major: Literal[3]
    shadow_policy_binding: ShadowPolicyBinding
    policy_epoch: PositiveExactInt
    execution_authority: Literal["NONE"]
```

- [ ] **Step 4: Migrate current Plan 05 observation output** by requiring an injected `ShadowPolicyBinding` and emitting schema major 3. This flow may continue to be a compatibility observation path, but it is not accepted by the official paired runner. `InMemoryShadowStore` reads legacy/current for reports but refuses to publish legacy.

- [ ] **Step 5: Update shadow issuer capability fixtures** to namespace v2/schema 3, register the new public models/alias, regenerate snapshots, and run the affected orchestration/reporting tests.

```bash
.venv/bin/python scripts/v3_refresh_contract_snapshots.py --accept-contract-change
.venv/bin/python scripts/v3_refresh_contract_snapshots.py --check
.venv/bin/python -m pytest tests/offensive/v3/contracts/test_shadow_decision_v3.py tests/offensive/v3/contracts/test_decision_checkpoint2_shadow.py tests/offensive/v3/orchestration/test_daily_action_flow.py tests/offensive/v3/reporting/test_shadow_store.py tests/offensive/v3/contracts/test_revision2_snapshot_matrix.py -q
```

Expected: all pass; new writes contain no `policy_activation_hash`; old bytes remain audit-readable only.

- [ ] **Step 6: Commit.**

```bash
git add src/screening/offensive/v3/contracts/decision.py src/screening/offensive/v3/contracts/trial.py src/screening/offensive/v3/contracts/compatibility.py src/screening/offensive/v3/contracts/__init__.py src/screening/offensive/v3/orchestration/daily_action_flow.py src/screening/offensive/v3/reporting/shadow_store.py tests/offensive/v3/contracts/test_shadow_decision_v3.py tests/offensive/v3/contracts/test_decision_checkpoint2_shadow.py tests/offensive/v3/contracts/revision2_snapshot_registry.py tests/offensive/v3/contracts/revision2_snapshot_exemplars.py tests/offensive/v3/contracts/test_revision2_snapshot_matrix.py tests/offensive/v3/contracts/fixtures/revision2 tests/offensive/v3/orchestration/test_daily_action_flow.py tests/offensive/v3/reporting/test_shadow_store.py
git commit -m "feat(v3): separate shadow policy provenance from activation"
```

---

### Task 5: Authority-free ShadowKernelInput and one shared decision core

**Files:**
- Modify: `src/screening/offensive/v3/kernel/models.py`
- Modify: `src/screening/offensive/v3/kernel/admission.py`
- Create: `src/screening/offensive/v3/kernel/core.py`
- Modify: `src/screening/offensive/v3/kernel/decide.py`
- Modify: `src/screening/offensive/v3/kernel/__init__.py`
- Modify: `src/screening/offensive/v3/orchestration/daily_action_flow.py`
- Modify: `tests/offensive/v3/kernel/test_admission.py`
- Modify: `tests/offensive/v3/kernel/test_decide.py`
- Create: `tests/offensive/v3/kernel/test_shadow_kernel.py`
- Modify: `tests/offensive/v3/kernel/test_import_boundary.py`
- Modify: `tests/offensive/v3/contracts/test_ports.py`
- Modify: `tests/offensive/v3/orchestration/test_daily_action_flow.py`

**Interfaces:**
- Consumes the single `contracts.trial.TrialArm`
- `CandidateEvidenceBinding`, `ShadowSharedInput`, `ShadowCapitalCheckpoint`, and exact `ShadowKernelInput`
- `DecisionConstraints`, `CoreNoTrade`, and internal `CorePortfolioDecision`
- `GrowthKernel.decide(KernelInput, *, trusted_at)` remains executable-only but now verifies an explicit matching `PolicySnapshot`
- `GrowthKernel.decide_shadow(ShadowKernelInput) -> ShadowDecision | NoTradeDecision`
- `BlockReason.REGIME_ADMISSION_BLOCKED`
- `economic_shadow_projection(decision: ShadowDecision | NoTradeDecision) -> bytes`

- [ ] **Step 1: Write RED shape and authority-isolation tests.** Strict construction must reject `PolicyActivation`, `CapitalAuthorizationEnvelope`, permit nonce, broker account, unknown extra fields, wrong mode, mismatched Trial/SAP/Stage/policy hashes, and a capital checkpoint whose embedded snapshot hash differs.

```python
def test_shadow_input_rejects_authority_objects(valid_input_dict, envelope) -> None:
    valid_input_dict["envelope"] = envelope
    with pytest.raises(ValidationError):
        ShadowKernelInput.model_validate(valid_input_dict, strict=True)


def test_shadow_kernel_has_no_external_clock_argument(kernel, shadow_input) -> None:
    result = kernel.decide_shadow(shadow_input)
    assert result.counterfactual_key.signal_session == shadow_input.shared.signal_session
```

- [ ] **Step 2: Write RED policy semantics tests.** With identical capital and NORMAL, both arm economic projections are byte-identical. With `RISK_OFF`, `CRISIS`, or canonical `UNKNOWN`, Champion follows the ungated path while Challenger returns `REGIME_ADMISSION_BLOCKED`. Changing regime must not alter Champion rank, strength, target, or size.

```python
@pytest.mark.parametrize("state", [RegimeState.RISK_OFF, RegimeState.CRISIS, RegimeState.UNKNOWN])
def test_normal_only_blocks_but_ignore_continues(kernel, paired_inputs, state) -> None:
    champion, challenger = paired_inputs.with_regime(state)
    assert isinstance(kernel.decide_shadow(champion), ShadowDecision)
    blocked = kernel.decide_shadow(challenger)
    assert isinstance(blocked, NoTradeDecision)
    assert blocked.reason is BlockReason.REGIME_ADMISSION_BLOCKED
```

- [ ] **Step 3: Verify RED.**

```bash
.venv/bin/python -m pytest tests/offensive/v3/kernel/test_shadow_kernel.py tests/offensive/v3/kernel/test_admission.py tests/offensive/v3/kernel/test_decide.py -q
```

Expected: shadow input/core APIs are missing.

- [ ] **Step 4: Extract the shared pure core.** `decide_core()` consumes only normalized candidates, integer `DecisionConstraints`, risk state, prices, industries, deadlines, and frozen trusted time. Executable admission maps PolicySnapshot + activation + envelope/grants into constraints; shadow admission maps Trial-bound PolicySnapshot into constraints without manufacturing a grant. Both call the same risk-once, rank, capacity, lot, reserve, and line builders.

```python
@dataclass(frozen=True)
class DecisionConstraints:
    lineage_gross_cap_cents: Mapping[str, int]
    sizing_config: SizingConfig
    portfolio_gross_cap_cents: int
    policy_epoch: int


def decide_core(
    *, candidates: tuple[RawCandidate, ...], constraints: DecisionConstraints,
    capital: CapitalRiskSnapshot, prices: Mapping[str, int],
    industries: Mapping[str, str], deadlines: DeadlineContract,
    trusted_at: datetime,
) -> CorePortfolioDecision | CoreNoTrade:
    if trusted_at > deadlines.seal_creation_deadline:
        return CoreNoTrade(reason=BlockReason.DEADLINE_MISSED)
    risk = evaluate_portfolio_risk(capital=capital, trusted_at=trusted_at)
    if risk.block_reason is not None:
        return CoreNoTrade(reason=risk.block_reason)
    adjusted = apply_portfolio_risk_once(
        unscaled_lineage_targets=constraints.lineage_gross_cap_cents,
        unscaled_portfolio_gross_cap_cents=(
            constraints.portfolio_gross_cap_cents
        ),
        risk_decision=risk,
    )
    sized = size_portfolio(
        ranked_candidates=rank_candidates(candidates),
        adjusted_target_gross_by_lineage=dict(
            adjusted.adjusted_lineage_gross_cents
        ),
        price_micros_by_candidate=prices,
        industry_by_candidate=industries,
        available_cash_cents=capital.available_cash_cents,
        config=constraints.sizing_config,
        adjusted_portfolio_gross_cap_cents=(
            adjusted.adjusted_portfolio_gross_cap_cents
        ),
        existing_portfolio_gross_cents=capital.total_gross_exposure_cents,
    )
    lines = decision_lines(sized)
    if not any(line.status == "ENTRY_PLANNED" for line in lines):
        return CoreNoTrade(reason=BlockReason.CAPACITY_EXHAUSTED)
    return CorePortfolioDecision(
        lines=lines,
        portfolio_gross_cap_cents=(
            adjusted.adjusted_portfolio_gross_cap_cents
        ),
        total_reserved_worst_case_cents=sum(
            line.worst_case_reserve_cents
            for line in lines
            if line.status == "ENTRY_PLANNED"
        ),
    )
```

The implementation must additionally validate `deadlines.ordering_valid()` before this sequence and raise `KernelError("deadline_order_invalid", ...)` on a malformed contract, matching the existing executable behavior.

- [ ] **Step 5: Add the explicit PolicySnapshot to executable KernelInput.** Verify `policy_activation.policy_snapshot_hash == policy_snapshot.content_hash()`. Clamp executable caps by the minimum of PolicySnapshot, envelope/grant, and the kernel's frozen sizing configuration. Clamp shadow caps by PolicySnapshot and the same frozen sizing configuration. Do not let producer target values raise a cap.

- [ ] **Step 6: Implement shadow projection.** The frozen trusted time lives inside `ShadowSharedInput`, so both arm calls consume exactly one observation. Build deterministic IDs from Trial/session/cycle/candidate (not call order), use the current ShadowPolicyBinding and Stage binding, derive T+1/T+10 target dates from the frozen calendar input, and set `execution_authority="NONE"`.

- [ ] **Step 7: Add deterministic/property tests.** Cover candidate permutation, repeated process serialization, risk applied once, NORMAL economic projection equality, regime-only admission, and malformed behavior fingerprint/evidence binding. The kernel import graph must contain no storage, environment, v2, network, gateway, execution, or broker modules.

Run:

```bash
.venv/bin/python -m pytest tests/offensive/v3/kernel -q
```

Expected: all kernel tests pass; existing executable decision economics remain unchanged for equivalent schema-major-2 policy inputs.

- [ ] **Step 8: Commit.**

```bash
git add src/screening/offensive/v3/kernel src/screening/offensive/v3/orchestration/daily_action_flow.py tests/offensive/v3/kernel tests/offensive/v3/contracts/test_ports.py tests/offensive/v3/orchestration/test_daily_action_flow.py
git commit -m "feat(v3): share decision economics with shadow trials"
```

---

### Task 6: Seal equal genesis, atomically store arm decisions, and fence the writer

**Files:**
- Create: `src/screening/offensive/v3/orchestration/genesis.py`
- Create: `src/screening/offensive/v3/orchestration/trial_store.py`
- Modify: `src/screening/offensive/v3/orchestration/__init__.py`
- Modify: `src/screening/offensive/v3/capital/conservation.py`
- Modify: `src/screening/offensive/v3/gateway/exits.py`
- Create: `tests/offensive/v3/orchestration/test_trial_genesis_archive.py`
- Create: `tests/offensive/v3/orchestration/test_trial_arm_store.py`

**Interfaces:**
- `TrialArmGenesisSource(capital_repository, exit_lane, proxy_state_reader)`
- `normalized_trial_arm_state(source) -> NormalizedTrialArmState` excluding only arm/portfolio identity while retaining all cash, units, positions, lots, reserves, ExitMandates/attempts/leases, receivables/payables, risk state, watermark, stream/capital versions, and unresolved proxy phases
- `TrialGenesisArchive.seal(trial_id, champion_source, challenger_source) -> TrialGenesisManifest`
- Consumes the single `contracts.trial.TrialArm`; the store does not define a second enum
- `TrialArmDecisionRecord(trial_id, signal_session, decision_cycle_id, arm, shared_input_hash, arm_policy_fingerprint, arm_capital_checkpoint_hash, regime_observation_hash, decision, created_at, artifact_hash)` wrapping `ShadowDecision | NoTradeDecision`
- `TrialArmDecisionStore.register_trial(bundle, genesis_manifest)`
- `TrialArmDecisionStore.commit_pair(champion, challenger) -> PairCommitReceipt`
- `claim_writer()`, `renew_writer()`, `require_writer()`, `release_writer()` with monotone fencing epoch

- [ ] **Step 1: Write RED genesis tests.** Two different portfolio IDs with identical normalized economics seal successfully; any cash/unit/position/reserve/pending-exit/risk/watermark/version mismatch rejects before enrollment. Captured SQLite backups and manifests are content-addressed, immutable, and restorable.

```python
def test_genesis_rejects_hidden_pending_exit_difference(arm_repositories, archive) -> None:
    champion, challenger = arm_repositories
    seed_pending_exit(challenger)
    with pytest.raises(TrialGenesisError, match="genesis_economic_state_mismatch"):
        archive.seal("trial-1", champion, challenger)
```

- [ ] **Step 2: Write RED decision-store tests** for FK registration, two-row atomicity, exact replay idempotence, same-key/different-content conflict, NoTrade persistence, partial-row tamper detection, two-process race, expired lease takeover, stale fencing token, and zero capital mutation before a successful pair commit.

```python
def test_commit_pair_is_atomic_and_conflicting_replay_is_rejected(store, pair) -> None:
    receipt = store.commit_pair(*pair)
    assert {row.arm for row in store.pair(receipt.key)} == {
        TrialArm.CHAMPION, TrialArm.CHALLENGER
    }
    assert store.commit_pair(*pair) == receipt
    with pytest.raises(TrialStoreError, match="arm_decision_conflict"):
        store.commit_pair(pair[0], mutate_decision(pair[1]))
```

- [ ] **Step 3: Verify RED.**

```bash
.venv/bin/python -m pytest tests/offensive/v3/orchestration/test_trial_genesis_archive.py tests/offensive/v3/orchestration/test_trial_arm_store.py -q
```

Expected: archive/store modules do not exist.

- [ ] **Step 4: Implement immutable genesis archives.** Call `backup_consistent()` for each capital ledger and an immutable SQLite backup/export for each ExitLane/proxy-state store before enrollment, fsync/rename them under a content-addressed Trial directory, recompute their roots, and bind all manifests plus one equal normalized full-state hash. Sealing is exact-idempotent; an existing trial with different bytes conflicts. A hidden pending exit, live lease, or unresolved proxy phase must therefore change the hash.

- [ ] **Step 5: Implement the SQLite/WAL store.** Use `trial_registrations`, `trial_arm_decisions`, `trial_writer_state`, and `trial_writer_leases`; decision rows have an FK to the registration, the exact unique key `(trial_id, signal_session, decision_cycle_id, arm)`, and UPDATE/DELETE triggers. `commit_pair()` opens `BEGIN IMMEDIATE`, validates shared input/regime/session/cycle and distinct arm/policy/capital bindings, inserts both rows, or inserts neither.

```python
with self._engine.connect() as conn:
    conn.exec_driver_sql("BEGIN IMMEDIATE")
    try:
        self._validate_pair(champion, challenger)
        self._insert_or_verify_exact(conn, champion)
        self._insert_or_verify_exact(conn, challenger)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
```

- [ ] **Step 6: Implement a fenced single-writer lease.** Every new owner increments the trial fencing epoch; renewals by the same live owner retain it; stale tokens fail before pair/capital lifecycle mutation. Lease tables may update, but registration/decision/genesis rows remain immutable.

- [ ] **Step 7: Verify concurrency and restore.** Spawn two local processes against one SQLite file; exactly one conflicting pair or writer claim wins. Restore both archives to fresh paths and prove their normalized genesis hash remains equal.

```bash
.venv/bin/python -m pytest tests/offensive/v3/orchestration/test_trial_genesis_archive.py tests/offensive/v3/orchestration/test_trial_arm_store.py -q
```

Expected: all pass; the store contains no NAV, return, bar, or duplicated evidence payload.

- [ ] **Step 8: Commit.**

```bash
git add src/screening/offensive/v3/orchestration src/screening/offensive/v3/capital/conservation.py src/screening/offensive/v3/gateway/exits.py tests/offensive/v3/orchestration
git commit -m "feat(v3): seal paired genesis and arm decisions"
```

---

### Task 7: Add causal capital-source bindings and atomic multi-line reserves

**Files:**
- Create: `src/screening/offensive/v3/capital/provenance.py`
- Modify: `src/screening/offensive/v3/capital/reserves.py`
- Modify: `src/screening/offensive/v3/capital/fills.py`
- Modify: `src/screening/offensive/v3/capital/nav.py`
- Modify: `src/screening/offensive/v3/capital/repository.py`
- Modify: `src/screening/offensive/v3/capital/__init__.py`
- Modify: `src/screening/offensive/v3/storage/schema.py`
- Create: `src/screening/offensive/v3/storage/migrations/versions/0006_capital_source_binding.py`
- Create: `tests/offensive/v3/capital/test_shadow_source_provenance.py`
- Modify: `tests/offensive/v3/capital/test_fills_and_conservation.py`
- Modify: `tests/offensive/v3/capital/test_schema.py`

**Interfaces:**
- `CapitalSourceBinding(mode, artifact_kind, artifact_id, artifact_hash)`
- Optional compatibility field `source_binding` on reserve/fill/fee/valuation/restatement requests; official shadow adapters require it
- Persisted `CapitalCommandPayload.source_binding`
- Persisted reserve `source_binding_json`
- `CapitalRepository.reserve_entries_atomic(requests: tuple[ReserveEntryRequest, ...]) -> CapitalRiskSnapshot`

- [ ] **Step 1: Write RED provenance tests.** A decision-derived proxy reserve/fill/fee must carry mode `DAILY_BAR_PROXY`, kind `SHADOW_DECISION`, and the exact current decision ID/hash; a valuation must carry kind `SNAPSHOT`. Wrong ledger mode, wrong artifact hash, missing shadow binding, or a source-ID collision fails without capital/version movement.

```python
def test_shadow_fill_persists_decision_source_binding(repository, request) -> None:
    receipt, _ = repository.record_fill_revision(request)
    event = repository.economic_event(receipt.event_id)
    assert event.payload.source_binding == CapitalSourceBinding(
        mode=ExecutionMode.DAILY_BAR_PROXY,
        artifact_kind=ArtifactKind.SHADOW_DECISION,
        artifact_id=request.source_binding.artifact_id,
        artifact_hash=request.source_binding.artifact_hash,
    )
```

- [ ] **Step 2: Write RED batch-reserve tests.** Multiple lines reserve in one capital transaction; insufficient cash or one conflicting source rolls back all lines and versions; exact batch replay is quiet; input order canonicalizes by `source_id`.

- [ ] **Step 3: Verify RED.**

```bash
.venv/bin/python -m pytest tests/offensive/v3/capital/test_shadow_source_provenance.py tests/offensive/v3/capital/test_fills_and_conservation.py tests/offensive/v3/capital/test_schema.py -q
```

Expected: source binding and batch API are missing.

- [ ] **Step 4: Add migration 0006 and metadata changes.** Store reserve source JSON explicitly; economic events already persist canonical payload JSON, so add the field to `CapitalCommandPayload` rather than a second provenance table. Migration upgrade/downgrade must preserve every existing row and pass the schema migrator tests.

- [ ] **Step 5: Factor one transaction-local reserve helper** and have both `reserve_entry()` and `reserve_entries_atomic()` call it. The batch method validates all request identities, expected stream version, total cash, lifecycle, and source bindings before inserting any row; it recomputes risk/stage loss once after the complete batch.

```python
def reserve_entries_atomic(
    self, requests: tuple[ReserveEntryRequest, ...]
) -> CapitalRiskSnapshot:
    ordered = tuple(sorted(requests, key=lambda item: item.source_id))
    def operation(context: GatewayTransactionContext) -> CapitalRiskSnapshot:
        self._validate_reserve_batch(context, ordered)
        for request in ordered:
            self._reserve_entry_in_context(context, request)
        context.recompute_risk_and_stage_loss(
            ordered[-1].as_of, self._batch_reserve_identity(ordered)
        )
        return context.read_capital_risk_snapshot(ordered[-1].as_of)
    return self._run_write_transaction(operation)
```

- [ ] **Step 6: Propagate source binding through fills, fees, valuation, restatement, bust/correction, conservation replay, and projection rebuild.** Existing non-Trial callers may omit the optional compatibility field; the shadow adapter added later must reject omission before calling capital.

- [ ] **Step 7: Verify full capital integrity.**

```bash
.venv/bin/python -m pytest tests/offensive/v3/capital -q
```

Expected: all capital tests pass, including `capital_conservation=PASS` and `projection_rebuild=PASS` cases.

- [ ] **Step 8: Commit.**

```bash
git add src/screening/offensive/v3/capital src/screening/offensive/v3/storage tests/offensive/v3/capital
git commit -m "feat(v3): bind shadow capital facts to causal artifacts"
```

---

### Task 8: Share mechanical shrink and proxy execution/settlement economics

**Files:**
- Modify: `src/screening/offensive/v3/contracts/execution.py`
- Create: `src/screening/offensive/v3/execution/proxy_core.py`
- Modify: `src/screening/offensive/v3/execution/proxy.py`
- Modify: `src/screening/offensive/v3/execution/__init__.py`
- Modify: `config/policies/v3/policy-v1.json`
- Modify: `config/policies/v3/policy-v2.json`
- Modify: `tests/offensive/v3/contracts/revision2_snapshot_exemplars.py`
- Regenerate: `tests/offensive/v3/contracts/fixtures/revision2/*.json`
- Create: `tests/offensive/v3/execution/test_proxy_mechanical.py`
- Create: `tests/offensive/v3/execution/test_proxy_economic_core.py`
- Modify: `tests/offensive/v3/execution/test_proxy.py`
- Modify: `tests/offensive/v3/contracts/test_execution.py`

**Interfaces:**
- `MechanicalQuantityResolution(permitted_quantity_units, reason_code)`
- `resolve_mechanical_quantity(sealed_quantity_units, lot_size_units, binding)`
- `ProxyCostScenario(scenario_id, entry_slippage_bps, exit_slippage_bps, fee_policy)`
- `NormalizedProxyOpenIntent`
- `settle_proxy_open(intent, *, bar, repository, scenario, command_at, send_deadline) -> ProxyOpenSettlement`
- Existing `DailyBarProxy.execute_open()` becomes the authorised adapter with a required explicit cost scenario
- Official Trial versions: execution `t1-open-t10-open-slippage.v2`, cost `cn-a-share-30bps-tax.v2`; old proxy version remains compatibility/research only

- [ ] **Step 1: Write RED mechanical tests** for unchanged, each cap priority, lot floor, zero quantity, input cap above sealed quantity, and identical results from ExecutionPermit validation and direct resolver use.

- [ ] **Step 2: Write RED proxy-core tests** for entry/exit, missing/suspended/late/one-price lock, ordinary touch, no-fill, reserve consumption/release, complete fee/tax, exact IDs, and source binding. Add current 30bps-per-side and stress 60bps adverse price tests; buy prices cannot exceed the limit and sell prices cannot fall below it.

```python
def test_double_slippage_changes_execution_price_not_final_return(intent, bar, repos) -> None:
    current = settle_proxy_open(
        intent, bar=bar, repository=repos.current,
        scenario=cost_scenario(slippage_bps=30), command_at=OPEN, send_deadline=DEADLINE,
    )
    stressed = settle_proxy_open(
        intent, bar=bar, repository=repos.stressed,
        scenario=cost_scenario(slippage_bps=60), command_at=OPEN, send_deadline=DEADLINE,
    )
    assert stressed.fill_price_cents >= current.fill_price_cents
```

- [ ] **Step 3: Verify RED.**

```bash
.venv/bin/python -m pytest tests/offensive/v3/execution/test_proxy_mechanical.py tests/offensive/v3/execution/test_proxy_economic_core.py tests/offensive/v3/execution/test_proxy.py -q
```

Expected: shared resolver/core and explicit cost scenario do not exist.

- [ ] **Step 4: Extract the mechanical resolver** into the contract module and make `_validate_permit_lines()` call it. Delete the duplicated lot-floor/reason calculation from the validator. The resolver is pure and authority-neutral; it cannot issue a permit.

- [ ] **Step 5: Extract normalized proxy economics.** Map permit/seal lines into `NormalizedProxyOpenIntent`; let the core call `resolve_open_execution`, apply integer adverse slippage, create fill/fee/release requests, and return a typed settlement. Keep authorised record storage in `DailyBarProxy`; do not move permit validation into the core. Bump the execution/cost versions and behavior fingerprints because adding explicit slippage changes economics; update both OFF policy candidates and literal snapshots without activating either policy.

- [ ] **Step 6: Add differential/property tests.** Feed equivalent normalized inputs through the authorised adapter and direct core into equal-genesis ledgers. After normalizing provenance IDs, cash, restricted cash, quantities, cost basis, fees, and NAV must match. Random candidate order, lot quantity, price, bar, and crash replay may not change the result.

Run:

```bash
.venv/bin/python -m pytest tests/offensive/v3/contracts/test_execution.py tests/offensive/v3/execution/test_proxy_mechanical.py tests/offensive/v3/execution/test_proxy_economic_core.py tests/offensive/v3/execution/test_proxy.py -q
.venv/bin/python scripts/v3_refresh_contract_snapshots.py --check
```

Expected: all pass; `DailyBarProxy` still rejects non-proxy permits and performs no broker call.

- [ ] **Step 7: Commit.**

```bash
git add src/screening/offensive/v3/contracts/execution.py src/screening/offensive/v3/execution config/policies/v3 tests/offensive/v3/contracts/revision2_snapshot_exemplars.py tests/offensive/v3/contracts/fixtures/revision2 tests/offensive/v3/contracts/test_execution.py tests/offensive/v3/execution
git commit -m "refactor(v3): share mechanical proxy settlement economics"
```

---

### Task 9: ShadowDecision-only T0 reserve and T+1 entry adapter

**Files:**
- Create: `src/screening/offensive/v3/execution/shadow_proxy.py`
- Modify: `src/screening/offensive/v3/execution/__init__.py`
- Create: `tests/offensive/v3/execution/test_shadow_proxy_entry.py`
- Modify: `tests/offensive/v3/execution/test_proxy_economic_core.py`

**Interfaces:**
- `ShadowArmExecutionContext(trial_id, arm, portfolio_id, decision_store, capital_repository, writer_lease)`
- `ShadowProxyAdapter.reserve_committed_pair(pair_key, contexts) -> tuple[ShadowReserveReceipt, ShadowReserveReceipt]`
- `ShadowProxyAdapter.execute_entries(pair_key, arm, session, mechanical_bindings, bars, scenario) -> ShadowEntryResult`
- Stable identity function `shadow_economic_id(trial_id, arm, cycle_id, line_id, event_kind)`
- Append-only `shadow_proxy_operations` and `shadow_proxy_phase_facts` storage

- [ ] **Step 1: Write RED admission-boundary tests.** The adapter accepts only the current schema-major-3 `ShadowDecision` retrieved from a complete committed pair. It rejects `LegacyShadowDecisionV2`, `ExecutionPermit`, `PortfolioDecisionSeal`, incomplete pair, wrong Trial/arm/portfolio, wrong target session, stale writer lease, or a decision with `execution_authority` other than the literal `NONE` before any capital write.

```python
def test_reserve_requires_complete_pair(adapter, contexts, uncommitted_pair) -> None:
    before = tuple(ctx.capital_repository.capital_risk_snapshot(NOW) for ctx in contexts)
    with pytest.raises(ShadowProxyError, match="pair_not_committed"):
        adapter.reserve_committed_pair(uncommitted_pair.key, contexts)
    after = tuple(ctx.capital_repository.capital_risk_snapshot(NOW) for ctx in contexts)
    assert after == before
```

- [ ] **Step 2: Write RED lifecycle tests** for atomic per-arm multi-line T0 reserves, stable source bindings, mechanical shrink-only T+1 quantities, current-cost fills, UNKNOWN/NO_FILL reserve release, exact replay, content conflict, one arm crash after capital write, and recovery from append-only phase facts.

- [ ] **Step 3: Verify RED.**

```bash
.venv/bin/python -m pytest tests/offensive/v3/execution/test_shadow_proxy_entry.py tests/offensive/v3/execution/test_proxy_economic_core.py -q
```

Expected: shadow adapter does not exist.

- [ ] **Step 4: Implement append-only operation state.** One immutable operation row binds decision hash, line, arm, portfolio, target session, and source binding. Each completed phase (`RESERVE_COMMITTED`, `MECHANICAL_RESOLVED`, `CAPITAL_SETTLED`, `RESERVE_RELEASED`) appends one fact with a unique `(operation_id, phase)` key and payload hash. Exact replay reads the phase; divergent replay raises `shadow_proxy_protocol_breach`.

- [ ] **Step 5: Reserve only after pair commit.** Revalidate the writer lease and both decision records, then call each arm's `reserve_entries_atomic()` using deterministic reserve IDs. The two capital databases are not one transaction: if arm 1 commits and the process dies, pair truth plus stable IDs must let replay commit arm 2 without changing arm 1.

```python
source = CapitalSourceBinding(
    mode=ExecutionMode.DAILY_BAR_PROXY,
    artifact_kind=ArtifactKind.SHADOW_DECISION,
    artifact_id=decision.shadow_decision_id,
    artifact_hash=decision.artifact_hash(),
)
reserve_id = shadow_economic_id(
    trial_id, arm, cycle_id, line.shadow_line_id, "entry-reserve"
)
```

- [ ] **Step 6: Execute T+1 through the shared core.** Resolve `PermitLineMechanicalBinding` with the shared mechanical function, never exceed the T0 target, map the permitted line to `NormalizedProxyOpenIntent`, and call `settle_proxy_open()`. A zero/unknown/no-fill releases the full reserve and leaves cash; a fill consumes the reserve, books fees, and returns surplus through CapitalTruth.

- [ ] **Step 7: Add a forbidden-dependency AST test.** `shadow_proxy.py` may import contracts, evidence read models, capital, `proxy_core`, and `TrialArmDecisionStore`; it may not import gateway decisions/authority, orchestration shadow trust, broker, outbox, network, or production adapter modules.

Run:

```bash
.venv/bin/python -m pytest tests/offensive/v3/execution/test_shadow_proxy_entry.py tests/offensive/v3/execution/test_proxy_economic_core.py -q
```

Expected: all pass; no permit/outbox/broker artifact can be obtained from the adapter.

- [ ] **Step 8: Commit.**

```bash
git add src/screening/offensive/v3/execution tests/offensive/v3/execution
git commit -m "feat(v3): settle committed shadow entries"
```

---

### Task 10: T+10 exits, daily valuation, company actions, and checkpoints

**Files:**
- Create: `src/screening/offensive/v3/execution/shadow_lifecycle.py`
- Modify: `src/screening/offensive/v3/execution/shadow_proxy.py`
- Modify: `src/screening/offensive/v3/gateway/exits.py`
- Modify: `src/screening/offensive/v3/services/lifecycle_scheduler.py`
- Create: `tests/offensive/v3/execution/test_shadow_proxy_exit.py`
- Create: `tests/offensive/v3/execution/test_shadow_proxy_lifecycle.py`
- Modify: `tests/offensive/v3/gateway/test_exits.py`
- Modify: `tests/offensive/v3/capital/test_bust_and_reopen.py`
- Modify: `tests/offensive/v3/capital/test_corporate_actions.py`

**Interfaces:**
- `ExitLane.release_lease(lease_id, *, worker_id) -> None`
- `ShadowProxyLifecycle.advance_session(session_input, arm_contexts) -> PairedLifecycleReceipt`
- `ShadowProxyLifecycle.derive_exits(arm, trading_sessions) -> tuple[ExitMandate, ...]`
- `ShadowProxyLifecycle.execute_due_exits(arm, session, bars, scenario) -> tuple[ShadowExitResult, ...]`
- `ShadowProxyLifecycle.close_valuation(arm, snapshot_evidence, marks) -> ValuationReceipt`
- `ShadowProxyLifecycle.finalize_session(arm, session) -> SessionCheckpointReceipt`

- [ ] **Step 1: Write RED exit tests** for exact T+10-open due date, overlapping cycles, partial tradable quantity, missing/suspended/late/one-price-limit-down exit, persistent unknown mandate, retry next session, stable attempt/order/fill IDs, no oversell, explicit lease release, and exit continuation while entry/risk/stage is halted.

```python
def test_unknown_exit_keeps_position_and_mandate(lifecycle, due_context) -> None:
    result = lifecycle.execute_due_exits(
        due_context.arm, due_context.session, bars={}, scenario=due_context.scenario
    )
    assert result[0].resolution.verdict is OpenExecutionVerdict.UNKNOWN
    assert due_context.capital.position_quantity(due_context.lot_id) > 0
    assert due_context.exit_lane.exit_state(*due_context.lot_key).claimable_quantity > 0
```

- [ ] **Step 2: Write RED valuation/correction tests.** Both arms consume the same close SnapshotEvidence/marks but produce arm-specific NAV. Missing marks block close finalization; no stale close is substituted. Split/dividend/successor-security and fill/fee bust/correction append through existing capital primitives, preserve mode/source, and reopen exit obligations without increasing outcome count.

- [ ] **Step 3: Verify RED.**

```bash
.venv/bin/python -m pytest tests/offensive/v3/execution/test_shadow_proxy_exit.py tests/offensive/v3/execution/test_shadow_proxy_lifecycle.py tests/offensive/v3/gateway/test_exits.py -q
```

Expected: lifecycle facade and lease release are missing.

- [ ] **Step 4: Implement the fixed session order.** For each arm: apply already-committed company actions/corrections; refresh/derive ExitMandates from CapitalRiskSnapshot positions plus their originating ShadowDecision; claim and settle due exits; settle target-session entries; close valuation from same-session SnapshotEvidence; advance monotone checkpoints through `SESSION_FINALIZED`. Entry failure never skips the exit phase.

```python
SESSION_ORDER = (
    "CORPORATE_ACTIONS_APPLIED",
    "PREOPEN_RISK_LOCKED",
    "EXIT_OPEN_RECONCILED",
    "ENTRY_OPEN_RECONCILED",
    "CLOSE_VALUED",
    "SESSION_FINALIZED",
)
```

Map these lifecycle phases onto the existing `CheckpointService` ladder without adding a second checkpoint truth: exit and entry reconciliation both complete before the existing `OPEN_RECONCILED` advance.

- [ ] **Step 5: Implement proxy exit resolution.** Record `SUBMITTED` against ExitLane, resolve/settle the EXIT intent through `settle_proxy_open()`, then record cumulative `FILLED` and release the lease. On `UNKNOWN`/`NO_FILL`, record `CANCELLED`, release the lease, retain the position/mandate, and retry on a later session. Capital fill commits before ExitLane FILLED so crash replay cannot declare shares sold without capital truth.

- [ ] **Step 6: Implement close valuation provenance.** Every mark/valuation request uses `CapitalSourceBinding(mode=DAILY_BAR_PROXY, artifact_kind=SNAPSHOT, artifact_id=evidence_id, artifact_hash=record.artifact_hash())`; decision-derived fills/fees retain the ShadowDecision binding. Run `CheckpointService` and full conservation/rebuild verification before returning a finalized receipt.

- [ ] **Step 7: Fault-inject every phase boundary.** A crash after capital exit fill but before ExitLane update, after valuation but before checkpoint, or after one arm finalizes must converge under exact replay. Different payload under the same stable ID is a protocol breach and jointly halts new entries while allowing exit/correction continuation.

Run:

```bash
.venv/bin/python -m pytest tests/offensive/v3/execution/test_shadow_proxy_exit.py tests/offensive/v3/execution/test_shadow_proxy_lifecycle.py tests/offensive/v3/gateway/test_exits.py tests/offensive/v3/capital/test_bust_and_reopen.py tests/offensive/v3/capital/test_corporate_actions.py -q
```

Expected: all pass; both ledgers finish each healthy session with conservation and projection rebuild passing.

- [ ] **Step 8: Commit.**

```bash
git add src/screening/offensive/v3/execution src/screening/offensive/v3/gateway/exits.py src/screening/offensive/v3/services/lifecycle_scheduler.py tests/offensive/v3/execution tests/offensive/v3/gateway/test_exits.py tests/offensive/v3/capital
git commit -m "feat(v3): run complete shadow capital lifecycle"
```

---

### Task 11: Thin ForwardPairedTrialRunner and terminal SessionSpine semantics

**Files:**
- Create: `src/screening/offensive/v3/orchestration/paired_trial.py`
- Modify: `src/screening/offensive/v3/orchestration/__init__.py`
- Modify: `src/screening/offensive/v3/evidence/session_spine.py`
- Create: `tests/offensive/v3/orchestration/test_forward_paired_runner.py`
- Modify: `tests/offensive/v3/evidence/test_session_spine.py`
- Modify: `tests/offensive/v3/services/test_btst_producer_api.py`

**Interfaces:**
- `ForwardPairedTrialRunner.decide_signal_session(request) -> PairedSignalReceipt`
- `ForwardPairedTrialRunner.advance_market_session(request) -> PairedLifecycleReceipt`
- `ForwardPairedTrialRunner.finalize_missed_sessions(trusted_at) -> tuple[date, ...]`
- Pure `classify_pair_session(champion_record, challenger_record, *, shared_candidate_count) -> SessionStatus`
- SessionSpine non-cancel statuses become exact-idempotent terminal facts; only a signed calendar revision may supersede them with `SESSION_CANCELLED`

- [ ] **Step 1: Write RED orchestration-count tests.** On one healthy signal session the runner reads one governance bundle, freezes the trusted clock once, reads one canonical regime observation, runs the producer exactly once, calls `decide_shadow` exactly once per arm with the same frozen shared input/time, commits one pair, records one status, and only then reserves both decisions.

```python
def test_runner_freezes_shared_work_once(rig) -> None:
    receipt = rig.runner.decide_signal_session(rig.request)
    assert rig.clock.calls == 1
    assert rig.producer.calls == 1
    assert rig.kernel.calls_by_arm == {
        TrialArm.CHAMPION: 1,
        TrialArm.CHALLENGER: 1,
    }
    assert rig.store.pair(receipt.pair_key)[0].shared_input_hash == rig.store.pair(receipt.pair_key)[1].shared_input_hash
```

- [ ] **Step 2: Write RED status tests.** Cover pair RUN with Challenger regime-blocked; shared empty candidates `NO_SIGNAL`; shared core evidence failure `DATA_UNKNOWN`; common capital integrity/risk block `BLOCKED`; absent canonical regime observation or absent pair after cutoff `NO_RUN`; signed calendar correction `SESSION_CANCELLED`; canonical UNKNOWN producing Champion trade remains RUN. Arm-specific capital block plus a valid other arm remains RUN.

- [ ] **Step 3: Write RED failure-order tests.** Pair-computation failure yields zero cycle capital side effects; pair commit followed by reserve crash replays stable IDs; expired writer lease blocks; same pair/different candidate/regime/policy/capital bytes latches breach; lifecycle exits still run when decision enrollment fails.

- [ ] **Step 4: Verify RED.**

```bash
.venv/bin/python -m pytest tests/offensive/v3/orchestration/test_forward_paired_runner.py tests/offensive/v3/evidence/test_session_spine.py -q
```

Expected: paired runner and terminal status rules are missing.

- [ ] **Step 5: Implement only orchestration.** The runner validates the sealed bundle/genesis/expected session/lease, rejects new decisions outside the sealed enrollment window, completes prior lifecycle, verifies both close checkpoints, freezes a shared input, reads active regime evidence before cutoff, calls the producer once, constructs two arm inputs, runs two pure decisions, and calls `commit_pair()`. `advance_market_session()` remains available for exit-only run-out through the sealed finality date. The runner contains no classifier, ranking, sizing, fee, fill, NAV, statistical, signing, activation, or broker logic.

- [ ] **Step 6: Make pair commit the side-effect boundary.** After commit, call `reserve_committed_pair()`. If the process dies, `decide_signal_session()` first finds and exact-validates the existing pair, skips both kernels, finishes missing reserves/status using stable IDs, and returns the same receipt. It never recomputes an alternate proposal after a pair exists.

- [ ] **Step 7: Harden SessionSpine.** An identical status retry is quiet; a conflicting non-cancel status fails; a signed calendar revision may append `SESSION_CANCELLED`; cancelled is terminal. `finalize_missed_sessions()` writes `NO_RUN` only for enrolled sessions whose decision cutoff has passed and whose pair/status is absent.

- [ ] **Step 8: Add static dependency guard.** The runner may reach evidence/governance read APIs, producer, kernel, decision store, capital read APIs, and shadow lifecycle. Reject imports or attribute calls containing `activate_`, `publish_entry`, `issue_permit`, `claim_send`, `outbox`, `broker`, `shadow_trust`, or production adapter paths.

Run:

```bash
.venv/bin/python -m pytest tests/offensive/v3/orchestration/test_forward_paired_runner.py tests/offensive/v3/evidence/test_session_spine.py tests/offensive/v3/services/test_btst_producer_api.py -q
```

Expected: all pass; a canonical UNKNOWN is policy behavior, while missing observation becomes operational NO_RUN.

- [ ] **Step 9: Commit.**

```bash
git add src/screening/offensive/v3/orchestration src/screening/offensive/v3/evidence/session_spine.py tests/offensive/v3/orchestration tests/offensive/v3/evidence/test_session_spine.py tests/offensive/v3/services/test_btst_producer_api.py
git commit -m "feat(v3): orchestrate forward paired shadow sessions"
```

---

### Task 12: Deterministic current-cost and 2x-slippage full replay

**Files:**
- Create: `src/screening/offensive/v3/orchestration/replay.py`
- Modify: `src/screening/offensive/v3/orchestration/__init__.py`
- Create: `tests/offensive/v3/orchestration/test_forward_trial_replay.py`
- Modify: `tests/offensive/v3/orchestration/test_trial_genesis_archive.py`
- Modify: `tests/offensive/v3/execution/test_shadow_proxy_lifecycle.py`

**Interfaces:**
- `ReplayScenario = CURRENT_COST | DOUBLE_SLIPPAGE`
- `TrialReplayInput` binding sealed bundle, genesis manifest, SessionSpine, Evidence Store cutoff reader, and immutable market/corporate-action/calendar facts
- `ForwardTrialReplayEngine.replay(input, scenario, target_directory) -> PairedReplayResult`
- `PairedReplayResult` exposes scenario, both verified capital reports, restated-final NAV checkpoint paths, decision hashes, and lifecycle/checkpoint roots

- [ ] **Step 1: Write RED replay tests.** Restore both pre-enrollment genesis archives into fresh paths, replay all expected sessions in chronological order, and require CURRENT_COST to reproduce official pair decisions, capital events, session checkpoints, and restated-final NAV paths byte-for-byte. Deleting the replay directory and rerunning must produce the same result hashes.

```python
def test_current_cost_replay_reproduces_official_path(rig, tmp_path) -> None:
    result = rig.replayer.replay(
        rig.input, ReplayScenario.CURRENT_COST, tmp_path / "current"
    )
    assert result.champion.nav_path_hash == rig.official.champion.nav_path_hash
    assert result.challenger.nav_path_hash == rig.official.challenger.nav_path_hash
    assert result.decision_root == rig.official.decision_root
```

- [ ] **Step 2: Write RED stress-state tests.** DOUBLE_SLIPPAGE uses 60bps adverse entry/exit execution from the open-resolution core, then reruns future cash, capacity, drawdown, decisions, fills, exits, and marks. Demonstrate a case where extra early cost removes a later lot due to cash: a post-hoc constant return drag would retain it and must not match.

- [ ] **Step 3: Write RED PIT tests.** Replay reads the exact active evidence revision before each original cutoff and rejects missing/late/revised-after-cutoff inputs, changed policy/classifier/cost/execution versions, incomplete SessionSpine, unfinalized exit, or genesis mismatch. It never calls the producer publisher or creates new SignalEvidence.

- [ ] **Step 4: Verify RED.**

```bash
.venv/bin/python -m pytest tests/offensive/v3/orchestration/test_forward_trial_replay.py tests/offensive/v3/orchestration/test_trial_genesis_archive.py -q
```

Expected: replay engine is missing.

- [ ] **Step 5: Implement chronological reconstruction.** Restore arm archives, then for each non-cancelled expected session load committed signal/regime/bar/action facts by original cutoff, complete prior lifecycle, rebuild arm-specific ShadowKernelInput from current replay capital, run the same pure kernel, settle through the same ShadowProxyLifecycle, close valuation, and verify checkpoints. CURRENT_COST additionally compares each reconstructed decision with the official decision store and fails on any byte difference.

- [ ] **Step 6: Implement stress as a complete alternate state path.** Use the same policy and market facts but the `DOUBLE_SLIPPAGE` cost scenario. Do not compare its later decisions to official bytes because capital/risk/capacity may legitimately diverge; instead persist only the temporary replay ledgers and return their content hashes. Stress replay does not append official EvidenceConsumption entries or change Trial truth.

- [ ] **Step 7: Verify conservation, finality, and deterministic cleanup.** Both scenarios must end with capital conservation and projection rebuild PASS for both arms; all expected sessions classified; all exit/fee/action/correction facts at sealed finality; no unresolved negative or unknown state. Replay refuses to overwrite a nonempty target directory with a different manifest.

Run:

```bash
.venv/bin/python -m pytest tests/offensive/v3/orchestration/test_forward_trial_replay.py tests/offensive/v3/execution/test_shadow_proxy_lifecycle.py -q
```

Expected: all pass; the 2x result is demonstrably a full path replay, not a transformed return series.

- [ ] **Step 8: Commit.**

```bash
git add src/screening/offensive/v3/orchestration tests/offensive/v3/orchestration tests/offensive/v3/execution/test_shadow_proxy_lifecycle.py
git commit -m "feat(v3): replay paired trial cost scenarios from genesis"
```

---

### Task 13: Frozen paired evaluator and deletable assessment projection

**Files:**
- Create: `src/screening/offensive/v3/evidence/paired_statistics.py`
- Modify: `src/screening/offensive/v3/evidence/statistics.py`
- Modify: `src/screening/offensive/v3/evidence/__init__.py`
- Create: `src/screening/offensive/v3/reporting/trial_projection.py`
- Modify: `src/screening/offensive/v3/reporting/__init__.py`
- Create: `tests/offensive/v3/evidence/test_frozen_paired_evaluation.py`
- Create: `tests/offensive/v3/reporting/test_trial_assessment_projection.py`
- Modify: `tests/offensive/v3/evidence/test_statistics.py`

**Interfaces:**
- `PairedNavPoint(session, champion_nav_numerator, champion_nav_denominator, challenger_nav_numerator, challenger_nav_denominator, checkpoint_hashes)`
- `paired_daily_log_growth(points) -> tuple[float, ...]` with fixed Challenger-minus-Champion sign
- `block_bootstrap_lcb(values, *, method, block_length, repetitions, seed, confidence) -> float` supporting only the pre-registered `moving | stationary | circular` methods
- `newey_west_lcb(values, *, lag, confidence) -> float`
- `evaluate_frozen_paired_portfolios(current_replay, stress_replay, plan, coverage) -> FrozenPairedEvaluation`
- `TrialAssessmentProjection` and `render_trial_assessment()`; no repository/table for the projection

- [ ] **Step 1: Write RED sign/alignment tests.** Include every non-cancelled expected market day, including cash/no-signal/blocked/equal days. Reject missing, duplicate, reordered, non-positive, mixed-scenario, or mismatched-session NAV points. A target-only gain is positive; swapping arms negates every `d_t` and the mean exactly.

```python
def test_delta_sign_is_challenger_minus_champion(points) -> None:
    delta = paired_daily_log_growth(points)
    swapped = paired_daily_log_growth(tuple(point.swap_arms() for point in points))
    assert swapped == tuple(-value for value in delta)
    assert sum(delta) / len(delta) > 0
```

- [ ] **Step 2: Write RED inference tests.** Freeze repetitions/seed/confidence/block rule from SAP; evaluate moving/stationary/circular method exactly as registered; include block-length sensitivity 10/20/40 plus a longer train-only diagnostic; compute HAC and chronological-fold lower bounds; use the most conservative registered lower bound. Samples too short for any required method are `NOT_ELIGIBLE`, never silently downgraded to an IID t-test.

- [ ] **Step 3: Write RED eligibility tests.** Require separate booleans for 150 mature outcomes, 60 decision days, ESS 60, 80 tickers, 12 months, adverse window, full ITT/finality, current and stress absolute growth, current and stress incremental `LCB >= incremental_MEE`, MDD/CDaR/overshoot/liquidity/capacity, consumption/multiplicity, conservation/rebuild, and zero unresolved breach. Threshold equality passes only the `>=` gates.

- [ ] **Step 4: Verify RED.**

```bash
.venv/bin/python -m pytest tests/offensive/v3/evidence/test_frozen_paired_evaluation.py tests/offensive/v3/reporting/test_trial_assessment_projection.py tests/offensive/v3/evidence/test_statistics.py -q
```

Expected: frozen paired evaluator/report types are missing.

- [ ] **Step 5: Implement exact paired growth.** Derive each arm's daily log growth from its exact UnitNAV rational and subtract Champion from Challenger. Keep original unwinsorized deltas. Do not call `evaluate_predictable_adaptive()` and do not swap its arguments; that function retains its separate adaptive semantics and sign.

```python
def paired_daily_log_growth(points: Sequence[PairedNavPoint]) -> tuple[float, ...]:
    champion = _daily_log_growth(points, arm=TrialArm.CHAMPION)
    challenger = _daily_log_growth(points, arm=TrialArm.CHALLENGER)
    return tuple(
        chal - champ
        for champ, chal in zip(champion, challenger, strict=True)
    )
```

- [ ] **Step 6: Implement conservative frozen inference.** The bootstrap resamples blocks only from the complete continuous-path deltas; MDD/CDaR/overshoot come directly from each continuous replay, never stitched blocks. Compute absolute arm growth against the sealed benchmark and incremental growth for current/stress separately. Set `passes_incremental = lcb >= mee`.

- [ ] **Step 7: Implement a pure assessment projection.** It contains only hashes/references to Trial/SAP/Stage, SessionSpine, pair decisions, genesis, current/stress replay, capital reports, and consumption ledgers plus calculated gates. Rendering the same inputs is byte-identical; deleting the report loses no truth. Headline is `NOT_ELIGIBLE` if any gate fails and at most `INACTIVE_PROMOTION_CANDIDATE` if all pass.

- [ ] **Step 8: Add a deletion/rebuild test** and a guard that `DAILY_BAR_PROXY` output cannot serialize a broker fill, active authorization, canary activation, or production deployment recommendation.

Run:

```bash
.venv/bin/python -m pytest tests/offensive/v3/evidence/test_frozen_paired_evaluation.py tests/offensive/v3/reporting/test_trial_assessment_projection.py tests/offensive/v3/evidence/test_statistics.py -q
```

Expected: all pass; sign, MEE boundary, PIT alignment, and projection rebuild are locked.

- [ ] **Step 9: Commit.**

```bash
git add src/screening/offensive/v3/evidence src/screening/offensive/v3/reporting tests/offensive/v3/evidence tests/offensive/v3/reporting
git commit -m "feat(v3): evaluate frozen paired portfolio growth"
```

---

### Task 14: Shadow runtime entrypoints, adversarial campaign, docs, and final gate

**Files:**
- Create: `src/cli/v3_regime_trial.py`
- Create: `scripts/v3_regime_trial.py`
- Create: `tests/offensive/v3/test_v3_regime_trial_cli.py`
- Create: `tests/offensive/v3/orchestration/test_regime_trial_fault_campaign.py`
- Create: `tests/offensive/v3/orchestration/test_regime_trial_import_boundary.py`
- Modify: `docs/superpowers/specs/2026-07-19-evidence-gated-growth-kernel-design.md`
- Modify: `docs/superpowers/specs/2026-08-09-btst-regime-gate-forward-paired-shadow-trial-design.md`
- Create: `docs/superpowers/migrations/2026-08-10-policy-v2-shadow-decision-v3.md`
- Create: `docs/runbooks/v3-btst-regime-forward-trial.md`
- Modify: `AGENTS.md`

**Interfaces:**
- `v3_regime_trial validate --root PATH --trial-id ID`
- `v3_regime_trial decide-session --root PATH --trial-id ID --signal-session YYYY-MM-DD`
- `v3_regime_trial advance-session --root PATH --trial-id ID --market-session YYYY-MM-DD`
- `v3_regime_trial assess --root PATH --trial-id ID --output PATH`
- Default invocation is read-only validation; mutation commands require an already sealed bundle, Stage, enrolled session, equal genesis manifest, and live writer lease. CLI arguments cannot supply or override policy, regime, caps, mode, or evidence cutoff.

- [ ] **Step 1: Write RED CLI tests.** Missing governance/genesis/spine/lease fails closed; default validate performs no writes; path traversal/symlink roots reject; unknown or post-enrollment session rejects; policy/mode/cap override flags are not recognized; valid fake-Trial commands invoke only the paired runner/lifecycle/evaluator.

- [ ] **Step 2: Write the adversarial fault campaign.** Cover crashes between arm computations, before/inside/after pair commit, after either arm reserve/fill/fee/exit/valuation/checkpoint, duplicate/out-of-order/conflicting observation/fill/fee/correction, prolonged missing/suspended/locked bars, policy/evidence/capital drift, lease takeover, conservation/rebuild failure, and finality with pending exits. Assert no quantity increase, no oversell, no sample inflation, no dropped ITT row, and exit continuation under every entry halt.

- [ ] **Step 3: Write a source-tree boundary test.** Parse imports/calls under `paired_trial.py`, `replay.py`, `shadow_proxy.py`, `shadow_lifecycle.py`, and CLI modules. Reject broker packages, Gateway authority/decision writers, `CapitalAuthorizationEnvelope`, `ExecutionPermit`, activation methods, outbox/send claims, environment policy overrides, legacy court/backtest imports, and Plan 05 `shadow_trust`.

- [ ] **Step 4: Verify RED.**

```bash
.venv/bin/python -m pytest tests/offensive/v3/test_v3_regime_trial_cli.py tests/offensive/v3/orchestration/test_regime_trial_fault_campaign.py tests/offensive/v3/orchestration/test_regime_trial_import_boundary.py -q
```

Expected: entrypoints and campaign are missing.

- [ ] **Step 5: Implement the thin CLI.** Build components from the Trial root's fixed database/archive layout, read the sealed governance artifacts, and delegate. `assess` writes only a deletable report to the explicit output path. Do not add environment switches that change policy behavior and do not auto-create or auto-seal a Trial.

- [ ] **Step 6: Update authoritative documentation.** Record PolicySnapshot schema 2, ShadowDecision schema 3 compatibility/read-only rules, authority-free ShadowKernelInput, decision-store/genesis/proxy/replay/evaluator boundaries, and the fact that no actual Trial, policy activation, capital authorization, broker connection, or canary was started. The migration note lists every old/new field, namespace/hash change, fixture regeneration, and rollback/audit behavior.

- [ ] **Step 7: Run focused suites.**

```bash
.venv/bin/python -m pytest tests/offensive/v3/contracts tests/offensive/v3/governance tests/offensive/v3/evidence tests/offensive/v3/kernel -q
.venv/bin/python -m pytest tests/offensive/v3/capital tests/offensive/v3/gateway tests/offensive/v3/execution tests/offensive/v3/orchestration tests/offensive/v3/reporting -q
.venv/bin/python -m pytest tests/offensive/v3/test_v3_shadow_cli.py tests/offensive/v3/test_v3_shadow_config.py tests/offensive/v3/test_v3_regime_trial_cli.py -q
```

Expected: every command exits 0.

- [ ] **Step 8: Run the complete v3 regression and static gates.**

```bash
.venv/bin/python -m pytest tests/offensive/v3 -q
.venv/bin/python -m flake8 src/screening/offensive/v3 src/cli/v3_regime_trial.py scripts/v3_regime_trial.py tests/offensive/v3
.venv/bin/python scripts/v3_refresh_contract_snapshots.py --check
git diff --check
```

Expected: all tests/lint/snapshot/diff checks pass. Capture exact pass counts and command output before any completion claim.

- [ ] **Step 9: Run explicit no-authority scans and inspect staged scope.**

```bash
rg -n "CapitalAuthorizationEnvelope|ExecutionPermit|publish_entry|issue_permit|claim_send|BrokerRuntime|BrokerDispatcher|shadow_trust" src/screening/offensive/v3/orchestration/paired_trial.py src/screening/offensive/v3/orchestration/replay.py src/screening/offensive/v3/execution/shadow_proxy.py src/screening/offensive/v3/execution/shadow_lifecycle.py src/cli/v3_regime_trial.py scripts/v3_regime_trial.py
git status --short
git diff --stat
```

Expected: the forbidden scan has no matches; only intended source/tests/docs/config/fixtures are staged, and the three user-owned data files remain modified but unstaged.

- [ ] **Step 10: Commit the integration gate.**

```bash
git add AGENTS.md docs/superpowers/specs/2026-07-19-evidence-gated-growth-kernel-design.md docs/superpowers/specs/2026-08-09-btst-regime-gate-forward-paired-shadow-trial-design.md docs/superpowers/migrations/2026-08-10-policy-v2-shadow-decision-v3.md docs/runbooks/v3-btst-regime-forward-trial.md src/cli/v3_regime_trial.py scripts/v3_regime_trial.py tests/offensive/v3/test_v3_regime_trial_cli.py tests/offensive/v3/orchestration/test_regime_trial_fault_campaign.py tests/offensive/v3/orchestration/test_regime_trial_import_boundary.py
git commit -m "feat(v3): complete BTST regime paired shadow trial"
```

## Completion Gate

- [ ] Champion and Challenger differ semantically only at `btst_regime_admission_mode`; the validated delta path is exactly one field.
- [ ] Canonical UNKNOWN lets Champion retain ungated semantics and blocks Challenger; absent observation becomes NO_RUN without backfill.
- [ ] ShadowKernelInput contains no activation/envelope/permit/broker identity and both boundaries share exactly one decision-economic core.
- [ ] Both arm decisions, including NoTrade, commit atomically before any reserve; stable replay converges and divergent replay latches a breach.
- [ ] Equal genesis is sealed over the complete normalized economic state, and both arm ledgers remain isolated, mode-pure, continuous, and conserved.
- [ ] T+1/T+10 opens, 30bps current slippage, full fees/tax, integer lots, unknown/no-fill, overlapping positions, exits, actions, corrections, and daily UnitNAV are represented in CapitalTruth.
- [ ] Authorised and shadow proxy adapters are economically differential-tested while remaining type/import separated.
- [ ] Current and 2x-slippage scenarios both replay from genesis; current reproduces official bytes and stress may change future decisions through capital state.
- [ ] SessionSpine contains every expected market day with terminal ITT status and only signed exchange revisions can cancel a session.
- [ ] Frozen evaluation uses full-path `Challenger - Champion`, conservative registered inference, `>= MEE`, absolute/incremental/current/stress/tail/capacity/coverage/integrity gates, and a deletable report.
- [ ] No broker, permit, outbox, activation, canary, real capital, or legacy headline enters the Trial path.
- [ ] Full v3 tests, fault injection, contract snapshots, flake8, `git diff --check`, docs, policy files, migration note, and AGENTS boundary all pass and agree.

## Plan Self-Review Before Execution

- [ ] Cross-check every requirement in Revision 2 design sections 3–10 against at least one task and one test above.
- [ ] Search this plan and implementation commits for unresolved placeholder markers; explanatory wildcard path notation is allowed only in file lists, never in source/test bodies.
- [ ] Verify every named type has one owner module and every producer/consumer uses the same field names, enum values, schema major, sign convention, and mode.
- [ ] Verify task commits do not stage the three user-owned paper-trading data files.
- [ ] Re-read the authoritative design and this plan immediately before implementation; if a code reality forces a semantic change, stop and amend/approve the design rather than silently adapting behavior.
