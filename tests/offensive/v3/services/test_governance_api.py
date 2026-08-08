"""Plan 05 Task 2 (RED): GovernanceApi 能力矩阵 + seal/issuance 行为。

覆盖 Step 1 能力矩阵(import 边界、无 gateway/capital 方法、kind 隔离、
signer 私有)与 Step 3 行为(seal_trial 显式 signed approval 强制、
EXPLORATION/RECOVERY 产出 INACTIVE 候选且 namespace 正确、幂等、
signer 失败无残留)。

本文件引用尚未实现的服务骨架(方法体一律 raise NotImplementedError);
当前应整体 RED, 由主代理随后实现 GREEN。
"""

from __future__ import annotations

from base64 import b64encode
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.screening.offensive.v3 import trust
from src.screening.offensive.v3.contracts import ExecutionMode
from src.screening.offensive.v3.contracts.authorization import (
    AuthorizationKind,
    CapitalAuthorizationEnvelope,
)
from src.screening.offensive.v3.contracts.governance import (
    GrantKind,
    LineageGrant,
    PrimaryMetric,
    StatisticalAnalysisPlan,
    TrialManifest,
)
from src.screening.offensive.v3.evidence.consumption import (
    AttemptLedger,
    AttemptStatus,
    EvidenceConsumptionLedger,
    GlobalMultiplicityBudgetLedger,
    MultiplicityBudgetKind,
)
from src.screening.offensive.v3.governance.issuer import (
    ExplorationIssuanceRequest,
    IssuerError,
    RecoveryIssuanceRequest,
)
from src.screening.offensive.v3.governance.repository import (
    GovernanceStoreError,
    TrialSealRequest,
)
from src.screening.offensive.v3.services import governance_api as gv_module
from src.screening.offensive.v3.services.governance_api import (
    APPROVAL_ARTIFACT_KINDS,
    GovernanceApi,
    SEAL_APPROVAL_ARTIFACT_REJECTED,
    SEAL_APPROVAL_NAMESPACE_MISMATCH,
    SEAL_APPROVAL_REQUIRED,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
HASH = "a" * 64
HASH2 = "b" * 64
TARGET_HASH = HASH2
PROGRAM = "prog-1"
LINEAGE = "eline-1"
PORTFOLIO = "paper-v3"
MODE = ExecutionMode.DAILY_BAR_PROXY
GOV_NAMESPACE = "capital.governance.btst"

GATEWAY_METHODS = (
    "activate_trust_bundle",
    "activate_policy_and_envelope",
    "replace_envelope",
    "raise_entry_fence",
    "acknowledge_fence",
    "active_state",
    "publish_entry",
    "issue_permit",
    "make_outbox_durable",
)
CAPITAL_METHODS = (
    "run_append",
    "append_atomic",
    "record_fill_revision",
    "record_fee_revision",
    "confirm_observed_nav",
)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value


# --------------------------------------------------------------------------
# trial/SAP fixtures (test_trials.py 风格)
# --------------------------------------------------------------------------


def _trial_manifest(**overrides) -> TrialManifest:
    values = {
        "family_id": "btst.limit-up-breakout",
        "economic_lineage_id": LINEAGE,
        "research_program_id": PROGRAM,
        "trial_id": "trial-001",
        "baseline_portfolio_policy_fingerprint": HASH,
        "target_portfolio_policy_fingerprint": TARGET_HASH,
        "trust_bundle_hash": HASH,
        "registry_epoch": 1,
        "baseline_policy_activation_hash": HASH,
        "target_policy_snapshot_registration_hash": TARGET_HASH,
        "attempt_ledger_checkpoint_before_trial": HASH,
        "attempt_budget_reservation_id": "attempt-001",
        "statistical_governance_policy_version": "stat-gov.v1",
        "champion_behavior_fingerprint": HASH,
        "challenger_behavior_fingerprint": "c" * 64,
        "primary_metric": PrimaryMetric.PORTFOLIO_LOG_GROWTH,
        "minimum_economic_effect": Decimal("0.001"),
        "weight_selection_rule": "fixed-50-50",
        "trial_manifest_sealed_at": NOW,
        "enrollment_start": NOW + timedelta(days=1),
        "enrollment_end": NOW + timedelta(days=30),
        "followup_finality_date": NOW + timedelta(days=60),
        "fixed_assessment_date": NOW + timedelta(days=90),
        "execution_version": "t1-open-t10-open.v1",
        "cost_version": "cn-a-share-costs.v1",
        "execution_mode": ExecutionMode.DAILY_BAR_PROXY,
        "benchmark_definition": "csi300-total-return",
        "capacity_policy": "capacity.v1",
        "tail_risk_policy": "tail.v1",
        "estimator": "wild-bootstrap",
        "one_sided_confidence_level": Decimal("0.95"),
        "bootstrap_method": "wild",
        "bootstrap_repetitions": 10_000,
        "bootstrap_seed": 42,
        "block_rule": "monthly",
        "ess_definition": "kish",
        "missing_censoring_itt_rule": "itt",
        "fold_boundaries": ("2026-09-01", "2026-10-01"),
        "purge_embargo": "purge-5d",
        "promotion_boolean_expression": "lcb > mee",
        "multiplicity_policy": "program-global",
        "broker_experiment_design": None,
        "canonical_outcome_counting_rule": "plan-line-contract",
        "stage_loss_measurement_basis": "stage-budget",
        "issuer_id": "governance.service",
        "issuer_capability": "governance.trial.manifest.v1",
        "issued_at": NOW,
        "expires_at": NOW + timedelta(days=120),
        "schema_major": 2,
    }
    values.update(overrides)
    return TrialManifest(**values)


def _sap_manifest(trial: TrialManifest, **overrides) -> StatisticalAnalysisPlan:
    values = {
        "sap_id": trial.trial_id,
        "trial_manifest_hash": trial.artifact_hash(),
        "research_program_id": trial.research_program_id,
        "economic_lineage_id": trial.economic_lineage_id,
        "primary_metric": PrimaryMetric.PORTFOLIO_LOG_GROWTH,
        "baseline_portfolio_policy_fingerprint": (
            trial.baseline_portfolio_policy_fingerprint
        ),
        "target_portfolio_policy_fingerprint": (
            trial.target_portfolio_policy_fingerprint
        ),
        "execution_mode": trial.execution_mode,
        "one_sided_confidence_level": Decimal("0.95"),
        "bootstrap_method": "wild",
        "repetitions": 10_000,
        "seed": 42,
        "block_rule": "monthly",
        "multiplicity_policy": "program-global",
        "alpha_or_evalue_budget_consumption_id": "budget-001",
        "issued_at": NOW,
        "sealed_at": NOW,
        "enrollment_start": trial.enrollment_start,
        "expires_at": NOW + timedelta(days=120),
        "issuer_id": "governance.service",
        "issuer_capability": "governance.sap.v1",
        "schema_major": 2,
    }
    values.update(overrides)
    return StatisticalAnalysisPlan(**values)


def _seal_request(**overrides) -> TrialSealRequest:
    trial = overrides.pop("trial_manifest", None) or _trial_manifest()
    sap = overrides.pop("sap_manifest", None) or _sap_manifest(trial)
    values = {
        "attempt_budget_reservation_id": trial.attempt_budget_reservation_id,
        "stage_id": "stage-1",
        "role": "champion",
        "trial_manifest": trial,
        "sap_manifest": sap,
        "policy_snapshot_json": '{"policy": "target"}',
        "policy_fingerprint": trial.target_portfolio_policy_fingerprint,
        "target_policy_snapshot_registration_hash": (
            trial.target_policy_snapshot_registration_hash
        ),
        "expected_signal_cutoff": NOW + timedelta(days=1),
    }
    values.update(overrides)
    return TrialSealRequest(**values)


# --------------------------------------------------------------------------
# envelope fixtures (test_authorizer.py 风格)
# --------------------------------------------------------------------------


def _grant(**overrides):
    values = {
        "grant_id": "grant-1",
        "grant_kind": GrantKind.EDGE,
        "grant_certificate_hash": HASH,
        "grant_issuer_id": "governance.service",
        "subject_producer": "btst",
        "family_id": "btst.limit-up-breakout",
        "economic_lineage_id": LINEAGE,
        "research_program_id": PROGRAM,
        "behavior_fingerprint": HASH,
        "execution_version": "t1-open-t10-open.v1",
        "cost_version": "cn-a-share-costs.v1",
        "capital_tier": 2,
        "lineage_gross_cap": Decimal("0.02"),
        "trial_id": "trial-001",
        "trial_manifest_hash": HASH,
        "statistical_analysis_plan_hash": HASH,
        "stage_id": "stage-1",
        "stage_manifest_hash": HASH,
        "stage_sample_reservation_id": "reservation-1",
        "stage_loss_budget_id": "budget-1",
        "stage_loss_budget_cents": 100_000,
        "stage_loss_version": 1,
        "assessment_result_hash": HASH,
        "grant_evidence_set_merkle_root": HASH,
        "attempt_ledger_checkpoint_hash": HASH,
        "alpha_or_evalue_budget_consumption_id": "budget-consumption-1",
        "alpha_sample_consumption_id": "sample-consumption-1",
        "schema_major": 2,
    }
    values.update(overrides)
    return LineageGrant(**values)


def _binding(**overrides):
    from src.screening.offensive.v3.contracts.governance import (
        ProgramLossBudgetBinding,
    )

    values = {
        "research_program_id": PROGRAM,
        "budget_id": "budget-1",
        "budget_cents": 100_000,
        "consumed_cents": 0,
        "version": 3,
        "schema_major": 2,
    }
    values.update(overrides)
    return ProgramLossBudgetBinding(**values)


def _envelope(
    *,
    kind: AuthorizationKind,
    risk_epoch: int = 1,
    **overrides,
) -> CapitalAuthorizationEnvelope:
    values: dict = {
        "authorization_kind": kind,
        "authorization_id": "auth-gov-1",
        "authorization_version": 1,
        "mode": MODE,
        "portfolio_id": PORTFOLIO,
        "broker_account_id": None,
        "broker_account_fingerprint": None,
        "base_currency": "CNY",
        "policy_activation_hash": HASH,
        "trust_bundle_hash": HASH,
        "registry_epoch": 1,
        "policy_epoch": 1,
        "authority_epoch": 1,
        "risk_epoch": risk_epoch,
        "research_program_ids": (PROGRAM,),
        "baseline_portfolio_policy_fingerprint": HASH,
        "target_portfolio_policy_fingerprint": HASH2,
        "evidence_as_of": NOW - timedelta(days=1),
        "evidence_set_merkle_root": HASH,
        "issued_at": NOW,
        "expires_at": NOW + timedelta(days=1),
        "activation_capital_snapshot_id": "snapshot-1",
        "activation_capital_snapshot_hash": HASH,
        "program_loss_budget_bindings": (_binding(),),
        "issuer_id": "governance.service",
        "portfolio_assessment_result_hash": HASH,
        "global_attempt_ledger_checkpoint_hash": HASH,
        "global_multiplicity_budget_consumption_id": "consumption-1",
        "schema_major": 2,
    }
    if kind is AuthorizationKind.EDGE:
        values.update(
            {
                "issuer_capability": "authorizer.edge.envelope.v1",
                "portfolio_gross_cap": Decimal("0.02"),
                "exploration_aggregate_gross_cap": Decimal("0"),
                "lineage_grants": (_grant(),),
            }
        )
    elif kind is AuthorizationKind.EXPLORATION:
        exploration_grant = _grant(
            grant_kind=GrantKind.EXPLORATION,
            capital_tier=2,
            lineage_gross_cap=Decimal("0.02"),
            shared_exploration_loss_budget_id="shared-budget-1",
        )
        values.update(
            {
                "mode": ExecutionMode.BROKER_CONFIRMED,
                "broker_account_id": "acct-1",
                "broker_account_fingerprint": HASH,
                "issuer_capability": "governance.exploration.envelope.v1",
                "portfolio_gross_cap": Decimal("0.02"),
                "exploration_aggregate_gross_cap": Decimal("0.02"),
                "lineage_grants": (exploration_grant,),
                "exploration_shared_stress_loss_budget_id": (
                    "shared-budget-1"
                ),
                "exploration_shared_stress_loss_budget_cents": 100_000,
                "exploration_shared_stress_loss_consumed_cents": 0,
                "exploration_shared_stress_loss_version": 1,
                "exploration_one_shot_reservation_id": "one-shot-res-1",
                "exploration_one_shot_consumption_id": (
                    "one-shot-consumption-1"
                ),
                "exploration_trial_id": exploration_grant.trial_id,
                "exploration_fixed_assessment_at": NOW
                + timedelta(days=30),
            }
        )
    else:  # RECOVERY
        recovery_grant = _grant(
            grant_kind=GrantKind.EDGE,
            capital_tier=2,
            lineage_gross_cap=Decimal("0.02"),
        )
        values.update(
            {
                "issuer_capability": "governance.recovery.envelope.v1",
                "portfolio_gross_cap": Decimal("0.02"),
                "exploration_aggregate_gross_cap": Decimal("0"),
                "lineage_grants": (recovery_grant,),
                "predecessor_active_authorization_id": "auth-prior",
                "predecessor_active_authorization_version": 2,
                "predecessor_active_authorization_hash": HASH,
                "predecessor_active_authorization_status_hash": HASH,
                "predecessor_target_policy_fingerprint": HASH2,
                "predecessor_active_edge_grant_certificate_hashes": (
                    recovery_grant.grant_certificate_hash,
                ),
                "recovery_inherited_risk_version": risk_epoch,
                "recovery_open_pending_risk_version": risk_epoch,
                "recovery_stage_program_loss_consumption_version": 3,
                "risk_epoch_started_hash": HASH,
                "recovery_manifest_hash": HASH,
            }
        )
    values.update(overrides)
    return CapitalAuthorizationEnvelope(**values)


# --------------------------------------------------------------------------
# signer / approval fixtures
# --------------------------------------------------------------------------


def _governance_signer():
    import hashlib as _hashlib

    def sign(payload: bytes):
        envelope = CapitalAuthorizationEnvelope.model_validate_json(payload)
        artifact = (
            trust.ArtifactKind.EXPLORATION_AUTHORIZATION
            if envelope.authorization_kind is AuthorizationKind.EXPLORATION
            else trust.ArtifactKind.RECOVERY_AUTHORIZATION
        )
        digest = _hashlib.sha256(payload).hexdigest()
        return trust.SignedEnvelope(
            issuer_id="governance.service",
            key_id="key-1",
            schema_major=2,
            artifact=artifact,
            namespace=GOV_NAMESPACE,
            mode=envelope.mode,
            capability_version="capital.governance.v1",
            capability_scope="portfolio:paper-v3",
            payload_hash=digest,
            payload=payload,
            signature=b64encode(b"0" * 64).decode("ascii"),
        )

    return sign


def _approval(
    *,
    namespace: str = GOV_NAMESPACE,
    artifact: trust.ArtifactKind = trust.ArtifactKind.TRIAL_MANIFEST,
) -> trust.SignedEnvelope:
    """One explicit signed approval input for seal_trial."""
    return trust.SignedEnvelope(
        issuer_id="governance.root",
        key_id="root-key-1",
        schema_major=2,
        artifact=artifact,
        namespace=namespace,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        capability_version="governance.manifest.approve.v1",
        capability_scope="trial-seal:approval",
        payload_hash="0" * 64,
        payload=b'{"approval": true}',
        signature=b64encode(b"0" * 64).decode("ascii"),
    )


class _FailingSigner:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, payload: bytes):
        self.calls += 1
        raise RuntimeError("external signer unavailable")


@pytest.fixture()
def ledgers(tmp_path: Path):
    budget = GlobalMultiplicityBudgetLedger(
        str(tmp_path / "budget.sqlite3")
    )
    budget.set_budget(MultiplicityBudgetKind.ALPHA, 100)
    attempts = AttemptLedger(
        str(tmp_path / "attempts.sqlite3"),
        budget=budget,
        clock=_Clock(NOW),
    )
    consumption = EvidenceConsumptionLedger(
        str(tmp_path / "consumption.sqlite3"),
        attempts=attempts,
        clock=_Clock(NOW),
    )
    return budget, attempts, consumption


def _make_api(tmp_path: Path, ledgers, *, signer=None) -> GovernanceApi:
    _, attempts, consumption = ledgers
    return GovernanceApi(
        database_path=str(tmp_path / "governance.sqlite3"),
        signer=signer or _governance_signer(),
        clock=_Clock(NOW),
        attempts=attempts,
        consumption=consumption,
        issuer_namespace=GOV_NAMESPACE,
    )


@pytest.fixture()
def api(tmp_path: Path, ledgers) -> GovernanceApi:
    return _make_api(tmp_path, ledgers)


def _reserve(attempts, attempt_id: str) -> None:
    attempts.reserve(
        attempt_id=attempt_id,
        research_program_id=PROGRAM,
        economic_lineage_id=LINEAGE,
        family_id="btst.limit-up-breakout",
        frozen_plan_hash=HASH,
    )


def _forbidden_import_segments(source: str) -> list[str]:
    violations: list[str] = []
    for line in source.splitlines():
        if not line or line[0].isspace():
            continue
        if line.startswith("import "):
            module = (
                line[len("import "):].split(" as ")[0].split(",")[0].strip()
            )
        elif line.startswith("from "):
            module = line[len("from "):].split(" import ")[0].strip()
        else:
            continue
        for segment in module.split("."):
            if segment in {"capital", "gateway", "execution"}:
                violations.append(line)
                break
    return violations


# --------------------------------------------------------------------------
# Step 1: 能力矩阵
# --------------------------------------------------------------------------


def test_import_boundaries_no_capital_gateway_execution(api: GovernanceApi) -> None:
    source = Path(gv_module.__file__).read_text(encoding="utf-8")
    assert _forbidden_import_segments(source) == []


def test_api_surface_excludes_gateway_capital_and_other_lanes(
    api: GovernanceApi,
) -> None:
    # 服务应暴露的六个方法
    assert callable(api.seal_trial)
    assert callable(api.issue_exploration)
    assert callable(api.issue_recovery)
    assert callable(api.sealed_trial)
    assert callable(api.target_policy)
    assert callable(api.issued_status)
    # gateway 状态激活/入口发布/permits 一律不得出现
    for name in GATEWAY_METHODS:
        assert not hasattr(api, name), name
    # capital 写入面一律不得出现
    for name in CAPITAL_METHODS:
        assert not hasattr(api, name), name
    # authorizer/publisher/finalizer 面一律不得出现
    for name in (
        "assess_edge",
        "publish_snapshot",
        "active_snapshot",
        "raw_payload",
        "register_plan_line",
        "finalize_due",
        "outcome_fact",
    ):
        assert not hasattr(api, name), name


def test_kind_isolation_issuer_only_exploration_recovery(
    api: GovernanceApi, ledgers,
) -> None:
    # EDGE envelope 一律不得被 governance issuer 签发
    _reserve(ledgers[1], "attempt-kind-1")
    edge = _envelope(kind=AuthorizationKind.EDGE)
    with pytest.raises(IssuerError) as excinfo:
        api.issue_exploration(
            ExplorationIssuanceRequest(
                envelope=edge,
                research_program_id=PROGRAM,
                attempt_id="attempt-kind-1",
                sample_evidence_id="sample-kind-1",
            )
        )
    assert excinfo.value.code == "envelope_kind_mismatch"
    # 成功签发的 envelope 只能是 EXPLORATION/RECOVERY 且 INACTIVE
    _reserve(ledgers[1], "attempt-expl-iso")
    exploration = _envelope(kind=AuthorizationKind.EXPLORATION)
    issued, _ = api.issue_exploration(
        ExplorationIssuanceRequest(
            envelope=exploration,
            research_program_id=PROGRAM,
            attempt_id="attempt-expl-iso",
            sample_evidence_id="sample-expl-iso",
        )
    )
    assert issued.authorization_kind is AuthorizationKind.EXPLORATION
    assert api.issued_status(issued.authorization_id) == "INACTIVE"


def test_signer_is_private_no_public_accessor(api: GovernanceApi) -> None:
    assert hasattr(api, "_signer")
    for name in ("signer", "get_signer", "sign", "signing_key"):
        assert not hasattr(api, name), name


# --------------------------------------------------------------------------
# Step 3: seal_trial 显式签名批准
# --------------------------------------------------------------------------


def test_seal_trial_requires_explicit_approval_argument(
    api: GovernanceApi,
) -> None:
    # 关键字参数为必填: 不传 approval 直接 TypeError (证明没有 env fallback)
    with pytest.raises(TypeError):
        api.seal_trial(_seal_request())


def test_seal_trial_rejects_none_approval(api: GovernanceApi) -> None:
    with pytest.raises(GovernanceStoreError) as excinfo:
        api.seal_trial(_seal_request(), approval=None)  # type: ignore[arg-type]
    assert excinfo.value.code == SEAL_APPROVAL_REQUIRED


def test_seal_trial_rejects_wrong_namespace_approval(api: GovernanceApi) -> None:
    approval = _approval(namespace="evidence.other.namespace")
    with pytest.raises(GovernanceStoreError) as excinfo:
        api.seal_trial(_seal_request(), approval=approval)
    assert excinfo.value.code == SEAL_APPROVAL_NAMESPACE_MISMATCH


def test_seal_trial_rejects_non_plan_trust_approval(api: GovernanceApi) -> None:
    approval = _approval(artifact=trust.ArtifactKind.SIGNAL)
    assert approval.artifact not in APPROVAL_ARTIFACT_KINDS
    with pytest.raises(GovernanceStoreError) as excinfo:
        api.seal_trial(_seal_request(), approval=approval)
    assert excinfo.value.code == SEAL_APPROVAL_ARTIFACT_REJECTED


def test_seal_trial_with_correct_approval_commits_atomically(
    api: GovernanceApi,
) -> None:
    receipt = api.seal_trial(
        _seal_request(), approval=_approval()
    )
    assert receipt.trial_id == "trial-001"
    sealed = api.sealed_trial("trial-001")
    assert sealed["role"] == "champion"
    assert sealed["research_program_id"] == PROGRAM
    target = api.target_policy(TARGET_HASH)
    # 注册的 target policy 显式 NON-executable
    assert target["executable"] == 0


# --------------------------------------------------------------------------
# Step 3: EXPLORATION / RECOVERY issuance
# --------------------------------------------------------------------------


def test_exploration_issuance_inactive_candidate_with_correct_namespace(
    api: GovernanceApi, ledgers,
) -> None:
    budget, attempts, _ = ledgers
    _reserve(attempts, "attempt-expl-1")
    envelope = _envelope(kind=AuthorizationKind.EXPLORATION)
    issued, signed = api.issue_exploration(
        ExplorationIssuanceRequest(
            envelope=envelope,
            research_program_id=PROGRAM,
            attempt_id="attempt-expl-1",
            sample_evidence_id="sample-expl-1",
        )
    )
    assert api.issued_status(issued.authorization_id) == "INACTIVE"
    assert signed.namespace == GOV_NAMESPACE
    assert signed.artifact is trust.ArtifactKind.EXPLORATION_AUTHORIZATION
    assert attempts.status("attempt-expl-1") is AttemptStatus.CONSUMED
    assert budget.consumed(MultiplicityBudgetKind.ALPHA) == 1


def test_recovery_issuance_inactive_candidate_with_correct_namespace(
    api: GovernanceApi, ledgers,
) -> None:
    attempts = ledgers[1]
    _reserve(attempts, "attempt-rec-1")
    envelope = _envelope(
        kind=AuthorizationKind.RECOVERY,
        risk_epoch=4,
        program_loss_budget_bindings=(_binding(version=7),),
    )
    issued, signed = api.issue_recovery(
        RecoveryIssuanceRequest(
            envelope=envelope,
            research_program_id=PROGRAM,
            attempt_id="attempt-rec-1",
            sample_evidence_id="sample-rec-1",
            inherited_authorization_id="auth-prior",
            inherited_risk_epoch=4,
            inherited_stage_loss_version=7,
        )
    )
    assert api.issued_status(issued.authorization_id) == "INACTIVE"
    assert signed.namespace == GOV_NAMESPACE
    assert signed.artifact is trust.ArtifactKind.RECOVERY_AUTHORIZATION


def test_reissue_same_sample_is_rejected(api: GovernanceApi, ledgers) -> None:
    attempts = ledgers[1]
    _reserve(attempts, "attempt-expl-dup-1")
    envelope = _envelope(kind=AuthorizationKind.EXPLORATION)
    api.issue_exploration(
        ExplorationIssuanceRequest(
            envelope=envelope,
            research_program_id=PROGRAM,
            attempt_id="attempt-expl-dup-1",
            sample_evidence_id="sample-expl-dup-1",
        )
    )
    _reserve(attempts, "attempt-expl-dup-2")
    second = _envelope(
        kind=AuthorizationKind.EXPLORATION,
        authorization_id="auth-gov-dup",
    )
    with pytest.raises(IssuerError) as excinfo:
        api.issue_exploration(
            ExplorationIssuanceRequest(
                envelope=second,
                research_program_id=PROGRAM,
                attempt_id="attempt-expl-dup-2",
                sample_evidence_id="sample-expl-dup-1",  # 复用同一 sample
            )
        )
    assert excinfo.value.code == "sample_reuse"


def test_signer_failure_leaves_no_envelope_and_retry_is_deterministic(
    tmp_path: Path, ledgers,
) -> None:
    attempts = ledgers[1]
    failing = _FailingSigner()
    api = _make_api(tmp_path, ledgers, signer=failing)
    _reserve(attempts, "attempt-expl-fail")
    envelope = _envelope(kind=AuthorizationKind.EXPLORATION)
    with pytest.raises(RuntimeError):
        api.issue_exploration(
            ExplorationIssuanceRequest(
                envelope=envelope,
                research_program_id=PROGRAM,
                attempt_id="attempt-expl-fail",
                sample_evidence_id="sample-expl-fail",
            )
        )
    # 失败的签名不留任何 envelope; attempt 保持 RESERVED
    with pytest.raises(IssuerError):
        api.issued_status(envelope.authorization_id)
    assert failing.calls == 1
    assert attempts.status("attempt-expl-fail") is AttemptStatus.RESERVED
    # 恢复后的确定性重试 (同一 database + ledgers 的新服务)
    recovered = _make_api(tmp_path, ledgers)
    _reserve(attempts, "attempt-expl-retry")
    issued, _ = recovered.issue_exploration(
        ExplorationIssuanceRequest(
            envelope=_envelope(
                kind=AuthorizationKind.EXPLORATION,
                authorization_id="auth-gov-retry",
            ),
            research_program_id=PROGRAM,
            attempt_id="attempt-expl-retry",
            sample_evidence_id="sample-expl-retry",
        )
    )
    assert recovered.issued_status(issued.authorization_id) == "INACTIVE"
