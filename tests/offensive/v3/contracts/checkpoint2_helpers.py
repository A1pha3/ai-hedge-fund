"""Shared tests-first builders for checkpoint 2 contract RED suites."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest


UTC = timezone.utc
SIGNAL_SESSION = date(2026, 7, 29)
TARGET_SESSION = date(2026, 7, 30)
CLOSE_FINALIZED = datetime(2026, 7, 29, 7, 59, tzinfo=UTC)
SEAL_CREATED = datetime(2026, 7, 29, 8, 0, tzinfo=UTC)
SEAL_DEADLINE = datetime(2026, 7, 29, 8, 1, tzinfo=UTC)
PERMIT_DEADLINE = datetime(2026, 7, 29, 8, 2, tzinfo=UTC)
PERMIT_EXPIRES = datetime(2026, 7, 29, 8, 3, tzinfo=UTC)
SEND_DEADLINE = PERMIT_EXPIRES
BROKER_CUTOFF = datetime(2026, 7, 29, 8, 4, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64
PORTFOLIO_ID = "portfolio-v3"
ACCOUNT_ID = "broker-account-v3"
ACCOUNT_FINGERPRINT = "1" * 64
AUTHORIZATION_ID = "authorization-v3"
AUTHORIZATION_VERSION = 3
EVIDENCE_ROOT = "2" * 64
STAGE_ID = "stage-broker-2pct"
DIFFERENT_LOGICAL_KEY = object()

# Approved from the plain, tests-first payloads above.  These literals are not
# derived from the production model under test.
APPROVED_SERIALIZATION_DIGESTS = {
    "seal": (
        "794cf274a92d93e8c7b1833801c2d65b232934f4b1f5064157687d2c3feef69e",
        "abc846695e00bfb6104b7f770318c23c3b230d8252bada03e2941af6a32f7d1b",
    ),
    "shadow": (
        "ef47050623a9627ff5366df0bb62d7440b5940672b0a5896fa8a77bf32534763",
        "3df3714bc82d3b30b09e4917ccea0bd47ef4ea91842539483a3f8d871cc7b2ea",
    ),
    "permit": (
        "3d9691aa3a5dbf1b456d76d50efaeb84ba6199393552290b55d1659c62d7bb66",
        "5461184cedebcb75a4e0c8598e02cb6eb605b83670c345831e5beec21556dabf",
    ),
}


CHECKPOINT2_NAMES = (
    "ClockHealth",
    "TrustedClockObservation",
    "TrustedExecutionWindow",
    "GatewayIssuerBinding",
    "ShadowIssuerBinding",
    "ShadowStageBinding",
    "StageAdmissionBinding",
    "SealReserveLineBinding",
    "PriorSealEligibilityBinding",
    "GatewayExpectedVersions",
    "PortfolioDecisionSeal",
    "CounterfactualDecisionKey",
    "ShadowOrderLine",
    "ShadowDecision",
    "PermitDisposition",
    "PermitReasonCode",
    "PermitNonceState",
    "ReservationState",
    "OutboxState",
    "ExecutionPermitLine",
    "PermitEvaluationState",
    "PermitCancellationBinding",
    "SendClaimExpectedVersions",
    "ExecutionPermit",
)


def _api() -> SimpleNamespace:
    from src.screening.offensive.v3 import contracts

    class _MissingContract:
        def __init__(self, name: str) -> None:
            self.name = name

        def __getattr__(self, member: str):
            pytest.fail(
                f"Checkpoint 2 contract API is missing: {self.name}.{member}",
                pytrace=False,
            )

        def __call__(self, *args, **kwargs):
            del args, kwargs
            pytest.fail(
                f"Checkpoint 2 contract API is missing: {self.name}", pytrace=False
            )

    return SimpleNamespace(
        **{
            name: getattr(contracts, name, _MissingContract(name))
            for name in CHECKPOINT2_NAMES
        },
        ArtifactKind=contracts.ArtifactKind,
        AuthorizationLifecycle=contracts.AuthorizationLifecycle,
        DecisionLogicalKey=contracts.DecisionLogicalKey,
        EvidenceScope=contracts.EvidenceScope,
        ExecutionMode=contracts.ExecutionMode,
        PlanEvidence=contracts.PlanEvidence,
        PortfolioDecision=contracts.PortfolioDecision,
        PortfolioOrderLine=contracts.PortfolioOrderLine,
        ReconciliationLatchState=contracts.ReconciliationLatchState,
        RiskLatchState=contracts.RiskLatchState,
        RiskSnapshotCompleteness=contracts.RiskSnapshotCompleteness,
        RiskSnapshotFreshness=contracts.RiskSnapshotFreshness,
        StageLossLatchState=contracts.StageLossLatchState,
        StageLossExpectedVersion=contracts.StageLossExpectedVersion,
        canonical_json_bytes=contracts.canonical_json_bytes,
        domain_hash=contracts.domain_hash,
    )


def _plan(
    api,
    *,
    suffix: str = "1",
    security_id: str = "600000.SH",
    economic_lineage_id: str = "btst-lineage-a",
):
    del security_id
    return api.PlanEvidence(
        evidence_id=f"plan-{suffix}",
        subject_scope=api.EvidenceScope.STRATEGY_LINEAGE,
        subject_producer="btst",
        family_id="btst-family",
        strategy_semver="3.0.0",
        behavior_fingerprint=HASH_A,
        policy_epoch=4,
        execution_version="t1-open-t10-open.v1",
        cost_version="cn-a-share.v1",
        effective_at=CLOSE_FINALIZED,
        observed_at=CLOSE_FINALIZED,
        available_at=CLOSE_FINALIZED,
        mode=api.ExecutionMode.BROKER_CONFIRMED,
        source_authority="btst-producer",
        payload_content_hash=HASH_B,
        schema_major=1,
        evidence_kind="plan",
        portfolio_id=PORTFOLIO_ID,
        signal_session=SIGNAL_SESSION,
        economic_lineage_id=economic_lineage_id,
        snapshot_id=f"signal-snapshot-{suffix}",
        raw_target_fraction=Decimal("0.01"),
        created_at=CLOSE_FINALIZED,
    )


def _proposal_line(api, *, suffix: str = "1", security_id: str = "600000.SH"):
    is_first = suffix == "1"
    lineage = "btst-lineage-a" if is_first else "btst-lineage-b"
    program = "btst-program-a" if is_first else "btst-program-b"
    stage = STAGE_ID if is_first else "stage-broker-2pct-b"
    plan = _plan(
        api,
        suffix=suffix,
        security_id=security_id,
        economic_lineage_id=lineage,
    )
    quantity = 100 if suffix == "1" else 200
    price = 1_050 if suffix == "1" else 800
    fee = 50 if suffix == "1" else 75
    return api.PortfolioOrderLine(
        order_line_id=f"line-{suffix}",
        security_id=security_id,
        order_action="ENTRY",
        producer_namespace="btst",
        family_id="btst-family",
        economic_lineage_id=lineage,
        research_program_id=program,
        stage_id=stage,
        stage_manifest_hash=HASH_C,
        grant_id=f"grant-{lineage}",
        grant_certificate_hash=HASH_D,
        authorization_id=AUTHORIZATION_ID,
        authorization_version=AUTHORIZATION_VERSION,
        plan_evidence=plan,
        plan_evidence_artifact_hash=plan.content_hash(),
        plan_payload_content_hash=plan.payload_content_hash,
        mode=api.ExecutionMode.BROKER_CONFIRMED,
        target_entry_session=TARGET_SESSION,
        exit_session_ordinal=10,
        sealed_quantity_units=quantity,
        lot_size_units=100,
        lot_rule_version="cn-a-share-lot.v1",
        order_type="LIMIT",
        limit_price_cents=price,
        worst_case_price_cents=price,
        price_boundary_version="cn-price-limit.v1",
        time_in_force="OPEN_AUCTION",
        worst_case_fee_reserve_cents=fee,
        worst_case_cash_reserve_cents=price * quantity + fee,
    )


def _proposal(api):
    lines = (
        _proposal_line(api),
        _proposal_line(api, suffix="2", security_id="600001.SH"),
    )
    return api.PortfolioDecision(
        logical_key=api.DecisionLogicalKey(
            portfolio_id=PORTFOLIO_ID,
            signal_session=SIGNAL_SESSION,
            decision_cycle_id="daily-t1-open-v1",
        ),
        portfolio_id=PORTFOLIO_ID,
        broker_account_id=ACCOUNT_ID,
        broker_account_fingerprint=ACCOUNT_FINGERPRINT,
        base_currency="CNY",
        mode=api.ExecutionMode.BROKER_CONFIRMED,
        target_entry_session=TARGET_SESSION,
        target_portfolio_policy_fingerprint=HASH_E,
        policy_activation_hash=HASH_A,
        trust_bundle_hash=HASH_B,
        registry_epoch=7,
        policy_epoch=4,
        authority_epoch=5,
        risk_epoch=6,
        authorization_id=AUTHORIZATION_ID,
        authorization_version=AUTHORIZATION_VERSION,
        authorization_artifact_hash=HASH_C,
        evidence_set_merkle_root=EVIDENCE_ROOT,
        risk_snapshot_id="risk-snapshot-1",
        risk_snapshot_artifact_hash=HASH_D,
        risk_snapshot_as_of=CLOSE_FINALIZED,
        capital_version=10,
        capital_stream_version=29,
        writer_fencing_epoch=11,
        order_lines=lines,
        total_worst_case_cash_reserve_cents=sum(
            line.worst_case_cash_reserve_cents for line in lines
        ),
        decision_cutoff=CLOSE_FINALIZED + timedelta(seconds=30),
        proposal_created_at=CLOSE_FINALIZED + timedelta(seconds=45),
        schema_major=2,
    )


def _window_payload(api, **overrides):
    values = {
        "signal_session": SIGNAL_SESSION,
        "target_entry_session": TARGET_SESSION,
        "exchange_id": "SSE",
        "calendar_snapshot_id": "calendar-cn-20260729",
        "calendar_snapshot_hash": HASH_A,
        "calendar_snapshot_version": 3,
        "cutoff_snapshot_id": "cutoff-sse-20260730",
        "cutoff_snapshot_hash": HASH_B,
        "cutoff_snapshot_version": 4,
        "cutoff_snapshot_session": TARGET_SESSION,
        "cutoff_snapshot_exchange_id": "SSE",
        "execution_policy_version": "t1-open-t10-open.v1",
        "cutoff_policy_version": "sse-opening-auction.v1",
        "seal_clock_observation": _clock_observation(api),
        "t0_close_finalized_at": CLOSE_FINALIZED,
        "seal_creation_deadline": SEAL_DEADLINE,
        "permit_issue_deadline": PERMIT_DEADLINE,
        "gateway_send_deadline": SEND_DEADLINE,
        "broker_auction_submission_cutoff": BROKER_CUTOFF,
    }
    values.update(overrides)
    return values


def _window(api, **overrides):
    return api.TrustedExecutionWindow.model_validate(_window_payload(api, **overrides))


def _clock_observation(
    api,
    *,
    observation_id="clock-observation-seal-1",
    raw_payload_hash=HASH_C,
    wall_clock_utc=SEAL_CREATED,
    monotonic_observation_ns=1_000_000,
    monotonic_sequence=8,
    clock_health=None,
):
    if clock_health is None:
        clock_health = api.ClockHealth.HEALTHY
    return api.TrustedClockObservation(
        observation_id=observation_id,
        raw_payload_hash=raw_payload_hash,
        wall_clock_utc=wall_clock_utc,
        monotonic_observation_ns=monotonic_observation_ns,
        monotonic_sequence=monotonic_sequence,
        clock_health=clock_health,
    )


def _permit_clock_observation(api, **overrides):
    values = {
        "observation_id": "clock-observation-permit-1",
        "raw_payload_hash": HASH_D,
        "wall_clock_utc": PERMIT_DEADLINE,
        "monotonic_observation_ns": 2_000_000,
        "monotonic_sequence": 9,
        "clock_health": api.ClockHealth.HEALTHY,
    }
    values.update(overrides)
    return _clock_observation(api, **values)


def _gateway_issuer(api, artifact_kind, namespace, *, verified_at=CLOSE_FINALIZED):
    return api.GatewayIssuerBinding(
        issuer_id="capital-gateway.service",
        key_id="capital-gateway-key-1",
        capability_artifact_kind=artifact_kind,
        capability_namespace=namespace,
        capability_mode=api.ExecutionMode.BROKER_CONFIRMED,
        capability_schema_major=2,
        capability_version="capital-gateway.v1",
        capability_scope=f"portfolio:{PORTFOLIO_ID}",
        verified_at=verified_at,
        trust_bundle_hash=HASH_B,
        registry_epoch=7,
    )


def _stage_binding(api, line=None):
    if line is None:
        line = _proposal_line(api)
    return api.StageAdmissionBinding(
        research_program_id=line.research_program_id,
        economic_lineage_id=line.economic_lineage_id,
        stage_id=line.stage_id,
        stage_loss_budget_id=f"budget-{line.economic_lineage_id}",
        expected_stage_loss_version=3,
        post_stage_loss_version=4,
        stage_loss_latch=api.StageLossLatchState.CLEAR,
    )


def _stage_expected_version(api, line):
    return api.StageLossExpectedVersion(
        research_program_id=line.research_program_id,
        economic_lineage_id=line.economic_lineage_id,
        stage_id=line.stage_id,
        stage_loss_budget_id=f"budget-{line.economic_lineage_id}",
        stage_loss_version=3,
        stage_loss_latch=api.StageLossLatchState.CLEAR,
    )


def _gateway_expected_versions(api, proposal=None, **overrides):
    if proposal is None:
        proposal = _proposal(api)
    values = {
        "policy_activation_hash": proposal.policy_activation_hash,
        "trust_bundle_hash": proposal.trust_bundle_hash,
        "registry_epoch": proposal.registry_epoch,
        "policy_epoch": proposal.policy_epoch,
        "authority_epoch": proposal.authority_epoch,
        "risk_epoch": proposal.risk_epoch,
        "authorization_id": proposal.authorization_id,
        "authorization_version": proposal.authorization_version,
        "authorization_envelope_hash": proposal.authorization_artifact_hash,
        "authorization_status_version": 5,
        "authorization_status_hash": HASH_E,
        "evidence_set_merkle_root": proposal.evidence_set_merkle_root,
        "entry_fence_id": "entry-fence-1",
        "entry_fence_hash": HASH_F,
        "entry_fence_version": 2,
        "risk_snapshot_id": proposal.risk_snapshot_id,
        "risk_snapshot_artifact_hash": proposal.risk_snapshot_artifact_hash,
        "capital_version": proposal.capital_version,
        "capital_stream_version": proposal.capital_stream_version,
        "writer_fencing_epoch": proposal.writer_fencing_epoch,
        "stage_loss_expected_versions": tuple(
            sorted(
                (_stage_expected_version(api, line) for line in proposal.order_lines),
                key=lambda item: (
                    item.research_program_id,
                    item.economic_lineage_id,
                    item.stage_id,
                    item.stage_loss_budget_id,
                ),
            )
        ),
        "expected_active_seal_id": None,
        "expected_active_seal_revision": None,
        "expected_active_seal_logical_key": None,
        "expected_active_seal_artifact_hash": None,
        "schema_major": 2,
    }
    values.update(overrides)
    return api.GatewayExpectedVersions.model_validate(values)


def _reserve_bindings(api, proposal):
    return tuple(
        api.SealReserveLineBinding(
            order_line_id=line.order_line_id,
            reservation_allocation_id=f"reserve-allocation-{line.order_line_id}",
            reserved_cash_cents=line.worst_case_cash_reserve_cents,
        )
        for line in proposal.order_lines
    )


def _prior_seal_eligibility(api, logical_key=None, **overrides):
    if logical_key is None:
        logical_key = _proposal(api).logical_key
    values = {
        "prior_seal_id": "seal-0",
        "prior_seal_revision": 1,
        "prior_seal_artifact_hash": "9" * 64,
        "logical_key": logical_key,
        "permit_issuance_sequence": 0,
        "fencing_token_issuance_sequence": 0,
        "live_order_count": 0,
    }
    values.update(overrides)
    return api.PriorSealEligibilityBinding.model_validate(values)


def _seal_payload(api, **overrides):
    proposal = overrides.pop("proposal", _proposal(api))
    eligibility = overrides.get("prior_seal_eligibility")
    if "consumed_gateway_expected_versions" in overrides:
        expected = overrides.pop("consumed_gateway_expected_versions")
    elif eligibility is None:
        expected = _gateway_expected_versions(api, proposal)
    else:
        expected = _gateway_expected_versions(
            api,
            proposal,
            expected_active_seal_id=eligibility.prior_seal_id,
            expected_active_seal_revision=eligibility.prior_seal_revision,
            expected_active_seal_logical_key=eligibility.logical_key,
            expected_active_seal_artifact_hash=(eligibility.prior_seal_artifact_hash),
        )
    reserve_lines = _reserve_bindings(api, proposal)
    values = {
        "artifact_kind": api.ArtifactKind.PORTFOLIO_DECISION_SEAL,
        "artifact_namespace": "capital-gateway.entry-seal.v1",
        "schema_major": 2,
        "seal_id": "seal-1",
        "seal_revision": 1,
        "logical_key": proposal.logical_key,
        "supersedes_seal_id": None,
        "supersedes_seal_revision": None,
        "prior_seal_eligibility": None,
        "proposal": proposal,
        "proposal_artifact_hash": proposal.artifact_hash(),
        "portfolio_id": proposal.portfolio_id,
        "broker_account_id": proposal.broker_account_id,
        "broker_account_fingerprint": proposal.broker_account_fingerprint,
        "base_currency": proposal.base_currency,
        "mode": proposal.mode,
        "target_entry_session": proposal.target_entry_session,
        "target_portfolio_policy_fingerprint": (
            proposal.target_portfolio_policy_fingerprint
        ),
        "policy_activation_hash": proposal.policy_activation_hash,
        "trust_bundle_hash": proposal.trust_bundle_hash,
        "registry_epoch": proposal.registry_epoch,
        "policy_epoch": proposal.policy_epoch,
        "authority_epoch": proposal.authority_epoch,
        "risk_epoch": proposal.risk_epoch,
        "authorization_id": proposal.authorization_id,
        "authorization_version": proposal.authorization_version,
        "authorization_envelope_hash": proposal.authorization_artifact_hash,
        "authorization_status_version": expected.authorization_status_version,
        "authorization_status_hash": expected.authorization_status_hash,
        "evidence_set_merkle_root": proposal.evidence_set_merkle_root,
        "entry_fence_id": "entry-fence-1",
        "entry_fence_hash": HASH_F,
        "entry_fence_version": 2,
        "risk_snapshot_id": proposal.risk_snapshot_id,
        "risk_snapshot_artifact_hash": proposal.risk_snapshot_artifact_hash,
        "capital_version": proposal.capital_version,
        "capital_stream_version": proposal.capital_stream_version,
        "stage_admission_bindings": tuple(
            sorted(
                (_stage_binding(api, line) for line in proposal.order_lines),
                key=lambda item: (
                    item.research_program_id,
                    item.economic_lineage_id,
                    item.stage_id,
                    item.stage_loss_budget_id,
                ),
            )
        ),
        "writer_fencing_epoch": proposal.writer_fencing_epoch,
        "consumed_gateway_expected_versions": expected,
        "consumed_gateway_expected_versions_artifact_hash": (expected.artifact_hash()),
        "reservation_id": "reservation-1",
        "reservation_version": 1,
        "line_reserve_bindings": reserve_lines,
        "total_reserved_cash_cents": sum(
            item.reserved_cash_cents for item in reserve_lines
        ),
        "post_admission_capital_version": proposal.capital_version + 1,
        "post_admission_reservation_version": 2,
        "execution_window": _window(api),
        "created_at": SEAL_CREATED,
        "issuer_binding": _gateway_issuer(
            api,
            api.ArtifactKind.PORTFOLIO_DECISION_SEAL,
            "capital-gateway.entry-seal.v1",
        ),
    }
    values.update(overrides)
    return values


def _seal(api, **overrides):
    return api.PortfolioDecisionSeal.model_validate(_seal_payload(api, **overrides))


def _shadow_issuer(api):
    return api.ShadowIssuerBinding(
        issuer_id="growth-kernel.shadow.service",
        key_id="shadow-key-1",
        capability_artifact_kind=api.ArtifactKind.SHADOW_DECISION,
        capability_namespace="growth-kernel.shadow.v1",
        capability_mode=api.ExecutionMode.BROKER_CONFIRMED,
        capability_schema_major=2,
        capability_version="growth-kernel-shadow.v1",
        capability_scope=f"portfolio:{PORTFOLIO_ID}",
        verified_at=CLOSE_FINALIZED,
        trust_bundle_hash=HASH_B,
        registry_epoch=7,
    )


def _shadow_stage_binding(api):
    return api.ShadowStageBinding(
        research_program_id="auto-program",
        economic_lineage_id="auto-lineage",
        stage_id="auto-shadow-stage",
        trial_id="auto-shadow-trial",
        stage_manifest_hash=HASH_C,
    )


def _shadow_line(api, *, suffix="1", security_id="600000.SH"):
    quantity = 100 if suffix == "1" else 200
    price = 1_050 if suffix == "1" else 800
    fee = 50 if suffix == "1" else 75
    return api.ShadowOrderLine(
        shadow_line_id=f"shadow-line-{suffix}",
        security_id=security_id,
        producer_namespace="auto.shadow",
        family_id="auto-family",
        economic_lineage_id="auto-lineage",
        research_program_id="auto-program",
        stage_id="auto-shadow-stage",
        trial_id="auto-shadow-trial",
        stage_manifest_hash=HASH_C,
        evidence_id=f"shadow-evidence-{suffix}",
        evidence_artifact_hash=HASH_D,
        evidence_payload_hash=HASH_E,
        target_quantity_units=quantity,
        lot_size_units=100,
        lot_rule_version="cn-a-share-lot.v1",
        order_type="LIMIT",
        limit_price_cents=price,
        worst_case_price_cents=price,
        price_boundary_version="cn-price-limit.v1",
        time_in_force="OPEN_AUCTION",
        exit_session_ordinal=10,
        estimated_fee_cents=fee,
        estimated_cash_reserve_cents=price * quantity + fee,
        cost_assumption_version="cn-a-share.v1",
        execution_assumption_version="t1-open-t10-open.v1",
    )


def _shadow_payload(api, **overrides):
    values = {
        "artifact_kind": api.ArtifactKind.SHADOW_DECISION,
        "artifact_namespace": "growth-kernel.shadow.v1",
        "schema_major": 2,
        "shadow_decision_id": "shadow-decision-1",
        "counterfactual_key": api.CounterfactualDecisionKey(
            portfolio_id=PORTFOLIO_ID,
            signal_session=SIGNAL_SESSION,
            counterfactual_cycle_id="auto-shadow-daily-v1",
        ),
        "portfolio_id": PORTFOLIO_ID,
        "mode": api.ExecutionMode.BROKER_CONFIRMED,
        "target_entry_session": TARGET_SESSION,
        "producer_namespace": "auto.shadow",
        "family_id": "auto-family",
        "research_program_id": "auto-program",
        "economic_lineage_id": "auto-lineage",
        "stage_id": "auto-shadow-stage",
        "trial_id": "auto-shadow-trial",
        "policy_activation_hash": HASH_A,
        "policy_epoch": 4,
        "evidence_set_merkle_root": EVIDENCE_ROOT,
        "shadow_stage_binding": _shadow_stage_binding(api),
        "counterfactual_lines": (
            _shadow_line(api),
            _shadow_line(api, suffix="2", security_id="600001.SH"),
        ),
        "cost_assumption_version": "cn-a-share.v1",
        "execution_assumption_version": "t1-open-t10-open.v1",
        "created_at": SEAL_CREATED,
        "available_at": SEAL_CREATED,
        "execution_authority": "NONE",
        "issuer_binding": _shadow_issuer(api),
    }
    values.update(overrides)
    return values


def _shadow(api, **overrides):
    return api.ShadowDecision.model_validate(_shadow_payload(api, **overrides))


def _permit_line(
    api,
    sealed_line,
    *,
    disposition=None,
    permitted_quantity=None,
    reason_code=None,
    preopen_fact_as_of=PERMIT_DEADLINE,
    client_order_id="AUTO",
):
    if disposition is None:
        disposition = api.PermitDisposition.ALLOW
    if permitted_quantity is None:
        permitted_quantity = sealed_line.sealed_quantity_units
    remaining = sealed_line.worst_case_price_cents * permitted_quantity + (
        sealed_line.worst_case_fee_reserve_cents if permitted_quantity else 0
    )
    released = sealed_line.worst_case_cash_reserve_cents - remaining
    sendable = disposition is api.PermitDisposition.ALLOW and permitted_quantity > 0
    if reason_code is None:
        reason_code = (
            api.PermitReasonCode.UNCHANGED
            if permitted_quantity == sealed_line.sealed_quantity_units
            else (
                api.PermitReasonCode.CAPITAL_RISK_REDUCTION
                if permitted_quantity > 0
                else api.PermitReasonCode.AUTHORIZATION_CANCEL
            )
        )
    if client_order_id == "AUTO":
        client_order_id = f"client-{sealed_line.order_line_id}" if sendable else None
    return api.ExecutionPermitLine(
        order_line_id=sealed_line.order_line_id,
        security_id=sealed_line.security_id,
        sealed_quantity_units=sealed_line.sealed_quantity_units,
        permitted_quantity_units=permitted_quantity,
        reason_code=reason_code,
        predicate_policy_version="t1-open-t10-open.v1",
        preopen_fact_snapshot_id="preopen-facts-1",
        preopen_fact_snapshot_hash=HASH_A,
        preopen_fact_as_of=preopen_fact_as_of,
        client_order_id=client_order_id,
        order_type=sealed_line.order_type,
        limit_price_cents=sealed_line.limit_price_cents,
        worst_case_price_cents=sealed_line.worst_case_price_cents,
        price_boundary_version=sealed_line.price_boundary_version,
        time_in_force=sealed_line.time_in_force,
        exit_session_ordinal=sealed_line.exit_session_ordinal,
        sealed_reserve_cents=sealed_line.worst_case_cash_reserve_cents,
        remaining_reserve_cents=remaining,
        released_reserve_cents=released,
    )


def _permit_evaluation_state(api, seal, **overrides):
    values = {
        "policy_activation_hash": seal.policy_activation_hash,
        "trust_bundle_hash": seal.trust_bundle_hash,
        "registry_epoch": seal.registry_epoch,
        "policy_epoch": seal.policy_epoch,
        "authority_epoch": seal.authority_epoch,
        "risk_epoch": seal.risk_epoch,
        "authorization_id": seal.authorization_id,
        "authorization_version": seal.authorization_version,
        "authorization_envelope_hash": seal.authorization_envelope_hash,
        "authorization_lifecycle": api.AuthorizationLifecycle.ACTIVE,
        "authorization_status_version": seal.authorization_status_version + 1,
        "authorization_status_hash": HASH_A,
        "authorization_revalidation_required": False,
        "evidence_set_merkle_root": seal.evidence_set_merkle_root,
        "entry_fence_id": seal.entry_fence_id,
        "entry_fence_hash": seal.entry_fence_hash,
        "entry_fence_version": seal.entry_fence_version,
        "capital_version": seal.post_admission_capital_version + 1,
        "capital_stream_version": seal.capital_stream_version + 2,
        "risk_snapshot_id": "risk-snapshot-preopen-1",
        "risk_snapshot_artifact_hash": HASH_E,
        "risk_snapshot_version": 4,
        "risk_snapshot_freshness": api.RiskSnapshotFreshness.FRESH,
        "risk_snapshot_completeness": api.RiskSnapshotCompleteness.COMPLETE,
        "risk_latch": api.RiskLatchState.CLEAR,
        "reconciliation_latch": api.ReconciliationLatchState.CLEAR,
        "stage_loss_bindings": tuple(
            api.StageLossExpectedVersion(
                research_program_id=item.research_program_id,
                economic_lineage_id=item.economic_lineage_id,
                stage_id=item.stage_id,
                stage_loss_budget_id=item.stage_loss_budget_id,
                stage_loss_version=item.post_stage_loss_version + 1,
                stage_loss_latch=api.StageLossLatchState.CLEAR,
            )
            for item in seal.stage_admission_bindings
        ),
        "reservation_id": seal.reservation_id,
        "reservation_version": seal.post_admission_reservation_version + 1,
        "reservation_state": api.ReservationState.ACTIVE,
        "remaining_reserved_cash_cents": seal.total_reserved_cash_cents,
        "writer_fencing_epoch": seal.writer_fencing_epoch,
    }
    values.update(overrides)
    return api.PermitEvaluationState.model_validate(values)


def _send_claim_versions(
    api,
    seal,
    permit_lines,
    *,
    nonce="permit-nonce-1",
    evaluation_state=None,
):
    if evaluation_state is None:
        evaluation_state = _permit_evaluation_state(api, seal)
    remaining = sum(line.remaining_reserve_cents for line in permit_lines)
    return api.SendClaimExpectedVersions(
        active_seal_id=seal.seal_id,
        active_seal_revision=seal.seal_revision,
        active_seal_artifact_hash=seal.artifact_hash(),
        active_permit_id="permit-1",
        active_permit_nonce=nonce,
        permit_nonce_sequence=1,
        permit_nonce_state=api.PermitNonceState.ACTIVE,
        policy_activation_hash=evaluation_state.policy_activation_hash,
        trust_bundle_hash=evaluation_state.trust_bundle_hash,
        registry_epoch=evaluation_state.registry_epoch,
        policy_epoch=evaluation_state.policy_epoch,
        authority_epoch=evaluation_state.authority_epoch,
        risk_epoch=evaluation_state.risk_epoch,
        authorization_id=evaluation_state.authorization_id,
        authorization_version=evaluation_state.authorization_version,
        authorization_envelope_hash=evaluation_state.authorization_envelope_hash,
        authorization_lifecycle=evaluation_state.authorization_lifecycle,
        authorization_status_version=evaluation_state.authorization_status_version,
        authorization_status_hash=evaluation_state.authorization_status_hash,
        authorization_revalidation_required=(
            evaluation_state.authorization_revalidation_required
        ),
        evidence_set_merkle_root=evaluation_state.evidence_set_merkle_root,
        entry_fence_id=evaluation_state.entry_fence_id,
        entry_fence_hash=evaluation_state.entry_fence_hash,
        entry_fence_version=evaluation_state.entry_fence_version,
        capital_version=evaluation_state.capital_version + 1,
        capital_stream_version=evaluation_state.capital_stream_version + 1,
        risk_snapshot_id=evaluation_state.risk_snapshot_id,
        risk_snapshot_artifact_hash=evaluation_state.risk_snapshot_artifact_hash,
        risk_snapshot_version=evaluation_state.risk_snapshot_version + 1,
        risk_snapshot_freshness=evaluation_state.risk_snapshot_freshness,
        risk_snapshot_completeness=evaluation_state.risk_snapshot_completeness,
        risk_latch=evaluation_state.risk_latch,
        reconciliation_latch=evaluation_state.reconciliation_latch,
        stage_loss_bindings=tuple(
            item.model_copy(update={"stage_loss_version": item.stage_loss_version + 1})
            for item in evaluation_state.stage_loss_bindings
        ),
        reservation_id=evaluation_state.reservation_id,
        reservation_version=evaluation_state.reservation_version + 1,
        reservation_state=api.ReservationState.ACTIVE,
        remaining_reserved_cash_cents=remaining,
        outbox_batch_id="outbox-batch-1",
        outbox_payload_hash=HASH_B,
        outbox_state=api.OutboxState.DURABLE,
        outbox_permit_nonce=nonce,
        writer_fencing_epoch=evaluation_state.writer_fencing_epoch,
        effective_send_deadline=min(PERMIT_EXPIRES, SEND_DEADLINE),
    )


def _cancellation_binding(api, seal, *, evaluation_state=None, nonce="permit-nonce-1"):
    if evaluation_state is None:
        evaluation_state = _permit_evaluation_state(api, seal)
    return api.PermitCancellationBinding(
        permit_nonce=nonce,
        reservation_id=evaluation_state.reservation_id,
        pre_reservation_version=evaluation_state.reservation_version,
        post_reservation_version=evaluation_state.reservation_version + 1,
        post_reservation_state=api.ReservationState.RELEASED,
        released_cash_cents=evaluation_state.remaining_reserved_cash_cents,
        remaining_reserved_cash_cents=0,
        outbox_batch_id="outbox-batch-1",
        outbox_payload_hash=HASH_B,
        post_outbox_state=api.OutboxState.TOMBSTONED,
        post_capital_version=evaluation_state.capital_version + 1,
        post_capital_stream_version=evaluation_state.capital_stream_version + 1,
        writer_fencing_epoch=evaluation_state.writer_fencing_epoch,
    )


def _permit_payload(api, **overrides):
    seal = overrides.pop("seal", _seal(api))
    disposition = overrides.pop("disposition", api.PermitDisposition.ALLOW)
    permit_nonce = overrides.pop("permit_nonce", "permit-nonce-1")
    permit_lines = overrides.pop(
        "permit_lines",
        tuple(
            _permit_line(api, line, disposition=disposition)
            for line in seal.proposal.order_lines
        ),
    )
    evaluation_state = overrides.pop(
        "evaluation_state", _permit_evaluation_state(api, seal)
    )
    if disposition is api.PermitDisposition.ALLOW:
        expected = overrides.pop(
            "send_claim_expected_versions",
            _send_claim_versions(
                api,
                seal,
                permit_lines,
                nonce=permit_nonce,
                evaluation_state=evaluation_state,
            ),
        )
        cancellation_binding = overrides.pop("cancellation_binding", None)
    else:
        expected = overrides.pop("send_claim_expected_versions", None)
        cancellation_binding = overrides.pop(
            "cancellation_binding",
            _cancellation_binding(
                api, seal, evaluation_state=evaluation_state, nonce=permit_nonce
            ),
        )
    values = {
        "artifact_kind": api.ArtifactKind.EXECUTION_PERMIT,
        "artifact_namespace": "capital-gateway.entry-permit.v1",
        "schema_major": 2,
        "permit_id": "permit-1",
        "permit_nonce": permit_nonce,
        "permit_nonce_sequence": 1,
        "permit_nonce_state": api.PermitNonceState.ACTIVE,
        "disposition": disposition,
        "seal": seal,
        "seal_id": seal.seal_id,
        "seal_revision": seal.seal_revision,
        "seal_artifact_hash": seal.artifact_hash(),
        "logical_key": seal.logical_key,
        "proposal_artifact_hash": seal.proposal_artifact_hash,
        "portfolio_id": seal.portfolio_id,
        "broker_account_id": seal.broker_account_id,
        "broker_account_fingerprint": seal.broker_account_fingerprint,
        "base_currency": seal.base_currency,
        "mode": seal.mode,
        "target_entry_session": seal.target_entry_session,
        "permit_lines": permit_lines,
        "total_remaining_reserve_cents": sum(
            line.remaining_reserve_cents for line in permit_lines
        ),
        "total_released_reserve_cents": sum(
            line.released_reserve_cents for line in permit_lines
        ),
        "permit_clock_observation": _permit_clock_observation(api),
        "evaluation_state": evaluation_state,
        "send_claim_expected_versions": expected,
        "cancellation_binding": cancellation_binding,
        "execution_window": seal.execution_window,
        "issued_at": PERMIT_DEADLINE,
        "permit_expires_at": PERMIT_EXPIRES,
        "issuer_binding": _gateway_issuer(
            api,
            api.ArtifactKind.EXECUTION_PERMIT,
            "capital-gateway.entry-permit.v1",
            verified_at=CLOSE_FINALIZED,
        ),
    }
    values.update(overrides)
    return values


def _permit(api, **overrides):
    return api.ExecutionPermit.model_validate(_permit_payload(api, **overrides))
