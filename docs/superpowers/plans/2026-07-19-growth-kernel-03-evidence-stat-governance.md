# PIT Evidence and Statistical Governance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把市场、信号、结果、试验、统计评估和资金授权变成可重验、双时态、不可重复消费的证据链，并确保 readiness、研究重建或多重试验不能伪造 edge。

**Architecture:** 内容寻址 blob 保存实际 payload，Evidence Store 保存信封、dependency revision 与 namespace；Outcome Finalizer 独立成熟经济结果；Trial/SAP、Attempt Ledger 和 EvidenceConsumptionLedger 在官方样本产生前封存。Authorizer 是独立 capability，只对完整组合政策签发限时授权，并在依赖更正时事务性吊销未来 entry permit。

**Tech Stack:** Python、SQLAlchemy Core/SQLite、Pydantic contracts、pandas/numpy/scipy（统计计算）、pytest。

## Global Constraints

- Depends on Plan 01; consumes Plan 02 read-only capital projections for economic outcomes.
- readiness 只能产生 SnapshotEvidence，不能生成 CapitalAuthorization。
- 旧 journal、Phase 0、research reconstruction 只能标 `PRIOR/RESEARCH`，永不成为 promotion 样本。
- 主要指标只用完整组合单位 NAV 的 excess daily log growth；单票收益、胜率、IC 只作诊断。
- 官方 sample eligibility 由信号时点决定；缺失 session 自动成为 `NO_RUN`，不能删失。
- 授权签发与 `alpha_sample_consumption_id` 消费必须在同一事务。
- SQLite 不提供表级 ACL：每个 issuer 使用独立、由对应 service principal 拥有的 namespace DB；跨 authority 查询只消费签名复制品或窄只读 API，禁止多个 issuer 共享一个可写 evidence DB。

---

## File Structure

- Create `src/screening/offensive/v3/evidence/blob_store.py`
- Create `src/screening/offensive/v3/evidence/repository.py`
- Create `src/screening/offensive/v3/evidence/dependencies.py`
- Create `src/screening/offensive/v3/evidence/outcomes.py`
- Create `src/screening/offensive/v3/evidence/trials.py`
- Create `src/screening/offensive/v3/evidence/consumption.py`
- Create `src/screening/offensive/v3/evidence/statistics.py`
- Create `src/screening/offensive/v3/evidence/authorizer.py`
- Create `src/screening/offensive/v3/evidence/projections.py`
- Create tests under `tests/offensive/v3/evidence/`

### Task 1: Content-addressed blob and bitemporal Evidence Store

**Interfaces:** Produces `BlobStore.put/get`, issuer-scoped `EvidenceRepository.publish/get/revise`, dependency Merkle roots and typed source states `SUCCESS_EMPTY | SUCCESS_NONEMPTY | FAILED | STALE`.

- [ ] **Step 1: Write failing tests** for payload round trip, hash mismatch, secure file reads, duplicate idempotency, same ID/different payload conflict, effective/observed/available ordering, legal empty overriding stale and namespace capability checks.
- [ ] **Step 2: Verify RED** with `uv run pytest tests/offensive/v3/evidence/test_{blob_store,repository}.py -v`.
- [ ] **Step 3: Implement atomic blob publication** and DB envelope transaction. Blob must be durable before envelope commit; orphan blobs are harmless and garbage-collected only after reachability audit.

```python
def publish(self, signed: SignedEnvelope, payload: bytes) -> EvidenceRecord:
    verified = self.verifier.verify(signed, required_capability(signed.kind))
    if sha256(payload).hexdigest() != signed.payload_content_hash:
        raise EvidenceConflict("payload hash mismatch")
    blob_uri = self.blobs.put(payload)
    return self._insert_idempotent(signed, blob_uri, verified)
```

- [ ] **Step 4: Verify GREEN**; rerun after process restart.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): persist bitemporal reproducible evidence"`.

### Task 2: Full signal funnel and expected-session spine

**Interfaces:** Produces `record_signal_funnel()`, `enroll_expected_sessions()`, `finalize_session_status()` and queries by producer/family/behavior/mode.

- [ ] **Step 1: Write failing tests** proving candidate/data_eligible/selected stages are distinct, all rejected candidates retain reasons, Auto carries `execution_authority=none` only in report projection, and missing daily runs become `NO_RUN` at finalization.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement immutable session spine** from official calendar before enrollment. Allowed statuses are exactly `RUN | NO_SIGNAL | BLOCKED | NO_RUN | DATA_UNKNOWN`; a later run may fill an unfinalized expected slot but cannot delete a finalized status.
- [ ] **Step 4: Verify GREEN** with `uv run pytest tests/offensive/v3/evidence/test_signal_funnel.py -v`.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): retain complete signal and session funnel"`.

### Task 3: Outcome Finalizer and execution-mode separation

**Interfaces:** Consumes Plan 02 `economic_lot`/NAV read models. Produces `OutcomeFinalizer.finalize_due(as_of)` and `OutcomeEvidence` with finality/missing reasons.

- [ ] **Step 1: Write failing tests** for T+1/T+10 session ordinals, partial fills, EXIT_PENDING, fee/company-action finality, raw close exclusion, proxy/manual/broker namespace separation, correction revision and unavailable outcomes.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement finalizer**. Simple round-trip may expose diagnostic `R_net`; complex lots aggregate all cash flows. Official portfolio outcomes come from daily unit NAV, not candidate rows.
- [ ] **Step 4: Verify GREEN** with `uv run pytest tests/offensive/v3/evidence/test_outcomes.py -v`.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): finalize execution-matched outcomes"`.

### Task 4: Trial/SAP, Attempt Ledger, and sample consumption

**Interfaces:** Produces `seal_trial()`, `seal_stage()`, `record_attempt()`, `reserve_sample()`, `consume_sample()` and reuse matrix validation.

- [ ] **Step 1: Write failing tests** for trial-before-signal, program/lineage identity, one champion + one challenger, failed/abandoned attempts consuming budget, fixed assessment dates, central governance floors and cross-lineage sample-repackaging rejection.

```python
def test_primary_sample_cannot_be_repackaged(repo) -> None:
    repo.consume(primary_consumption(evidence_id="e1", stage_id="s1"))
    with pytest.raises(SampleReuseConflict):
        repo.consume(primary_consumption(evidence_id="e1", stage_id="s2"))
```

- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement DB uniqueness** on `(research_program_id, evidence_id, evaluation_unit, role=PRIMARY_PROMOTION)` and exact idempotency. Governance policy may be more conservative per trial, never looser.
- [ ] **Step 4: Verify GREEN** with `uv run pytest tests/offensive/v3/evidence/test_{trials,consumption}.py -v`.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): seal trials attempts and evidence consumption"`.

### Task 5: Continuous portfolio evaluator and conservative gates

**Interfaces:** Produces `PortfolioEvaluation`, `evaluate_frozen_policy()`, `evaluate_predictable_adaptive()`, `check_minimum_evidence()` and `check_tail_capacity()`.

- [ ] **Step 1: Write deterministic tests** with fixed fixtures for excess log growth, paired champion/challenger days, ESS, chronological folds, MEE, 2× slippage, adverse window, MDD/CDaR/overshoot, capacity stress and pending finality.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement transparent initial estimator**: raw daily log excess mean + pre-registered one-sided 95% lower bound; block bootstrap only for complete continuous frozen-policy paired paths. Stateful tail metrics come from continuous replay, never stitched NAV blocks.

```python
def minimum_evidence_ok(s: EvidenceSummary, gate: GovernanceGate) -> bool:
    return all((
        s.mature_outcomes >= 150,
        s.decision_days >= 60,
        s.ess >= Decimal("60"),
        s.distinct_tickers >= 80,
        s.coverage_months >= 12,
        s.adverse_window_complete,
    ))
```

- [ ] **Step 4: Verify GREEN and golden numbers** with `uv run pytest tests/offensive/v3/evidence/test_statistics.py -v`.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): evaluate conservative portfolio growth gates"`.

### Task 6: Authorizer, exploration governance, and dependency revalidation

**Interfaces:** Produces `Authorizer.assess_and_issue()`, `GovernanceIssuer.issue_exploration()`, `DependencyTracker.revise()` and authorization states `ACTIVE | EDGE_REVALIDATION_REQUIRED | REVOKED | EXPIRED | DRAINING`.

- [ ] **Step 1: Write adversarial tests** for missing benchmark, stale estimator, mode/lineage/version mismatch, below-MEE LCB, target worse than baseline, tail breach, repeated issuance, exploration >2%, exploration renewal, outstanding risk, combined program cap and evidence correction.
- [ ] **Step 2: Verify RED**.
- [ ] **Step 3: Implement issuance transaction**: lock assessment, attempt checkpoint and sample slot; re-evaluate frozen Trial/SAP; consume sample; persist authorization payload/hash; call isolated signer port; commit. On evidence revision, the same Authorizer transaction changes state、increments `capital_authorization_version` and appends a signed revocation outbox record；因为每个 permit 绑定旧 version，这次递增在逻辑上立即使全部未消费 permit 失效。Plan 04/07 gateway 在最终提交时同步重验 Authorizer 当前状态/version，Authorizer 不可用则零提交；本地 permit projection 随 revocation outbox 幂等收敛，不依赖跨 SQLite 分布式事务保证安全。
- [ ] **Step 4: Verify GREEN** with `uv run pytest tests/offensive/v3/evidence/test_{authorizer,revalidation}.py -v`.
- [ ] **Step 5: Commit** with `git commit -m "feat(v3): gate and revalidate capital authorizations"`.

### Task 7: Evidence projections, audit command, and compatibility import

**Interfaces:** Produces read-only health/audit projections and a research-only importer for current setup log/panel/journal corrections.

- [ ] **Step 1: Write tests** proving imported legacy evidence is forced to `RESEARCH_RECONSTRUCTION` or `PRIOR`, cannot acquire promotion role, records missing payload provenance and never mutates originals.
- [ ] **Step 2: Implement** `scripts/v3_import_research_evidence.py` with `--dry-run` default and explicit destination under an isolated v3 research DB.
- [ ] **Step 3: Verify**:

```bash
uv run pytest tests/offensive/v3/evidence/ -v
uv run pytest tests/offensive/test_join_setup_outputs.py tests/offensive/test_setup_performance.py -q
uv run python scripts/v3_import_research_evidence.py --dry-run
git diff --check
```

Expected: tests pass; command reports counts and `authorization_eligible=0`.

- [ ] **Step 4: Update `AGENTS.md`** with implemented evidence roles and the explicit “no current edge authorization” status.
- [ ] **Step 5: Commit** exact evidence, test, script and documentation files.

## Completion Gate

- [ ] Every evidence hash resolves to retained payload and parser/source metadata.
- [ ] Every official session has an ITT status; missing pipeline runs cannot disappear.
- [ ] Mode and behavior generations cannot share official promotion samples.
- [ ] Authorization issuance and sample consumption are atomic and one-time.
- [ ] Evidence correction immediately blocks future entry while preserving exits and historical audit.
