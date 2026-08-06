"""Plan 04 Task 5: atomic reserve and PortfolioDecisionSeal idempotency."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.screening.offensive.v3.contracts import ExecutionMode
from src.screening.offensive.v3.contracts.base import EvidenceScope
from src.screening.offensive.v3.contracts.decision import (
    ClockHealth,
    PriorSealEligibilityBinding,
    AuthorizationIssuanceBinding,
    DecisionLogicalKey,
    GatewayExpectedVersions,
    GatewayIssuerBinding,
    PlanEvidence,
    PortfolioDecision,
    PortfolioDecisionSeal,
    PortfolioOrderLine,
    SealReserveLineBinding,
    StageAdmissionBinding,
    StageLossExpectedVersion,
    TrustedClockObservation,
    TrustedExecutionWindow,
)
from src.screening.offensive.v3.contracts.evidence import (
    EvidenceRecord,
    ProviderPublicationState,
)
from src.screening.offensive.v3.contracts.risk import StageLossLatchState
from src.screening.offensive.v3.contracts import ArtifactKind
from src.screening.offensive.v3.gateway.decisions import (
    AdmissionContext,
    CapitalGateway,
    CapitalGatewayError,
)

UTC = timezone.utc
NOW = datetime(2026, 8, 6, 15, 30, tzinfo=UTC)
SIGNAL_SESSION = date(2026, 8, 6)
ENTRY_SESSION = date(2026, 8, 7)
HASH = "a" * 64
PORTFOLIO = "paper-v3"

T0_CLOSE = datetime(2026, 8, 6, 15, 0, tzinfo=UTC)
SEAL_DEADLINE = datetime(2026, 8, 6, 16, 0, tzinfo=UTC)
PERMIT_DEADLINE = datetime(2026, 8, 6, 16, 30, tzinfo=UTC)
SEND_DEADLINE = datetime(2026, 8, 7, 9, 25, tzinfo=UTC)
BROKER_CUTOFF = datetime(2026, 8, 7, 9, 30, tzinfo=UTC)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value


def _plan_record() -> EvidenceRecord[PlanEvidence]:
    envelope = PlanEvidence(
        evidence_id="plan-1",
        subject_scope=EvidenceScope.STRATEGY_LINEAGE,
        subject_producer="btst",
        family_id="btst.limit-up-breakout",
        economic_lineage_id="eline-1",
        strategy_semver="3.0.0",
        behavior_fingerprint=HASH,
        policy_epoch=1,
        execution_version="t1-open-t10-open.v1",
        cost_version="cn-a-share-costs.v1",
        effective_at=T0_CLOSE - timedelta(hours=1),
        provider_published_at=T0_CLOSE - timedelta(minutes=30),
        observed_at=T0_CLOSE - timedelta(minutes=20),
        available_at=T0_CLOSE - timedelta(minutes=10),
        mode=ExecutionMode.DAILY_BAR_PROXY,
        source_authority="btst",
        payload_content_hash=HASH,
        schema_major=2,
        evidence_kind="plan",
        portfolio_id=PORTFOLIO,
        signal_session=SIGNAL_SESSION,
        snapshot_id="snapshot-1",
        raw_target_fraction=Decimal("0.02"),
        created_at=T0_CLOSE - timedelta(hours=1),
    )
    return EvidenceRecord[PlanEvidence](
        evidence=envelope,
        ingested_at=T0_CLOSE - timedelta(minutes=12),
        commit_sequence=1,
        revision=1,
        supersedes_revision=None,
        active_revision=1,
    )


def _order_line(
    *,
    order_line_id="line-1",
    quantity=100,
    limit_price_cents=1_000,
    worst_case_price_cents=1_100,
    fee_reserve_cents=300,
    plan_record=None,
) -> PortfolioOrderLine:
    record = plan_record or _plan_record()
    worst_case_cash = (
        worst_case_price_cents * quantity + fee_reserve_cents
    )
    return PortfolioOrderLine(
        order_line_id=order_line_id,
        security_id="600000.SH",
        order_action="ENTRY",
        producer_namespace="btst",
        family_id="btst.limit-up-breakout",
        economic_lineage_id="eline-1",
        research_program_id="prog-1",
        stage_id="stage-1",
        stage_manifest_hash=HASH,
        grant_id="grant-1",
        grant_certificate_hash=HASH,
        authorization_id="auth-1",
        authorization_version=1,
        plan_evidence=record,
        plan_evidence_artifact_hash=record.artifact_hash(),
        plan_payload_content_hash=record.evidence.payload_content_hash,
        mode=ExecutionMode.DAILY_BAR_PROXY,
        target_entry_session=ENTRY_SESSION,
        exit_session_ordinal=10,
        sealed_quantity_units=quantity,
        lot_size_units=100,
        lot_rule_version="ashare-lot-100.v1",
        order_type="LIMIT",
        limit_price_cents=limit_price_cents,
        worst_case_price_cents=worst_case_price_cents,
        price_boundary_version="board-limit.v1",
        time_in_force="DAY",
        worst_case_fee_reserve_cents=fee_reserve_cents,
        worst_case_cash_reserve_cents=worst_case_cash,
    )


def _logical_key(cycle="cycle-1") -> DecisionLogicalKey:
    return DecisionLogicalKey(
        portfolio_id=PORTFOLIO,
        signal_session=SIGNAL_SESSION,
        decision_cycle_id=cycle,
    )


def _decision(
    *,
    cycle="cycle-1",
    lines=None,
    policy_activation_hash=None,
    authorization_id="auth-1",
    authorization_version=1,
    capital_version=1,
) -> PortfolioDecision:
    order_lines = lines if lines is not None else (_order_line(),)
    total_reserve = sum(
        line.worst_case_cash_reserve_cents for line in order_lines
    )
    return PortfolioDecision(
        logical_key=_logical_key(cycle),
        portfolio_id=PORTFOLIO,
        broker_account_id=None,
        broker_account_fingerprint=None,
        base_currency="CNY",
        mode=ExecutionMode.DAILY_BAR_PROXY,
        target_entry_session=ENTRY_SESSION,
        target_portfolio_policy_fingerprint="c" * 64,
        policy_activation_hash=policy_activation_hash or HASH,
        trust_bundle_hash=HASH,
        registry_epoch=1,
        policy_epoch=1,
        authority_epoch=1,
        risk_epoch=1,
        authorization_id=authorization_id,
        authorization_version=authorization_version,
        authorization_artifact_hash=HASH,
        evidence_set_merkle_root=HASH,
        risk_snapshot_id="risk-snap-1",
        risk_snapshot_artifact_hash=HASH,
        risk_snapshot_as_of=NOW - timedelta(minutes=10),
        capital_version=capital_version,
        capital_stream_version=capital_version,
        writer_fencing_epoch=1,
        order_lines=order_lines,
        total_worst_case_cash_reserve_cents=total_reserve,
        decision_cutoff=T0_CLOSE,
        proposal_created_at=NOW,
        schema_major=2,
    )


def _execution_window() -> TrustedExecutionWindow:
    return TrustedExecutionWindow(
        signal_session=SIGNAL_SESSION,
        target_entry_session=ENTRY_SESSION,
        exchange_id="SSE",
        calendar_snapshot_id="cal-1",
        calendar_snapshot_hash=HASH,
        calendar_snapshot_version=1,
        cutoff_snapshot_id="cutoff-1",
        cutoff_snapshot_hash=HASH,
        cutoff_snapshot_version=1,
        cutoff_snapshot_session=ENTRY_SESSION,
        cutoff_snapshot_exchange_id="SSE",
        execution_policy_version="exec-policy.v1",
        cutoff_policy_version="cutoff-policy.v1",
        seal_clock_observation=TrustedClockObservation(
            observation_id="clock-1",
            raw_payload_hash=HASH,
            wall_clock_utc=NOW,
            monotonic_observation_ns=1_000_000_000,
            monotonic_sequence=1,
            clock_health=ClockHealth.HEALTHY,
        ),
        t0_close_finalized_at=T0_CLOSE,
        seal_creation_deadline=SEAL_DEADLINE,
        permit_issue_deadline=PERMIT_DEADLINE,
        gateway_send_deadline=SEND_DEADLINE,
        broker_auction_submission_cutoff=BROKER_CUTOFF,
    )


def _expected_versions(
    *,
    expected_seal=None,
    status_version=1,
    status_hash=None,
    capital_version=1,
) -> GatewayExpectedVersions:
    seal_binding = {
        "expected_active_seal_id": None,
        "expected_active_seal_revision": None,
        "expected_active_seal_logical_key": None,
        "expected_active_seal_artifact_hash": None,
    }
    if expected_seal is not None:
        seal_binding = {
            "expected_active_seal_id": expected_seal.seal_id,
            "expected_active_seal_revision": expected_seal.seal_revision,
            "expected_active_seal_logical_key": expected_seal.logical_key,
            "expected_active_seal_artifact_hash": (
                expected_seal.artifact_hash()
            ),
        }
    return GatewayExpectedVersions(
        policy_activation_hash=HASH,
        trust_bundle_hash=HASH,
        registry_epoch=1,
        policy_epoch=1,
        authority_epoch=1,
        risk_epoch=1,
        authorization_id="auth-1",
        authorization_version=1,
        authorization_envelope_hash=HASH,
        authorization_status_version=status_version,
        authorization_status_hash=status_hash or HASH,
        evidence_set_merkle_root=HASH,
        entry_fence_id="fence-0",
        entry_fence_hash=HASH,
        entry_fence_version=0,
        risk_snapshot_id="risk-snap-1",
        risk_snapshot_artifact_hash=HASH,
        capital_version=capital_version,
        capital_stream_version=capital_version,
        writer_fencing_epoch=1,
        stage_loss_expected_versions=(
            StageLossExpectedVersion(
                research_program_id="prog-1",
                economic_lineage_id="eline-1",
                stage_id="stage-1",
                stage_loss_budget_id="budget-1",
                stage_loss_version=1,
                stage_loss_latch=StageLossLatchState.CLEAR,
            ),
        ),
        schema_major=2,
        **seal_binding,
    )


def _issuer_binding() -> GatewayIssuerBinding:
    return GatewayIssuerBinding(
        issuer_id="capital.gateway",
        key_id="gateway-key-1",
        capability_artifact_kind=ArtifactKind.PORTFOLIO_DECISION_SEAL,
        capability_namespace="capital-gateway.entry-seal.v1",
        capability_mode=ExecutionMode.DAILY_BAR_PROXY,
        capability_schema_major=2,
        capability_version="capital-gateway.seal.v1",
        capability_scope=f"portfolio:{PORTFOLIO}",
        verification_result="VALID",
        verified_at=NOW,
        valid_until=NOW + timedelta(days=1),
        trust_bundle_hash=HASH,
        registry_epoch=1,
    )


def _seal(
    *,
    seal_id="seal-1",
    seal_revision=1,
    cycle="cycle-1",
    decision=None,
    supersedes=None,
    expected_versions=None,
    total_reserved=None,
) -> PortfolioDecisionSeal:
    proposal = decision or _decision(cycle=cycle)
    expected = expected_versions or _expected_versions()
    line = proposal.order_lines[0]
    reserve_total = (
        total_reserved
        if total_reserved is not None
        else int(proposal.total_worst_case_cash_reserve_cents)
    )
    supersedes_id = None
    supersedes_revision = None
    prior_eligibility = None
    if supersedes is not None:
        supersedes_id = supersedes.seal_id
        supersedes_revision = supersedes.seal_revision
        prior_eligibility = PriorSealEligibilityBinding(
            prior_seal_id=supersedes.seal_id,
            prior_seal_revision=supersedes.seal_revision,
            prior_seal_artifact_hash=supersedes.artifact_hash(),
            logical_key=supersedes.logical_key,
            permit_issuance_sequence=0,
            fencing_token_issuance_sequence=0,
            live_order_count=0,
        )
    issuance_binding = AuthorizationIssuanceBinding(
        authorization_envelope_hash=HASH,
        authorization_issuer_id="authorizer.service",
        authorization_issuer_key_id="key-1",
        authorization_issuer_capability="authorizer.edge.envelope.v1",
        authorization_issuer_capability_version="v1",
        authorization_issuer_identity_fingerprint=HASH,
        registry_epoch=1,
        trust_bundle_hash=HASH,
    )
    return PortfolioDecisionSeal(
        artifact_kind=ArtifactKind.PORTFOLIO_DECISION_SEAL,
        artifact_namespace="capital-gateway.entry-seal.v1",
        schema_major=2,
        seal_id=seal_id,
        seal_revision=seal_revision,
        logical_key=proposal.logical_key,
        supersedes_seal_id=supersedes_id,
        supersedes_seal_revision=supersedes_revision,
        prior_seal_eligibility=prior_eligibility,
        proposal=proposal,
        proposal_artifact_hash=proposal.artifact_hash(),
        portfolio_id=proposal.portfolio_id,
        broker_account_id=proposal.broker_account_id,
        broker_account_fingerprint=proposal.broker_account_fingerprint,
        base_currency=proposal.base_currency,
        mode=proposal.mode,
        target_entry_session=proposal.target_entry_session,
        target_portfolio_policy_fingerprint=(
            proposal.target_portfolio_policy_fingerprint
        ),
        policy_activation_hash=proposal.policy_activation_hash,
        trust_bundle_hash=proposal.trust_bundle_hash,
        registry_epoch=proposal.registry_epoch,
        policy_epoch=proposal.policy_epoch,
        authority_epoch=proposal.authority_epoch,
        risk_epoch=proposal.risk_epoch,
        authorization_id=proposal.authorization_id,
        authorization_version=proposal.authorization_version,
        authorization_envelope_hash=HASH,
        authorization_issuance_binding=issuance_binding,
        authorization_issuance_binding_artifact_hash=(
            issuance_binding.artifact_hash()
        ),
        authorization_status_version=(
            expected.authorization_status_version
        ),
        authorization_status_hash=(
            expected.authorization_status_hash
        ),
        evidence_set_merkle_root=proposal.evidence_set_merkle_root,
        entry_fence_id=expected.entry_fence_id,
        entry_fence_hash=expected.entry_fence_hash,
        entry_fence_version=expected.entry_fence_version,
        risk_snapshot_id=proposal.risk_snapshot_id,
        risk_snapshot_artifact_hash=(
            proposal.risk_snapshot_artifact_hash
        ),
        capital_version=proposal.capital_version,
        capital_stream_version=proposal.capital_stream_version,
        stage_admission_bindings=(
            StageAdmissionBinding(
                research_program_id="prog-1",
                economic_lineage_id="eline-1",
                stage_id="stage-1",
                stage_loss_budget_id="budget-1",
                expected_stage_loss_version=1,
                post_stage_loss_version=2,
                stage_loss_latch=StageLossLatchState.CLEAR,
            ),
        ),
        writer_fencing_epoch=proposal.writer_fencing_epoch,
        consumed_gateway_expected_versions=expected,
        consumed_gateway_expected_versions_artifact_hash=(
            expected.artifact_hash()
        ),
        reservation_id=f"reservation-{seal_id}",
        reservation_version=seal_revision,
        line_reserve_bindings=tuple(
            SealReserveLineBinding(
                order_line_id=line.order_line_id,
                reservation_allocation_id=(
                    f"allocation-{seal_id}-{line.order_line_id}"
                ),
                reserved_cash_cents=line.worst_case_cash_reserve_cents,
            )
            for line in proposal.order_lines
        ),
        total_reserved_cash_cents=reserve_total,
        post_admission_capital_version=proposal.capital_version + 1,
        post_admission_capital_stream_version=(
            proposal.capital_stream_version + 1
        ),
        post_admission_reservation_version=seal_revision + 1,
        post_admission_risk_snapshot_id="risk-snap-2",
        post_admission_risk_snapshot_artifact_hash="b1" * 32,
        execution_window=_execution_window(),
        created_at=NOW,
        issuer_binding=_issuer_binding(),
    )


def _context(*, available_cash_cents=1_000_000) -> AdmissionContext:
    return AdmissionContext(
        available_cash_cents=available_cash_cents,
        active_authorization_id="auth-1",
        active_authorization_version=1,
        active_envelope_hash=HASH,
        policy_activation_hash=HASH,
        authorization_status_version=1,
        authorization_status_hash=HASH,
        writer_fencing_epoch=1,
    )


@pytest.fixture()
def gateway(tmp_path) -> CapitalGateway:
    return CapitalGateway(
        database_path=str(tmp_path / "gateway-decisions.sqlite3"),
        clock=_Clock(NOW),
    )


def test_publish_entry_admits_atomically(gateway) -> None:
    seal = _seal()
    admitted = gateway.publish_entry(
        seal, expected_versions=_expected_versions(), context=_context()
    )
    assert admitted.total_reserved_cash_cents == int(
        seal.total_reserved_cash_cents
    )
    active = gateway.active_seal(seal.logical_key)
    assert active == ("seal-1", 1)


def test_identical_rerun_is_idempotent(gateway) -> None:
    seal = _seal()
    first = gateway.publish_entry(
        seal, expected_versions=_expected_versions(), context=_context()
    )
    second = gateway.publish_entry(
        seal, expected_versions=_expected_versions(), context=_context()
    )
    assert second.seal.seal_id == first.seal.seal_id
    assert gateway.active_seal(seal.logical_key) == ("seal-1", 1)


def test_reserve_failure_writes_nothing(gateway) -> None:
    seal = _seal()
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.publish_entry(
            seal,
            expected_versions=_expected_versions(),
            context=_context(available_cash_cents=1_000),
        )
    assert excinfo.value.code == "reserve_insufficient"
    assert gateway.active_seal(seal.logical_key) is None


def test_same_key_different_payload_supersedes(gateway) -> None:
    original = _seal()
    gateway.publish_entry(
        original,
        expected_versions=_expected_versions(),
        context=_context(),
    )
    shrunk_line = _order_line(quantity=100, worst_case_price_cents=1_050)
    shrunk_decision = _decision(cycle="cycle-1", lines=(shrunk_line,))
    replacement = _seal(
        seal_id="seal-2",
        seal_revision=2,
        decision=shrunk_decision,
        supersedes=original,
        expected_versions=_expected_versions(expected_seal=original),
    )
    admitted = gateway.publish_entry(
        replacement,
        expected_versions=_expected_versions(expected_seal=original),
        context=_context(),
    )
    assert admitted.seal.seal_id == "seal-2"
    assert gateway.active_seal(replacement.logical_key) == ("seal-2", 2)


def test_supersede_cannot_increase_reserve(gateway) -> None:
    original = _seal()
    gateway.publish_entry(
        original,
        expected_versions=_expected_versions(),
        context=_context(),
    )
    bigger_line = _order_line(quantity=100, worst_case_price_cents=1_200)
    bigger_decision = _decision(cycle="cycle-1", lines=(bigger_line,))
    bigger = _seal(
        seal_id="seal-2",
        seal_revision=2,
        decision=bigger_decision,
        supersedes=original,
        expected_versions=_expected_versions(expected_seal=original),
    )
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.publish_entry(
            bigger,
            expected_versions=_expected_versions(expected_seal=original),
            context=_context(),
        )
    assert excinfo.value.code == "supersede_increases_reserve"


def test_supersede_after_permit_is_forbidden(gateway) -> None:
    original = _seal()
    gateway.publish_entry(
        original,
        expected_versions=_expected_versions(),
        context=_context(),
    )
    gateway.mark_seal_permitted("seal-1")
    shrunk_line = _order_line(quantity=100, worst_case_price_cents=1_050)
    replacement = _seal(
        seal_id="seal-2",
        seal_revision=2,
        decision=_decision(cycle="cycle-1", lines=(shrunk_line,)),
        supersedes=original,
        expected_versions=_expected_versions(expected_seal=original),
    )
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.publish_entry(
            replacement,
            expected_versions=_expected_versions(expected_seal=original),
            context=_context(),
        )
    assert excinfo.value.code == "supersede_forbidden_after_permit"


def test_stale_expected_versions_are_rejected(gateway) -> None:
    seal = _seal()
    stale = _expected_versions(status_version=99, status_hash="f" * 64)
    rebuilt = _seal(expected_versions=stale)
    with pytest.raises(CapitalGatewayError) as excinfo:
        gateway.publish_entry(
            rebuilt, expected_versions=stale, context=_context()
        )
    assert excinfo.value.code == "authorization_status_stale"


def test_epoch_change_cannot_escape_economic_key(gateway) -> None:
    original = _seal()
    gateway.publish_entry(
        original,
        expected_versions=_expected_versions(),
        context=_context(),
    )
    # Same logical key under a different epoch: the economic idempotency
    # key still binds - a second seal needs the supersede path.
    replayed = _seal(seal_id="seal-epoch")
    with pytest.raises(CapitalGatewayError):
        gateway.publish_entry(
            replayed,
            expected_versions=_expected_versions(),
            context=_context(),
        )
    assert gateway.active_seal(original.logical_key) == ("seal-1", 1)


def test_two_gateway_writers_race_one_seal_wins(tmp_path) -> None:
    db_path = str(tmp_path / "shared.sqlite3")
    writer_a = CapitalGateway(database_path=db_path, clock=_Clock(NOW))
    writer_b = CapitalGateway(database_path=db_path, clock=_Clock(NOW))
    seal_a = _seal(seal_id="seal-a")
    seal_b = _seal(seal_id="seal-b")
    writer_a.publish_entry(
        seal_a, expected_versions=_expected_versions(), context=_context()
    )
    with pytest.raises(CapitalGatewayError):
        writer_b.publish_entry(
            seal_b,
            expected_versions=_expected_versions(),
            context=_context(),
        )
    assert writer_a.active_seal(seal_a.logical_key) == ("seal-a", 1)
    assert writer_b.active_seal(seal_b.logical_key) == ("seal-a", 1)
