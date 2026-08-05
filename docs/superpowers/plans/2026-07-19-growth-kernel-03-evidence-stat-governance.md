# PIT Evidence, Statistical Governance, and Authorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把市场、信号、结果、试验、统计评估、全局多重性预算和授权候选变成可重验、受信时间轴、不可换 ID 重复消费的证据链；readiness、legacy 研究、partial fill 或 outcome revision 均不能伪造新 edge。

**Architecture:** 内容寻址 blob 保存原文；Evidence Store 追加自己控制的 `ingested_at`/`commit_sequence` 和 revision；Outcome Finalizer 从 Plan 02 资本投影生成 mode-pure 结果。Trial/SAP/Stage、Attempt reservation、expected-session spine 和 target `PolicySnapshot` registration 在信号前冻结。Authorizer 只签 `EDGE` envelope；Governance issuer 签 `EXPLORATION`/`RECOVERY` 候选。任何 correction 先取得 Capital Gateway 的 `EntryFenceRaised` durable ACK，再激活 evidence revision，不声称跨库事务。

**Tech Stack:** Python、SQLAlchemy Core/SQLite、Pydantic Revision 2 contracts、pandas/numpy/scipy、pytest。

## Global Constraints

- Depends on Plan 01；只读消费 Plan 02 economic/NAV projections。
- readiness 只能形成 `SnapshotEvidence`，不能形成 edge assessment 或 authorization。
- legacy journal/Phase 0/reconstruction 只能是 `PRIOR | RESEARCH_RECONSTRUCTION`，不可进入 primary promotion role。
- 官方目标是完整组合单位 NAV 的 excess daily log growth；单票收益、胜率和 IC 只作诊断。
- `provider_published_at` 来自源；`observed_at` 来自受信采集器；`ingested_at`、`commit_sequence`、active revision 只能由 Evidence Store 写。
- official OOS 只消费 signal cutoff 前已 commit 的 evidence；读取 wall-clock 或事后 correction 不得改变历史决策输入。
- 每个 issuer 拥有独立 writable namespace DB；跨 authority 只传签名不可变对象或窄 API。
- envelope issuance 与本 authority 的 sample/attempt/multiplicity budget 消费同一事务；Capital Gateway activation 是后续独立 CAS。

---

## File Structure

- Create `src/screening/offensive/v3/evidence/blob_store.py`
- Create `src/screening/offensive/v3/evidence/repository.py`
- Create `src/screening/offensive/v3/evidence/dependencies.py`
- Create `src/screening/offensive/v3/evidence/session_spine.py`
- Create `src/screening/offensive/v3/evidence/outcomes.py`
- Create `src/screening/offensive/v3/evidence/trials.py`
- Create `src/screening/offensive/v3/evidence/attempts.py`
- Create `src/screening/offensive/v3/evidence/consumption.py`
- Create `src/screening/offensive/v3/evidence/multiplicity.py`
- Create `src/screening/offensive/v3/evidence/statistics.py`
- Create `src/screening/offensive/v3/evidence/authorizer.py`
- Create `src/screening/offensive/v3/governance/repository.py`
- Create `src/screening/offensive/v3/governance/issuer.py`
- Create `src/screening/offensive/v3/evidence/projections.py`
- Create `scripts/v3_import_research_evidence.py`
- Create tests under `tests/offensive/v3/evidence/` and `tests/offensive/v3/governance/`

### Task 1: Content-addressed revisioned PIT Evidence Store

**Interfaces:** Produces `BlobStore.put/get`, issuer-scoped `EvidenceRepository.publish/get/prepare_revision/activate_revision`, an `EvidenceRepository` implementation of final `EvidenceQueryPort.active_revision()/outcome()`, store commit sequence and dependency Merkle roots.

- [x] **Step 1: Write failing tests** in `test_blob_store.py` and `test_repository.py` for payload round-trip/hash mismatch, secure file reads, duplicate/same-ID conflict, effective/published/observed/ingested/available ordering, trusted-clock stamp ownership, commit sequence monotonicity, revision/supersedes chain, legal empty overriding stale and issuer namespace.
- [x] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/evidence/test_{blob_store,repository}.py -v`.
- [x] **Step 3: Implement durable blob-before-envelope publication**. Orphan blob is safe; envelope without durable payload is impossible. Producer payload cannot set store-controlled timestamps/sequence/active revision.

```python
def publish(self, signed: SignedEnvelope, payload: bytes) -> ActiveEvidenceRecord:
    trusted_at = self.clock.now()
    verified = self.verifier.verify(
        signed,
        required_capability(signed.artifact),
        current_head=self.authority.current_trust_head(trusted_at),
        trusted_at=trusted_at,
    )
    self._require_payload_hash(signed, payload)
    blob = self.blobs.put_durable(payload)
    with self.db.begin_immediate() as tx:
        return tx.insert_with_store_time_and_sequence(signed, blob, verified)
```

`publish()`/`get()` must decode all four concrete record variants through `TypeAdapter(ActiveEvidenceRecord).validate_json(..., strict=True)`. The storage round-trip must preserve the concrete type, full value, and `artifact_hash()` exactly; a bare generic record or construction path that bypasses validation is forbidden.

- [x] **Step 4: Verify GREEN** after restart and concurrent publisher tests.
- [x] **Step 5: Commit** with `git commit -m "feat(v3): persist trusted revisioned evidence"`.

### Task 2: Pre-sealed trial, target registration, and expected-session spine

**Interfaces:** Produces atomic `reserve_attempt_and_seal_trial()`, immutable target-policy registration, `enroll_expected_sessions()` and session revisions `RUN | NO_SIGNAL | BLOCKED | NO_RUN | DATA_UNKNOWN | SESSION_CANCELLED`.

- [x] **Step 1: Write failing tests** for seal-before-signal cutoff, immutable economic lineage/program, exactly one champion/challenger, target `PolicySnapshot` registration that is explicitly non-executable, fixed assessment dates and calendar spine enrollment before observations.
- [x] **Step 2: Add tests** proving attempt reservation and Trial/SAP seal either both commit or neither; cancelled exchange sessions use a signed calendar revision and `SESSION_CANCELLED`, not deletion; finalized missing run becomes `NO_RUN`.
- [x] **Step 3: Verify RED** with `uv run pytest tests/offensive/v3/evidence/test_{trials,session_spine}.py -v`.
- [x] **Step 4: Implement one governance transaction** for attempt reservation + Trial/SAP/Stage seal + target registration. Activation types are rejected from this repository.
- [x] **Step 5: Verify and commit** with `git commit -m "feat(v3): seal trials targets and expected sessions"`.

### Task 3: Outcome Finalizer, plan-line identity, and mode-pure portfolio paths

**Interfaces:** Produces `OutcomeFinalizer.finalize_due(as_of)` and `OutcomeEvidence` revisions tied to `plan_line_economic_contract_key` plus distinct decision-day evaluation units.

- [x] **Step 1: Write failing tests** for T+1/T+10 session ordinals, no-fill, partial fill, late fill, EXIT_PENDING, fee/company-action finality, raw close exclusion, proxy/manual/broker separation, bust/reopen and unavailable finality.
- [x] **Step 2: Add counting tests** proving all partial fills/fee revisions/corrections of one plan-line contract count as one mature outcome, while each pre-registered decision day contributes at most one governance evaluation unit; 150 outcomes and 60 decision days/ESS remain separate fields.
- [x] **Step 3: Verify RED** with `uv run pytest tests/offensive/v3/evidence/test_outcomes.py -v`.
- [x] **Step 4: Implement finalizer** from AccountCapitalTruth/read models. Official portfolio path uses daily unit NAV by mode projection; broker account economics remain complete even if an out-of-protocol trade is unattributed.
- [x] **Step 5: Verify and commit** with `git commit -m "feat(v3): finalize economic outcomes without sample inflation"`.

### Task 4: Attempt, dual-key evidence consumption, and global multiplicity ledgers

**Interfaces:** Produces `AttemptLedger`, `EvidenceConsumptionLedger`, `GlobalMultiplicityBudgetLedger`, `reserve_evaluation_units()` and `consume_primary_promotion()`.

- [x] **Step 1: Write failing tests** for failed/abandoned attempt consumption, fixed plan, cross-lineage/program repackaging, concurrent reservations, outcome revision, partial fill and relabeled evaluation unit.
- [x] **Step 2: Create independent DB uniqueness constraints**:

```text
(research_program_id, evidence_id, PRIMARY_PROMOTION)
(research_program_id, governance_minted_evaluation_unit_id, PRIMARY_PROMOTION)
```

Do not collapse them into one four-column key.

- [x] **Step 3: Add global multiplicity tests** proving a new program/lineage/name cannot escape the governance-wide alpha/e-value budget; idempotent retry returns the original consumption, conflicting retry writes nothing.
- [x] **Step 4: Verify RED/GREEN** with `uv run pytest tests/offensive/v3/evidence/test_{attempts,consumption,multiplicity}.py -v`.
- [x] **Step 5: Commit** with `git commit -m "feat(v3): prevent evidence and evaluation-unit reuse"`.

### Task 5: Continuous portfolio evaluator and conservative promotion gates

**Interfaces:** Produces `PortfolioEvaluation`, `evaluate_frozen_policy()`, `evaluate_predictable_adaptive()`, `check_minimum_evidence()` and `check_tail_capacity()`.

- [x] **Step 1: Write deterministic golden tests** for excess daily log growth, paired champion/challenger decision days, outcome count, decision-day count, ESS, chronological outer folds, MEE, one-sided 95% LCB, 2x slippage, adverse window, MDD/CDaR/overshoot, capacity and pending finality.
- [x] **Step 2: Add leakage tests** proving outer future windows never tune hyperparameters and official OOS checks store `ingested_at/commit_sequence <= signal cutoff`; post-cutoff revision is excluded from the original evaluation.
- [x] **Step 3: Verify RED** with `uv run pytest tests/offensive/v3/evidence/test_statistics.py -v`.
- [x] **Step 4: Implement transparent estimators**. Stateful tail metrics use continuous replay or complete per-scenario replay, never stitched independent return blocks. Minimum evidence checks 150 mature plan-line outcomes, 60 decision days, ESS >= 60, 80 tickers, 12 months and a complete adverse window as distinct predicates.
- [x] **Step 5: Verify and commit** with `git commit -m "feat(v3): evaluate conservative continuous portfolio evidence"`.

### Task 6: EDGE Authorizer and governed EXPLORATION/RECOVERY issuance

**Interfaces:** Produces `Authorizer.assess_and_issue_edge()`, `GovernanceIssuer.issue_exploration()`, `issue_recovery()` and signed inactive `CapitalAuthorizationEnvelope` candidates.

- [x] **Step 1: Write adversarial tests** for stale/missing benchmark, mode/account/behavior/cost mismatch, below-MEE LCB, target worse than baseline, tail breach, reused sample/budget, multiple independent envelopes, exploration >2%, exploration renewal, first broker portfolio >2%, recovery ignoring inherited risk/loss and expired manifest.
- [x] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/evidence/test_authorizer.py tests/offensive/v3/governance/test_issuer.py -v`.
- [x] **Step 3: Implement separate issuer transactions**. Authorizer alone signs `EDGE`; Governance alone signs `EXPLORATION | RECOVERY`. `EXPLORATION` 强制 `BROKER_CONFIRMED` 且只声明受限证据采集，不声明 live edge；`RECOVERY` 引用既有 grants/assessments 和全部继承风险/loss versions，不制造新 grant。Each transaction consumes its local attempt/sample/global budget and signs one complete target portfolio envelope. Result remains inactive until Plan 04 Gateway CAS.
- [x] **Step 4: Add signer-failure test**: a failed external signer call leaves no consumption or issued envelope; a retry is deterministic.
- [x] **Step 5: Verify and commit** with `git commit -m "feat(v3): issue complete governed authorization envelopes"`.

### Task 7: Fail-closed dependency correction and research-only import

**Interfaces:** Produces `DependencyTracker.prepare_correction()`, `EntryFenceClient.raise_and_wait_ack()`, `activate_corrected_revision()` and a dry-run-first legacy importer.

- [x] **Step 1: Write crash/race tests** for correction prepare, Gateway unavailable, fence ACK persisted, crash before revision activation, duplicate fence, old authorization status and concurrent entry attempt. Safety rule: revision is never active before durable fence ACK; fence-without-activation may overblock but never underblock.
- [x] **Step 2: Implement the protocol** using a Plan 04 port fake now; Plan 04 replaces it with the real Gateway. Do not hold an Evidence DB transaction open across network I/O and do not claim distributed atomicity.
- [x] **Step 3: Implement** `scripts/v3_import_research_evidence.py --dry-run` forcing imported material to `RESEARCH_RECONSTRUCTION | PRIOR`, retaining provenance gaps and `authorization_eligible=0`.
- [x] **Step 4: Run full checks**.

```bash
uv run pytest tests/offensive/v3/evidence/ tests/offensive/v3/governance/ -v
uv run pytest tests/offensive/test_join_setup_outputs.py tests/offensive/test_setup_performance.py -q
uv run python scripts/v3_import_research_evidence.py --dry-run
git diff --check
```

Expected: all pass; importer mutates no source and reports `authorization_eligible=0`.

- [ ] **Step 5: Update `AGENTS.md`** with implemented evidence/governance roles and “no active capital envelope” status, then commit scoped files.

## Completion Gate

- [x] Every evidence hash resolves to retained payload, source/parser metadata and trusted store time/sequence.
- [x] Every enrolled official session has an immutable status or signed cancellation revision.
- [x] Partial fill/correction cannot inflate outcome or decision-day counts.
- [x] Both primary-promotion unique keys and the global multiplicity budget are enforced under concurrency.
- [x] EDGE/EXPLORATION/RECOVERY issuer capabilities are distinct; every candidate envelope is a complete portfolio policy and inactive by default.
- [x] Correction activation always follows durable Gateway entry-fence ACK; exits remain unaffected.
