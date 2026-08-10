"""Governance tests for the exact paired regime trial bundle.

The only pre-registered behavioural delta between the two arms is
``ProducerPolicy.btst_regime_admission_mode`` (Champion IGNORE, Challenger
NORMAL_ONLY). Any second semantic delta, wrong mode, wrong family, or loose hash
binding rejects the trial before enrolment.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.screening.offensive.v3.contracts.base import ExecutionMode
from src.screening.offensive.v3.contracts.governance import (
    PolicyActivation,
    PrimaryMetric,
    StatisticalAnalysisPlan,
    TrialManifest,
)
from src.screening.offensive.v3.contracts.regime import RegimeAdmissionMode
from src.screening.offensive.v3.governance.regime_trial import (
    policy_semantic_delta_paths,
    RegimeTrialBundle,
    RegimeTrialGovernanceError,
    target_policy_registration_hash,
    validate_regime_trial_bundle,
    ValidatedRegimeTrialBundle,
)
from src.screening.offensive.v3.policy.models import PolicySnapshot, RuntimeMode

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
ENROLLMENT_START = NOW + timedelta(days=1)
ENROLLMENT_END = NOW + timedelta(days=30)
LINEAGE = "btst-regime-paired"
PROGRAM = "research.btst.regime"
HASH = "a" * 64
TARGET_HASH = "b" * 64
ZERO64 = "0" * 64


def _trial_policy(admission: RegimeAdmissionMode) -> PolicySnapshot:
    return PolicySnapshot.model_validate_json(
        json.dumps(
            {
                "schema_major": 2,
                "policy_id": "growth-kernel-v3",
                "policy_version": "policy-v2",
                "policy_epoch": 1,
                "authority_epoch": 1,
                "risk_epoch": 1,
                "runtime_mode": RuntimeMode.SHADOW,
                "capital": {
                    "governed_tiers": [2, 5, 10],
                    "exploration_aggregate_gross_cap": "0.02",
                    "portfolio_gross_cap": "0.02",
                    "single_name_gross_cap": "0.01",
                    "industry_gross_cap": "0.02",
                    "daily_entry_gross_cap": "0.02",
                    "stage_loss_budget_cap": "0.02",
                },
                "risk": {
                    "drawdown_scale_start": "0.10",
                    "drawdown_halt": "0.15",
                    "halt_is_latched": True,
                    "inherited_risk_counts_on_restart": True,
                },
                "adv": {
                    "lookback_sessions": 20,
                    "max_participation_rate": "0.05",
                    "missing_data_behavior": "fail_closed",
                },
                "producers": {
                    "btst_enabled": True,
                    "oversold_bounce_enabled": False,
                    "btst_regime_admission_mode": admission.value,
                    "regime_sizing_enabled": False,
                    "streak_sizing_enabled": False,
                    "trigger_strength_sizing_enabled": False,
                    "composite_sizing_enabled": False,
                },
                "execution": {
                    "entry_session_ordinal": 1,
                    "exit_session_ordinal": 10,
                    "order_type": "opening_auction_limit",
                    "time_in_force": "opening_auction",
                    "seal_deadline_after_t0_close_minutes": 240,
                    "permit_deadline_before_auction_minutes": 20,
                    "gateway_send_deadline_before_auction_minutes": 10,
                    "broker_auction_submission_cutoff_cn": "09:20:00",
                    "worst_case_cost_multiplier": "2",
                },
                "versions": {
                    "execution_contract_version": "t0-close-t1-open-t10-open.v1",
                    "cost_version": "cn-a-share-costs.v1",
                    "board_rule_version": "ashare-board-prefix-v1",
                    "calendar_version": "sse-szse-official-sessions.v1",
                    "lot_rule_version": "cn-board-lot.v1",
                    "price_boundary_version": "sse-szse-price-limits.v1",
                    "setup_version": "daily-action-setups-v1",
                    "exit_policy_version": "t10-open.v1",
                    "governance_version": "growth-kernel-governance.v2",
                },
                "evidence_gates": {
                    "min_mature_outcomes": 150,
                    "min_decision_days": 60,
                    "min_effective_sample_size": "60",
                    "min_distinct_tickers": 80,
                    "min_forward_months": 12,
                    "adverse_window_required": True,
                    "chronological_fold_gate_required": True,
                    "capacity_stress_required": True,
                    "tail_risk_gate_required": True,
                    "fresh_evidence_per_tier_required": True,
                    "slippage_stress_multiple": "2",
                    "minimum_economic_effect": "0.001",
                    "incremental_minimum_economic_effect": "0.001",
                },
            }
        ),
        strict=True,
    )


def _trial_manifest(baseline: PolicySnapshot, target: PolicySnapshot) -> TrialManifest:
    return TrialManifest(
        family_id="btst.limit-up-breakout",
        economic_lineage_id=LINEAGE,
        research_program_id=PROGRAM,
        trial_id="trial-regime-001",
        baseline_portfolio_policy_fingerprint=baseline.policy_fingerprint,
        target_portfolio_policy_fingerprint=target.policy_fingerprint,
        trust_bundle_hash=HASH,
        registry_epoch=1,
        baseline_policy_activation_hash=HASH,
        target_policy_snapshot_registration_hash=target_policy_registration_hash(target),
        attempt_ledger_checkpoint_before_trial=HASH,
        attempt_budget_reservation_id="attempt-regime-001",
        statistical_governance_policy_version="stat-gov.v1",
        champion_behavior_fingerprint=HASH,
        challenger_behavior_fingerprint="c" * 64,
        primary_metric=PrimaryMetric.PORTFOLIO_LOG_GROWTH,
        minimum_economic_effect=Decimal("0.001"),
        weight_selection_rule="fixed-50-50",
        trial_manifest_sealed_at=NOW,
        enrollment_start=ENROLLMENT_START,
        enrollment_end=ENROLLMENT_END,
        followup_finality_date=NOW + timedelta(days=60),
        fixed_assessment_date=NOW + timedelta(days=90),
        execution_version="t0-close-t1-open-t10-open.v1",
        cost_version="cn-a-share-costs.v1",
        execution_mode=ExecutionMode.DAILY_BAR_PROXY,
        benchmark_definition="csi300-total-return",
        capacity_policy="capacity.v1",
        tail_risk_policy="tail.v1",
        estimator="wild-bootstrap",
        one_sided_confidence_level=Decimal("0.95"),
        bootstrap_method="wild",
        bootstrap_repetitions=10_000,
        bootstrap_seed=42,
        block_rule="monthly",
        ess_definition="kish",
        missing_censoring_itt_rule="itt",
        fold_boundaries=("2026-09-01", "2026-10-01"),
        purge_embargo="purge-5d",
        promotion_boolean_expression="lcb > mee",
        multiplicity_policy="program-global",
        broker_experiment_design=None,
        canonical_outcome_counting_rule="plan-line-contract",
        stage_loss_measurement_basis="stage-budget",
        issuer_id="governance.service",
        issuer_capability="governance.trial.manifest.v1",
        issued_at=NOW,
        expires_at=NOW + timedelta(days=120),
        schema_major=2,
    )


def _sap_manifest(trial: TrialManifest) -> StatisticalAnalysisPlan:
    return StatisticalAnalysisPlan(
        sap_id=trial.trial_id,
        trial_manifest_hash=trial.artifact_hash(),
        research_program_id=trial.research_program_id,
        economic_lineage_id=trial.economic_lineage_id,
        primary_metric=PrimaryMetric.PORTFOLIO_LOG_GROWTH,
        baseline_portfolio_policy_fingerprint=(trial.baseline_portfolio_policy_fingerprint),
        target_portfolio_policy_fingerprint=(trial.target_portfolio_policy_fingerprint),
        execution_mode=trial.execution_mode,
        one_sided_confidence_level=Decimal("0.95"),
        bootstrap_method="wild",
        repetitions=10_000,
        seed=42,
        block_rule="monthly",
        multiplicity_policy="program-global",
        alpha_or_evalue_budget_consumption_id="budget-001",
        issued_at=NOW,
        sealed_at=NOW,
        enrollment_start=trial.enrollment_start,
        expires_at=NOW + timedelta(days=120),
        issuer_id="governance.service",
        issuer_capability="governance.sap.v1",
        schema_major=2,
    )


def _baseline_activation(baseline: PolicySnapshot) -> PolicyActivation:
    return PolicyActivation(
        portfolio_id="paper-v3",
        broker_account_id=None,
        broker_account_fingerprint=None,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        policy_snapshot_hash=baseline.policy_fingerprint,
        predecessor_policy_activation_hash=ZERO64,
        trust_bundle_hash=HASH,
        registry_epoch=1,
        policy_epoch=1,
        authority_epoch=1,
        risk_epoch=1,
        effective_from=NOW,
        expires_at=NOW + timedelta(days=120),
        issuer_id="governance.service",
        issuer_capability="governance.policy.activation.v1",
        schema_major=2,
    )


def _bundle(
    *,
    baseline: PolicySnapshot | None = None,
    target: PolicySnapshot | None = None,
) -> RegimeTrialBundle:
    baseline = baseline or _trial_policy(RegimeAdmissionMode.IGNORE)
    target = target or _trial_policy(RegimeAdmissionMode.NORMAL_ONLY)
    trial = _trial_manifest(baseline, target)
    sap = _sap_manifest(trial)
    return RegimeTrialBundle(
        baseline_policy=baseline,
        target_policy=target,
        trial_manifest=trial,
        sap_manifest=sap,
        baseline_policy_activation=_baseline_activation(baseline),
    )


# --------------------------------------------------------------------------- #
# target_policy_registration_hash
# --------------------------------------------------------------------------- #


def test_target_policy_registration_hash_is_domain_separated_and_stable() -> None:
    target = _trial_policy(RegimeAdmissionMode.NORMAL_ONLY)
    digest = target_policy_registration_hash(target)
    assert len(digest) == 64
    assert digest == target_policy_registration_hash(target)
    other = _trial_policy(RegimeAdmissionMode.IGNORE)
    assert digest != target_policy_registration_hash(other)


# --------------------------------------------------------------------------- #
# policy_semantic_delta_paths
# --------------------------------------------------------------------------- #


def test_semantic_delta_is_exactly_the_admission_mode() -> None:
    baseline = _trial_policy(RegimeAdmissionMode.IGNORE)
    target = _trial_policy(RegimeAdmissionMode.NORMAL_ONLY)
    assert policy_semantic_delta_paths(baseline, target) == ("producers.btst_regime_admission_mode",)


def test_semantic_delta_ignores_provenance_only_labels() -> None:
    baseline = _trial_policy(RegimeAdmissionMode.IGNORE)
    republished = baseline.model_copy(
        update={
            "policy_id": "growth-kernel-v3-republished",
            "policy_version": "policy-v3",
            "policy_epoch": 2,
            "authority_epoch": 3,
            "risk_epoch": 4,
        }
    )
    assert policy_semantic_delta_paths(baseline, republished) == ()


def test_second_behavior_delta_adds_a_path() -> None:
    baseline = _trial_policy(RegimeAdmissionMode.IGNORE)
    target = _trial_policy(RegimeAdmissionMode.NORMAL_ONLY).model_copy(update={"capital": baseline.capital.model_copy(update={"daily_entry_gross_cap": Decimal("0.01")})})
    delta = policy_semantic_delta_paths(baseline, target)
    assert "producers.btst_regime_admission_mode" in delta
    assert "capital.daily_entry_gross_cap" in delta
    assert len(delta) == 2


# --------------------------------------------------------------------------- #
# validate_regime_trial_bundle
# --------------------------------------------------------------------------- #


def test_valid_bundle_yields_champion_ignore_challenger_normal_only() -> None:
    checked = validate_regime_trial_bundle(_bundle(), trusted_at=ENROLLMENT_START)
    assert isinstance(checked, ValidatedRegimeTrialBundle)
    assert checked.champion_policy.producers.btst_regime_admission_mode is RegimeAdmissionMode.IGNORE
    assert checked.challenger_policy.producers.btst_regime_admission_mode is RegimeAdmissionMode.NORMAL_ONLY


def test_second_behavior_delta_rejects_trial() -> None:
    bundle = _bundle(target=_trial_policy(RegimeAdmissionMode.NORMAL_ONLY).model_copy(update={"capital": _trial_policy(RegimeAdmissionMode.NORMAL_ONLY).capital.model_copy(update={"daily_entry_gross_cap": Decimal("0.01")})}))
    with pytest.raises(RegimeTrialGovernanceError, match="policy_delta_mismatch"):
        validate_regime_trial_bundle(bundle, trusted_at=ENROLLMENT_START)


def test_baseline_must_be_ignore() -> None:
    bundle = _bundle(baseline=_trial_policy(RegimeAdmissionMode.NORMAL_ONLY))
    with pytest.raises(RegimeTrialGovernanceError, match="baseline_admission"):
        validate_regime_trial_bundle(bundle, trusted_at=ENROLLMENT_START)


def test_target_must_be_normal_only() -> None:
    bundle = _bundle(target=_trial_policy(RegimeAdmissionMode.IGNORE))
    with pytest.raises(RegimeTrialGovernanceError, match="target_admission"):
        validate_regime_trial_bundle(bundle, trusted_at=ENROLLMENT_START)


def test_btst_family_is_required() -> None:
    bundle = _bundle(baseline=_trial_policy(RegimeAdmissionMode.IGNORE).model_copy(update={"producers": _trial_policy(RegimeAdmissionMode.IGNORE).producers.model_copy(update={"btst_enabled": False})}))
    with pytest.raises(RegimeTrialGovernanceError, match="btst_family|producer"):
        validate_regime_trial_bundle(bundle, trusted_at=ENROLLMENT_START)


def test_oversold_bounce_must_be_disabled() -> None:
    base = _trial_policy(RegimeAdmissionMode.IGNORE)
    bundle = _bundle(
        baseline=base.model_copy(update={"producers": base.producers.model_copy(update={"oversold_bounce_enabled": True})}),
        target=_trial_policy(RegimeAdmissionMode.NORMAL_ONLY).model_copy(update={"producers": _trial_policy(RegimeAdmissionMode.NORMAL_ONLY).producers.model_copy(update={"oversold_bounce_enabled": True})}),
    )
    with pytest.raises(RegimeTrialGovernanceError, match="oversold|family"):
        validate_regime_trial_bundle(bundle, trusted_at=ENROLLMENT_START)


def test_shadow_mode_and_daily_bar_proxy_required() -> None:
    bundle = _bundle(baseline=_trial_policy(RegimeAdmissionMode.IGNORE).model_copy(update={"runtime_mode": RuntimeMode.BTST_CANARY}))
    with pytest.raises(RegimeTrialGovernanceError, match="runtime_mode|shadow"):
        validate_regime_trial_bundle(bundle, trusted_at=ENROLLMENT_START)


def test_sizing_switches_must_be_disabled() -> None:
    base = _trial_policy(RegimeAdmissionMode.IGNORE)
    tgt = _trial_policy(RegimeAdmissionMode.NORMAL_ONLY)
    bundle = _bundle(
        baseline=base.model_copy(update={"producers": base.producers.model_copy(update={"streak_sizing_enabled": True})}),
        target=tgt.model_copy(
            update={"producers": tgt.producers.model_copy(update={"streak_sizing_enabled": True})},
        ),
    )
    with pytest.raises(RegimeTrialGovernanceError, match="sizing"):
        validate_regime_trial_bundle(bundle, trusted_at=ENROLLMENT_START)


def test_execution_and_cost_versions_must_match() -> None:
    base = _trial_policy(RegimeAdmissionMode.IGNORE)
    bundle = _bundle(target=_trial_policy(RegimeAdmissionMode.NORMAL_ONLY).model_copy(update={"versions": base.versions.model_copy(update={"cost_version": "cn-a-share-costs.v2"})}))
    with pytest.raises(RegimeTrialGovernanceError, match="version"):
        validate_regime_trial_bundle(bundle, trusted_at=ENROLLMENT_START)


def test_target_registration_hash_must_bind_target_policy() -> None:
    bundle = _bundle()
    tampered_trial = bundle.trial_manifest.model_copy(update={"target_policy_snapshot_registration_hash": "e" * 64})
    tampered = bundle.model_copy(
        update={
            "trial_manifest": tampered_trial,
            "sap_manifest": bundle.sap_manifest.model_copy(update={"trial_manifest_hash": tampered_trial.artifact_hash()}),
        }
    )
    with pytest.raises(RegimeTrialGovernanceError, match="registration_hash|target"):
        validate_regime_trial_bundle(tampered, trusted_at=ENROLLMENT_START)


def test_baseline_activation_must_bind_baseline_policy() -> None:
    bundle = _bundle()
    tampered = bundle.model_copy(update={"baseline_policy_activation": bundle.baseline_policy_activation.model_copy(update={"policy_snapshot_hash": "f" * 64})})
    with pytest.raises(RegimeTrialGovernanceError, match="baseline_activation|baseline"):
        validate_regime_trial_bundle(tampered, trusted_at=ENROLLMENT_START)


def test_validation_outside_enrollment_window_is_rejected() -> None:
    with pytest.raises(RegimeTrialGovernanceError, match="enrollment|window"):
        validate_regime_trial_bundle(_bundle(), trusted_at=NOW)
    with pytest.raises(RegimeTrialGovernanceError, match="enrollment|window"):
        validate_regime_trial_bundle(_bundle(), trusted_at=ENROLLMENT_END)


def test_sap_must_bind_trial_manifest() -> None:
    bundle = _bundle()
    tampered = bundle.model_copy(update={"sap_manifest": bundle.sap_manifest.model_copy(update={"trial_manifest_hash": "0" * 64})})
    with pytest.raises(RegimeTrialGovernanceError, match="sap|trial_manifest"):
        validate_regime_trial_bundle(tampered, trusted_at=ENROLLMENT_START)
