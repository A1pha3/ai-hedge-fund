"""Checkpoint 2 RED contracts for seal, shadow, permit, and trusted time."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
from types import SimpleNamespace

import pytest
from pydantic import ValidationError


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
        "d8e1782149a2bc11172c4ba396d7eb066f7e957986b4c62bfdb16f7ac46b7939",
        "f24235e42f77b56ebd37830298557eedc1e8cc696b1f70b0a11b8bb445f8d7a1",
    ),
    "shadow": (
        "3b26055f7bd6cf8827c90f36ad6c419278b16021a1c15b183bf8cf1ce42d293e",
        "96ead2ca6154758257c07ea90e64ee281295c7e0a986e47dcca4a0bba139e6f9",
    ),
    "permit": (
        "02afcfd9961682360788c997d04ef79d6e3769d509e32910a519526e966696a0",
        "81fa38b10dd4708cb535a279c8544adb2958f18252c033f1f1a933f33ed17e99",
    ),
}


CHECKPOINT2_NAMES = (
    "ClockHealth",
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
    "ExecutionPermitLine",
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
        "clock_observation_id": "clock-observation-1",
        "clock_observation_hash": HASH_C,
        "wall_clock_observed_at": SEAL_CREATED,
        "monotonic_observation_ns": 1_000_000,
        "monotonic_sequence": 8,
        "clock_health": api.ClockHealth.HEALTHY,
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
    expected = overrides.pop(
        "consumed_gateway_expected_versions",
        _gateway_expected_versions(api, proposal),
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
        "stage_bindings": (_shadow_stage_binding(api),),
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
        predicate_policy_version="preopen-mechanical.v1",
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


def _send_claim_versions(api, seal, permit_lines, *, nonce="permit-nonce-1"):
    remaining = sum(line.remaining_reserve_cents for line in permit_lines)
    return api.SendClaimExpectedVersions(
        active_seal_id=seal.seal_id,
        active_seal_revision=seal.seal_revision,
        active_seal_artifact_hash=seal.artifact_hash(),
        active_permit_id="permit-1",
        active_permit_nonce=nonce,
        permit_nonce_sequence=1,
        permit_nonce_state="ACTIVE",
        policy_activation_hash=seal.policy_activation_hash,
        trust_bundle_hash=seal.trust_bundle_hash,
        registry_epoch=seal.registry_epoch,
        policy_epoch=seal.policy_epoch,
        authority_epoch=seal.authority_epoch,
        risk_epoch=seal.risk_epoch,
        authorization_id=seal.authorization_id,
        authorization_version=seal.authorization_version,
        authorization_envelope_hash=seal.authorization_envelope_hash,
        authorization_status="ACTIVE",
        authorization_status_version=seal.authorization_status_version,
        authorization_status_hash=seal.authorization_status_hash,
        authorization_revalidation_required=False,
        evidence_set_merkle_root=seal.evidence_set_merkle_root,
        entry_fence_id=seal.entry_fence_id,
        entry_fence_hash=seal.entry_fence_hash,
        entry_fence_version=seal.entry_fence_version,
        capital_version=seal.post_admission_capital_version,
        capital_stream_version=seal.capital_stream_version,
        risk_snapshot_id=seal.risk_snapshot_id,
        risk_snapshot_artifact_hash=seal.risk_snapshot_artifact_hash,
        risk_snapshot_version=3,
        risk_snapshot_freshness=api.RiskSnapshotFreshness.FRESH,
        risk_snapshot_completeness=api.RiskSnapshotCompleteness.COMPLETE,
        risk_latch=api.RiskLatchState.CLEAR,
        reconciliation_latch=api.ReconciliationLatchState.CLEAR,
        stage_loss_bindings=seal.stage_admission_bindings,
        reservation_id=seal.reservation_id,
        reservation_version=seal.post_admission_reservation_version,
        reservation_state="ACTIVE",
        remaining_reserved_cash_cents=remaining,
        outbox_batch_id="outbox-batch-1",
        outbox_payload_hash=HASH_B,
        outbox_state="DURABLE",
        outbox_permit_nonce=nonce,
        writer_fencing_epoch=seal.writer_fencing_epoch,
        effective_send_deadline=min(PERMIT_EXPIRES, SEND_DEADLINE),
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
    expected = overrides.pop(
        "send_claim_expected_versions",
        _send_claim_versions(api, seal, permit_lines, nonce=permit_nonce),
    )
    values = {
        "artifact_kind": api.ArtifactKind.EXECUTION_PERMIT,
        "artifact_namespace": "capital-gateway.entry-permit.v1",
        "schema_major": 2,
        "permit_id": "permit-1",
        "permit_nonce": permit_nonce,
        "permit_nonce_sequence": 1,
        "permit_nonce_state": "ACTIVE",
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
        "send_claim_expected_versions": expected,
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


@pytest.mark.parametrize("name", CHECKPOINT2_NAMES)
def test_each_checkpoint2_public_contract_is_exported_independently(name) -> None:
    from src.screening.offensive.v3 import contracts

    assert hasattr(contracts, name), f"missing independent contract export: {name}"


@pytest.mark.parametrize(
    "name",
    ("PORTFOLIO_DECISION_SEAL", "SHADOW_DECISION", "EXECUTION_PERMIT"),
)
def test_each_checkpoint2_artifact_kind_is_exported_independently(name) -> None:
    from src.screening.offensive.v3.contracts import ArtifactKind

    assert hasattr(ArtifactKind, name), f"missing independent artifact kind: {name}"


def test_checkpoint2_public_api_and_artifact_kinds_are_explicit() -> None:
    api = _api()

    assert api.ArtifactKind.PORTFOLIO_DECISION_SEAL.value == ("portfolio_decision_seal")
    assert api.ArtifactKind.SHADOW_DECISION.value == "shadow_decision"
    assert api.ArtifactKind.EXECUTION_PERMIT.value == "execution_permit"
    assert {item.value for item in api.ClockHealth} == {
        "HEALTHY",
        "UNKNOWN",
        "EXCESSIVE_SKEW",
        "ROLLBACK_DETECTED",
    }
    assert {item.value for item in api.PermitDisposition} == {"ALLOW", "CANCEL"}


def test_seal_shadow_and_permit_use_distinct_type_namespace_and_hash_domain() -> None:
    api = _api()

    seal = _seal(api)
    shadow = _shadow(api)
    permit = _permit(api)
    assert (
        seal.artifact_kind,
        seal.artifact_namespace,
        seal.HASH_DOMAIN,
    ) == (
        api.ArtifactKind.PORTFOLIO_DECISION_SEAL,
        "capital-gateway.entry-seal.v1",
        "ai-hedge-fund.v3.decision.portfolio-seal.v1",
    )
    assert (
        shadow.artifact_kind,
        shadow.artifact_namespace,
        shadow.HASH_DOMAIN,
    ) == (
        api.ArtifactKind.SHADOW_DECISION,
        "growth-kernel.shadow.v1",
        "ai-hedge-fund.v3.decision.shadow-decision.v1",
    )
    assert (
        permit.artifact_kind,
        permit.artifact_namespace,
        permit.HASH_DOMAIN,
    ) == (
        api.ArtifactKind.EXECUTION_PERMIT,
        "capital-gateway.entry-permit.v1",
        "ai-hedge-fund.v3.decision.execution-permit.v1",
    )
    assert (
        len({seal.artifact_hash(), shadow.artifact_hash(), permit.artifact_hash()}) == 3
    )


@pytest.mark.parametrize(
    ("source_builder", "target_name"),
    [
        (_seal, "ExecutionPermit"),
        (_seal, "ShadowDecision"),
        (_shadow, "PortfolioDecisionSeal"),
        (_shadow, "ExecutionPermit"),
        (_shadow, "PortfolioDecision"),
        (_permit, "PortfolioDecisionSeal"),
        (_permit, "ShadowDecision"),
    ],
)
def test_checkpoint2_artifacts_cannot_cross_parse(source_builder, target_name) -> None:
    api = _api()
    source = source_builder(api)

    with pytest.raises(ValidationError):
        getattr(api, target_name).model_validate(
            source.model_dump(mode="python", round_trip=True)
        )


def test_changing_shadow_discriminator_still_cannot_create_seal() -> None:
    api = _api()
    shadow_payload = _shadow(api).model_dump(mode="python", round_trip=True)
    shadow_payload.update(
        artifact_kind=api.ArtifactKind.PORTFOLIO_DECISION_SEAL,
        artifact_namespace="capital-gateway.entry-seal.v1",
    )

    with pytest.raises(ValidationError):
        api.PortfolioDecisionSeal.model_validate(shadow_payload)


def test_all_three_artifacts_forbid_unknown_and_cross_type_fields() -> None:
    api = _api()
    cases = (
        (api.PortfolioDecisionSeal, _seal_payload(api), "permit_nonce"),
        (api.ShadowDecision, _shadow_payload(api), "reservation_id"),
        (api.ExecutionPermit, _permit_payload(api), "shadow_decision_id"),
    )
    for model, payload, foreign_field in cases:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            model.model_validate(payload | {foreign_field: "forbidden"})


def test_issuer_bindings_have_exact_verified_capability_and_registry_fields() -> None:
    api = _api()
    expected = {
        "issuer_id",
        "key_id",
        "capability_artifact_kind",
        "capability_namespace",
        "capability_mode",
        "capability_schema_major",
        "capability_version",
        "capability_scope",
        "verified_at",
        "trust_bundle_hash",
        "registry_epoch",
    }
    assert set(api.GatewayIssuerBinding.model_fields) == expected
    assert set(api.ShadowIssuerBinding.model_fields) == expected


def test_artifact_issuer_capability_must_match_type_namespace_mode_and_registry() -> (
    None
):
    api = _api()
    seal = _seal(api)
    shadow = _shadow(api)
    permit = _permit(api)
    assert CLOSE_FINALIZED <= seal.issuer_binding.verified_at <= seal.created_at
    assert CLOSE_FINALIZED <= shadow.issuer_binding.verified_at <= shadow.created_at
    assert CLOSE_FINALIZED <= permit.issuer_binding.verified_at <= permit.issued_at
    cases = (
        (
            api.PortfolioDecisionSeal,
            seal,
            seal.issuer_binding.model_copy(
                update={"capability_artifact_kind": api.ArtifactKind.EXECUTION_PERMIT}
            ),
        ),
        (
            api.ShadowDecision,
            shadow,
            shadow.issuer_binding.model_copy(
                update={"capability_namespace": "capital-gateway.entry-seal.v1"}
            ),
        ),
        (
            api.ExecutionPermit,
            permit,
            permit.issuer_binding.model_copy(update={"registry_epoch": 999}),
        ),
        (
            api.PortfolioDecisionSeal,
            seal,
            seal.issuer_binding.model_copy(
                update={"verified_at": seal.created_at + timedelta(microseconds=1)}
            ),
        ),
        (
            api.PortfolioDecisionSeal,
            seal,
            seal.issuer_binding.model_copy(
                update={"verified_at": CLOSE_FINALIZED - timedelta(microseconds=1)}
            ),
        ),
        (
            api.ExecutionPermit,
            permit,
            permit.issuer_binding.model_copy(update={"trust_bundle_hash": HASH_F}),
        ),
    )
    for model, artifact, issuer in cases:
        with pytest.raises(
            ValidationError, match="issuer|capability|namespace|registry"
        ):
            model.model_validate(
                artifact.model_dump(
                    mode="python", round_trip=True, exclude={"issuer_binding"}
                )
                | {"issuer_binding": issuer}
            )


def test_portfolio_decision_seal_has_exact_gateway_receipt_fields() -> None:
    api = _api()

    assert set(api.PortfolioDecisionSeal.model_fields) == {
        "artifact_kind",
        "artifact_namespace",
        "schema_major",
        "seal_id",
        "seal_revision",
        "logical_key",
        "supersedes_seal_id",
        "supersedes_seal_revision",
        "prior_seal_eligibility",
        "proposal",
        "proposal_artifact_hash",
        "portfolio_id",
        "broker_account_id",
        "broker_account_fingerprint",
        "base_currency",
        "mode",
        "target_entry_session",
        "target_portfolio_policy_fingerprint",
        "policy_activation_hash",
        "trust_bundle_hash",
        "registry_epoch",
        "policy_epoch",
        "authority_epoch",
        "risk_epoch",
        "authorization_id",
        "authorization_version",
        "authorization_envelope_hash",
        "authorization_status_version",
        "authorization_status_hash",
        "evidence_set_merkle_root",
        "entry_fence_id",
        "entry_fence_hash",
        "entry_fence_version",
        "risk_snapshot_id",
        "risk_snapshot_artifact_hash",
        "capital_version",
        "capital_stream_version",
        "stage_admission_bindings",
        "writer_fencing_epoch",
        "consumed_gateway_expected_versions",
        "consumed_gateway_expected_versions_artifact_hash",
        "reservation_id",
        "reservation_version",
        "line_reserve_bindings",
        "total_reserved_cash_cents",
        "post_admission_capital_version",
        "post_admission_reservation_version",
        "execution_window",
        "created_at",
        "issuer_binding",
    }


def test_stage_and_reserve_bindings_have_exact_composite_fields() -> None:
    api = _api()

    assert set(api.StageAdmissionBinding.model_fields) == {
        "research_program_id",
        "economic_lineage_id",
        "stage_id",
        "stage_loss_budget_id",
        "expected_stage_loss_version",
        "post_stage_loss_version",
        "stage_loss_latch",
    }
    assert set(api.SealReserveLineBinding.model_fields) == {
        "order_line_id",
        "reservation_allocation_id",
        "reserved_cash_cents",
    }
    assert set(api.PriorSealEligibilityBinding.model_fields) == {
        "prior_seal_id",
        "prior_seal_revision",
        "prior_seal_artifact_hash",
        "logical_key",
        "permit_issuance_sequence",
        "fencing_token_issuance_sequence",
        "live_order_count",
    }
    with pytest.raises(ValidationError, match="post|version|monotonic"):
        api.StageAdmissionBinding.model_validate(
            _stage_binding(api).model_dump(mode="python", round_trip=True)
            | {"post_stage_loss_version": 2}
        )


def test_stage_coverage_is_exactly_the_composite_identities_in_proposal_lines() -> None:
    api = _api()
    seal = _seal(api)
    proposal_identities = {
        (line.research_program_id, line.economic_lineage_id, line.stage_id)
        for line in seal.proposal.order_lines
    }
    admission_identities = {
        (item.research_program_id, item.economic_lineage_id, item.stage_id)
        for item in seal.stage_admission_bindings
    }
    consumed_identities = {
        (item.research_program_id, item.economic_lineage_id, item.stage_id)
        for item in (
            seal.consumed_gateway_expected_versions.stage_loss_expected_versions
        )
    }
    assert admission_identities == consumed_identities == proposal_identities

    for changed in (
        seal.stage_admission_bindings[:1],
        seal.stage_admission_bindings
        + (
            seal.stage_admission_bindings[0].model_copy(
                update={"economic_lineage_id": "unrelated-lineage"}
            ),
        ),
    ):
        with pytest.raises(ValidationError, match="stage|lineage|coverage|proposal"):
            api.PortfolioDecisionSeal.model_validate(
                _seal_payload(api, stage_admission_bindings=changed)
            )


def test_gateway_expected_versions_is_a_hashable_consumed_cas_artifact() -> None:
    api = _api()
    expected = _gateway_expected_versions(api)

    assert type(expected).HASH_DOMAIN == (
        "ai-hedge-fund.v3.decision.gateway-expected-versions.v1"
    )
    assert expected.artifact_hash() == api.domain_hash(
        type(expected).HASH_DOMAIN,
        expected.schema_major,
        expected,
    )


def test_seal_embeds_the_exact_consumed_gateway_expected_versions_artifact() -> None:
    api = _api()
    seal = _seal(api)
    consumed = seal.consumed_gateway_expected_versions

    assert seal.consumed_gateway_expected_versions_artifact_hash == (
        consumed.artifact_hash()
    )
    assert consumed.policy_activation_hash == seal.policy_activation_hash
    assert consumed.trust_bundle_hash == seal.trust_bundle_hash
    assert consumed.authorization_envelope_hash == seal.authorization_envelope_hash
    assert consumed.authorization_status_hash == seal.authorization_status_hash
    assert consumed.entry_fence_hash == seal.entry_fence_hash
    assert consumed.risk_snapshot_artifact_hash == seal.risk_snapshot_artifact_hash


def test_seal_logical_key_proposal_hash_and_identity_exactly_match_proposal() -> None:
    api = _api()
    proposal = _proposal(api)
    base = _seal_payload(api)
    drift_cases = (
        {"logical_key": proposal.logical_key.model_copy(update={"portfolio_id": "x"})},
        {"proposal_artifact_hash": HASH_F},
        {"portfolio_id": "other-portfolio"},
        {"broker_account_id": "other-account"},
        {"broker_account_fingerprint": HASH_F},
        {"mode": api.ExecutionMode.MANUAL_CONFIRMED},
        {"target_entry_session": TARGET_SESSION + timedelta(days=1)},
        {"target_portfolio_policy_fingerprint": HASH_F},
        {"policy_activation_hash": HASH_F},
        {"trust_bundle_hash": HASH_F},
        {"registry_epoch": proposal.registry_epoch + 1},
        {"policy_epoch": proposal.policy_epoch + 1},
        {"authority_epoch": proposal.authority_epoch + 1},
        {"risk_epoch": proposal.risk_epoch + 1},
        {"authorization_id": "other-authorization"},
        {"authorization_version": 99},
        {"evidence_set_merkle_root": HASH_F},
        {"risk_snapshot_id": "other-risk-snapshot"},
        {"risk_snapshot_artifact_hash": HASH_F},
        {"capital_version": proposal.capital_version + 1},
        {"capital_stream_version": proposal.capital_stream_version + 1},
        {"writer_fencing_epoch": proposal.writer_fencing_epoch + 1},
    )
    for drift in drift_cases:
        with pytest.raises(
            ValidationError,
            match="proposal|logical|portfolio|account|mode|policy|authorization|evidence",
        ):
            api.PortfolioDecisionSeal.model_validate(base | drift)


def test_seal_rejects_each_consumed_cas_binding_drift_even_with_fresh_hash() -> None:
    api = _api()
    seal = _seal(api)
    expected = seal.consumed_gateway_expected_versions
    scalar_drifts = {
        "policy_activation_hash": HASH_F,
        "trust_bundle_hash": HASH_F,
        "registry_epoch": expected.registry_epoch + 1,
        "policy_epoch": expected.policy_epoch + 1,
        "authority_epoch": expected.authority_epoch + 1,
        "risk_epoch": expected.risk_epoch + 1,
        "authorization_id": "other-authorization",
        "authorization_version": expected.authorization_version + 1,
        "authorization_envelope_hash": HASH_F,
        "authorization_status_version": expected.authorization_status_version + 1,
        "authorization_status_hash": HASH_F,
        "evidence_set_merkle_root": HASH_F,
        "entry_fence_hash": HASH_A,
        "entry_fence_version": expected.entry_fence_version + 1,
        "risk_snapshot_id": "other-risk-snapshot",
        "risk_snapshot_artifact_hash": HASH_F,
        "capital_version": expected.capital_version + 1,
        "capital_stream_version": expected.capital_stream_version + 1,
        "writer_fencing_epoch": expected.writer_fencing_epoch + 1,
    }
    changed_stage = expected.stage_loss_expected_versions[0].model_copy(
        update={
            "stage_loss_version": (
                expected.stage_loss_expected_versions[0].stage_loss_version + 1
            )
        }
    )
    structured_drifts = {
        "stage_loss_expected_versions": (
            changed_stage,
            *expected.stage_loss_expected_versions[1:],
        ),
        "expected_active_seal_id": "seal-0",
    }
    for field, value in scalar_drifts.items():
        changed = type(expected).model_validate(
            expected.model_dump(mode="python", round_trip=True) | {field: value}
        )
        with pytest.raises(ValidationError, match="expected|proposal|seal|CAS|binding"):
            api.PortfolioDecisionSeal.model_validate(
                _seal_payload(
                    api,
                    consumed_gateway_expected_versions=changed,
                    consumed_gateway_expected_versions_artifact_hash=(
                        changed.artifact_hash()
                    ),
                )
            )
    changed = type(expected).model_validate(
        expected.model_dump(mode="python", round_trip=True)
        | {
            "stage_loss_expected_versions": structured_drifts[
                "stage_loss_expected_versions"
            ]
        }
    )
    with pytest.raises(ValidationError, match="stage|expected|proposal|coverage"):
        api.PortfolioDecisionSeal.model_validate(
            _seal_payload(
                api,
                consumed_gateway_expected_versions=changed,
                consumed_gateway_expected_versions_artifact_hash=changed.artifact_hash(),
            )
        )

    with pytest.raises(ValidationError, match="expected|active seal|supersede"):
        type(expected).model_validate(
            expected.model_dump(mode="python", round_trip=True)
            | {"expected_active_seal_id": "seal-0"}
        )


def test_proposal_cannot_supply_gateway_owned_seal_or_reservation_identity() -> None:
    api = _api()
    proposal = _proposal(api)

    for field in (
        "seal_id",
        "seal_revision",
        "reservation_id",
        "reservation_version",
        "gateway_created_at",
        "created_at",
    ):
        with pytest.raises(ValidationError, match="extra_forbidden"):
            api.PortfolioDecision.model_validate(
                proposal.model_dump(mode="python", round_trip=True) | {field: "owned"}
            )


def test_seal_has_one_strictly_revalidated_proposal_economics_representation() -> None:
    api = _api()
    seal = _seal(api)
    assert "order_lines" not in api.PortfolioDecisionSeal.model_fields
    assert seal.proposal.order_lines == _proposal(api).order_lines

    poisoned = seal.proposal.model_copy(
        update={"total_worst_case_cash_reserve_cents": 1}
    )
    with pytest.raises(ValidationError, match="reserve"):
        api.PortfolioDecisionSeal.model_validate(_seal_payload(api, proposal=poisoned))


def test_seal_cannot_change_any_bound_proposal_order_line() -> None:
    api = _api()
    proposal = _proposal(api)
    changed_line = proposal.order_lines[0].model_copy(
        update={"security_id": "000001.SZ"}
    )
    changed_proposal = proposal.model_copy(
        update={"order_lines": (changed_line, *proposal.order_lines[1:])}
    )
    with pytest.raises(ValidationError, match="proposal|artifact hash"):
        api.PortfolioDecisionSeal.model_validate(
            _seal_payload(api, proposal=changed_proposal)
        )


def test_seal_reserve_is_exact_per_line_and_in_aggregate() -> None:
    api = _api()
    seal = _seal(api)
    assert tuple(item.order_line_id for item in seal.line_reserve_bindings) == tuple(
        line.order_line_id for line in seal.proposal.order_lines
    )
    assert seal.total_reserved_cash_cents == sum(
        line.worst_case_cash_reserve_cents for line in seal.proposal.order_lines
    )

    reserve_lines = list(seal.line_reserve_bindings)
    reserve_lines[0] = reserve_lines[0].model_copy(
        update={"reserved_cash_cents": reserve_lines[0].reserved_cash_cents - 1}
    )
    for drift in (
        {"line_reserve_bindings": tuple(reserve_lines)},
        {"total_reserved_cash_cents": seal.total_reserved_cash_cents - 1},
    ):
        with pytest.raises(ValidationError, match="reserve"):
            api.PortfolioDecisionSeal.model_validate(_seal_payload(api, **drift))


def test_seal_supersedes_identity_is_typed_all_or_none_and_has_no_self_claim() -> None:
    api = _api()
    assert "active_seal_id" not in api.PortfolioDecisionSeal.model_fields
    for drift in (
        {"supersedes_seal_id": "seal-0"},
        {"supersedes_seal_revision": 1},
    ):
        with pytest.raises(ValidationError, match="supersedes|all-or-none|pair"):
            api.PortfolioDecisionSeal.model_validate(_seal_payload(api, **drift))

    eligible = _prior_seal_eligibility(api)
    superseding = _seal(
        api,
        seal_revision=2,
        supersedes_seal_id=eligible.prior_seal_id,
        supersedes_seal_revision=eligible.prior_seal_revision,
        prior_seal_eligibility=eligible,
    )
    assert superseding.seal_revision > eligible.prior_seal_revision


@pytest.mark.parametrize(
    "drift",
    [
        {"logical_key": DIFFERENT_LOGICAL_KEY},
        {"permit_issuance_sequence": 1},
        {"fencing_token_issuance_sequence": 1},
        {"live_order_count": 1},
    ],
)
def test_supersede_requires_same_key_no_prior_permit_fence_or_live_order(drift) -> None:
    api = _api()
    if drift.get("logical_key") is DIFFERENT_LOGICAL_KEY:
        drift = {
            "logical_key": _proposal(api).logical_key.model_copy(
                update={"decision_cycle_id": "other-cycle"}
            )
        }
    eligibility = _prior_seal_eligibility(api, **drift)
    with pytest.raises(
        ValidationError, match="supersede|logical|permit|fenc|live order|eligib"
    ):
        api.PortfolioDecisionSeal.model_validate(
            _seal_payload(
                api,
                seal_revision=2,
                supersedes_seal_id=eligibility.prior_seal_id,
                supersedes_seal_revision=eligibility.prior_seal_revision,
                prior_seal_eligibility=eligibility,
            )
        )


def test_supersede_revision_must_be_strictly_higher_than_prior_revision() -> None:
    api = _api()
    eligibility = _prior_seal_eligibility(api)
    with pytest.raises(ValidationError, match="revision|higher|supersede"):
        api.PortfolioDecisionSeal.model_validate(
            _seal_payload(
                api,
                seal_revision=eligibility.prior_seal_revision,
                supersedes_seal_id=eligibility.prior_seal_id,
                supersedes_seal_revision=eligibility.prior_seal_revision,
                prior_seal_eligibility=eligibility,
            )
        )


def test_seal_hash_covers_proposal_and_every_gateway_binding() -> None:
    api = _api()
    seal = _seal(api)
    proposal = _proposal(api)
    proposal_variant = api.PortfolioDecision.model_validate(
        proposal.model_dump(mode="python", round_trip=True)
        | {
            "logical_key": proposal.logical_key.model_copy(
                update={"decision_cycle_id": "daily-t1-open-v2"}
            )
        }
    )
    expected_variant = _gateway_expected_versions(
        api,
        proposal,
        authorization_status_version=6,
        authorization_status_hash=HASH_F,
    )
    reserve_variant = tuple(
        item.model_copy(
            update={
                "reservation_allocation_id": (
                    f"replacement-{item.reservation_allocation_id}"
                )
            }
        )
        for item in seal.line_reserve_bindings
    )
    issuer_variant = seal.issuer_binding.model_copy(
        update={"key_id": "capital-gateway-key-2"}
    )
    window_variant = _window(
        api,
        broker_auction_submission_cutoff=BROKER_CUTOFF + timedelta(microseconds=1),
    )
    eligibility = _prior_seal_eligibility(api)
    valid_variants = {
        "proposal": _seal(api, proposal=proposal_variant),
        "consumed_expected": _seal(
            api, consumed_gateway_expected_versions=expected_variant
        ),
        "reserve": _seal(api, line_reserve_bindings=reserve_variant),
        "issuer": _seal(api, issuer_binding=issuer_variant),
        "deadline": _seal(api, execution_window=window_variant),
        "supersede": _seal(
            api,
            seal_revision=2,
            supersedes_seal_id=eligibility.prior_seal_id,
            supersedes_seal_revision=eligibility.prior_seal_revision,
            prior_seal_eligibility=eligibility,
        ),
    }
    for label, valid_variant in valid_variants.items():
        assert valid_variant.artifact_hash() != seal.artifact_hash(), label


def test_trusted_execution_window_has_exact_semantic_fields() -> None:
    api = _api()

    assert set(api.TrustedExecutionWindow.model_fields) == {
        "signal_session",
        "target_entry_session",
        "exchange_id",
        "calendar_snapshot_id",
        "calendar_snapshot_hash",
        "calendar_snapshot_version",
        "cutoff_snapshot_id",
        "cutoff_snapshot_hash",
        "cutoff_snapshot_version",
        "cutoff_snapshot_session",
        "cutoff_snapshot_exchange_id",
        "execution_policy_version",
        "cutoff_policy_version",
        "clock_observation_id",
        "clock_observation_hash",
        "wall_clock_observed_at",
        "monotonic_observation_ns",
        "monotonic_sequence",
        "clock_health",
        "t0_close_finalized_at",
        "seal_creation_deadline",
        "permit_issue_deadline",
        "gateway_send_deadline",
        "broker_auction_submission_cutoff",
    }
    assert set(api.ClockHealth) == {
        api.ClockHealth.HEALTHY,
        api.ClockHealth.UNKNOWN,
        api.ClockHealth.EXCESSIVE_SKEW,
        api.ClockHealth.ROLLBACK_DETECTED,
    }
    assert "deadline" not in api.PortfolioDecisionSeal.model_fields
    assert "deadline" not in api.ExecutionPermit.model_fields


@pytest.mark.parametrize(
    "drift",
    [
        {"t0_close_finalized_at": SEAL_DEADLINE},
        {"seal_creation_deadline": PERMIT_DEADLINE},
        {"permit_issue_deadline": SEND_DEADLINE},
        {"gateway_send_deadline": BROKER_CUTOFF},
    ],
)
def test_trusted_execution_window_rejects_every_strict_boundary_equality(
    drift,
) -> None:
    api = _api()
    with pytest.raises(ValidationError, match="close|seal|permit|send|broker|deadline"):
        api.TrustedExecutionWindow.model_validate(_window_payload(api, **drift))


def test_seal_created_at_may_equal_creation_deadline_but_must_follow_close() -> None:
    api = _api()
    seal = _seal(api, created_at=SEAL_DEADLINE)
    assert seal.created_at == seal.execution_window.seal_creation_deadline

    for created_at in (CLOSE_FINALIZED, SEAL_DEADLINE + timedelta(microseconds=1)):
        with pytest.raises(ValidationError, match="close|created|deadline"):
            api.PortfolioDecisionSeal.model_validate(
                _seal_payload(api, created_at=created_at)
            )


def test_permit_time_boundaries_are_exact() -> None:
    api = _api()
    permit = _permit(api)
    assert permit.issued_at == permit.execution_window.permit_issue_deadline
    assert permit.permit_expires_at == permit.execution_window.gateway_send_deadline

    for drift in (
        {"issued_at": SEAL_CREATED},
        {"issued_at": PERMIT_DEADLINE + timedelta(microseconds=1)},
        {"permit_expires_at": PERMIT_DEADLINE},
        {"permit_expires_at": SEND_DEADLINE + timedelta(microseconds=1)},
    ):
        with pytest.raises(ValidationError, match="issued|expires|seal|deadline"):
            api.ExecutionPermit.model_validate(_permit_payload(api, **drift))


def test_unhealthy_or_rollback_clock_blocks_seal_and_permit() -> None:
    api = _api()
    for health in (
        api.ClockHealth.UNKNOWN,
        api.ClockHealth.EXCESSIVE_SKEW,
        api.ClockHealth.ROLLBACK_DETECTED,
    ):
        unhealthy = _window(api, clock_health=health)
        with pytest.raises(ValidationError, match="clock"):
            api.PortfolioDecisionSeal.model_validate(
                _seal_payload(api, execution_window=unhealthy)
            )
        with pytest.raises(ValidationError, match="clock"):
            api.ExecutionPermit.model_validate(
                _permit_payload(api, execution_window=unhealthy)
            )


def test_cutoff_snapshot_session_exchange_and_observation_are_bounded() -> None:
    api = _api()
    for drift in (
        {"cutoff_snapshot_session": SIGNAL_SESSION},
        {"cutoff_snapshot_exchange_id": "SZSE"},
        {"wall_clock_observed_at": SEAL_DEADLINE + timedelta(microseconds=1)},
    ):
        with pytest.raises(
            ValidationError, match="cutoff|session|exchange|clock|deadline"
        ):
            api.TrustedExecutionWindow.model_validate(_window_payload(api, **drift))


def test_execution_permit_has_exact_complete_binding_fields() -> None:
    api = _api()

    assert set(api.ExecutionPermit.model_fields) == {
        "artifact_kind",
        "artifact_namespace",
        "schema_major",
        "permit_id",
        "permit_nonce",
        "permit_nonce_sequence",
        "permit_nonce_state",
        "disposition",
        "seal",
        "seal_id",
        "seal_revision",
        "seal_artifact_hash",
        "logical_key",
        "proposal_artifact_hash",
        "portfolio_id",
        "broker_account_id",
        "broker_account_fingerprint",
        "base_currency",
        "mode",
        "target_entry_session",
        "permit_lines",
        "total_remaining_reserve_cents",
        "total_released_reserve_cents",
        "send_claim_expected_versions",
        "execution_window",
        "issued_at",
        "permit_expires_at",
        "issuer_binding",
    }
    assert set(api.ExecutionPermitLine.model_fields) == {
        "order_line_id",
        "security_id",
        "sealed_quantity_units",
        "permitted_quantity_units",
        "reason_code",
        "predicate_policy_version",
        "preopen_fact_snapshot_id",
        "preopen_fact_snapshot_hash",
        "preopen_fact_as_of",
        "client_order_id",
        "order_type",
        "limit_price_cents",
        "worst_case_price_cents",
        "price_boundary_version",
        "time_in_force",
        "exit_session_ordinal",
        "sealed_reserve_cents",
        "remaining_reserve_cents",
        "released_reserve_cents",
    }


def test_send_claim_expected_versions_freezes_complete_recheck_bundle() -> None:
    api = _api()
    assert set(api.SendClaimExpectedVersions.model_fields) == {
        "active_seal_id",
        "active_seal_revision",
        "active_seal_artifact_hash",
        "active_permit_id",
        "active_permit_nonce",
        "permit_nonce_sequence",
        "permit_nonce_state",
        "policy_activation_hash",
        "trust_bundle_hash",
        "registry_epoch",
        "policy_epoch",
        "authority_epoch",
        "risk_epoch",
        "authorization_id",
        "authorization_version",
        "authorization_envelope_hash",
        "authorization_status",
        "authorization_status_version",
        "authorization_status_hash",
        "authorization_revalidation_required",
        "evidence_set_merkle_root",
        "entry_fence_id",
        "entry_fence_hash",
        "entry_fence_version",
        "capital_version",
        "capital_stream_version",
        "risk_snapshot_id",
        "risk_snapshot_artifact_hash",
        "risk_snapshot_version",
        "risk_snapshot_freshness",
        "risk_snapshot_completeness",
        "risk_latch",
        "reconciliation_latch",
        "stage_loss_bindings",
        "reservation_id",
        "reservation_version",
        "reservation_state",
        "remaining_reserved_cash_cents",
        "outbox_batch_id",
        "outbox_payload_hash",
        "outbox_state",
        "outbox_permit_nonce",
        "writer_fencing_epoch",
        "effective_send_deadline",
    }


def test_permit_identity_authority_nonce_outbox_and_deadline_match_seal() -> None:
    api = _api()
    permit = _permit(api)
    expected = permit.send_claim_expected_versions
    assert permit.seal_artifact_hash == permit.seal.artifact_hash()
    assert permit.logical_key == permit.seal.logical_key
    assert permit.proposal_artifact_hash == permit.seal.proposal_artifact_hash
    assert expected.active_permit_nonce == permit.permit_nonce
    assert expected.outbox_permit_nonce == permit.permit_nonce
    assert expected.effective_send_deadline == min(
        permit.permit_expires_at,
        permit.execution_window.gateway_send_deadline,
    )

    top_level_drifts = (
        {"seal_id": "other-seal"},
        {"seal_revision": permit.seal_revision + 1},
        {"seal_artifact_hash": HASH_F},
        {
            "logical_key": permit.logical_key.model_copy(
                update={"decision_cycle_id": "other-cycle"}
            )
        },
        {"proposal_artifact_hash": HASH_F},
        {"portfolio_id": "other-portfolio"},
        {"broker_account_id": "other-account"},
        {"broker_account_fingerprint": HASH_F},
        {"base_currency": "USD"},
        {"mode": api.ExecutionMode.MANUAL_CONFIRMED},
        {"target_entry_session": TARGET_SESSION + timedelta(days=1)},
        {"permit_nonce": "different-nonce"},
    )
    for drift in top_level_drifts:
        with pytest.raises(
            ValidationError,
            match="seal|logical|proposal|portfolio|account|currency|mode|session|nonce",
        ):
            api.ExecutionPermit.model_validate(_permit_payload(api, **drift))

    changed_stage = expected.stage_loss_bindings[0].model_copy(
        update={
            "expected_stage_loss_version": (
                expected.stage_loss_bindings[0].expected_stage_loss_version + 1
            ),
            "post_stage_loss_version": (
                expected.stage_loss_bindings[0].post_stage_loss_version + 1
            ),
        }
    )
    expected_drifts = {
        "active_seal_id": "other-seal",
        "active_seal_revision": expected.active_seal_revision + 1,
        "active_seal_artifact_hash": HASH_F,
        "active_permit_id": "other-permit",
        "active_permit_nonce": "other-nonce",
        "permit_nonce_sequence": expected.permit_nonce_sequence + 1,
        "permit_nonce_state": "CONSUMED",
        "policy_activation_hash": HASH_F,
        "trust_bundle_hash": HASH_F,
        "registry_epoch": expected.registry_epoch + 1,
        "policy_epoch": expected.policy_epoch + 1,
        "authority_epoch": expected.authority_epoch + 1,
        "risk_epoch": expected.risk_epoch + 1,
        "authorization_id": "other-authorization",
        "authorization_version": expected.authorization_version + 1,
        "authorization_envelope_hash": HASH_F,
        "authorization_status": "REVOKED",
        "authorization_status_version": expected.authorization_status_version + 1,
        "authorization_status_hash": HASH_F,
        "authorization_revalidation_required": True,
        "evidence_set_merkle_root": HASH_F,
        "entry_fence_id": "other-fence",
        "entry_fence_hash": HASH_A,
        "entry_fence_version": expected.entry_fence_version + 1,
        "capital_version": expected.capital_version + 1,
        "capital_stream_version": expected.capital_stream_version + 1,
        "risk_snapshot_id": "other-risk-snapshot",
        "risk_snapshot_artifact_hash": HASH_F,
        "risk_snapshot_freshness": api.RiskSnapshotFreshness.STALE,
        "risk_snapshot_completeness": api.RiskSnapshotCompleteness.INCOMPLETE,
        "risk_latch": api.RiskLatchState.RISK_HALTED,
        "reconciliation_latch": (api.ReconciliationLatchState.RECONCILIATION_HALT),
        "stage_loss_bindings": (
            changed_stage,
            *expected.stage_loss_bindings[1:],
        ),
        "reservation_id": "other-reservation",
        "reservation_version": expected.reservation_version + 1,
        "reservation_state": "RELEASED",
        "remaining_reserved_cash_cents": (expected.remaining_reserved_cash_cents + 1),
        "outbox_permit_nonce": "different-nonce",
        "writer_fencing_epoch": expected.writer_fencing_epoch + 1,
        "effective_send_deadline": (
            expected.effective_send_deadline + timedelta(microseconds=1)
        ),
    }
    for field, value in expected_drifts.items():
        changed = expected.model_copy(update={field: value})
        with pytest.raises(
            ValidationError,
            match="seal|permit|nonce|policy|trust|registry|authority|authorization|risk|fence|capital|stage|reservation|outbox|deadline|latch",
        ):
            api.ExecutionPermit.model_validate(
                _permit_payload(api, send_claim_expected_versions=changed)
            )


def test_permit_nonce_contract_is_single_use_shaped_and_cannot_self_claim() -> None:
    api = _api()
    permit = _permit(api)
    assert permit.permit_nonce_state == "ACTIVE"
    assert permit.send_claim_expected_versions.permit_nonce_state == "ACTIVE"
    assert "nonce_consumed_at" not in api.ExecutionPermit.model_fields
    assert "send_claimed_at" not in api.ExecutionPermit.model_fields

    for field, value in (
        ("permit_nonce_state", "CONSUMED"),
        ("permit_nonce_sequence", 0),
    ):
        with pytest.raises(ValidationError, match="nonce|greater than"):
            api.ExecutionPermit.model_validate(_permit_payload(api, **{field: value}))


def test_permit_line_set_exactly_matches_seal_and_never_grows_own_line() -> None:
    api = _api()
    permit = _permit(api)
    lines = list(permit.permit_lines)
    assert tuple(line.order_line_id for line in lines) == tuple(
        line.order_line_id for line in _seal(api).proposal.order_lines
    )

    added = lines[0].model_copy(
        update={"order_line_id": "new-line", "security_id": "000001.SZ"}
    )
    grown = lines[0].model_copy(
        update={"permitted_quantity_units": lines[0].sealed_quantity_units + 100}
    )
    for changed in ((added, *lines[1:]), (grown, *lines[1:]), tuple(lines[:1])):
        with pytest.raises(ValidationError, match="line|quantity|seal"):
            api.ExecutionPermit.model_validate(
                _permit_payload(api, permit_lines=changed)
            )


def test_permit_accepts_partial_positive_shrink_with_exact_cash_release() -> None:
    api = _api()
    seal = _seal(api)
    lines = (
        _permit_line(api, seal.proposal.order_lines[0]),
        _permit_line(
            api,
            seal.proposal.order_lines[1],
            permitted_quantity=100,
            reason_code=api.PermitReasonCode.CAPITAL_RISK_REDUCTION,
        ),
    )
    permit = _permit(api, seal=seal, permit_lines=lines)
    changed = permit.permit_lines[1]

    assert changed.permitted_quantity_units == 100
    assert changed.remaining_reserve_cents == 800 * 100 + 75
    assert changed.released_reserve_cents == 800 * 100
    assert permit.total_released_reserve_cents == 800 * 100


def test_same_total_quantity_cannot_hide_line_a_shrink_and_line_b_growth() -> None:
    api = _api()
    permit = _permit(api)
    line_b, line_a = permit.permit_lines
    changed = (
        line_b.model_copy(
            update={
                "permitted_quantity_units": line_b.permitted_quantity_units + 100,
                "remaining_reserve_cents": (
                    line_b.worst_case_price_cents
                    * (line_b.permitted_quantity_units + 100)
                    + 50
                ),
            }
        ),
        line_a.model_copy(
            update={
                "permitted_quantity_units": line_a.permitted_quantity_units - 100,
                "reason_code": api.PermitReasonCode.CAPITAL_RISK_REDUCTION,
                "remaining_reserve_cents": (
                    line_a.worst_case_price_cents
                    * (line_a.permitted_quantity_units - 100)
                    + 75
                ),
                "released_reserve_cents": (line_a.worst_case_price_cents * 100),
            }
        ),
    )
    assert sum(line.permitted_quantity_units for line in changed) == sum(
        line.sealed_quantity_units for line in permit.permit_lines
    )
    with pytest.raises(ValidationError, match="line|grow|sealed|quantity"):
        api.ExecutionPermit.model_validate(_permit_payload(api, permit_lines=changed))


def test_permit_cannot_change_line_economics_or_reallocate_released_cash() -> None:
    api = _api()
    permit = _permit(api)
    line = permit.permit_lines[0]
    drift = {
        "security_id": "000001.SZ",
        "sealed_quantity_units": line.sealed_quantity_units + 100,
        "order_type": "MARKET",
        "limit_price_cents": line.limit_price_cents + 1,
        "worst_case_price_cents": line.worst_case_price_cents + 1,
        "price_boundary_version": "other-price-boundary.v2",
        "time_in_force": "DAY",
        "exit_session_ordinal": 9,
        "sealed_reserve_cents": line.sealed_reserve_cents + 1,
        "remaining_reserve_cents": line.remaining_reserve_cents + 1,
        "released_reserve_cents": line.released_reserve_cents + 1,
    }
    for field, value in drift.items():
        changed = line.model_copy(update={field: value})
        with pytest.raises(
            ValidationError, match="line|security|price|order|time|exit|reserve"
        ):
            api.ExecutionPermit.model_validate(
                _permit_payload(
                    api,
                    permit_lines=(changed, *permit.permit_lines[1:]),
                )
            )


@pytest.mark.parametrize(
    "reason",
    ["PREOPEN_ALPHA", "NEWS", "QUOTE", "DISCRETIONARY"],
)
def test_permit_reasons_reject_alpha_news_quote_and_discretion(reason) -> None:
    api = _api()
    assert {item.value for item in api.PermitReasonCode} == {
        "UNCHANGED",
        "AVAILABILITY_REDUCTION",
        "PRICE_REDUCTION",
        "CAPACITY_REDUCTION",
        "CASH_REDUCTION",
        "CAPITAL_RISK_REDUCTION",
        "STAGE_HALT_CANCEL",
        "RECONCILIATION_CANCEL",
        "FACT_INTEGRITY_CANCEL",
        "AUTHORIZATION_CANCEL",
        "FENCE_CANCEL",
        "DEADLINE_CANCEL",
    }
    line = _permit(api).permit_lines[0]
    with pytest.raises(ValidationError, match="reason"):
        api.ExecutionPermitLine.model_validate(
            line.model_dump(mode="python", round_trip=True) | {"reason_code": reason}
        )


@pytest.mark.parametrize(
    "reason",
    [
        "AVAILABILITY_REDUCTION",
        "PRICE_REDUCTION",
        "CAPACITY_REDUCTION",
        "CASH_REDUCTION",
        "CAPITAL_RISK_REDUCTION",
        "STAGE_HALT_CANCEL",
        "RECONCILIATION_CANCEL",
        "FACT_INTEGRITY_CANCEL",
        "AUTHORIZATION_CANCEL",
        "FENCE_CANCEL",
        "DEADLINE_CANCEL",
    ],
)
def test_permit_reason_categories_are_typed_mechanical_facts(reason) -> None:
    api = _api()
    assert api.PermitReasonCode(reason).value == reason


@pytest.mark.parametrize(
    ("quantity_delta", "reason"),
    [
        (0, "CAPITAL_RISK_REDUCTION"),
        (-100, "UNCHANGED"),
        (-100, "AUTHORIZATION_CANCEL"),
    ],
)
def test_permit_reason_must_match_unchanged_shrink_or_cancel(
    quantity_delta, reason
) -> None:
    api = _api()
    seal_line = _seal(api).proposal.order_lines[1]
    quantity = seal_line.sealed_quantity_units + quantity_delta
    with pytest.raises(ValidationError, match="reason|unchanged|shrink|cancel"):
        _permit_line(
            api,
            seal_line,
            permitted_quantity=quantity,
            reason_code=api.PermitReasonCode(reason),
        )


def test_permit_rejects_future_preopen_fact_timestamp() -> None:
    api = _api()
    seal = _seal(api)
    line = _permit_line(
        api,
        seal.proposal.order_lines[0],
        preopen_fact_as_of=PERMIT_DEADLINE + timedelta(microseconds=1),
    )
    with pytest.raises(ValidationError, match="preopen|fact|issued|future"):
        api.ExecutionPermit.model_validate(
            _permit_payload(
                api,
                seal=seal,
                permit_lines=(line, _permit_line(api, seal.proposal.order_lines[1])),
            )
        )


@pytest.mark.parametrize("case", ["duplicate", "missing_positive", "present_zero"])
def test_client_order_ids_are_unique_and_exactly_match_sendable_lines(case) -> None:
    api = _api()
    seal = _seal(api)
    lines = [
        _permit_line(api, line, disposition=api.PermitDisposition.ALLOW)
        for line in seal.proposal.order_lines
    ]
    if case == "duplicate":
        lines[1] = lines[1].model_copy(
            update={"client_order_id": lines[0].client_order_id}
        )
    elif case == "missing_positive":
        lines[0] = lines[0].model_copy(update={"client_order_id": None})
    else:
        lines[0] = _permit_line(
            api,
            seal.proposal.order_lines[0],
            permitted_quantity=0,
            reason_code=api.PermitReasonCode.AUTHORIZATION_CANCEL,
            client_order_id="client-zero-line",
        )
    with pytest.raises(ValidationError, match="client|order|sendable|unique|zero"):
        api.ExecutionPermit.model_validate(
            _permit_payload(api, seal=seal, permit_lines=tuple(lines))
        )


def test_cancel_and_allow_dispositions_are_typed_and_non_interchangeable() -> None:
    api = _api()
    assert set(api.PermitDisposition) == {
        api.PermitDisposition.ALLOW,
        api.PermitDisposition.CANCEL,
    }
    allow = _permit(api)
    assert any(line.permitted_quantity_units > 0 for line in allow.permit_lines)

    seal = _seal(api)
    cancelled_lines = tuple(
        _permit_line(
            api,
            line,
            disposition=api.PermitDisposition.CANCEL,
            permitted_quantity=0,
        )
        for line in seal.proposal.order_lines
    )
    cancel_expected = _send_claim_versions(api, seal, cancelled_lines).model_copy(
        update={
            "remaining_reserved_cash_cents": 0,
            "outbox_batch_id": None,
            "outbox_payload_hash": None,
            "outbox_state": "TOMBSTONED",
            "outbox_permit_nonce": None,
        }
    )
    cancel = api.ExecutionPermit.model_validate(
        _permit_payload(
            api,
            disposition=api.PermitDisposition.CANCEL,
            permit_lines=cancelled_lines,
            total_remaining_reserve_cents=0,
            total_released_reserve_cents=sum(
                line.released_reserve_cents for line in cancelled_lines
            ),
            send_claim_expected_versions=cancel_expected,
        )
    )
    assert all(line.permitted_quantity_units == 0 for line in cancel.permit_lines)
    assert all(line.client_order_id is None for line in cancel.permit_lines)

    with pytest.raises(ValidationError, match="ALLOW|positive|sendable"):
        api.ExecutionPermit.model_validate(
            cancel.model_dump(mode="python", round_trip=True)
            | {"disposition": api.PermitDisposition.ALLOW}
        )


def test_cancel_rejects_positive_line_or_durable_sendable_outbox() -> None:
    api = _api()
    seal = _seal(api)
    positive_lines = tuple(
        _permit_line(api, line, disposition=api.PermitDisposition.ALLOW)
        for line in seal.proposal.order_lines
    )
    with pytest.raises(ValidationError, match="CANCEL|zero|positive|sendable"):
        api.ExecutionPermit.model_validate(
            _permit_payload(
                api,
                seal=seal,
                disposition=api.PermitDisposition.CANCEL,
                permit_lines=positive_lines,
            )
        )

    zero_lines = tuple(
        _permit_line(
            api,
            line,
            disposition=api.PermitDisposition.CANCEL,
            permitted_quantity=0,
        )
        for line in seal.proposal.order_lines
    )
    durable = _send_claim_versions(api, seal, zero_lines)
    with pytest.raises(ValidationError, match="CANCEL|outbox|tombstone|sendable"):
        api.ExecutionPermit.model_validate(
            _permit_payload(
                api,
                seal=seal,
                disposition=api.PermitDisposition.CANCEL,
                permit_lines=zero_lines,
                send_claim_expected_versions=durable,
            )
        )


def test_shadow_has_complete_counterfactual_provenance_and_independent_lines() -> None:
    api = _api()
    assert set(api.CounterfactualDecisionKey.model_fields) == {
        "portfolio_id",
        "signal_session",
        "counterfactual_cycle_id",
    }
    assert set(api.ShadowDecision.model_fields) == {
        "artifact_kind",
        "artifact_namespace",
        "schema_major",
        "shadow_decision_id",
        "counterfactual_key",
        "portfolio_id",
        "mode",
        "target_entry_session",
        "producer_namespace",
        "family_id",
        "research_program_id",
        "economic_lineage_id",
        "stage_id",
        "trial_id",
        "policy_activation_hash",
        "policy_epoch",
        "evidence_set_merkle_root",
        "stage_bindings",
        "counterfactual_lines",
        "cost_assumption_version",
        "execution_assumption_version",
        "created_at",
        "available_at",
        "execution_authority",
        "issuer_binding",
    }
    assert set(api.ShadowOrderLine.model_fields) == {
        "shadow_line_id",
        "security_id",
        "producer_namespace",
        "family_id",
        "economic_lineage_id",
        "research_program_id",
        "stage_id",
        "trial_id",
        "stage_manifest_hash",
        "evidence_id",
        "evidence_artifact_hash",
        "evidence_payload_hash",
        "target_quantity_units",
        "lot_size_units",
        "lot_rule_version",
        "order_type",
        "limit_price_cents",
        "worst_case_price_cents",
        "price_boundary_version",
        "time_in_force",
        "exit_session_ordinal",
        "estimated_fee_cents",
        "estimated_cash_reserve_cents",
        "cost_assumption_version",
        "execution_assumption_version",
    }
    shadow = _shadow(api)
    assert shadow.execution_authority == "NONE"
    assert len(shadow.counterfactual_lines) == 2
    assert set(api.ShadowStageBinding.model_fields) == {
        "research_program_id",
        "economic_lineage_id",
        "stage_id",
        "trial_id",
        "stage_manifest_hash",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("producer_namespace", "different-producer"),
        ("research_program_id", "different-program"),
        ("economic_lineage_id", "different-lineage"),
        ("stage_id", "different-stage"),
        ("trial_id", "different-trial"),
        ("cost_assumption_version", "different-cost"),
        ("execution_assumption_version", "different-execution"),
    ],
)
def test_shadow_lines_must_match_header_provenance_and_assumptions(
    field, value
) -> None:
    api = _api()
    shadow = _shadow(api)
    changed = shadow.counterfactual_lines[0].model_copy(update={field: value})
    with pytest.raises(
        ValidationError,
        match="producer|program|lineage|stage|trial|cost|execution|header",
    ):
        api.ShadowDecision.model_validate(
            _shadow_payload(
                api,
                counterfactual_lines=(changed, *shadow.counterfactual_lines[1:]),
            )
        )


def test_shadow_stage_bindings_are_canonical_unique_and_exactly_cover_lines() -> None:
    api = _api()
    shadow = _shadow(api)
    expected = {
        (
            line.research_program_id,
            line.economic_lineage_id,
            line.stage_id,
            line.trial_id,
            line.stage_manifest_hash,
        )
        for line in shadow.counterfactual_lines
    }
    actual = {
        (
            item.research_program_id,
            item.economic_lineage_id,
            item.stage_id,
            item.trial_id,
            item.stage_manifest_hash,
        )
        for item in shadow.stage_bindings
    }
    assert actual == expected
    assert shadow.stage_bindings == tuple(
        sorted(
            shadow.stage_bindings,
            key=lambda item: (
                item.research_program_id,
                item.economic_lineage_id,
                item.stage_id,
                item.trial_id,
            ),
        )
    )
    for bindings in ((), shadow.stage_bindings + shadow.stage_bindings):
        with pytest.raises(ValidationError, match="stage|coverage|duplicate|canonical"):
            api.ShadowDecision.model_validate(
                _shadow_payload(api, stage_bindings=bindings)
            )
    with pytest.raises(ValidationError, match="line|canonical|order"):
        api.ShadowDecision.model_validate(
            _shadow_payload(
                api,
                counterfactual_lines=tuple(reversed(shadow.counterfactual_lines)),
            )
        )


def test_shadow_schema_forbids_every_authority_and_execution_field() -> None:
    api = _api()
    forbidden = {
        "seal_id",
        "seal_revision",
        "active_seal_id",
        "authorization_id",
        "authorization_status",
        "gateway_expected_versions",
        "reservation_id",
        "reserve_cents",
        "permit_nonce",
        "outbox_batch_id",
        "client_order_id",
        "broker_ack_id",
        "fill_id",
    }
    assert forbidden.isdisjoint(api.ShadowDecision.model_fields)
    for field in forbidden:
        with pytest.raises(ValidationError, match="extra_forbidden"):
            api.ShadowDecision.model_validate(
                _shadow_payload(api) | {field: "forbidden"}
            )


def test_shadow_counterfactual_key_is_not_a_seal_logical_key() -> None:
    api = _api()
    key = _shadow(api).counterfactual_key
    with pytest.raises(ValidationError):
        api.DecisionLogicalKey.model_validate(
            key.model_dump(mode="python", round_trip=True)
        )


INTEGER_FIELDS_BY_FIXTURE = {
    "window": (
        "calendar_snapshot_version",
        "cutoff_snapshot_version",
        "monotonic_observation_ns",
        "monotonic_sequence",
    ),
    "gateway_issuer": ("capability_schema_major", "registry_epoch"),
    "shadow_issuer": ("capability_schema_major", "registry_epoch"),
    "stage": ("expected_stage_loss_version", "post_stage_loss_version"),
    "stage_expected": ("stage_loss_version",),
    "reserve": ("reserved_cash_cents",),
    "prior": (
        "prior_seal_revision",
        "permit_issuance_sequence",
        "fencing_token_issuance_sequence",
        "live_order_count",
    ),
    "gateway_expected": (
        "registry_epoch",
        "policy_epoch",
        "authority_epoch",
        "risk_epoch",
        "authorization_version",
        "authorization_status_version",
        "entry_fence_version",
        "capital_version",
        "capital_stream_version",
        "writer_fencing_epoch",
        "expected_active_seal_revision",
        "schema_major",
    ),
    "seal": (
        "schema_major",
        "seal_revision",
        "supersedes_seal_revision",
        "registry_epoch",
        "policy_epoch",
        "authority_epoch",
        "risk_epoch",
        "authorization_version",
        "authorization_status_version",
        "entry_fence_version",
        "capital_version",
        "capital_stream_version",
        "writer_fencing_epoch",
        "reservation_version",
        "total_reserved_cash_cents",
        "post_admission_capital_version",
        "post_admission_reservation_version",
    ),
    "shadow_line": (
        "target_quantity_units",
        "lot_size_units",
        "limit_price_cents",
        "worst_case_price_cents",
        "exit_session_ordinal",
        "estimated_fee_cents",
        "estimated_cash_reserve_cents",
    ),
    "shadow": ("schema_major", "policy_epoch"),
    "permit_line": (
        "sealed_quantity_units",
        "permitted_quantity_units",
        "limit_price_cents",
        "worst_case_price_cents",
        "exit_session_ordinal",
        "sealed_reserve_cents",
        "remaining_reserve_cents",
        "released_reserve_cents",
    ),
    "send_claim": (
        "active_seal_revision",
        "permit_nonce_sequence",
        "registry_epoch",
        "policy_epoch",
        "authority_epoch",
        "risk_epoch",
        "authorization_version",
        "authorization_status_version",
        "entry_fence_version",
        "capital_version",
        "capital_stream_version",
        "risk_snapshot_version",
        "reservation_version",
        "remaining_reserved_cash_cents",
        "writer_fencing_epoch",
    ),
    "permit": (
        "schema_major",
        "permit_nonce_sequence",
        "seal_revision",
        "total_remaining_reserve_cents",
        "total_released_reserve_cents",
    ),
}


def _strict_fixture(api, fixture_name):
    if fixture_name == "window":
        instance = _window(api)
    elif fixture_name == "gateway_issuer":
        instance = _gateway_issuer(
            api,
            api.ArtifactKind.PORTFOLIO_DECISION_SEAL,
            "capital-gateway.entry-seal.v1",
        )
    elif fixture_name == "shadow_issuer":
        instance = _shadow_issuer(api)
    elif fixture_name == "stage":
        instance = _stage_binding(api)
    elif fixture_name == "stage_expected":
        instance = _stage_expected_version(api, _proposal(api).order_lines[0])
    elif fixture_name == "reserve":
        instance = _reserve_bindings(api, _proposal(api))[0]
    elif fixture_name == "prior":
        instance = _prior_seal_eligibility(api)
    elif fixture_name == "gateway_expected":
        instance = _gateway_expected_versions(api)
    elif fixture_name == "seal":
        instance = _seal(api)
    elif fixture_name == "shadow_line":
        instance = _shadow_line(api)
    elif fixture_name == "shadow":
        instance = _shadow(api)
    elif fixture_name == "permit_line":
        instance = _permit(api).permit_lines[0]
    elif fixture_name == "send_claim":
        instance = _permit(api).send_claim_expected_versions
    elif fixture_name == "permit":
        instance = _permit(api)
    else:  # pragma: no cover - the parameter table is closed above
        raise AssertionError(f"unknown strict fixture: {fixture_name}")
    return type(instance), instance


@pytest.mark.parametrize(
    ("fixture_name", "field"),
    [
        (fixture_name, field)
        for fixture_name, fields in INTEGER_FIELDS_BY_FIXTURE.items()
        for field in fields
    ],
)
def test_every_checkpoint2_integer_field_rejects_non_native_integer(
    fixture_name, field
) -> None:
    api = _api()
    model, instance = _strict_fixture(api, fixture_name)
    base = instance.model_dump(mode="python", round_trip=True)
    if base[field] is None:
        if field == "expected_active_seal_revision":
            base["expected_active_seal_id"] = "seal-0"
            base[field] = 1
        elif field == "supersedes_seal_revision":
            eligibility = _prior_seal_eligibility(api)
            base.update(
                seal_revision=2,
                supersedes_seal_id=eligibility.prior_seal_id,
                supersedes_seal_revision=eligibility.prior_seal_revision,
                prior_seal_eligibility=eligibility,
            )
    for bad in (True, 1.0, Decimal("1")):
        with pytest.raises(ValidationError, match="integer|native int|valid integer"):
            model.model_validate(base | {field: bad})


UTC_FIELDS_BY_FIXTURE = {
    "window": (
        "wall_clock_observed_at",
        "t0_close_finalized_at",
        "seal_creation_deadline",
        "permit_issue_deadline",
        "gateway_send_deadline",
        "broker_auction_submission_cutoff",
    ),
    "gateway_issuer": ("verified_at",),
    "shadow_issuer": ("verified_at",),
    "seal": ("created_at",),
    "shadow": ("created_at", "available_at"),
    "permit_line": ("preopen_fact_as_of",),
    "send_claim": ("effective_send_deadline",),
    "permit": ("issued_at", "permit_expires_at"),
}


@pytest.mark.parametrize(
    ("fixture_name", "field"),
    [
        (fixture_name, field)
        for fixture_name, fields in UTC_FIELDS_BY_FIXTURE.items()
        for field in fields
    ],
)
def test_every_checkpoint2_time_field_rejects_naive_or_non_utc(
    fixture_name, field
) -> None:
    api = _api()
    model, instance = _strict_fixture(api, fixture_name)
    for bad_time in (
        SEAL_CREATED.replace(tzinfo=None),
        SEAL_CREATED.astimezone(timezone(timedelta(hours=8))),
    ):
        with pytest.raises(ValidationError, match="UTC|timezone"):
            model.model_validate(
                instance.model_dump(mode="python", round_trip=True) | {field: bad_time}
            )


def test_nested_line_models_forbid_unknown_fields() -> None:
    api = _api()
    seal_line = _reserve_bindings(api, _proposal(api))[0]
    shadow_line = _shadow_line(api)
    permit_line = _permit(api).permit_lines[0]
    cases = (
        (
            api.StageAdmissionBinding,
            _stage_binding(api),
            "expected_stage_loss_version",
        ),
        (api.SealReserveLineBinding, seal_line, "reserved_cash_cents"),
        (api.ShadowOrderLine, shadow_line, "target_quantity_units"),
        (api.ExecutionPermitLine, permit_line, "permitted_quantity_units"),
    )
    for model, instance, _field in cases:
        base = instance.model_dump(mode="python", round_trip=True)
        with pytest.raises(ValidationError, match="extra_forbidden"):
            model.model_validate(base | {"unknown": "forbidden"})


def test_nested_unchecked_models_are_recursively_revalidated() -> None:
    api = _api()
    seal = _seal(api)
    poisoned_reserve = seal.line_reserve_bindings[0].model_construct(
        **(
            seal.line_reserve_bindings[0].model_dump(mode="python")
            | {"reserved_cash_cents": -1}
        )
    )
    poisoned_seal_payload = _seal_payload(
        api,
        line_reserve_bindings=(
            poisoned_reserve,
            *seal.line_reserve_bindings[1:],
        ),
    )
    with pytest.raises(ValidationError):
        api.PortfolioDecisionSeal.model_validate(poisoned_seal_payload)
    poisoned_seal = api.PortfolioDecisionSeal.model_construct(**poisoned_seal_payload)
    with pytest.raises(ValidationError):
        poisoned_seal.artifact_hash()

    permit = _permit(api)
    poisoned_line = permit.permit_lines[0].model_copy(
        update={"permitted_quantity_units": -1}
    )
    poisoned_permit_payload = _permit_payload(
        api,
        permit_lines=(poisoned_line, *permit.permit_lines[1:]),
    )
    with pytest.raises(ValidationError):
        api.ExecutionPermit.model_validate(poisoned_permit_payload)
    poisoned_permit = api.ExecutionPermit.model_construct(**poisoned_permit_payload)
    with pytest.raises(ValidationError):
        poisoned_permit.artifact_hash()


def test_checkpoint2_artifacts_are_frozen_and_canonical_ordered() -> None:
    api = _api()
    for artifact in (_seal(api), _shadow(api), _permit(api)):
        with pytest.raises(ValidationError, match="frozen_instance"):
            artifact.schema_major = 2

    seal = _seal(api)
    with pytest.raises(ValidationError, match="canonical|order"):
        api.PortfolioDecisionSeal.model_validate(
            _seal_payload(
                api,
                line_reserve_bindings=tuple(reversed(seal.line_reserve_bindings)),
            )
        )
    permit = _permit(api)
    with pytest.raises(ValidationError, match="canonical|order"):
        api.ExecutionPermit.model_validate(
            _permit_payload(api, permit_lines=tuple(reversed(permit.permit_lines)))
        )


def test_nested_binding_identities_are_unique_and_composite() -> None:
    api = _api()
    stage = _stage_binding(api)
    duplicate_stages = (stage, stage)
    with pytest.raises(ValidationError, match="stage|unique|duplicate"):
        api.PortfolioDecisionSeal.model_validate(
            _seal_payload(api, stage_admission_bindings=duplicate_stages)
        )

    shadow = _shadow(api)
    with pytest.raises(ValidationError, match="line|unique|duplicate"):
        api.ShadowDecision.model_validate(
            _shadow_payload(
                api,
                counterfactual_lines=(
                    shadow.counterfactual_lines[0],
                    shadow.counterfactual_lines[0],
                ),
            )
        )

    permit = _permit(api)
    with pytest.raises(ValidationError, match="line|unique|duplicate"):
        api.ExecutionPermit.model_validate(
            _permit_payload(
                api,
                permit_lines=(permit.permit_lines[0], permit.permit_lines[0]),
            )
        )


def test_seal_shadow_and_permit_have_stable_canonical_serialization_fixtures() -> None:
    api = _api()
    fixtures = (
        ("seal", _seal(api)),
        ("shadow", _shadow(api)),
        ("permit", _permit(api)),
    )
    for label, artifact in fixtures:
        approved_canonical_digest, approved_artifact_hash = (
            APPROVED_SERIALIZATION_DIGESTS[label]
        )
        assert hashlib.sha256(api.canonical_json_bytes(artifact)).hexdigest() == (
            approved_canonical_digest
        )
        assert artifact.artifact_hash() == approved_artifact_hash


def test_every_authority_reserve_line_or_deadline_change_changes_artifact_hash() -> (
    None
):
    api = _api()
    permit = _permit(api)
    seal = permit.seal
    partial_lines = (
        permit.permit_lines[0],
        _permit_line(
            api,
            seal.proposal.order_lines[1],
            permitted_quantity=100,
            reason_code=api.PermitReasonCode.CAPITAL_RISK_REDUCTION,
        ),
    )
    outbox_expected = api.SendClaimExpectedVersions.model_validate(
        permit.send_claim_expected_versions.model_dump(mode="python", round_trip=True)
        | {"outbox_payload_hash": HASH_F}
    )
    earlier_expiry = PERMIT_EXPIRES - timedelta(microseconds=1)
    deadline_expected = api.SendClaimExpectedVersions.model_validate(
        permit.send_claim_expected_versions.model_dump(mode="python", round_trip=True)
        | {"effective_send_deadline": earlier_expiry}
    )
    valid_permit_variants = {
        "line": _permit(api, seal=seal, permit_lines=partial_lines),
        "nonce": _permit(api, permit_nonce="permit-nonce-2"),
        "outbox": _permit(api, send_claim_expected_versions=outbox_expected),
        "deadline": _permit(
            api,
            permit_expires_at=earlier_expiry,
            send_claim_expected_versions=deadline_expected,
        ),
        "issuer": _permit(
            api,
            issuer_binding=permit.issuer_binding.model_copy(
                update={"key_id": "capital-gateway-key-2"}
            ),
        ),
    }
    for label, valid_variant in valid_permit_variants.items():
        assert valid_variant.artifact_hash() != permit.artifact_hash(), label

    shadow = _shadow(api)
    changed_shadow = _shadow(api, evidence_set_merkle_root=HASH_F)
    assert changed_shadow.artifact_hash() != shadow.artifact_hash()


def test_hash_preimage_excludes_self_hash_and_signature_fields() -> None:
    api = _api()
    forbidden = {"artifact_hash", "signature", "self_hash"}
    for model in (
        api.PortfolioDecisionSeal,
        api.ShadowDecision,
        api.ExecutionPermit,
        api.GatewayIssuerBinding,
        api.ShadowIssuerBinding,
    ):
        assert forbidden.isdisjoint(model.model_fields)
