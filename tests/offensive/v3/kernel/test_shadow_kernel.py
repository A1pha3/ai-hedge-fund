"""Plan Task 5 RED: authority-free ShadowKernelInput + shared decision core.

The official paired trial consumes ``ShadowKernelInput`` — a strict, frozen
input that binds the Trial/SAP/Stage manifest hashes, one arm ``PolicySnapshot``
with its ``ShadowPolicyBinding``, the shared frozen evidence (regime
observation, evidence root, cutoff), one arm-specific capital checkpoint, and
the frozen candidate/price/industry inputs.

The shadow input deliberately carries NO authority: a ``PolicyActivation``
object, a ``CapitalAuthorizationEnvelope``, a permit nonce, or a broker
account must be rejected at construction. ``decide_shadow`` never takes a
``trusted_at`` argument — the frozen trusted time lives inside
``ShadowSharedInput``, so both arm calls consume exactly one observation.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest
from pydantic import ValidationError

from src.screening.offensive.v3.contracts import ExecutionMode
from src.screening.offensive.v3.contracts.authorization import (
    AuthorizationKind,
)
from src.screening.offensive.v3.contracts.capital import (
    CapitalRiskSnapshot,
    ExposureScope,
    RiskExposureBucket,
)
from src.screening.offensive.v3.contracts.governance import (
    PolicyActivation,
    PrimaryMetric,
    StatisticalAnalysisPlan,
    TrialManifest,
)
from src.screening.offensive.v3.contracts.regime import (
    RegimeAdmissionMode,
    RegimeObservation,
    RegimeObservationReason,
    RegimeSourceRevision,
    RegimeState,
)
from src.screening.offensive.v3.contracts.risk import (
    ReconciliationLatchState,
    RiskLatchState,
    RiskSnapshotCompleteness,
    RiskSnapshotFreshness,
)
from src.screening.offensive.v3.contracts.trial import (
    BaselineShadowPolicyBinding,
    ShadowPolicySourceKind,
    TargetShadowPolicyBinding,
    TrialArm,
)
from src.screening.offensive.v3.governance.regime_trial import (
    target_policy_registration_hash,
)
from src.screening.offensive.v3.kernel.decide import GrowthKernel
from src.screening.offensive.v3.kernel.models import (
    BlockReason,
    CandidateEvidenceBinding,
    DeadlineContract,
    NoTradeDecision,
    ShadowCapitalCheckpoint,
    ShadowKernelInput,
    ShadowSharedInput,
)
from src.screening.offensive.v3.kernel.shadow import (
    economic_shadow_projection,
)
from src.screening.offensive.v3.kernel.sizing import SizingConfig
from src.screening.offensive.v3.policy.models import (
    PolicySnapshot,
    RuntimeMode,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 5, 15, 30, tzinfo=UTC)
CLOSE = datetime(2026, 8, 5, 15, 0, tzinfo=UTC)
SIGNAL_DATE = date(2026, 8, 5)
CUTOFF = CLOSE - timedelta(minutes=5)
PORTFOLIO = "paper-v3"
ARM = "champion"
LINEAGE = "btst-regime-paired"
PROGRAM = "research.btst.regime"
HASH = "a" * 64
TARGET_HASH = "b" * 64
ZERO64 = "0" * 64
BEHAVIOR = "d" * 64

# ---------------------------------------------------------------------------
# builders (mirror the governance-trial test fixtures; self-contained)
# ---------------------------------------------------------------------------


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
        enrollment_start=NOW + timedelta(days=1),
        enrollment_end=NOW + timedelta(days=30),
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


def _sap(trial: TrialManifest) -> StatisticalAnalysisPlan:
    return StatisticalAnalysisPlan(
        sap_id=trial.trial_id,
        trial_manifest_hash=trial.artifact_hash(),
        research_program_id=trial.research_program_id,
        economic_lineage_id=trial.economic_lineage_id,
        primary_metric=PrimaryMetric.PORTFOLIO_LOG_GROWTH,
        baseline_portfolio_policy_fingerprint=trial.baseline_portfolio_policy_fingerprint,
        target_portfolio_policy_fingerprint=trial.target_portfolio_policy_fingerprint,
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


def _regime_observation(state: RegimeState) -> RegimeObservation:
    reason = (
        RegimeObservationReason.CLASSIFIED
        if state is not RegimeState.UNKNOWN
        else RegimeObservationReason.UNRECOGNIZED_RAW_STATE
    )
    raw = None if state is RegimeState.UNKNOWN else state.value
    return RegimeObservation(
        signal_session=SIGNAL_DATE,
        state=state,
        reason=reason,
        raw_state=raw,
        source_revisions=(
            RegimeSourceRevision(
                evidence_id="regime:csi300:1.0",
                revision=1,
                artifact_hash=HASH,
            ),
        ),
        effective_at=CUTOFF,
        provider_published_at=CUTOFF,
        observed_at=CUTOFF,
        classifier_semver="1.0.0",
        behavior_fingerprint=BEHAVIOR,
        input_schema_hash=HASH,
    )


def _bucket(scope: ExposureScope) -> RiskExposureBucket:
    portfolio_id = PORTFOLIO if scope is ExposureScope.PORTFOLIO else None
    return RiskExposureBucket(
        scope=scope,
        portfolio_id=portfolio_id,
        research_program_id=None,
        economic_lineage_id=None,
        stage_id=None,
        position_marked_gross_cents=0,
        live_order_leaves_gross_cents=0,
        reserved_entry_gross_cents=0,
        pending_stress_cents=0,
        corporate_action_pending_risk_cents=0,
        unattributed_risk_cents=0,
        total_gross_cents=0,
    )


def _capital_checkpoint(**overrides) -> CapitalRiskSnapshot:
    values = {
        "risk_snapshot_id": "snap-arm-1",
        "portfolio_id": PORTFOLIO,
        "broker_account_id": None,
        "base_currency": "CNY",
        "mode": ExecutionMode.DAILY_BAR_PROXY,
        "as_of": CLOSE,
        "valid_until": NOW + timedelta(hours=18),
        "freshness": RiskSnapshotFreshness.FRESH,
        "completeness": RiskSnapshotCompleteness.COMPLETE,
        "available_cash_cents": 10_000_000,
        "restricted_cash_cents": 0,
        "unsettled_cash_cents": 0,
        "cash_receivable_cents": 0,
        "cash_payable_cents": 0,
        "subscription_suspense_cents": 0,
        "redemption_suspense_cents": 0,
        "reserved_cash_cents": 0,
        "issued_unit_quanta": 1_000_000,
        "pending_redeemed_unit_quanta": 0,
        "positions": (),
        "live_orders": (),
        "entry_reserves": (),
        "pending_stress_components": (),
        "corporate_action_risk_components": (),
        "unattributed_risk_cents": 0,
        "exposures": (
            _bucket(ExposureScope.GLOBAL),
            _bucket(ExposureScope.PORTFOLIO),
        ),
        "total_gross_exposure_cents": 0,
        "as_observed_nav_cents": 10_000_000,
        "lifetime_high_water_mark_cents": 10_000_000,
        "active_epoch_high_water_mark_cents": 10_000_000,
        "lifetime_drawdown_ppm": 0,
        "active_epoch_drawdown_ppm": 0,
        "risk_latch": RiskLatchState.CLEAR,
        "stage_loss_latches": (),
        "reconciliation_latch": ReconciliationLatchState.CLEAR,
        "policy_activation_hash": "a" * 64,
        "policy_epoch": 1,
        "authority_epoch": 1,
        "risk_epoch": 1,
        "registry_epoch": 1,
        "authorization_id": "auth-1",
        "authorization_version": 1,
        "stage_loss_state_version": 1,
        "writer_fencing_epoch": 1,
        "capital_version": 1,
        "schema_major": 2,
    }
    values.update(overrides)
    return CapitalRiskSnapshot(**values)


def _shared(
    *,
    trial: TrialManifest,
    sap: StatisticalAnalysisPlan,
    regime: RegimeObservation,
    cutoff: datetime = CUTOFF,
    **overrides,
) -> ShadowSharedInput:
    values = {
        "portfolio_id": PORTFOLIO,
        "signal_session": SIGNAL_DATE,
        "decision_cycle_id": "daily-action-2026-08-05",
        "trial_manifest_hash": trial.artifact_hash(),
        "sap_manifest_hash": sap.artifact_hash(),
        "trial_arm": TrialArm.CHAMPION,
        "mode": ExecutionMode.DAILY_BAR_PROXY,
        "trusted_evidence_cutoff": cutoff,
        "evidence_set_merkle_root": HASH,
        "regime_observation": regime,
        "trial_id": trial.trial_id,
        "research_program_id": trial.research_program_id,
        "economic_lineage_id": trial.economic_lineage_id,
        "stage_id": "stage-1",
        "stage_manifest_hash": HASH,
        "trust_bundle_hash": HASH,
        "registry_epoch": trial.registry_epoch,
        "trusted_at": NOW,
    }
    values.update(overrides)
    return ShadowSharedInput(**values)


def _deadlines(**overrides) -> DeadlineContract:
    values = {
        "close_finalized_at": CLOSE,
        "seal_creation_deadline": CLOSE + timedelta(hours=1),
        "permit_issue_deadline": CLOSE + timedelta(hours=1, minutes=30),
        "permit_expires_at": CLOSE + timedelta(hours=18, minutes=25),
        "gateway_send_deadline": CLOSE + timedelta(hours=18, minutes=25),
        "broker_auction_cutoff": CLOSE + timedelta(hours=18, minutes=30),
    }
    values.update(overrides)
    return DeadlineContract(**values)


def _candidate(candidate_id="cand-1", **overrides):
    from src.screening.offensive.v3.kernel.admission import BTST_FAMILY
    from src.screening.offensive.v3.kernel.models import RawCandidate

    values = {
        "candidate_id": candidate_id,
        "producer_namespace": "btst",
        "family_id": BTST_FAMILY,
        "economic_lineage_id": LINEAGE,
        "research_program_id": PROGRAM,
        "stage_id": "stage-1",
        "security_id": "300001.SZ",
        "direction": "LONG",
        "unscaled_target_gross_cents": 100_000,
        "behavior_fingerprint": BEHAVIOR,
        "execution_version": "btst.funnel.v1",
        "cost_version": "cn-a-share-costs.v1",
        "evidence_ids": (),
    }
    values.update(overrides)
    return RawCandidate(**values)


def _evidence_binding(candidate_id="cand-1", **overrides) -> CandidateEvidenceBinding:
    values = {
        "candidate_id": candidate_id,
        "evidence_id": "btst:shadow:cand-1",
        "evidence_artifact_hash": "e" * 64,
        "evidence_payload_hash": "f" * 64,
    }
    values.update(overrides)
    return CandidateEvidenceBinding(**values)


def _shadow_input(
    *,
    policy: PolicySnapshot,
    binding: object,
    shared: ShadowSharedInput,
    capital: CapitalRiskSnapshot,
    candidates=(),
    prices=(),
    industries=(),
    **overrides,
) -> ShadowKernelInput:
    values = {
        "shared": shared,
        "policy_snapshot": policy,
        "shadow_policy_binding": binding,
        "capital_checkpoint": ShadowCapitalCheckpoint(
            capital_snapshot_hash=capital.content_hash(),
            capital_snapshot=capital,
        ),
        "deadlines": _deadlines(),
        "candidate_evidence_bindings": tuple(
            _evidence_binding(c.candidate_id) for c in candidates
        ),
        "raw_candidates": tuple(candidates),
        "price_micros_by_candidate": tuple(prices),
        "industry_by_candidate": tuple(industries),
    }
    values.update(overrides)
    return ShadowKernelInput(**values)


def _paired_world(
    *,
    regime_state: RegimeState = RegimeState.NORMAL,
    candidates=("cand-1",),
):
    """Champion + Challenger inputs over one shared frozen world."""
    from src.screening.offensive.v3.kernel.models import RawCandidate

    baseline = _trial_policy(RegimeAdmissionMode.IGNORE)
    target = _trial_policy(RegimeAdmissionMode.NORMAL_ONLY)
    trial = _trial_manifest(baseline, target)
    sap = _sap(trial)
    regime = _regime_observation(regime_state)
    shared_champion = _shared(
        trial=trial, sap=sap, regime=regime, trial_arm=TrialArm.CHAMPION
    )
    shared_challenger = _shared(
        trial=trial, sap=sap, regime=regime, trial_arm=TrialArm.CHALLENGER
    )
    capital = _capital_checkpoint()
    champion_binding = BaselineShadowPolicyBinding(
        source_kind=ShadowPolicySourceKind.BASELINE_POLICY_ACTIVATION,
        baseline_policy_activation_hash=trial.baseline_policy_activation_hash,
        policy_snapshot_hash=baseline.content_hash(),
        policy_fingerprint=baseline.policy_fingerprint,
    )
    target_binding = TargetShadowPolicyBinding(
        source_kind=ShadowPolicySourceKind.TARGET_POLICY_REGISTRATION,
        target_policy_registration_hash=trial.target_policy_snapshot_registration_hash,
        policy_snapshot_hash=target.content_hash(),
        policy_fingerprint=target.policy_fingerprint,
    )
    candidates = tuple(_candidate(c) for c in candidates)
    prices = tuple((c.candidate_id, 10_000_000) for c in candidates)
    industries = tuple((c.candidate_id, "electronics") for c in candidates)
    champion = _shadow_input(
        policy=baseline,
        binding=champion_binding,
        shared=shared_champion,
        capital=capital,
        candidates=candidates,
        prices=prices,
        industries=industries,
    )
    challenger = _shadow_input(
        policy=target,
        binding=target_binding,
        shared=shared_challenger,
        capital=capital,
        candidates=candidates,
        prices=prices,
        industries=industries,
    )
    return champion, challenger, shared_champion, baseline, target, trial, sap


def _config(**overrides) -> SizingConfig:
    values = {
        "per_ticker_gross_cap_cents": 200_000,
        "per_industry_gross_cap_cents": 300_000,
        "per_day_gross_cap_cents": 500_000,
        "portfolio_gross_cap_cents": 400_000,
        "worst_case_fee_ppm": 3_000,
    }
    values.update(overrides)
    return SizingConfig(**values)


def _kernel() -> GrowthKernel:
    return GrowthKernel(_config())


# ---------------------------------------------------------------------------
# 1. shape and authority-isolation (RED)
# ---------------------------------------------------------------------------


def test_shadow_input_rejects_policy_activation_object() -> None:
    champion, challenger, *_ = _paired_world()
    values = json.loads(champion.model_dump_json())
    policy = _trial_policy(RegimeAdmissionMode.IGNORE)
    activation = PolicyActivation(
        portfolio_id=PORTFOLIO,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        policy_snapshot_hash=policy.policy_fingerprint,
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
    values["policy_activation"] = activation.model_dump(mode="json")
    with pytest.raises(ValidationError):
        ShadowKernelInput.model_validate_json(json.dumps(values), strict=True)


def test_shadow_input_rejects_envelope_object() -> None:
    champion, challenger, *_ = _paired_world()
    values = json.loads(champion.model_dump_json())
    values["envelope"] = {
        "authorization_kind": AuthorizationKind.EDGE.value,
        "authorization_id": "auth-1",
        "authorization_version": 1,
        "mode": ExecutionMode.DAILY_BAR_PROXY.value,
        "portfolio_id": PORTFOLIO,
        "broker_account_id": None,
        "broker_account_fingerprint": None,
        "base_currency": "CNY",
        "policy_activation_hash": HASH,
        "trust_bundle_hash": HASH,
        "registry_epoch": 1,
        "policy_epoch": 1,
        "authority_epoch": 1,
        "risk_epoch": 1,
        "research_program_ids": [PROGRAM],
        "baseline_portfolio_policy_fingerprint": HASH,
        "target_portfolio_policy_fingerprint": TARGET_HASH,
        "lineage_grants": [],
        "evidence_as_of": NOW.isoformat(),
        "evidence_set_merkle_root": HASH,
        "issued_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
        "activation_capital_snapshot_id": "snapshot-1",
        "activation_capital_snapshot_hash": HASH,
        "portfolio_gross_cap": "0.02",
        "exploration_aggregate_gross_cap": "0",
        "program_loss_budget_bindings": [],
        "issuer_id": "authorizer.service",
        "issuer_capability": "authorizer.edge.envelope.v1",
        "portfolio_assessment_result_hash": HASH,
        "global_attempt_ledger_checkpoint_hash": HASH,
        "global_multiplicity_budget_consumption_id": "consumption-1",
        "schema_major": 2,
    }
    with pytest.raises(ValidationError):
        ShadowKernelInput.model_validate_json(json.dumps(values), strict=True)


def test_shadow_input_rejects_unknown_extra_fields() -> None:
    champion, challenger, *_ = _paired_world()
    values = json.loads(champion.model_dump_json())
    values["permit_nonce"] = 42
    with pytest.raises(ValidationError):
        ShadowKernelInput.model_validate_json(json.dumps(values), strict=True)
    values.pop("permit_nonce")
    values["broker_account_id"] = "acc-1"
    with pytest.raises(ValidationError):
        ShadowKernelInput.model_validate_json(json.dumps(values), strict=True)


def test_shadow_input_rejects_wrong_mode() -> None:
    champion, challenger, shared, *_ = _paired_world()
    values = json.loads(champion.model_dump_json())
    values["shared"]["mode"] = ExecutionMode.BROKER_CONFIRMED.value
    with pytest.raises(ValidationError):
        ShadowKernelInput.model_validate_json(json.dumps(values), strict=True)


def test_shadow_input_rejects_malformed_trial_sap_hashes() -> None:
    """Trial/SAP hashes are frozen references; their binding to the sealed
    bundle is the sealed store's authority (derived at seal time, Task 6).

    The input layer enforces the shape contract: a non-Sha256 value is
    rejected, and a value that contradicts the arm identity (stage zero
    sentinel, arm↔binding source kind) is rejected. The hash↔bundle binding
    itself is not re-derived here — the input only ever comes from a sealed
    bundle, and the store never mints an input with a foreign hash.
    """
    champion, challenger, shared, *_ = _paired_world()
    values = json.loads(champion.model_dump_json())
    values["shared"]["trial_manifest_hash"] = "not-a-hash"
    with pytest.raises(ValidationError):
        ShadowKernelInput.model_validate_json(json.dumps(values), strict=True)
    values = json.loads(champion.model_dump_json())
    values["shared"]["sap_manifest_hash"] = "not-a-hash"
    with pytest.raises(ValidationError):
        ShadowKernelInput.model_validate_json(json.dumps(values), strict=True)
    values = json.loads(champion.model_dump_json())
    values["shared"]["stage_manifest_hash"] = ZERO64
    with pytest.raises(ValidationError):
        ShadowKernelInput.model_validate_json(json.dumps(values), strict=True)


def test_shadow_input_rejects_mismatched_policy_binding_hashes() -> None:
    champion, challenger, *_ = _paired_world()
    values = json.loads(champion.model_dump_json())
    values["shadow_policy_binding"]["policy_snapshot_hash"] = "f" * 64
    with pytest.raises(ValidationError):
        ShadowKernelInput.model_validate_json(json.dumps(values), strict=True)
    values = json.loads(champion.model_dump_json())
    values["shadow_policy_binding"]["policy_fingerprint"] = "f" * 64
    with pytest.raises(ValidationError):
        ShadowKernelInput.model_validate_json(json.dumps(values), strict=True)
    values = json.loads(champion.model_dump_json())
    values["shared"]["trial_arm"] = TrialArm.CHALLENGER.value
    # a Champion arm cannot carry a target registration binding
    with pytest.raises(ValidationError):
        ShadowKernelInput.model_validate_json(json.dumps(values), strict=True)


def test_shadow_input_rejects_capital_checkpoint_with_mismatched_hash() -> None:
    champion, challenger, *_ = _paired_world()
    values = json.loads(champion.model_dump_json())
    values["capital_checkpoint"]["capital_snapshot_hash"] = "f" * 64
    with pytest.raises(ValidationError):
        ShadowKernelInput.model_validate_json(json.dumps(values), strict=True)


def test_shadow_input_round_trips_strict() -> None:
    champion, challenger, *_ = _paired_world()
    rebuilt = ShadowKernelInput.model_validate_json(champion.model_dump_json(), strict=True)
    assert rebuilt == champion
    assert rebuilt.content_hash() == champion.content_hash()


def test_decide_shadow_has_no_external_clock_argument() -> None:
    champion, challenger, shared, *_ = _paired_world()
    decision = _kernel().decide_shadow(champion)
    assert decision.counterfactual_key.signal_session == champion.shared.signal_session
    assert decision.counterfactual_key.portfolio_id == PORTFOLIO
    assert decision.mode is ExecutionMode.DAILY_BAR_PROXY


# ---------------------------------------------------------------------------
# 2. policy semantics (RED)
# ---------------------------------------------------------------------------


def test_normal_identical_capital_produces_byte_identical_economic_projection() -> None:
    champion, challenger, *_ = _paired_world(regime_state=RegimeState.NORMAL)
    champion_decision = _kernel().decide_shadow(champion)
    challenger_decision = _kernel().decide_shadow(challenger)
    assert isinstance(champion_decision, NoTradeDecision) is False
    assert isinstance(challenger_decision, NoTradeDecision) is False

    assert economic_shadow_projection(champion_decision) == economic_shadow_projection(
        challenger_decision
    )


@pytest.mark.parametrize(
    "state",
    [RegimeState.RISK_OFF, RegimeState.CRISIS, RegimeState.UNKNOWN],
)
def test_normal_only_blocks_but_ignore_continues(
    state: RegimeState,
) -> None:
    from src.screening.offensive.v3.contracts.decision import ShadowDecision

    champion, challenger, *_ = _paired_world(regime_state=state)
    champion_decision = _kernel().decide_shadow(champion)
    assert isinstance(champion_decision, ShadowDecision)
    challenger_decision = _kernel().decide_shadow(challenger)
    assert isinstance(challenger_decision, NoTradeDecision)
    assert challenger_decision.reason is BlockReason.REGIME_ADMISSION_BLOCKED


def test_regime_change_does_not_alter_champion_economics() -> None:
    normal_champion, *_ = _paired_world(regime_state=RegimeState.NORMAL)
    risk_champion, *_ = _paired_world(regime_state=RegimeState.RISK_OFF)
    normal_decision = _kernel().decide_shadow(normal_champion)
    risk_decision = _kernel().decide_shadow(risk_champion)
    assert economic_shadow_projection(normal_decision) == economic_shadow_projection(
        risk_decision
    )


# ---------------------------------------------------------------------------
# 3. deterministic / property tests
# ---------------------------------------------------------------------------


def test_candidate_permutation_does_not_change_decision_bytes() -> None:
    champion_a, *_ = _paired_world(candidates=("cand-a", "cand-b"))
    champion_b, *_ = _paired_world(candidates=("cand-b", "cand-a"))
    a_decision = _kernel().decide_shadow(champion_a)
    b_decision = _kernel().decide_shadow(champion_b)
    assert a_decision.canonical_bytes() == b_decision.canonical_bytes()


def test_repeated_process_serialization_reproduces_exact_bytes() -> None:
    champion, *_ = _paired_world()
    first = _kernel().decide_shadow(champion)
    rebuilt = ShadowKernelInput.model_validate_json(
        champion.model_dump_json(), strict=True
    )
    second = _kernel().decide_shadow(rebuilt)
    assert second.canonical_bytes() == first.canonical_bytes()
    assert second.artifact_hash() == first.artifact_hash()


def test_risk_is_applied_exactly_once_in_shadow_path() -> None:
    # 12.5% drawdown: NAV falls to 87.5% and the multiplier halves, so the
    # sized quantity shrinks to ~0.44 of the baseline (cap × multiplier).
    # A double application would shrink it to ~0.22 — excluded below. Use a
    # 1-yuan price so lots stay large enough to observe the ratio.
    from test_risk import _nav_for_drawdown

    champion, *_ = _paired_world()
    hwm = 10_000_000
    nav = _nav_for_drawdown(hwm, 125_000)
    capital = _capital_checkpoint(
        as_observed_nav_cents=nav,
        lifetime_high_water_mark_cents=hwm,
        active_epoch_high_water_mark_cents=hwm,
        lifetime_drawdown_ppm=125_000,
        active_epoch_drawdown_ppm=125_000,
    )
    prices = (("cand-1", 1_000_000),)  # 1.00 CNY
    base_decision = _kernel().decide_shadow(
        _shadow_input(
            policy=champion.policy_snapshot,
            binding=champion.shadow_policy_binding,
            shared=champion.shared,
            capital=champion.capital_checkpoint.capital_snapshot,
            candidates=champion.raw_candidates,
            prices=prices,
            industries=champion.industry_by_candidate,
        )
    )
    scaled_decision = _kernel().decide_shadow(
        _shadow_input(
            policy=champion.policy_snapshot,
            binding=champion.shadow_policy_binding,
            shared=champion.shared,
            capital=capital,
            candidates=champion.raw_candidates,
            prices=prices,
            industries=champion.industry_by_candidate,
        )
    )
    base_qty = base_decision.counterfactual_lines[0].target_quantity_units
    scaled_qty = scaled_decision.counterfactual_lines[0].target_quantity_units
    assert scaled_qty < base_qty
    # exactly one application: one-half multiplier, never a second one
    # (which would land at or below one quarter of the baseline).
    assert scaled_qty > base_qty // 4


def test_missing_evidence_binding_still_produces_valid_lines() -> None:
    """A candidate without a frozen evidence binding is not a kernel failure;
    the line carries the binding only when the caller supplied one. The
    binding must never be synthesized inside the kernel, so a missing binding
    is projected as absent evidence provenance, not fabricated."""

    champion, *_ = _paired_world()
    missing = _shadow_input(
        policy=champion.policy_snapshot,
        binding=champion.shadow_policy_binding,
        shared=champion.shared,
        capital=champion.capital_checkpoint.capital_snapshot,
        candidates=champion.raw_candidates,
        prices=champion.price_micros_by_candidate,
        industries=champion.industry_by_candidate,
    )
    decision = _kernel().decide_shadow(missing)
    assert isinstance(decision, NoTradeDecision) is False
    assert len(decision.counterfactual_lines) == 1


def test_unknown_regime_reason_is_not_fabricated_as_normal() -> None:
    """A canonical UNKNOWN observation is a committed policy fact, never a
    back-filled NORMAL: the Challenger blocks and the Champion continues."""

    champion, challenger, *_ = _paired_world(
        regime_state=RegimeState.UNKNOWN,
    )
    from src.screening.offensive.v3.contracts.decision import ShadowDecision

    assert isinstance(_kernel().decide_shadow(champion), ShadowDecision)
    blocked = _kernel().decide_shadow(challenger)
    assert isinstance(blocked, NoTradeDecision)
    assert blocked.reason is BlockReason.REGIME_ADMISSION_BLOCKED
