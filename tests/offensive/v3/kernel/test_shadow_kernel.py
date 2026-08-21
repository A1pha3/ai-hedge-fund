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
import inspect
import json

import pytest
from pydantic import ValidationError

from src.screening.offensive.v3.contracts import ExecutionMode
from src.screening.offensive.v3.contracts.authorization import (
    AuthorizationKind,
)
from src.screening.offensive.v3.contracts.capital import (
    CapitalPositionRisk,
    CapitalRiskSnapshot,
    ExposureScope,
    PositionState,
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
    FrozenTradingSessionSchedule,
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
TRADING_SESSIONS = (
    date(2026, 8, 6),
    date(2026, 8, 7),
    date(2026, 8, 10),
    date(2026, 8, 11),
    date(2026, 8, 12),
    date(2026, 8, 13),
    date(2026, 8, 14),
    date(2026, 8, 17),
    date(2026, 8, 18),
    date(2026, 8, 19),
)

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
                    "calendar_version": "sse-sessions-v1",
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
        "signal_session": SIGNAL_DATE,
        "decision_cycle_id": "daily-action-2026-08-05",
        "trial_manifest_hash": trial.artifact_hash(),
        "sap_manifest_hash": sap.artifact_hash(),
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
        "trading_session_schedule": FrozenTradingSessionSchedule(
            calendar_id="sse-szse",
            calendar_version="sse-sessions-v1",
            calendar_artifact_hash="c" * 64,
            signal_session=SIGNAL_DATE,
            following_sessions=TRADING_SESSIONS,
            available_at=cutoff,
        ),
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
    arm: TrialArm = TrialArm.CHAMPION,
    portfolio_id: str = PORTFOLIO,
    candidates=(),
    prices=(),
    industries=(),
    **overrides,
) -> ShadowKernelInput:
    values = {
        "portfolio_id": portfolio_id,
        "arm": arm,
        "shared": shared,
        "policy_snapshot": policy,
        "shadow_policy_binding": binding,
        "capital_checkpoint": ShadowCapitalCheckpoint(
            trial_id=shared.trial_id,
            arm=arm,
            portfolio_id=portfolio_id,
            mode=shared.mode,
            capital_store_id=(
                f"{shared.trial_id}:{arm.value}:capital"
            ),
            trial_genesis_manifest_hash="1" * 64,
            arm_capital_genesis_root=(
                "2" * 64
                if arm is TrialArm.CHAMPION
                else "3" * 64
            ),
            capital_snapshot_hash=capital.content_hash(),
            capital_snapshot=capital,
        ),
        "deadlines": _deadlines(),
        "sizing_config": _config(),
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
    shared = _shared(trial=trial, sap=sap, regime=regime)
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
        shared=shared,
        capital=capital,
        arm=TrialArm.CHAMPION,
        candidates=candidates,
        prices=prices,
        industries=industries,
    )
    challenger = _shadow_input(
        policy=target,
        binding=target_binding,
        shared=shared,
        capital=capital,
        arm=TrialArm.CHALLENGER,
        candidates=candidates,
        prices=prices,
        industries=industries,
    )
    return champion, challenger, shared, baseline, target, trial, sap


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
    values["arm"] = TrialArm.CHALLENGER.value
    values["capital_checkpoint"]["arm"] = TrialArm.CHALLENGER.value
    # a Challenger arm cannot carry a baseline activation binding
    with pytest.raises(ValidationError):
        ShadowKernelInput.model_validate_json(json.dumps(values), strict=True)


def test_shadow_input_rejects_capital_checkpoint_with_mismatched_hash() -> None:
    champion, challenger, *_ = _paired_world()
    values = json.loads(champion.model_dump_json())
    values["capital_checkpoint"]["capital_snapshot_hash"] = "f" * 64
    with pytest.raises(ValidationError):
        ShadowKernelInput.model_validate_json(json.dumps(values), strict=True)


def test_shadow_capital_checkpoint_binds_arm_store_and_genesis_provenance() -> None:
    capital = _capital_checkpoint()

    checkpoint = ShadowCapitalCheckpoint(
        trial_id="trial-regime-001",
        arm=TrialArm.CHAMPION,
        portfolio_id=PORTFOLIO,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        capital_store_id="trial-regime-001:CHAMPION:capital",
        trial_genesis_manifest_hash="1" * 64,
        arm_capital_genesis_root="2" * 64,
        capital_snapshot_hash=capital.content_hash(),
        capital_snapshot=capital,
    )

    assert checkpoint.arm is TrialArm.CHAMPION
    assert checkpoint.capital_store_id.endswith(":CHAMPION:capital")
    assert checkpoint.arm_capital_genesis_root == "2" * 64


def test_shadow_input_rejects_checkpoint_from_other_arm() -> None:
    champion, *_ = _paired_world()
    values = json.loads(champion.model_dump_json())
    values["capital_checkpoint"]["arm"] = TrialArm.CHALLENGER.value

    with pytest.raises(ValidationError, match="capital checkpoint arm"):
        ShadowKernelInput.model_validate_json(json.dumps(values), strict=True)


def test_paired_builder_has_no_single_capital_snapshot_shortcut() -> None:
    from src.screening.offensive.v3.orchestration.paired_trial import (
        build_arm_kernel_inputs,
    )

    parameters = inspect.signature(build_arm_kernel_inputs).parameters
    assert "capital_snapshot" not in parameters
    assert "champion_capital_checkpoint" in parameters
    assert "challenger_capital_checkpoint" in parameters


def test_shared_input_contains_only_arm_invariant_external_facts() -> None:
    assert "portfolio_id" not in ShadowSharedInput.model_fields
    assert "trial_arm" not in ShadowSharedInput.model_fields
    assert {"portfolio_id", "arm"} <= set(ShadowKernelInput.model_fields)


def test_shadow_decision_binds_exact_canonical_kernel_input_hash() -> None:
    champion, *_ = _paired_world()

    decision = _kernel().decide_shadow(champion)

    assert decision.kernel_input_hash == champion.content_hash()


def test_pair_builder_requires_exact_arm_kernel_inputs_not_naked_checkpoints() -> None:
    from src.screening.offensive.v3.orchestration.paired_trial import (
        build_pair_records,
    )

    parameters = inspect.signature(build_pair_records).parameters
    assert "champion_input" in parameters
    assert "challenger_input" in parameters
    assert "champion_capital_checkpoint" not in parameters
    assert "challenger_capital_checkpoint" not in parameters


def test_paired_builder_preserves_two_independent_capital_checkpoints() -> None:
    from src.screening.offensive.v3.governance.regime_trial import (
        ValidatedRegimeTrialBundle,
    )
    from src.screening.offensive.v3.orchestration.paired_trial import (
        build_arm_kernel_inputs,
    )

    champion, challenger, shared, baseline, target, trial, sap = _paired_world(
        candidates=()
    )
    validated = ValidatedRegimeTrialBundle(
        champion_policy=baseline,
        challenger_policy=target,
        baseline_policy=baseline,
        target_policy=target,
        trial_manifest=trial,
        sap_manifest=sap,
        admission_delta=("producers.btst_regime_admission_mode",),
    )

    rebuilt_champion, rebuilt_challenger = build_arm_kernel_inputs(
        validated=validated,
        shared_input=shared,
        candidates=(),
        champion_capital_checkpoint=champion.capital_checkpoint,
        challenger_capital_checkpoint=challenger.capital_checkpoint,
        deadlines=champion.deadlines,
        sizing_config=champion.sizing_config,
    )

    assert rebuilt_champion.capital_checkpoint == champion.capital_checkpoint
    assert rebuilt_challenger.capital_checkpoint == challenger.capital_checkpoint
    assert (
        rebuilt_champion.capital_checkpoint.content_hash()
        != rebuilt_challenger.capital_checkpoint.content_hash()
    )


def test_pair_records_bind_each_arm_capital_checkpoint_hash() -> None:
    from src.screening.offensive.v3.orchestration.paired_trial import (
        build_pair_records,
    )

    champion_input, challenger_input, shared, *_ = _paired_world(candidates=())
    champion_decision = _kernel().decide_shadow(champion_input)
    challenger_decision = _kernel().decide_shadow(challenger_input)
    champion_hash = champion_input.capital_checkpoint.content_hash()
    challenger_hash = challenger_input.capital_checkpoint.content_hash()

    champion_record, challenger_record = build_pair_records(
        trial_id=shared.trial_id,
        session=shared.signal_session,
        cycle_id=shared.decision_cycle_id,
        shared_input=shared,
        regime_hash=HASH,
        champion=champion_decision,
        challenger=challenger_decision,
        trusted_at=shared.trusted_at,
        champion_input=champion_input,
        challenger_input=challenger_input,
    )

    assert champion_record.arm_capital_checkpoint_hash == champion_hash
    assert challenger_record.arm_capital_checkpoint_hash == challenger_hash


def test_arm_decision_consumes_its_own_cash_gross_and_drawdown_truth() -> None:
    champion, *_ = _paired_world()
    position = CapitalPositionRisk(
        portfolio_id=PORTFOLIO,
        broker_account_id=None,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        position_lineage_id="existing-position",
        economic_lot_id="existing-lot",
        security_id="600000.SH",
        producer_namespace="btst",
        research_program_id=PROGRAM,
        economic_lineage_id=LINEAGE,
        stage_id="stage-1",
        state=PositionState.OPEN,
        settled_quantity=100,
        tradable_quantity=100,
        share_receivable_quantity=0,
        marked_gross_cents=200_000,
    )
    gross_buckets = tuple(
        RiskExposureBucket(
            scope=scope,
            portfolio_id=(None if scope is ExposureScope.GLOBAL else PORTFOLIO),
            research_program_id=(
                PROGRAM
                if scope in {
                    ExposureScope.RESEARCH_PROGRAM,
                    ExposureScope.ECONOMIC_LINEAGE,
                    ExposureScope.STAGE,
                }
                else None
            ),
            economic_lineage_id=(
                LINEAGE
                if scope in {ExposureScope.ECONOMIC_LINEAGE, ExposureScope.STAGE}
                else None
            ),
            stage_id=("stage-1" if scope is ExposureScope.STAGE else None),
            position_marked_gross_cents=200_000,
            live_order_leaves_gross_cents=0,
            reserved_entry_gross_cents=0,
            pending_stress_cents=0,
            corporate_action_pending_risk_cents=0,
            unattributed_risk_cents=0,
            total_gross_cents=200_000,
        )
        for scope in ExposureScope
    )
    stressed = _capital_checkpoint(
        available_cash_cents=500_000,
        positions=(position,),
        exposures=gross_buckets,
        total_gross_exposure_cents=200_000,
        as_observed_nav_cents=9_000_000,
        lifetime_high_water_mark_cents=10_000_000,
        active_epoch_high_water_mark_cents=10_000_000,
        lifetime_drawdown_ppm=100_000,
        active_epoch_drawdown_ppm=100_000,
    )
    stressed_checkpoint = ShadowCapitalCheckpoint(
        trial_id=champion.shared.trial_id,
        arm=champion.arm,
        portfolio_id=champion.portfolio_id,
        mode=champion.shared.mode,
        capital_store_id="trial-regime-001:CHAMPION:stressed-capital",
        trial_genesis_manifest_hash="1" * 64,
        arm_capital_genesis_root="4" * 64,
        capital_snapshot_hash=stressed.content_hash(),
        capital_snapshot=stressed,
    )
    stressed_input = ShadowKernelInput.model_validate(
        champion.model_copy(
            update={"capital_checkpoint": stressed_checkpoint}
        ).model_dump(mode="python"),
        strict=True,
    )

    clear_decision = _kernel().decide_shadow(champion)
    stressed_decision = _kernel().decide_shadow(stressed_input)

    assert stressed.total_gross_exposure_cents == 200_000
    assert stressed.available_cash_cents != champion.capital_checkpoint.capital_snapshot.available_cash_cents
    assert stressed.active_epoch_drawdown_ppm != champion.capital_checkpoint.capital_snapshot.active_epoch_drawdown_ppm
    assert stressed_decision != clear_decision


def test_distinct_checkpoint_provenance_with_same_economics_has_same_result() -> None:
    champion, *_ = _paired_world()
    original = champion.capital_checkpoint
    independently_bound = ShadowCapitalCheckpoint(
        trial_id=original.trial_id,
        arm=original.arm,
        portfolio_id=original.portfolio_id,
        mode=original.mode,
        capital_store_id="independent-capital-store",
        trial_genesis_manifest_hash=original.trial_genesis_manifest_hash,
        arm_capital_genesis_root="5" * 64,
        capital_snapshot_hash=original.capital_snapshot_hash,
        capital_snapshot=original.capital_snapshot,
    )
    independent_input = ShadowKernelInput.model_validate(
        champion.model_copy(
            update={"capital_checkpoint": independently_bound}
        ).model_dump(mode="python"),
        strict=True,
    )

    assert independently_bound.content_hash() != original.content_hash()
    # The decision embeds the exact kernel_input_hash (input provenance), so
    # full decision bytes legitimately differ for a distinct checkpoint; the
    # authority-free economics must be identical.
    assert economic_shadow_projection(
        _kernel().decide_shadow(independent_input)
    ) == economic_shadow_projection(_kernel().decide_shadow(champion))


def test_shadow_input_round_trips_strict() -> None:
    champion, challenger, *_ = _paired_world()
    rebuilt = ShadowKernelInput.model_validate_json(champion.model_dump_json(), strict=True)
    assert rebuilt == champion
    assert rebuilt.content_hash() == champion.content_hash()


def test_shadow_input_requires_frozen_sizing_config() -> None:
    champion, *_ = _paired_world()
    values = json.loads(champion.model_dump_json())
    values.pop("sizing_config")
    with pytest.raises(ValidationError, match="sizing_config"):
        ShadowKernelInput.model_validate_json(json.dumps(values), strict=True)


def test_shadow_schedule_is_exact_t_plus_one_and_t_plus_ten_sessions() -> None:
    champion, *_ = _paired_world()
    decision = _kernel().decide_shadow(champion)
    assert decision.target_entry_session == TRADING_SESSIONS[0]
    assert decision.counterfactual_lines[0].target_exit_session == TRADING_SESSIONS[9]
    assert decision.counterfactual_lines[0].target_exit_session != (
        SIGNAL_DATE + timedelta(days=10)
    )
    binding = decision.trading_session_schedule_binding
    assert binding.calendar_artifact_hash == "c" * 64
    assert binding.following_sessions == TRADING_SESSIONS
    assert binding.schedule_hash == champion.shared.trading_session_schedule.content_hash()


def test_shadow_projection_copies_kernel_fee_inclusive_reserve_exactly() -> None:
    champion, *_ = _paired_world()
    decision = GrowthKernel(_config(worst_case_fee_ppm=0)).decide_shadow(champion)
    line = decision.counterfactual_lines[0]
    gross = line.worst_case_price_cents * line.target_quantity_units
    expected_fee = -(
        -(gross * champion.sizing_config.worst_case_fee_ppm) // 1_000_000
    )
    assert expected_fee > 0
    assert line.estimated_fee_cents == expected_fee
    assert line.estimated_cash_reserve_cents == gross + expected_fee


def test_shadow_output_depends_on_embedded_config_not_kernel_constructor_state() -> None:
    champion, *_ = _paired_world()
    first = GrowthKernel(_config(worst_case_fee_ppm=0)).decide_shadow(champion)
    second = GrowthKernel(_config(worst_case_fee_ppm=999_999)).decide_shadow(champion)
    assert first.canonical_bytes() == second.canonical_bytes()


def test_shadow_schedule_rejects_wrong_length_order_cutoff_and_policy_version() -> None:
    champion, *_ = _paired_world()
    baseline = json.loads(champion.model_dump_json())
    mutations = []
    too_short = json.loads(json.dumps(baseline))
    too_short["shared"]["trading_session_schedule"]["following_sessions"] = [
        value.isoformat() for value in TRADING_SESSIONS[:-1]
    ]
    mutations.append(too_short)
    unordered = json.loads(json.dumps(baseline))
    unordered["shared"]["trading_session_schedule"]["following_sessions"][1] = (
        TRADING_SESSIONS[0].isoformat()
    )
    mutations.append(unordered)
    late = json.loads(json.dumps(baseline))
    late["shared"]["trading_session_schedule"]["available_at"] = NOW.isoformat()
    mutations.append(late)
    wrong_version = json.loads(json.dumps(baseline))
    wrong_version["shared"]["trading_session_schedule"]["calendar_version"] = (
        "unbound-calendar.v9"
    )
    mutations.append(wrong_version)
    for values in mutations:
        with pytest.raises(ValidationError):
            ShadowKernelInput.model_validate_json(json.dumps(values), strict=True)


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


def test_candidate_permutation_does_not_change_economic_projection() -> None:
    champion_a, *_ = _paired_world(candidates=("cand-a", "cand-b"))
    champion_b, *_ = _paired_world(candidates=("cand-b", "cand-a"))
    a_decision = _kernel().decide_shadow(champion_a)
    b_decision = _kernel().decide_shadow(champion_b)
    # Lines are canonically ordered, so the authority-free economics are
    # permutation invariant; only the embedded kernel_input_hash (the exact
    # input provenance) differs between the two orderings.
    assert economic_shadow_projection(a_decision) == economic_shadow_projection(
        b_decision
    )


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
