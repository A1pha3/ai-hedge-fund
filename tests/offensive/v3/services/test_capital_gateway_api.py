"""Plan 05 Task 3 (RED): CapitalGatewayApi 能力矩阵 + 路由行为。

Step 1 覆盖能力矩阵与 fail-closed: import 边界(唯一允许 import
capital/gateway 的服务)、API surface(19 公开方法, 不暴露其它 lane 写面)、
capital ledger 唯一句柄、runtime OFF|SHADOW 拒绝全部可执行 entry、policy
激活要求显式签名批准、entry halt 期间 exit/reconcile 仍可用。

Step 2 覆盖 route 级行为: joint policy/envelope CAS、one-active-envelope、
durable fence ACK、economic idempotency/supersede、reserve rollback、
permit expiry、SEND_CLAIMED disabled、risk snapshot 只读。

本文件引用尚未实现的服务骨架(方法体一律 raise NotImplementedError);
当前应整体 RED(每个测试在方法体/构造点失败于 NotImplementedError), 由主
代理随后实现 GREEN。
"""

from __future__ import annotations

from base64 import b64encode
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.screening.offensive.v3 import trust
from src.screening.offensive.v3.capital.repository import (
    CapitalCommand,
    CapitalCommandPayload,
    CapitalRepository,
)
from src.screening.offensive.v3.contracts import (
    ArtifactKind,
    CapitalRiskSnapshot,
    CashReceivableEconomicEventLeg,
    EconomicAssetKind,
    EconomicEventKind,
    EconomicLegDirection,
    ExecutionMode,
    PositionState,
    SignedEnvelope,
)
from src.screening.offensive.v3.contracts.authorization import (
    AuthorizationKind,
    CapitalAuthorizationEnvelope,
)
from src.screening.offensive.v3.contracts.base import EvidenceScope
from src.screening.offensive.v3.contracts.decision import (
    AuthorizationIssuanceBinding,
    ClockHealth,
    DecisionLogicalKey,
    GatewayExpectedVersions,
    GatewayIssuerBinding,
    PlanEvidence,
    PortfolioDecision,
    PortfolioDecisionSeal,
    PortfolioOrderLine,
    PriorSealEligibilityBinding,
    SealReserveLineBinding,
    StageAdmissionBinding,
    StageLossExpectedVersion,
    TrustedClockObservation,
    TrustedExecutionWindow,
)
from src.screening.offensive.v3.contracts.evidence import EvidenceRecord
from src.screening.offensive.v3.contracts.governance import (
    EntryFenceAcknowledgement,
    EntryFenceRaised,
    GrantKind,
    LineageGrant,
    PolicyActivation,
    ProgramLossBudgetBinding,
    TrustBundle,
)
from src.screening.offensive.v3.contracts.risk import StageLossLatchState
from src.screening.offensive.v3.gateway.authority import GatewayAuthorityError
from src.screening.offensive.v3.gateway.decisions import (
    AdmissionContext,
    CapitalGatewayError,
)
from src.screening.offensive.v3.gateway.exits import (
    ExitAttemptOutcome,
    ExitDerivationContext,
    ExitLotTruth,
)
from src.screening.offensive.v3.policy.models import RuntimeMode
from src.screening.offensive.v3.services import capital_gateway_api as cga_module
from src.screening.offensive.v3.services.capital_gateway_api import (
    CapitalGatewayApi,
    EXECUTION_AUTHORITY_DISABLED,
    POLICY_APPROVAL_ARTIFACT_KINDS,
    POLICY_APPROVAL_ARTIFACT_REJECTED,
    POLICY_APPROVAL_NAMESPACE,
    POLICY_APPROVAL_NAMESPACE_MISMATCH,
    POLICY_APPROVAL_REQUIRED,
    SEND_CLAIMED_DISABLED,
)
from tests.offensive.v3.contracts.checkpoint2_helpers import _api as _ck_api
from tests.offensive.v3.contracts.checkpoint2_helpers import _permit as _ck_permit

UTC = timezone.utc
NOW = datetime(2026, 8, 7, 9, 0, tzinfo=UTC)
HASH = "a" * 64
BEHAVIOR = "b" * 64
PORTFOLIO = "paper-v3"
MODE = ExecutionMode.DAILY_BAR_PROXY

# -- Step 2 决策 fixtures 时间基(与 test_decisions.py 一致) -------------------
SIGNAL_SESSION = date(2026, 8, 6)
ENTRY_SESSION = date(2026, 8, 7)
T0_CLOSE = datetime(2026, 8, 6, 15, 0, tzinfo=UTC)
SEAL_DEADLINE = datetime(2026, 8, 6, 16, 0, tzinfo=UTC)
PERMIT_DEADLINE = datetime(2026, 8, 6, 16, 30, tzinfo=UTC)
SEND_DEADLINE = datetime(2026, 8, 7, 9, 25, tzinfo=UTC)
BROKER_CUTOFF = datetime(2026, 8, 7, 9, 30, tzinfo=UTC)

# -- Step 2 exit fixtures 时间基(与 test_exits.py 一致) ------------------------
EXIT_SIGNAL_SESSION = date(2026, 7, 16)  # Thursday


def _sessions_after_signal(count: int) -> tuple[date, ...]:
    sessions: list[date] = []
    day = EXIT_SIGNAL_SESSION
    while len(sessions) < count:
        day = day + timedelta(days=1)
        if day.weekday() < 5:
            sessions.append(day)
    return tuple(sessions)


ALL_SESSIONS = _sessions_after_signal(15)
DUE_SESSION = ALL_SESSIONS[9]  # 10th session after signal (entry ordinal 1)


# 其它 lane 的写面 — CapitalGatewayApi 一律不得暴露
PUBLISHER_FINALIZER_AUTHORIZER_GOVERNANCE = (
    "publish_snapshot",
    "active_snapshot",
    "raw_payload",
    "register_plan_line",
    "finalize_due",
    "outcome_fact",
    "assess_edge",
    "issued_status",
    "seal_trial",
    "issue_exploration",
    "issue_recovery",
    "sealed_trial",
    "target_policy",
)
CAPITAL_RAW_WRITES = (
    "append_atomic",
    "run_append",
    "record_fill_revision",
    "record_fee_revision",
    "confirm_observed_nav",
)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value


class _StubVerifier:
    """构造 fixture 用的占位 bundle verifier; 本测试不激活 trust bundle。"""

    def verify_signed_bundle(
        self, signed: SignedEnvelope, *, trusted_at: datetime
    ) -> TrustBundle:
        raise AssertionError("unexpected trust bundle verification")


# --------------------------------------------------------------------------
# authority fixtures(test_authority.py 同款)
# --------------------------------------------------------------------------


def _public_key_b64(private_key: Ed25519PrivateKey) -> str:
    return b64encode(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")


def _signed_bundle(
    *, registry_epoch: int = 1, root_key=None, registry=None
):
    if root_key is None:
        root_key = Ed25519PrivateKey.generate()
    root_public = _public_key_b64(root_key)
    import hashlib

    root_hash = hashlib.sha256(
        root_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).hexdigest()
    if registry is None:
        registry = trust.TrustedRegistry(issuers=())
    bundle = TrustBundle(
        registry_epoch=registry_epoch,
        predecessor_bundle_hash="0" * 64,
        root_hash=root_hash,
        root_key_id="offline-root-1",
        trusted_issuer_registry_hash=registry.content_hash(),
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(days=1),
        revoked_at=None,
        issuer_id="offline-governance-root",
        issuer_capability="root.trust.bundle.v1",
        schema_major=2,
    )
    signature = b64encode(
        root_key.sign(trust.trust_bundle_signature_preimage(bundle, registry))
    ).decode("ascii")
    anchor = trust.RootTrustAnchor(
        root_hash=root_hash,
        root_key_id="offline-root-1",
        public_key=root_public,
        valid_from=NOW - timedelta(days=30),
        valid_until=NOW + timedelta(days=30),
        revoked_at=None,
    )
    verifier = trust.TrustBundleVerifier((anchor,))
    signed = trust.SignedTrustBundle(
        bundle=bundle, registry=registry, signature=signature
    )
    return signed, verifier, root_key


def _policy_activation(
    policy_epoch: int = 1, authority_epoch: int = 1
) -> PolicyActivation:
    return PolicyActivation(
        portfolio_id=PORTFOLIO,
        mode=MODE,
        policy_snapshot_hash=HASH,
        predecessor_policy_activation_hash="0" * 64,
        trust_bundle_hash=HASH,
        registry_epoch=1,
        policy_epoch=policy_epoch,
        authority_epoch=authority_epoch,
        risk_epoch=1,
        effective_from=NOW,
        expires_at=NOW + timedelta(days=1),
        issuer_id="governance.service",
        issuer_capability="governance.policy.activation.v1",
        schema_major=2,
    )


def _grant(**overrides) -> LineageGrant:
    values = {
        "grant_id": "grant-1",
        "grant_kind": GrantKind.EDGE,
        "grant_certificate_hash": HASH,
        "grant_issuer_id": "authorizer.service",
        "subject_producer": "btst",
        "family_id": "btst.limit-up-breakout",
        "economic_lineage_id": "eline-1",
        "research_program_id": "prog-1",
        "behavior_fingerprint": BEHAVIOR,
        "execution_version": "t1-open-t10-open.v1",
        "cost_version": "cn-a-share-costs.v1",
        "capital_tier": 2,
        "lineage_gross_cap": Decimal("0.02"),
        "trial_id": "trial-1",
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
        "alpha_or_evalue_budget_consumption_id": "consumption-1",
        "alpha_sample_consumption_id": "sample-1",
        "schema_major": 2,
    }
    values.update(overrides)
    return LineageGrant(**values)


def _binding() -> ProgramLossBudgetBinding:
    return ProgramLossBudgetBinding(
        research_program_id="prog-1",
        budget_id="budget-1",
        budget_cents=100_000,
        consumed_cents=0,
        version=1,
        schema_major=2,
    )


def _envelope(
    policy_activation: PolicyActivation,
    *,
    authorization_id="auth-1",
    authorization_version=1,
    grants=None,
    portfolio_gross_cap=Decimal("0.02"),
    exploration_cap=Decimal("0"),
) -> CapitalAuthorizationEnvelope:
    return CapitalAuthorizationEnvelope(
        authorization_kind=AuthorizationKind.EDGE,
        authorization_id=authorization_id,
        authorization_version=authorization_version,
        mode=MODE,
        portfolio_id=PORTFOLIO,
        broker_account_id=None,
        broker_account_fingerprint=None,
        base_currency="CNY",
        policy_activation_hash=policy_activation.artifact_hash(),
        trust_bundle_hash=HASH,
        registry_epoch=1,
        policy_epoch=policy_activation.policy_epoch,
        authority_epoch=policy_activation.authority_epoch,
        risk_epoch=1,
        research_program_ids=("prog-1",),
        baseline_portfolio_policy_fingerprint=HASH,
        target_portfolio_policy_fingerprint="c" * 64,
        lineage_grants=(grants if grants is not None else (_grant(),)),
        evidence_as_of=NOW,
        evidence_set_merkle_root=HASH,
        issued_at=NOW,
        expires_at=NOW + timedelta(days=1),
        activation_capital_snapshot_id="snapshot-1",
        activation_capital_snapshot_hash=HASH,
        portfolio_gross_cap=portfolio_gross_cap,
        exploration_aggregate_gross_cap=exploration_cap,
        program_loss_budget_bindings=(_binding(),),
        issuer_id="authorizer.service",
        issuer_capability="authorizer.edge.envelope.v1",
        portfolio_assessment_result_hash=HASH,
        global_attempt_ledger_checkpoint_hash=HASH,
        global_multiplicity_budget_consumption_id="consumption-1",
        schema_major=2,
    )


def _fence(
    fence_id="fence-1",
    *,
    fence_version=1,
    raised_at=None,
) -> EntryFenceRaised:
    return EntryFenceRaised(
        fence_id=fence_id,
        portfolio_id=PORTFOLIO,
        mode=MODE,
        fence_version=fence_version,
        predecessor_fence_hash="0" * 64,
        trust_bundle_hash=HASH,
        registry_epoch=1,
        policy_activation_hash=HASH,
        policy_epoch=1,
        authority_epoch=1,
        risk_epoch=1,
        predecessor_authorization_status_hash=HASH,
        authorization_status_version=1,
        reason="entry correction requires fence",
        cause_revision_id="revision-1",
        cause_revision_hash=HASH,
        raised_at=raised_at or NOW,
        affected_authorization_id=None,
        affected_authorization_version=None,
        affected_authorization_envelope_hash=None,
        affected_evidence_set_merkle_root=None,
        issuer_id="dependency.tracker",
        issuer_capability="dependency-tracker.entry-fence.raise.v1",
        schema_major=2,
    )


def _ack(
    fence: EntryFenceRaised,
    *,
    ack_id="ack-1",
    acknowledged_at=None,
) -> EntryFenceAcknowledgement:
    return EntryFenceAcknowledgement(
        acknowledgement_id=ack_id,
        fence_id=fence.fence_id,
        entry_fence_hash=fence.artifact_hash(),
        fence_version=fence.fence_version,
        portfolio_id=PORTFOLIO,
        mode=MODE,
        authority_epoch=1,
        risk_epoch=1,
        authorization_status_hash=HASH,
        authorization_status_version=2,
        fence_raised_at=fence.raised_at,
        durably_acknowledged_at=acknowledged_at
        or (fence.raised_at + timedelta(minutes=1)),
        gateway_writer_id="gateway-1",
        gateway_writer_version=1,
        gateway_fencing_epoch=1,
        issuer_id="capital.gateway",
        issuer_capability="capital-gateway.entry-fence.acknowledge.v1",
        schema_major=2,
    )


def _policy_approval(
    *,
    namespace: str = POLICY_APPROVAL_NAMESPACE,
    artifact: ArtifactKind = ArtifactKind.POLICY_ACTIVATION,
) -> SignedEnvelope:
    """一个显式签名批准输入(activate_policy_and_envelope 的 approval)。"""
    return SignedEnvelope(
        issuer_id="governance.root",
        key_id="root-key-1",
        schema_major=2,
        artifact=artifact,
        namespace=namespace,
        mode=MODE,
        capability_version="governance.policy-activation.approve.v1",
        capability_scope="policy-activation:approval",
        payload_hash="0" * 64,
        payload=b'{"approval": true}',
        signature=b64encode(b"0" * 64).decode("ascii"),
    )


# --------------------------------------------------------------------------
# decision fixtures(test_decisions.py 同款)
# --------------------------------------------------------------------------


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
        mode=MODE,
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
        mode=MODE,
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
        mode=MODE,
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
        risk_snapshot_as_of=T0_CLOSE - timedelta(minutes=10),
        capital_version=capital_version,
        capital_stream_version=capital_version,
        writer_fencing_epoch=1,
        order_lines=order_lines,
        total_worst_case_cash_reserve_cents=total_reserve,
        decision_cutoff=T0_CLOSE,
        proposal_created_at=T0_CLOSE + timedelta(minutes=20),
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
            wall_clock_utc=T0_CLOSE + timedelta(minutes=30),
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
        capability_mode=MODE,
        capability_schema_major=2,
        capability_version="capital-gateway.seal.v1",
        capability_scope=f"portfolio:{PORTFOLIO}",
        verification_result="VALID",
        verified_at=T0_CLOSE + timedelta(minutes=15),
        valid_until=T0_CLOSE + timedelta(minutes=15, hours=24),
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
        created_at=T0_CLOSE + timedelta(minutes=30),
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


# --------------------------------------------------------------------------
# exit fixtures(test_exits.py 同款; context 改名避免与 AdmissionContext 冲突)
# --------------------------------------------------------------------------


def _lot(**overrides) -> ExitLotTruth:
    values = {
        "position_lineage_id": "lin-1",
        "economic_lot_id": "lot-1",
        "security_id": "600000.SH",
        "producer_namespace": "btst",
        "research_program_id": "prog-1",
        "economic_lineage_id": "eline-1",
        "stage_id": "stage-1",
        "position_state": PositionState.OPEN,
        "signal_session": EXIT_SIGNAL_SESSION,
        "entry_session_ordinal": 1,
        "entry_plan_evidence_artifact_hash": HASH,
        "settled_quantity": 200,
        "tradable_quantity": 200,
        "live_exit_leaves": 0,
        "successor_security_id": None,
        "reopen": None,
    }
    values.update(overrides)
    return ExitLotTruth(**values)


def _exit_context(**overrides) -> ExitDerivationContext:
    values = {
        "portfolio_id": PORTFOLIO,
        "broker_account_id": None,
        "base_currency": "CNY",
        "mode": MODE,
        "capital_version": 1,
        "writer_fencing_epoch": 1,
        "fixed_exit_policy_fingerprint": "c" * 64,
        "source_risk_snapshot_id": "risk-snap-exit-1",
        "source_risk_snapshot_hash": HASH,
        "trading_sessions": ALL_SESSIONS,
    }
    values.update(overrides)
    return ExitDerivationContext(**values)


# --------------------------------------------------------------------------
# capital ledger fixtures(test_repository.py 同款)
# --------------------------------------------------------------------------

ENVIRONMENT_FINGERPRINT = "ab" * 32
T0 = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)


def _account_binding(**overrides):
    from src.screening.offensive.v3.capital.repository import AccountBinding

    kwargs = dict(
        portfolio_id="pf-test",
        mode=ExecutionMode.MANUAL_CONFIRMED,
        broker_account_id="acct-test",
        base_currency="CNY",
        environment_fingerprint=ENVIRONMENT_FINGERPRINT,
    )
    kwargs.update(overrides)
    return AccountBinding(**kwargs)


def _receivable_command(
    key: str,
    expected_version: int,
    *,
    cents: int = 10_000,
    receivable_id: str = "rcv-1",
    as_of: datetime = T0,
) -> CapitalCommand:
    amount = Decimal(cents) / 100
    payload = CapitalCommandPayload(
        event_kind=EconomicEventKind.DIVIDEND_RECEIVABLE,
        effective_at=as_of,
        source_authority="test.manual",
        legs=(
            CashReceivableEconomicEventLeg(
                leg_id=f"{key}-r",
                direction=EconomicLegDirection.CREDIT,
                asset_kind=EconomicAssetKind.CASH_RECEIVABLE,
                receivable_id=receivable_id,
                security_id="600000.SH",
                cash_amount=amount,
            ),
        ),
    )
    return CapitalCommand(
        idempotency_key=key,
        account_binding=_account_binding(),
        expected_stream_version=expected_version,
        as_of=as_of,
        payload=payload,
    )


# --------------------------------------------------------------------------
# service factory(在测试体里调用: RED 阶段构造/路由失败于 NotImplementedError)
# --------------------------------------------------------------------------


def _make_api(
    tmp_path: Path,
    *,
    runtime_mode_provider: Callable[[], RuntimeMode] | None = None,
) -> CapitalGatewayApi:
    capital_path = tmp_path / "capital.sqlite3"
    if not capital_path.exists():
        CapitalRepository.initialize(capital_path)
    return CapitalGatewayApi(
        database_path=str(tmp_path / "gateway.sqlite3"),
        capital_path=capital_path,
        clock=_Clock(NOW),
        bundle_verifier=_StubVerifier(),
        mode=MODE,
        broker_account_id=None,
        runtime_mode_provider=runtime_mode_provider,
    )


# --------------------------------------------------------------------------
# import 边界 helper
# --------------------------------------------------------------------------


def _import_lines(source: str) -> list[tuple[str, str]]:
    """返回 [(kind, module)]: kind ∈ {"import", "from"}, module 为源模块名。"""
    lines: list[tuple[str, str]] = []
    for line in source.splitlines():
        if not line or line[0].isspace():
            continue
        if line.startswith("import "):
            module = (
                line[len("import "):].split(" as ")[0].split(",")[0].strip()
            )
            lines.append(("import", module))
        elif line.startswith("from "):
            module = line[len("from "):].split(" import ")[0].strip()
            lines.append(("from", module))
    return lines


def _forbidden_import_segments(source: str, forbidden: set[str]) -> list[str]:
    """顶层 v3 子包段命中 forbidden 的 import 行(相对 import 一律忽略)。"""
    violations: list[str] = []
    for _, module in _import_lines(source):
        if module.startswith("."):
            continue
        parts = module.split(".")
        if len(parts) >= 5 and parts[4] in forbidden:
            violations.append(module)
    return violations


def _has_import_segment(source: str, segment: str) -> bool:
    for _, module in _import_lines(source):
        if module.startswith("."):
            continue
        parts = module.split(".")
        if len(parts) >= 5 and parts[4] == segment:
            return True
    return False


# --------------------------------------------------------------------------
# Step 1: 能力矩阵 + fail-closed
# --------------------------------------------------------------------------


def test_import_boundaries_allow_capital_gateway_execution_only() -> None:
    # 唯一允许 import capital/gateway 的服务: 顶层不得出现 evidence /
    # governance / producers 段(contracts.* 段不在禁止面)
    source = Path(cga_module.__file__).read_text(encoding="utf-8")
    assert (
        _forbidden_import_segments(
            source, {"evidence", "governance", "producers"}
        )
        == []
    )
    # 它必须持有 capital ledger 与 gateway 的 import 面(sole-writer 证明)
    assert _has_import_segment(source, "capital")
    assert _has_import_segment(source, "gateway")


def test_no_other_service_imports_capital_ledger() -> None:
    # 除 capital_gateway_api 外, services/*.py 一律不得 import capital 段:
    # 与各服务自身的 import 边界测试互补, 共同证明 capital ledger 只有
    # CapitalGatewayApi 一个句柄
    services_dir = Path(cga_module.__file__).parent
    for sibling in sorted(services_dir.glob("*.py")):
        if sibling.name == "capital_gateway_api.py":
            continue
        source = sibling.read_text(encoding="utf-8")
        assert not _has_import_segment(source, "capital"), sibling.name


def test_api_surface_exposes_sole_writer_methods(tmp_path: Path) -> None:
    api = _make_api(tmp_path)
    # 读面
    assert callable(api.risk_snapshot)
    assert callable(api.authority_state)
    assert callable(api.entry_state)
    assert callable(api.active_seal)
    assert callable(api.exit_state)
    # authority 激活 / fence
    assert callable(api.activate_trust_bundle)
    assert callable(api.activate_policy_and_envelope)
    assert callable(api.raise_entry_fence)
    assert callable(api.acknowledge_fence)
    # lifecycle(exit/reconcile/correction)
    assert callable(api.derive_exit_mandates)
    assert callable(api.claim_due_exit_work)
    assert callable(api.record_exit_attempt)
    assert callable(api.reconcile_exit)
    # gated entry
    assert callable(api.publish_entry)
    assert callable(api.issue_permit)
    assert callable(api.make_outbox_durable)
    assert callable(api.claim_send)
    assert callable(api.cancel_unclaimed_entry)
    assert callable(api.record_delivery_outcome)
    # 其它 lane 的写面一律不得暴露
    for name in PUBLISHER_FINALIZER_AUTHORIZER_GOVERNANCE:
        assert not hasattr(api, name), name
    # capital 裸写一律不得暴露
    for name in CAPITAL_RAW_WRITES:
        assert not hasattr(api, name), name


def test_signer_is_private_no_public_accessor(tmp_path: Path) -> None:
    api = _make_api(tmp_path)
    for name in ("signer", "get_signer", "sign", "signing_key"):
        assert not hasattr(api, name), name


def test_shadow_mode_rejects_all_executable_entry_routes(
    tmp_path: Path,
) -> None:
    shadow_api = _make_api(
        tmp_path,
        runtime_mode_provider=lambda: RuntimeMode.SHADOW,
    )
    seal = _seal()
    with pytest.raises(CapitalGatewayError) as excinfo:
        shadow_api.publish_entry(
            seal,
            expected_versions=_expected_versions(),
            context=_context(),
        )
    assert excinfo.value.code == EXECUTION_AUTHORITY_DISABLED

    # 其余可执行 entry 路由: runtime gate 最先执行, 参数不触达底层仓库
    with pytest.raises(CapitalGatewayError) as excinfo:
        shadow_api.issue_permit(None, context=None)  # type: ignore[arg-type]
    assert excinfo.value.code == EXECUTION_AUTHORITY_DISABLED

    with pytest.raises(CapitalGatewayError) as excinfo:
        shadow_api.make_outbox_durable(None)  # type: ignore[arg-type]
    assert excinfo.value.code == EXECUTION_AUTHORITY_DISABLED

    with pytest.raises(CapitalGatewayError) as excinfo:
        shadow_api.claim_send(None, None, context=None)  # type: ignore[arg-type]
    assert excinfo.value.code == EXECUTION_AUTHORITY_DISABLED

    with pytest.raises(CapitalGatewayError) as excinfo:
        shadow_api.cancel_unclaimed_entry(None)  # type: ignore[arg-type]
    assert excinfo.value.code == EXECUTION_AUTHORITY_DISABLED

    with pytest.raises(CapitalGatewayError) as excinfo:
        shadow_api.record_delivery_outcome("seal-1", None)  # type: ignore[arg-type]
    assert excinfo.value.code == EXECUTION_AUTHORITY_DISABLED


def test_off_mode_rejects_executable_entry(tmp_path: Path) -> None:
    off_api = _make_api(
        tmp_path,
        runtime_mode_provider=lambda: RuntimeMode.OFF,
    )
    seal = _seal()
    with pytest.raises(CapitalGatewayError) as excinfo:
        off_api.publish_entry(
            seal,
            expected_versions=_expected_versions(),
            context=_context(),
        )
    assert excinfo.value.code == EXECUTION_AUTHORITY_DISABLED


def test_policy_activation_requires_explicit_signed_approval(
    tmp_path: Path,
) -> None:
    api = _make_api(tmp_path)
    policy = _policy_activation()
    envelope = _envelope(policy)
    # approval 为必填关键字: 不传直接 TypeError (证明没有 env fallback)
    with pytest.raises(TypeError):
        api.activate_policy_and_envelope(policy, envelope)
    # None approval 拒绝
    with pytest.raises(CapitalGatewayError) as excinfo:
        api.activate_policy_and_envelope(
            policy, envelope, approval=None  # type: ignore[arg-type]
        )
    assert excinfo.value.code == POLICY_APPROVAL_REQUIRED
    # 错误 namespace 拒绝
    approval = _policy_approval(namespace="evidence.other.namespace")
    with pytest.raises(CapitalGatewayError) as excinfo:
        api.activate_policy_and_envelope(policy, envelope, approval=approval)
    assert excinfo.value.code == POLICY_APPROVAL_NAMESPACE_MISMATCH
    # 非 PLAN/TRUST-class artifact 拒绝
    approval = _policy_approval(artifact=ArtifactKind.SIGNAL)
    assert approval.artifact not in POLICY_APPROVAL_ARTIFACT_KINDS
    with pytest.raises(CapitalGatewayError) as excinfo:
        api.activate_policy_and_envelope(policy, envelope, approval=approval)
    assert excinfo.value.code == POLICY_APPROVAL_ARTIFACT_REJECTED


def test_shadow_rejects_policy_activation(tmp_path: Path) -> None:
    # 即使 approval 完全合法, OFF|SHADOW 下也不能本地激活 policy
    shadow_api = _make_api(
        tmp_path,
        runtime_mode_provider=lambda: RuntimeMode.SHADOW,
    )
    policy = _policy_activation()
    envelope = _envelope(policy)
    with pytest.raises(CapitalGatewayError) as excinfo:
        shadow_api.activate_policy_and_envelope(
            policy, envelope, approval=_policy_approval()
        )
    assert excinfo.value.code == EXECUTION_AUTHORITY_DISABLED


def test_exit_and_reconcile_routes_available_during_entry_halt(
    tmp_path: Path,
) -> None:
    # runtime_mode=OFF 期间 exit/reconcile/correction 全程可用
    off_api = _make_api(
        tmp_path,
        runtime_mode_provider=lambda: RuntimeMode.OFF,
    )
    (mandate,) = off_api.derive_exit_mandates(
        (_lot(),), context=_exit_context()
    )
    assert mandate.mandate_revision == 1
    claimed = off_api.claim_due_exit_work(
        as_of_session=DUE_SESSION, worker_id="worker-1"
    )
    assert len(claimed) == 1
    work = claimed[0]
    off_api.record_exit_attempt(
        exit_mandate_id=work.exit_mandate_id,
        attempt_id="attempt-1",
        client_order_id=work.stable_client_order_id,
        outcome=ExitAttemptOutcome.SUBMITTED,
        submitted_leaves=work.executable_quantity,
    )
    resolved = off_api.reconcile_exit(
        position_lineage_id="lin-1",
        economic_lot_id="lot-1",
        reason="broker statement confirms holding",
        verified_tradable_quantity=200,
        live_exit_leaves=0,
    )
    assert resolved is not None
    state = off_api.exit_state("lin-1", "lot-1")
    assert state.status == "PENDING"


# --------------------------------------------------------------------------
# Step 2: route 级行为
# --------------------------------------------------------------------------


def test_joint_activation_shows_active_envelope_and_rejects_identical_replay(
    tmp_path: Path,
) -> None:
    api = _make_api(tmp_path)
    policy = _policy_activation()
    envelope = _envelope(policy)
    api.activate_policy_and_envelope(
        policy, envelope, approval=_policy_approval()
    )
    state = api.authority_state(PORTFOLIO)
    assert state.active_authorization_id == "auth-1"
    assert state.active_authorization_version == 1
    assert state.active_envelope_hash == envelope.artifact_hash()
    assert state.policy_activation_hash == policy.artifact_hash()
    # 同一 activation 原样重放: 单调 epochs 先拒绝
    with pytest.raises(GatewayAuthorityError) as excinfo:
        api.activate_policy_and_envelope(
            policy, envelope, approval=_policy_approval()
        )
    assert excinfo.value.code == "policy_epoch_rollback"


def test_second_active_envelope_is_rejected(tmp_path: Path) -> None:
    api = _make_api(tmp_path)
    policy = _policy_activation()
    api.activate_policy_and_envelope(
        policy, _envelope(policy), approval=_policy_approval()
    )
    policy2 = _policy_activation(policy_epoch=2, authority_epoch=2)
    with pytest.raises(GatewayAuthorityError) as excinfo:
        api.activate_policy_and_envelope(
            policy2,
            _envelope(policy2, authorization_id="auth-2"),
            approval=_policy_approval(),
        )
    assert excinfo.value.code == "envelope_already_active"


def test_durable_fence_ack_is_idempotent_and_requires_committed_fence(
    tmp_path: Path,
) -> None:
    api = _make_api(tmp_path)
    fence = _fence()
    api.raise_entry_fence(fence)
    api.acknowledge_fence(_ack(fence))
    api.acknowledge_fence(_ack(fence))  # 幂等 identical retry
    state = api.authority_state(PORTFOLIO)
    assert state.open_fence_count == 0
    # 未 raise 的 fence 不可 ACK(durable ACK 必须引用已提交 fence)
    fresh = _make_api(tmp_path / "fresh")
    with pytest.raises(GatewayAuthorityError) as excinfo:
        fresh.acknowledge_fence(_ack(_fence(fence_id="fence-unknown")))
    assert excinfo.value.code == "fence_unknown"


def test_publish_entry_replay_is_economically_idempotent(
    tmp_path: Path,
) -> None:
    api = _make_api(tmp_path)
    seal = _seal()
    first = api.publish_entry(
        seal, expected_versions=_expected_versions(), context=_context()
    )
    second = api.publish_entry(
        seal, expected_versions=_expected_versions(), context=_context()
    )
    assert second.seal.seal_id == first.seal.seal_id
    # 不新增 seal: active 仍是同一 (seal_id, revision)
    assert api.active_seal(seal.logical_key) == ("seal-1", 1)


def test_same_key_different_payload_supersedes(tmp_path: Path) -> None:
    api = _make_api(tmp_path)
    original = _seal()
    api.publish_entry(
        original,
        expected_versions=_expected_versions(),
        context=_context(),
    )
    shrunk_line = _order_line(
        quantity=100, worst_case_price_cents=1_050
    )
    shrunk_decision = _decision(cycle="cycle-1", lines=(shrunk_line,))
    replacement = _seal(
        seal_id="seal-2",
        seal_revision=2,
        decision=shrunk_decision,
        supersedes=original,
        expected_versions=_expected_versions(expected_seal=original),
    )
    admitted = api.publish_entry(
        replacement,
        expected_versions=_expected_versions(expected_seal=original),
        context=_context(),
    )
    assert admitted.seal.seal_id == "seal-2"
    assert api.active_seal(replacement.logical_key) == ("seal-2", 2)


def test_reserve_insufficient_rolls_back_without_seal_residue(
    tmp_path: Path,
) -> None:
    api = _make_api(tmp_path)
    seal = _seal()
    with pytest.raises(CapitalGatewayError) as excinfo:
        api.publish_entry(
            seal,
            expected_versions=_expected_versions(),
            context=_context(available_cash_cents=1_000),
        )
    assert excinfo.value.code == "reserve_insufficient"
    # 失败不留下任何 seal 残留
    assert api.active_seal(seal.logical_key) is None


def test_expired_permit_rejected_by_issue_and_outbox(
    tmp_path: Path,
) -> None:
    api = _make_api(tmp_path)
    # checkpoint2 时间基(2026-07-29)整体早于本服务时钟(2026-08-07):
    # 该 permit 相对 gateway 已过期。底层 guard 顺序: issue_permit 先检查
    # issue deadline(permit_issue_deadline_missed), make_outbox_durable
    # 只检查 expiry(permit_expired) — 两者都证明过期 permit 无法前进。
    permit = _ck_permit(_ck_api())
    with pytest.raises(CapitalGatewayError) as excinfo:
        api.issue_permit(permit, context=None)  # type: ignore[arg-type]
    assert excinfo.value.code == "permit_issue_deadline_missed"
    with pytest.raises(CapitalGatewayError) as excinfo:
        api.make_outbox_durable(permit)
    assert excinfo.value.code == "permit_expired"


def test_claim_send_disabled_in_this_plan_regardless_of_mode(
    tmp_path: Path,
) -> None:
    # 默认 runtime(AUTHORITATIVE): gate 通过后仍被 SEND_CLAIMED 禁令拒绝
    api = _make_api(tmp_path)
    with pytest.raises(CapitalGatewayError) as excinfo:
        api.claim_send(None, None, context=None)  # type: ignore[arg-type]
    assert excinfo.value.code == SEND_CLAIMED_DISABLED
    # BTST_CANARY 同样禁用真实发送路径
    canary = _make_api(
        tmp_path / "canary",
        runtime_mode_provider=lambda: RuntimeMode.BTST_CANARY,
    )
    with pytest.raises(CapitalGatewayError) as excinfo:
        canary.claim_send(None, None, context=None)  # type: ignore[arg-type]
    assert excinfo.value.code == SEND_CLAIMED_DISABLED


def test_risk_snapshot_read_only_does_not_grow_ledger(
    tmp_path: Path,
) -> None:
    capital = CapitalRepository.initialize(tmp_path / "capital.sqlite3")
    capital.append_atomic(_receivable_command("k1", 0))
    before = (capital.stream_version(), capital.capital_version())
    assert before == (1, 1)

    api = _make_api(tmp_path)
    snapshot = api.risk_snapshot("pf-test", as_of=NOW)
    assert isinstance(snapshot, CapitalRiskSnapshot)

    after = (capital.stream_version(), capital.capital_version())
    assert after == before  # quiet 读: 不增长 stream/capital version
