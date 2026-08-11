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
# derived from the production model under test.  Re-approved for the official
# Trial execution/cost versions (t1-open-t10-open-slippage.v2 /
# cn-a-share-30bps-tax.v2); the field-level diff vs the v1 approval touches
# only those version strings and the artifact hashes they feed.
APPROVED_SERIALIZATION_DIGESTS = {
    "seal": (
        "4952edac2f11b57b14bd3c4890d30ba5584144ab27677740f4c7075dc0588ffb",
        "f60ce29b40a8f2fd55e893b0d3b5959d151ef004195ffa067c783513c28f39e7",
    ),
    "shadow": (
        "07e355206ffe89ab3833a00022a2cb3f04d79464bc2d58dee89609a638564dee",
        "5aab361743b455592aed78d0378be7c723f7962e01c2504938680da9e1a7c446",
    ),
    "permit": (
        "559cd93df4056284cde96eb0fbc5a3af3a5f3513eb6f39e26ee69a2818f7ce5c",
        "b8ce5ea9897686b8a46cd097e890168b2b65793ba4a4a657dbf3d779dc80bac7",
    ),
    "receipt": (
        "398ee67e3560b4dc79ef70b8c0507e93574df2ce4068b579dd97ee4dafd3f3ba",
        "bc7f5d3317b758318f42d5b5d2176f8803bf7a36bb46d379f4840121577cd668",
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
    "BaselineShadowPolicyBinding",
    "ShadowPolicySourceKind",
    "PermitDisposition",
    "PermitReasonCode",
    "PermitNonceState",
    "ReservationState",
    "OutboxState",
    "ActiveEntryClaimState",
    "AuthorizationIssuanceBinding",
    "AuthorizationIssuerVerificationResult",
    "AuthorizationIssuerRevalidation",
    "ReservationLineAllocation",
    "PermitLineMechanicalBinding",
    "ExecutionPermitLine",
    "PermitEvaluationState",
    "PermitCancellationBinding",
    "SendClaimExpectedVersions",
    "ExecutionPermit",
    "EntryCancellationReceipt",
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
        CapitalRiskSnapshot=contracts.CapitalRiskSnapshot,
        EntryReserveRiskComponent=contracts.EntryReserveRiskComponent,
        ExposureScope=contracts.ExposureScope,
        RiskExposureBucket=contracts.RiskExposureBucket,
        StageLossLatchSnapshot=contracts.StageLossLatchSnapshot,
        DecisionLogicalKey=contracts.DecisionLogicalKey,
        EvidenceRecord=contracts.EvidenceRecord,
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
        execution_version="t1-open-t10-open-slippage.v2",
        cost_version="cn-a-share-30bps-tax.v2",
        effective_at=CLOSE_FINALIZED,
        provider_published_at=CLOSE_FINALIZED,
        observed_at=CLOSE_FINALIZED,
        available_at=CLOSE_FINALIZED,
        mode=api.ExecutionMode.BROKER_CONFIRMED,
        source_authority="btst-producer",
        payload_content_hash=HASH_B,
        schema_major=2,
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
    plan_record = api.EvidenceRecord[api.PlanEvidence](
        evidence=plan,
        ingested_at=plan.available_at,
        commit_sequence=int(suffix),
        revision=1,
        supersedes_revision=None,
        active_revision=1,
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
        plan_evidence=plan_record,
        plan_evidence_artifact_hash=plan_record.artifact_hash(),
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
        "execution_policy_version": "t1-open-t10-open-slippage.v2",
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


def _gateway_issuer(
    api,
    artifact_kind,
    namespace,
    *,
    verified_at=CLOSE_FINALIZED,
    valid_until=BROKER_CUTOFF,
    trust_bundle_hash=HASH_B,
    registry_epoch=7,
):
    return api.GatewayIssuerBinding(
        issuer_id="capital-gateway.service",
        key_id="capital-gateway-key-1",
        capability_artifact_kind=artifact_kind,
        capability_namespace=namespace,
        capability_mode=api.ExecutionMode.BROKER_CONFIRMED,
        capability_schema_major=2,
        capability_version="capital-gateway.v1",
        capability_scope=f"portfolio:{PORTFOLIO_ID}",
        verification_result="VALID",
        verified_at=verified_at,
        valid_until=valid_until,
        trust_bundle_hash=trust_bundle_hash,
        registry_epoch=registry_epoch,
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
    stage_admissions = overrides.get(
        "stage_admission_bindings",
        tuple(
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
    )
    post_admission_capital_version = overrides.get(
        "post_admission_capital_version", proposal.capital_version + 1
    )
    post_admission_capital_stream_version = overrides.get(
        "post_admission_capital_stream_version",
        proposal.capital_stream_version + 1,
    )
    post_snapshot_context = SimpleNamespace(
        proposal=proposal,
        portfolio_id=proposal.portfolio_id,
        broker_account_id=proposal.broker_account_id,
        base_currency=proposal.base_currency,
        mode=proposal.mode,
        policy_activation_hash=proposal.policy_activation_hash,
        policy_epoch=proposal.policy_epoch,
        authority_epoch=proposal.authority_epoch,
        risk_epoch=proposal.risk_epoch,
        registry_epoch=proposal.registry_epoch,
        authorization_id=proposal.authorization_id,
        authorization_version=proposal.authorization_version,
        writer_fencing_epoch=proposal.writer_fencing_epoch,
        stage_admission_bindings=stage_admissions,
        post_admission_capital_version=post_admission_capital_version,
    )
    post_admission_snapshot = _capital_risk_snapshot(
        api,
        post_snapshot_context,
        tuple(
            api.ReservationLineAllocation(
                order_line_id=item.order_line_id,
                reservation_allocation_id=item.reservation_allocation_id,
                reserved_cash_cents=item.reserved_cash_cents,
            )
            for item in reserve_lines
        ),
        snapshot_id="risk-snapshot-post-admission-1",
        as_of=SEAL_CREATED,
        valid_until=PERMIT_EXPIRES,
        capital_version=post_admission_capital_version,
    )
    authorization_issuance_binding = api.AuthorizationIssuanceBinding(
        authorization_envelope_hash=proposal.authorization_artifact_hash,
        authorization_issuer_id="authorizer.service",
        authorization_issuer_key_id="authorizer-key-1",
        authorization_issuer_capability="capital-authorization.edge.v1",
        authorization_issuer_capability_version="authorizer-capability.v1",
        authorization_issuer_identity_fingerprint=HASH_A,
        registry_epoch=proposal.registry_epoch,
        trust_bundle_hash=proposal.trust_bundle_hash,
    )
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
        "authorization_issuance_binding": authorization_issuance_binding,
        "authorization_issuance_binding_artifact_hash": (
            authorization_issuance_binding.artifact_hash()
        ),
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
        "stage_admission_bindings": stage_admissions,
        "writer_fencing_epoch": proposal.writer_fencing_epoch,
        "consumed_gateway_expected_versions": expected,
        "consumed_gateway_expected_versions_artifact_hash": (expected.artifact_hash()),
        "reservation_id": "reservation-1",
        "reservation_version": 1,
        "line_reserve_bindings": reserve_lines,
        "total_reserved_cash_cents": sum(
            item.reserved_cash_cents for item in reserve_lines
        ),
        "post_admission_capital_version": post_admission_capital_version,
        "post_admission_capital_stream_version": (
            post_admission_capital_stream_version
        ),
        "post_admission_reservation_version": 2,
        "post_admission_risk_snapshot_id": post_admission_snapshot.risk_snapshot_id,
        "post_admission_risk_snapshot_artifact_hash": (
            post_admission_snapshot.artifact_hash()
        ),
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
        capability_namespace="growth-kernel.shadow.v2",
        capability_mode=api.ExecutionMode.BROKER_CONFIRMED,
        capability_schema_major=3,
        capability_version="growth-kernel-shadow.v2",
        capability_scope=f"portfolio:{PORTFOLIO_ID}",
        verification_result="VALID",
        verified_at=CLOSE_FINALIZED,
        valid_until=BROKER_CUTOFF,
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
        cost_assumption_version="cn-a-share-30bps-tax.v2",
        execution_assumption_version="t1-open-t10-open-slippage.v2",
        target_exit_session=date(2026, 8, 8),
    )


def _shadow_payload(api, **overrides):
    values = {
        "artifact_kind": api.ArtifactKind.SHADOW_DECISION,
        "artifact_namespace": "growth-kernel.shadow.v2",
        "schema_major": 3,
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
        "shadow_policy_binding": api.BaselineShadowPolicyBinding(
            source_kind=api.ShadowPolicySourceKind.BASELINE_POLICY_ACTIVATION,
            baseline_policy_activation_hash=HASH_A,
            policy_snapshot_hash=HASH_B,
            policy_fingerprint=EVIDENCE_ROOT,
        ),
        "policy_epoch": 4,
        "evidence_set_merkle_root": EVIDENCE_ROOT,
        "shadow_stage_binding": _shadow_stage_binding(api),
        "counterfactual_lines": (
            _shadow_line(api),
            _shadow_line(api, suffix="2", security_id="600001.SH"),
        ),
        "cost_assumption_version": "cn-a-share-30bps-tax.v2",
        "execution_assumption_version": "t1-open-t10-open-slippage.v2",
        "created_at": SEAL_CREATED,
        "available_at": SEAL_CREATED,
        "execution_authority": "NONE",
        "issuer_binding": _shadow_issuer(api),
    }
    values.update(overrides)
    return values


def _shadow(api, **overrides):
    return api.ShadowDecision.model_validate(_shadow_payload(api, **overrides))


def _reservation_allocations(api, seal, *, current_cents_by_line=None):
    current_cents_by_line = current_cents_by_line or {}
    return tuple(
        api.ReservationLineAllocation(
            order_line_id=item.order_line_id,
            reservation_allocation_id=item.reservation_allocation_id,
            reserved_cash_cents=current_cents_by_line.get(
                item.order_line_id, item.reserved_cash_cents
            ),
        )
        for item in seal.line_reserve_bindings
    )


def _authorization_revalidation(
    api,
    seal,
    *,
    current_registry_epoch=None,
    current_trust_bundle_hash=None,
    **overrides,
):
    issuance = seal.authorization_issuance_binding
    values = {
        "revalidation_id": "authorization-revalidation-1",
        "authorization_envelope_hash": seal.authorization_envelope_hash,
        "authorization_issuance_binding_artifact_hash": (
            seal.authorization_issuance_binding_artifact_hash
        ),
        "authorization_issuer_id": issuance.authorization_issuer_id,
        "authorization_issuer_key_id": issuance.authorization_issuer_key_id,
        "authorization_issuer_capability": issuance.authorization_issuer_capability,
        "authorization_issuer_capability_version": (
            issuance.authorization_issuer_capability_version
        ),
        "authorization_issuer_identity_fingerprint": (
            issuance.authorization_issuer_identity_fingerprint
        ),
        "issuance_registry_epoch": issuance.registry_epoch,
        "issuance_trust_bundle_hash": issuance.trust_bundle_hash,
        "current_registry_epoch": (
            seal.registry_epoch
            if current_registry_epoch is None
            else current_registry_epoch
        ),
        "current_trust_bundle_hash": (
            seal.trust_bundle_hash
            if current_trust_bundle_hash is None
            else current_trust_bundle_hash
        ),
        "verification_result": api.AuthorizationIssuerVerificationResult.VALID,
        "verified_at": PERMIT_DEADLINE,
        "valid_until": PERMIT_EXPIRES,
    }
    values.update(overrides)
    return api.AuthorizationIssuerRevalidation.model_validate(values)


def _capital_risk_snapshot(
    api,
    seal,
    allocations,
    *,
    snapshot_id="risk-snapshot-preopen-1",
    as_of=PERMIT_DEADLINE,
    valid_until=PERMIT_EXPIRES,
    capital_version=None,
    stage_loss_bindings=None,
    policy_activation_hash=None,
    policy_epoch=None,
    authority_epoch=None,
    risk_epoch=None,
    registry_epoch=None,
    authorization_id=None,
    authorization_version=None,
    writer_fencing_epoch=None,
    extra_entry_reserves=(),
    extra_stage_latches=(),
):
    if capital_version is None:
        capital_version = seal.post_admission_capital_version
    if stage_loss_bindings is None:
        stage_loss_bindings = tuple(
            api.StageLossExpectedVersion(
                research_program_id=item.research_program_id,
                economic_lineage_id=item.economic_lineage_id,
                stage_id=item.stage_id,
                stage_loss_budget_id=item.stage_loss_budget_id,
                stage_loss_version=item.post_stage_loss_version,
                stage_loss_latch=item.stage_loss_latch,
            )
            for item in seal.stage_admission_bindings
        )
    line_by_id = {line.order_line_id: line for line in seal.proposal.order_lines}
    entry_reserves = tuple(
        sorted(
            (
                *(
                    api.EntryReserveRiskComponent(
                        research_program_id=(
                            line_by_id[item.order_line_id].research_program_id
                        ),
                        economic_lineage_id=(
                            line_by_id[item.order_line_id].economic_lineage_id
                        ),
                        stage_id=line_by_id[item.order_line_id].stage_id,
                        source_id=item.reservation_allocation_id,
                        covered_live_order_id=None,
                        reserved_entry_gross_cents=item.reserved_cash_cents,
                    )
                    for item in allocations
                    if item.reserved_cash_cents > 0
                ),
                *extra_entry_reserves,
            ),
            key=lambda item: item.identity(),
        )
    )
    total_reserved = sum(item.reserved_entry_gross_cents for item in entry_reserves)

    def exposure(scope, *, program=None, lineage=None, stage=None):
        if scope in {api.ExposureScope.GLOBAL, api.ExposureScope.PORTFOLIO}:
            gross = total_reserved
        else:
            gross = sum(
                item.reserved_entry_gross_cents
                for item in entry_reserves
                if item.research_program_id == program
                and (
                    scope is api.ExposureScope.RESEARCH_PROGRAM
                    or item.economic_lineage_id == lineage
                )
                and (scope is not api.ExposureScope.STAGE or item.stage_id == stage)
            )
        return api.RiskExposureBucket(
            scope=scope,
            portfolio_id=(
                None if scope is api.ExposureScope.GLOBAL else seal.portfolio_id
            ),
            research_program_id=(
                program
                if scope
                in {
                    api.ExposureScope.RESEARCH_PROGRAM,
                    api.ExposureScope.ECONOMIC_LINEAGE,
                    api.ExposureScope.STAGE,
                }
                else None
            ),
            economic_lineage_id=(
                lineage
                if scope
                in {api.ExposureScope.ECONOMIC_LINEAGE, api.ExposureScope.STAGE}
                else None
            ),
            stage_id=(stage if scope is api.ExposureScope.STAGE else None),
            position_marked_gross_cents=0,
            live_order_leaves_gross_cents=0,
            reserved_entry_gross_cents=gross,
            pending_stress_cents=0,
            corporate_action_pending_risk_cents=0,
            unattributed_risk_cents=0,
            total_gross_cents=gross,
        )

    exposures = [
        exposure(api.ExposureScope.GLOBAL),
        exposure(api.ExposureScope.PORTFOLIO),
    ]
    seen_exposure_identities = set()
    for reserve in entry_reserves:
        for scope in (
            api.ExposureScope.RESEARCH_PROGRAM,
            api.ExposureScope.ECONOMIC_LINEAGE,
            api.ExposureScope.STAGE,
        ):
            identity = (
                scope,
                reserve.research_program_id,
                reserve.economic_lineage_id
                if scope is not api.ExposureScope.RESEARCH_PROGRAM
                else None,
                reserve.stage_id if scope is api.ExposureScope.STAGE else None,
            )
            if identity in seen_exposure_identities:
                continue
            seen_exposure_identities.add(identity)
            exposures.append(
                exposure(
                    scope,
                    program=identity[1],
                    lineage=identity[2],
                    stage=identity[3],
                )
            )

    stage_latches = tuple(
        sorted(
            (
                *(
                    api.StageLossLatchSnapshot(
                        research_program_id=item.research_program_id,
                        economic_lineage_id=item.economic_lineage_id,
                        stage_id=item.stage_id,
                        stage_loss_budget_id=item.stage_loss_budget_id,
                        frozen_budget_cents=100_000,
                        consumed_cents=(
                            100_000
                            if item.stage_loss_latch
                            is api.StageLossLatchState.STAGE_LOSS_HALTED
                            else 0
                        ),
                        stage_loss_version=item.stage_loss_version,
                        state=item.stage_loss_latch,
                    )
                    for item in stage_loss_bindings
                ),
                *extra_stage_latches,
            ),
            key=lambda item: item.identity(),
        )
    )
    return api.CapitalRiskSnapshot(
        risk_snapshot_id=snapshot_id,
        portfolio_id=seal.portfolio_id,
        broker_account_id=seal.broker_account_id,
        base_currency=seal.base_currency,
        mode=seal.mode,
        as_of=as_of,
        valid_until=valid_until,
        freshness=api.RiskSnapshotFreshness.FRESH,
        completeness=api.RiskSnapshotCompleteness.COMPLETE,
        available_cash_cents=1_000_000,
        restricted_cash_cents=0,
        unsettled_cash_cents=0,
        cash_receivable_cents=0,
        cash_payable_cents=0,
        subscription_suspense_cents=0,
        redemption_suspense_cents=0,
        reserved_cash_cents=total_reserved,
        issued_unit_quanta=1_000_000,
        pending_redeemed_unit_quanta=0,
        positions=(),
        live_orders=(),
        entry_reserves=entry_reserves,
        pending_stress_components=(),
        corporate_action_risk_components=(),
        unattributed_risk_cents=0,
        exposures=tuple(exposures),
        total_gross_exposure_cents=total_reserved,
        as_observed_nav_cents=1_000_000,
        lifetime_high_water_mark_cents=1_000_000,
        active_epoch_high_water_mark_cents=1_000_000,
        lifetime_drawdown_ppm=0,
        active_epoch_drawdown_ppm=0,
        risk_latch=api.RiskLatchState.CLEAR,
        stage_loss_latches=stage_latches,
        reconciliation_latch=api.ReconciliationLatchState.CLEAR,
        policy_activation_hash=(policy_activation_hash or seal.policy_activation_hash),
        policy_epoch=policy_epoch or seal.policy_epoch,
        authority_epoch=authority_epoch or seal.authority_epoch,
        risk_epoch=risk_epoch or seal.risk_epoch,
        registry_epoch=registry_epoch or seal.registry_epoch,
        authorization_id=authorization_id or seal.authorization_id,
        authorization_version=authorization_version or seal.authorization_version,
        stage_loss_state_version=max(
            item.stage_loss_version for item in stage_loss_bindings
        ),
        writer_fencing_epoch=writer_fencing_epoch or seal.writer_fencing_epoch,
        capital_version=capital_version,
        schema_major=2,
    )


def _normalized_reserve_delta_snapshot(current, candidate):
    """Apply only the fields owned by an atomic reserve projection."""

    mutable_fields = {
        "risk_snapshot_id",
        "as_of",
        "valid_until",
        "capital_version",
        "entry_reserves",
        "reserved_cash_cents",
        "exposures",
        "total_gross_exposure_cents",
    }
    payload = current.model_dump(mode="python", round_trip=True)
    candidate_payload = candidate.model_dump(mode="python", round_trip=True)
    payload.update({name: candidate_payload[name] for name in mutable_fields})
    return type(current).model_validate(payload)


def _mechanical_binding(
    api,
    sealed_line,
    *,
    permitted_quantity=None,
    reason_code=None,
    preopen_fact_as_of=PERMIT_DEADLINE,
    **overrides,
):
    if permitted_quantity is None:
        permitted_quantity = sealed_line.sealed_quantity_units
    caps = {
        "availability_cap_units": sealed_line.sealed_quantity_units,
        "price_cap_units": sealed_line.sealed_quantity_units,
        "capacity_cap_units": sealed_line.sealed_quantity_units,
        "cash_cap_units": sealed_line.sealed_quantity_units,
        "capital_risk_cap_units": sealed_line.sealed_quantity_units,
    }
    reason_to_cap = {
        api.PermitReasonCode.AVAILABILITY_REDUCTION: "availability_cap_units",
        api.PermitReasonCode.PRICE_REDUCTION: "price_cap_units",
        api.PermitReasonCode.CAPACITY_REDUCTION: "capacity_cap_units",
        api.PermitReasonCode.CASH_REDUCTION: "cash_cap_units",
        api.PermitReasonCode.CAPITAL_RISK_REDUCTION: "capital_risk_cap_units",
    }
    if reason_code in reason_to_cap:
        caps[reason_to_cap[reason_code]] = permitted_quantity
    caps.update(overrides)
    return api.PermitLineMechanicalBinding(
        order_line_id=sealed_line.order_line_id,
        predicate_policy_version="t1-open-t10-open-slippage.v2",
        preopen_fact_snapshot_id="preopen-facts-1",
        preopen_fact_snapshot_hash=HASH_A,
        preopen_fact_as_of=preopen_fact_as_of,
        **caps,
    )


def _permit_line(
    api,
    sealed_line,
    *,
    disposition=None,
    permitted_quantity=None,
    reason_code=None,
    preopen_fact_as_of=PERMIT_DEADLINE,
    client_order_id="AUTO",
    current_reserved_cents=None,
    mechanical_binding=None,
):
    if disposition is None:
        disposition = api.PermitDisposition.ALLOW
    if permitted_quantity is None:
        permitted_quantity = sealed_line.sealed_quantity_units
    if reason_code is None:
        reason_code = (
            api.PermitReasonCode.UNCHANGED
            if permitted_quantity == sealed_line.sealed_quantity_units
            else (
                api.PermitReasonCode.CAPITAL_RISK_REDUCTION
                if disposition is api.PermitDisposition.ALLOW
                else api.PermitReasonCode.AUTHORIZATION_CANCEL
            )
        )
    remaining = sealed_line.worst_case_price_cents * permitted_quantity + (
        sealed_line.worst_case_fee_reserve_cents if permitted_quantity else 0
    )
    if current_reserved_cents is None:
        current_reserved_cents = sealed_line.worst_case_cash_reserve_cents
    released = current_reserved_cents - remaining
    sendable = disposition is api.PermitDisposition.ALLOW and permitted_quantity > 0
    if client_order_id == "AUTO":
        client_order_id = f"client-{sealed_line.order_line_id}" if sendable else None
    if mechanical_binding is None and disposition is api.PermitDisposition.ALLOW:
        mechanical_binding = _mechanical_binding(
            api,
            sealed_line,
            permitted_quantity=permitted_quantity,
            reason_code=reason_code,
            preopen_fact_as_of=preopen_fact_as_of,
        )
    return api.ExecutionPermitLine(
        order_line_id=sealed_line.order_line_id,
        security_id=sealed_line.security_id,
        sealed_quantity_units=sealed_line.sealed_quantity_units,
        permitted_quantity_units=permitted_quantity,
        reason_code=reason_code,
        mechanical_binding=mechanical_binding,
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
    overrides = dict(overrides)
    risk_snapshot_changes = {}
    for public_name, snapshot_name in (
        ("risk_snapshot_freshness", "freshness"),
        ("risk_snapshot_completeness", "completeness"),
        ("risk_latch", "risk_latch"),
        ("reconciliation_latch", "reconciliation_latch"),
    ):
        if public_name in overrides:
            risk_snapshot_changes[snapshot_name] = overrides.pop(public_name)
    sealed_allocations = _reservation_allocations(api, seal)
    reservation_allocations = overrides.get(
        "reservation_allocations", sealed_allocations
    )
    sealed_stage_loss_bindings = tuple(
        api.StageLossExpectedVersion(
            research_program_id=item.research_program_id,
            economic_lineage_id=item.economic_lineage_id,
            stage_id=item.stage_id,
            stage_loss_budget_id=item.stage_loss_budget_id,
            stage_loss_version=item.post_stage_loss_version,
            stage_loss_latch=api.StageLossLatchState.CLEAR,
        )
        for item in seal.stage_admission_bindings
    )
    stage_loss_bindings = overrides.get(
        "stage_loss_bindings", sealed_stage_loss_bindings
    )
    snapshot_context_defaults = {
        "policy_activation_hash": seal.policy_activation_hash,
        "policy_epoch": seal.policy_epoch,
        "authority_epoch": seal.authority_epoch,
        "risk_epoch": seal.risk_epoch,
        "registry_epoch": seal.registry_epoch,
        "authorization_id": seal.authorization_id,
        "authorization_version": seal.authorization_version,
        "writer_fencing_epoch": seal.writer_fencing_epoch,
    }
    snapshot_truth_changed = bool(risk_snapshot_changes) or (
        reservation_allocations != sealed_allocations
        or stage_loss_bindings != sealed_stage_loss_bindings
        or any(
            name in overrides and overrides[name] != default
            for name, default in snapshot_context_defaults.items()
        )
    )
    capital_version = overrides.get(
        "capital_version",
        seal.post_admission_capital_version + int(snapshot_truth_changed),
    )
    if "risk_snapshot" in overrides:
        risk_snapshot = overrides["risk_snapshot"]
    else:
        anchored = capital_version == seal.post_admission_capital_version
        risk_snapshot = _capital_risk_snapshot(
            api,
            seal,
            reservation_allocations,
            snapshot_id=(
                seal.post_admission_risk_snapshot_id
                if anchored
                else "risk-snapshot-preopen-1"
            ),
            as_of=seal.created_at if anchored else PERMIT_DEADLINE,
            valid_until=PERMIT_EXPIRES,
            capital_version=capital_version,
            stage_loss_bindings=stage_loss_bindings,
            policy_activation_hash=overrides.get(
                "policy_activation_hash", seal.policy_activation_hash
            ),
            policy_epoch=overrides.get("policy_epoch", seal.policy_epoch),
            authority_epoch=overrides.get("authority_epoch", seal.authority_epoch),
            risk_epoch=overrides.get("risk_epoch", seal.risk_epoch),
            registry_epoch=overrides.get("registry_epoch", seal.registry_epoch),
            authorization_id=overrides.get("authorization_id", seal.authorization_id),
            authorization_version=overrides.get(
                "authorization_version", seal.authorization_version
            ),
            writer_fencing_epoch=overrides.get(
                "writer_fencing_epoch", seal.writer_fencing_epoch
            ),
        )
    if risk_snapshot_changes:
        risk_snapshot = type(risk_snapshot).model_validate(
            risk_snapshot.model_dump(mode="python", round_trip=True)
            | risk_snapshot_changes
        )
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
        "authorization_status_version": seal.authorization_status_version,
        "authorization_status_hash": seal.authorization_status_hash,
        "authorization_revalidation": _authorization_revalidation(
            api,
            seal,
            current_registry_epoch=overrides.get("registry_epoch", seal.registry_epoch),
            current_trust_bundle_hash=overrides.get(
                "trust_bundle_hash", seal.trust_bundle_hash
            ),
        ),
        "evidence_set_merkle_root": seal.evidence_set_merkle_root,
        "entry_fence_id": seal.entry_fence_id,
        "entry_fence_hash": seal.entry_fence_hash,
        "entry_fence_version": seal.entry_fence_version,
        "capital_version": capital_version,
        "capital_stream_version": overrides.get(
            "capital_stream_version",
            seal.post_admission_capital_stream_version + int(snapshot_truth_changed),
        ),
        "risk_snapshot": risk_snapshot,
        "risk_snapshot_artifact_hash": risk_snapshot.artifact_hash(),
        "stage_loss_bindings": stage_loss_bindings,
        "reservation_id": seal.reservation_id,
        "reservation_version": seal.post_admission_reservation_version,
        "reservation_state": api.ReservationState.ACTIVE,
        "reservation_allocations": reservation_allocations,
        "remaining_reserved_cash_cents": sum(
            item.reserved_cash_cents for item in reservation_allocations
        ),
        "prior_permit_nonce_sequence": 0,
        "active_permit_id": None,
        "active_permit_artifact_hash": None,
        "active_permit_nonce": None,
        "active_permit_nonce_sequence": None,
        "active_permit_nonce_state": None,
        "active_outbox_batch_id": None,
        "active_outbox_payload_hash": None,
        "active_outbox_state": None,
        "active_send_claim_state": api.ActiveEntryClaimState.UNCLAIMED,
        "send_claim_sequence": 0,
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
    remaining = sum(
        line.remaining_reserve_cents
        for line, _ in zip(
            permit_lines, evaluation_state.reservation_allocations, strict=False
        )
    )
    post_allocations = tuple(
        api.ReservationLineAllocation(
            order_line_id=current_allocation.order_line_id,
            reservation_allocation_id=(current_allocation.reservation_allocation_id),
            reserved_cash_cents=line.remaining_reserve_cents,
        )
        for line, current_allocation in zip(
            permit_lines, evaluation_state.reservation_allocations, strict=False
        )
    )
    allocations_changed = post_allocations != evaluation_state.reservation_allocations
    version_delta = 1 if allocations_changed else 0
    owned_sources = {
        item.reservation_allocation_id
        for item in evaluation_state.reservation_allocations
    }
    required_stages = {
        (
            item.research_program_id,
            item.economic_lineage_id,
            item.stage_id,
        )
        for item in evaluation_state.stage_loss_bindings
    }
    extra_reserves = tuple(
        item
        for item in evaluation_state.risk_snapshot.entry_reserves
        if item.source_id not in owned_sources
    )
    extra_latches = tuple(
        item
        for item in evaluation_state.risk_snapshot.stage_loss_latches
        if item.identity() not in required_stages
    )
    post_snapshot = (
        _normalized_reserve_delta_snapshot(
            evaluation_state.risk_snapshot,
            _capital_risk_snapshot(
                api,
                seal,
                post_allocations,
                snapshot_id="risk-snapshot-post-permit-1",
                as_of=PERMIT_DEADLINE,
                valid_until=PERMIT_EXPIRES,
                capital_version=evaluation_state.capital_version + version_delta,
                stage_loss_bindings=evaluation_state.stage_loss_bindings,
                policy_activation_hash=evaluation_state.policy_activation_hash,
                policy_epoch=evaluation_state.policy_epoch,
                authority_epoch=evaluation_state.authority_epoch,
                risk_epoch=evaluation_state.risk_epoch,
                registry_epoch=evaluation_state.registry_epoch,
                authorization_id=evaluation_state.authorization_id,
                authorization_version=evaluation_state.authorization_version,
                writer_fencing_epoch=evaluation_state.writer_fencing_epoch,
                extra_entry_reserves=extra_reserves,
                extra_stage_latches=extra_latches,
            ),
        )
        if allocations_changed
        else evaluation_state.risk_snapshot
    )
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
        authorization_revalidation=evaluation_state.authorization_revalidation,
        evidence_set_merkle_root=evaluation_state.evidence_set_merkle_root,
        entry_fence_id=evaluation_state.entry_fence_id,
        entry_fence_hash=evaluation_state.entry_fence_hash,
        entry_fence_version=evaluation_state.entry_fence_version,
        capital_version=evaluation_state.capital_version + version_delta,
        capital_stream_version=(
            evaluation_state.capital_stream_version + version_delta
        ),
        post_risk_snapshot=post_snapshot,
        post_risk_snapshot_artifact_hash=post_snapshot.artifact_hash(),
        stage_loss_bindings=evaluation_state.stage_loss_bindings,
        reservation_id=evaluation_state.reservation_id,
        reservation_version=evaluation_state.reservation_version + version_delta,
        reservation_state=api.ReservationState.ACTIVE,
        post_reservation_allocations=post_allocations,
        remaining_reserved_cash_cents=remaining,
        outbox_batch_id="outbox-batch-1",
        outbox_payload_hash=HASH_B,
        outbox_state=api.OutboxState.DURABLE,
        outbox_permit_nonce=nonce,
        writer_fencing_epoch=evaluation_state.writer_fencing_epoch,
        effective_send_deadline=min(PERMIT_EXPIRES, SEND_DEADLINE),
    )


def _cancellation_binding(
    api,
    seal,
    *,
    evaluation_state=None,
    nonce="permit-nonce-1",
    event_at=PERMIT_DEADLINE,
):
    if evaluation_state is None:
        evaluation_state = _permit_evaluation_state(api, seal)
    has_release = evaluation_state.remaining_reserved_cash_cents > 0
    version_delta = 1 if has_release else 0
    zero_allocations = tuple(
        item.model_copy(update={"reserved_cash_cents": 0})
        for item in evaluation_state.reservation_allocations
    )
    owned_sources = {
        item.reservation_allocation_id
        for item in evaluation_state.reservation_allocations
    }
    required_stages = {
        (item.research_program_id, item.economic_lineage_id, item.stage_id)
        for item in evaluation_state.stage_loss_bindings
    }
    extra_reserves = tuple(
        item
        for item in evaluation_state.risk_snapshot.entry_reserves
        if item.source_id not in owned_sources
    )
    extra_latches = tuple(
        item
        for item in evaluation_state.risk_snapshot.stage_loss_latches
        if item.identity() not in required_stages
    )
    post_snapshot = (
        _normalized_reserve_delta_snapshot(
            evaluation_state.risk_snapshot,
            _capital_risk_snapshot(
                api,
                seal,
                zero_allocations,
                snapshot_id="risk-snapshot-post-cancel-1",
                as_of=event_at,
                valid_until=max(PERMIT_EXPIRES, event_at + timedelta(minutes=1)),
                capital_version=evaluation_state.capital_version + version_delta,
                stage_loss_bindings=evaluation_state.stage_loss_bindings,
                policy_activation_hash=evaluation_state.policy_activation_hash,
                policy_epoch=evaluation_state.policy_epoch,
                authority_epoch=evaluation_state.authority_epoch,
                risk_epoch=evaluation_state.risk_epoch,
                registry_epoch=evaluation_state.registry_epoch,
                authorization_id=evaluation_state.authorization_id,
                authorization_version=evaluation_state.authorization_version,
                writer_fencing_epoch=evaluation_state.writer_fencing_epoch,
                extra_entry_reserves=extra_reserves,
                extra_stage_latches=extra_latches,
            ),
        )
        if has_release
        else evaluation_state.risk_snapshot
    )
    return api.PermitCancellationBinding(
        permit_nonce=nonce,
        post_permit_nonce_sequence=2,
        post_permit_nonce_state=api.PermitNonceState.INVALIDATED,
        reservation_id=evaluation_state.reservation_id,
        pre_reservation_version=evaluation_state.reservation_version,
        post_reservation_version=evaluation_state.reservation_version + 1,
        post_reservation_state=api.ReservationState.RELEASED,
        released_cash_cents=evaluation_state.remaining_reserved_cash_cents,
        remaining_reserved_cash_cents=0,
        outbox_batch_id=evaluation_state.active_outbox_batch_id,
        outbox_payload_hash=evaluation_state.active_outbox_payload_hash,
        post_outbox_state=(
            api.OutboxState.TOMBSTONED
            if evaluation_state.active_outbox_batch_id is not None
            else None
        ),
        post_capital_version=evaluation_state.capital_version + version_delta,
        post_capital_stream_version=(
            evaluation_state.capital_stream_version + version_delta
        ),
        post_risk_snapshot=post_snapshot,
        post_risk_snapshot_artifact_hash=post_snapshot.artifact_hash(),
        writer_fencing_epoch=evaluation_state.writer_fencing_epoch,
    )


def _permit_payload(api, **overrides):
    seal = overrides.pop("seal", _seal(api))
    disposition = overrides.pop("disposition", api.PermitDisposition.ALLOW)
    permit_nonce = overrides.pop("permit_nonce", "permit-nonce-1")
    evaluation_state = overrides.pop(
        "evaluation_state", _permit_evaluation_state(api, seal)
    )
    current_by_line = {
        item.order_line_id: item.reserved_cash_cents
        for item in evaluation_state.reservation_allocations
    }
    if "permit_lines" in overrides:
        permit_lines = overrides.pop("permit_lines")
    else:
        permit_lines = tuple(
            _permit_line(
                api,
                line,
                disposition=disposition,
                current_reserved_cents=current_by_line[line.order_line_id],
            )
            for line in seal.proposal.order_lines
        )
    permit_clock_observation = overrides.pop(
        "permit_clock_observation", _permit_clock_observation(api)
    )
    issued_at = overrides.pop("issued_at", PERMIT_DEADLINE)
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
                api,
                seal,
                evaluation_state=evaluation_state,
                nonce=permit_nonce,
                event_at=issued_at,
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
        "permit_clock_observation": permit_clock_observation,
        "evaluation_state": evaluation_state,
        "send_claim_expected_versions": expected,
        "cancellation_binding": cancellation_binding,
        "execution_window": seal.execution_window,
        "issued_at": issued_at,
        "permit_expires_at": PERMIT_EXPIRES,
        "issuer_binding": _gateway_issuer(
            api,
            api.ArtifactKind.EXECUTION_PERMIT,
            "capital-gateway.entry-permit.v1",
            verified_at=CLOSE_FINALIZED,
            trust_bundle_hash=evaluation_state.trust_bundle_hash,
            registry_epoch=evaluation_state.registry_epoch,
        ),
    }
    values.update(overrides)
    return values


def _permit(api, **overrides):
    return api.ExecutionPermit.model_validate(_permit_payload(api, **overrides))


def _active_permit_evaluation_state(api, prior_permit=None, **overrides):
    if prior_permit is None:
        prior_permit = _permit(api)
    seal = prior_permit.seal
    expected = prior_permit.send_claim_expected_versions
    active_field_names = {
        "active_permit_id",
        "active_permit_artifact_hash",
        "active_permit_nonce",
        "active_permit_nonce_sequence",
        "active_permit_nonce_state",
        "active_outbox_batch_id",
        "active_outbox_payload_hash",
        "active_outbox_state",
        "active_send_claim_state",
        "send_claim_sequence",
    }
    active_overrides = {
        name: overrides.pop(name)
        for name in tuple(overrides)
        if name in active_field_names
    }
    overrides.setdefault("risk_snapshot", expected.post_risk_snapshot)
    overrides.setdefault(
        "risk_snapshot_artifact_hash",
        expected.post_risk_snapshot_artifact_hash,
    )
    base = _permit_evaluation_state(
        api,
        seal,
        capital_version=expected.capital_version,
        capital_stream_version=expected.capital_stream_version,
        stage_loss_bindings=expected.stage_loss_bindings,
        reservation_version=expected.reservation_version,
        reservation_allocations=expected.post_reservation_allocations,
        **overrides,
    )
    values = {
        "prior_permit_nonce_sequence": prior_permit.permit_nonce_sequence,
        "active_permit_id": prior_permit.permit_id,
        "active_permit_artifact_hash": prior_permit.artifact_hash(),
        "active_permit_nonce": prior_permit.permit_nonce,
        "active_permit_nonce_sequence": prior_permit.permit_nonce_sequence,
        "active_permit_nonce_state": api.PermitNonceState.ACTIVE,
        "active_outbox_batch_id": expected.outbox_batch_id,
        "active_outbox_payload_hash": expected.outbox_payload_hash,
        "active_outbox_state": api.OutboxState.DURABLE,
        "active_send_claim_state": api.ActiveEntryClaimState.UNCLAIMED,
        "send_claim_sequence": 0,
    }
    values.update(active_overrides)
    if (
        values["active_send_claim_state"] is api.ActiveEntryClaimState.SEND_CLAIMED
        and "active_permit_nonce_state" not in active_overrides
    ):
        values["active_permit_nonce_state"] = api.PermitNonceState.CONSUMED
    return type(base).model_validate(
        base.model_dump(mode="python", round_trip=True) | values
    )


def _receipt_clock_observation(api, **overrides):
    values = {
        "observation_id": "clock-observation-cancellation-1",
        "raw_payload_hash": HASH_E,
        "wall_clock_utc": PERMIT_EXPIRES + timedelta(seconds=1),
        "monotonic_observation_ns": 3_000_000,
        "monotonic_sequence": 10,
        "clock_health": api.ClockHealth.HEALTHY,
    }
    values.update(overrides)
    return _clock_observation(api, **values)


def _receipt_payload(api, **overrides):
    prior_permit = overrides.pop("prior_permit", None)
    if prior_permit is None:
        prior_permit = _permit(api)
    observation = overrides.pop("cancellation_clock_observation", None)
    if observation is None:
        observation = _receipt_clock_observation(api)
    current = overrides.pop("evaluation_state", None)
    if current is None:
        if prior_permit.send_claim_expected_versions is None:
            current = _permit_evaluation_state(api, prior_permit.seal)
        else:
            current = _active_permit_evaluation_state(api, prior_permit)
        revalidation = current.authorization_revalidation.model_copy(
            update={
                "verified_at": observation.wall_clock_utc,
                "valid_until": observation.wall_clock_utc + timedelta(minutes=1),
            }
        )
        current = type(current).model_validate(
            current.model_dump(mode="python", round_trip=True)
            | {"authorization_revalidation": revalidation}
        )
    kind = getattr(
        api.ArtifactKind,
        "ENTRY_CANCELLATION_RECEIPT",
        api.ArtifactKind.EXECUTION_PERMIT,
    )
    values = {
        "artifact_kind": kind,
        "artifact_namespace": "capital-gateway.entry-cancellation.v1",
        "schema_major": 2,
        "cancellation_receipt_id": "entry-cancellation-receipt-1",
        "reason_code": api.PermitReasonCode.DEADLINE_CANCEL,
        "prior_permit": prior_permit,
        "prior_permit_artifact_hash": prior_permit.artifact_hash(),
        "permit_id": prior_permit.permit_id,
        "permit_nonce": prior_permit.permit_nonce,
        "permit_nonce_sequence": prior_permit.permit_nonce_sequence,
        "logical_key": prior_permit.logical_key,
        "evaluation_state": current,
        "cancellation_binding": _cancellation_binding(
            api,
            prior_permit.seal,
            evaluation_state=current,
            nonce=prior_permit.permit_nonce,
            event_at=observation.wall_clock_utc,
        ),
        "cancellation_clock_observation": observation,
        "cancelled_at": observation.wall_clock_utc,
        "issuer_binding": _gateway_issuer(
            api,
            kind,
            "capital-gateway.entry-cancellation.v1",
            verified_at=CLOSE_FINALIZED,
            trust_bundle_hash=current.trust_bundle_hash,
            registry_epoch=current.registry_epoch,
        ),
    }
    values.update(overrides)
    return values


def _receipt(api, **overrides):
    return api.EntryCancellationReceipt.model_validate(
        _receipt_payload(api, **overrides)
    )
