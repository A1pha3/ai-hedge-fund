"""Plan 07 broker 测试基建: 驱动真实 CapitalGateway 到 SEND_CLAIMED.

复用 Plan 04 checkpoint2_helpers 的契约构造器与 test_entry_state 的网关
驱动序列 (publish_entry -> issue_permit -> make_outbox_durable ->
claim_send), 让 dispatcher 测试在真实 claim 边界上验证 post-claim 的
send/inbox/outcome 行为, 而非重新发明网关装配.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.screening.offensive.v3.gateway.decisions import (
    AdmissionContext,
    CapitalGateway,
    GatewayTruthContext,
    StageLossTruth,
)
from tests.offensive.v3.contracts.checkpoint2_helpers import (
    AUTHORIZATION_ID,
    AUTHORIZATION_VERSION,
    PERMIT_DEADLINE,
    _api,
    _gateway_expected_versions,
    _permit,
    _seal,
)


class Clock:
    """A controllable UTC clock for gateway/dispatcher tests."""

    def __init__(self, start: datetime = PERMIT_DEADLINE) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value


@dataclass
class ClaimedGateway:
    """A gateway driven to one SEND_CLAIMED entry, with its permit + context."""

    gateway: CapitalGateway
    api: object
    seal: object
    permit: object
    claimed: object
    claim_context: GatewayTruthContext


def _stage_truths(source) -> tuple[StageLossTruth, ...]:
    return tuple(
        StageLossTruth(
            research_program_id=item.research_program_id,
            economic_lineage_id=item.economic_lineage_id,
            stage_id=item.stage_id,
            stage_loss_budget_id=item.stage_loss_budget_id,
            stage_loss_version=item.stage_loss_version,
            stage_loss_latch=item.stage_loss_latch,
        )
        for item in source
    )


def _claim_context(api, expected) -> GatewayTruthContext:
    snapshot = expected.post_risk_snapshot
    return GatewayTruthContext(
        policy_activation_hash=expected.policy_activation_hash,
        trust_bundle_hash=expected.trust_bundle_hash,
        registry_epoch=expected.registry_epoch,
        policy_epoch=expected.policy_epoch,
        authority_epoch=expected.authority_epoch,
        risk_epoch=expected.risk_epoch,
        active_authorization_id=expected.authorization_id,
        active_authorization_version=expected.authorization_version,
        active_envelope_hash=expected.authorization_envelope_hash,
        authorization_lifecycle=expected.authorization_lifecycle,
        authorization_status_version=expected.authorization_status_version,
        authorization_status_hash=expected.authorization_status_hash,
        entry_fence_id=expected.entry_fence_id,
        entry_fence_hash=expected.entry_fence_hash,
        entry_fence_version=expected.entry_fence_version,
        capital_version=expected.capital_version,
        capital_stream_version=expected.capital_stream_version,
        risk_snapshot_artifact_hash=expected.post_risk_snapshot_artifact_hash,
        risk_latch=snapshot.risk_latch,
        reconciliation_latch=snapshot.reconciliation_latch,
        stage_loss_states=_stage_truths(expected.stage_loss_bindings),
        writer_fencing_epoch=expected.writer_fencing_epoch,
    )


def _truth_context(api, evaluation) -> GatewayTruthContext:
    return GatewayTruthContext(
        policy_activation_hash=evaluation.policy_activation_hash,
        trust_bundle_hash=evaluation.trust_bundle_hash,
        registry_epoch=evaluation.registry_epoch,
        policy_epoch=evaluation.policy_epoch,
        authority_epoch=evaluation.authority_epoch,
        risk_epoch=evaluation.risk_epoch,
        active_authorization_id=evaluation.authorization_id,
        active_authorization_version=evaluation.authorization_version,
        active_envelope_hash=evaluation.authorization_envelope_hash,
        authorization_lifecycle=evaluation.authorization_lifecycle,
        authorization_status_version=evaluation.authorization_status_version,
        authorization_status_hash=evaluation.authorization_status_hash,
        entry_fence_id=evaluation.entry_fence_id,
        entry_fence_hash=evaluation.entry_fence_hash,
        entry_fence_version=evaluation.entry_fence_version,
        capital_version=evaluation.capital_version,
        capital_stream_version=evaluation.capital_stream_version,
        risk_snapshot_artifact_hash=evaluation.risk_snapshot_artifact_hash,
        risk_latch=evaluation.risk_snapshot.risk_latch,
        reconciliation_latch=evaluation.risk_snapshot.reconciliation_latch,
        stage_loss_states=_stage_truths(evaluation.stage_loss_bindings),
        writer_fencing_epoch=evaluation.writer_fencing_epoch,
    )


def drive_to_outbox(
    db_path: Path | str,
    clock: Clock,
    *,
    seal=None,
    permit=None,
) -> ClaimedGateway:
    """Publish → permit → outbox, stopping BEFORE claim_send.

    ``run_once`` performs the claim itself, so dispatcher tests need an
    OUTBOX_DURABLE entry (not a pre-claimed one). ``claim_context`` is
    ready for the dispatcher to pass into ``claim_send``.
    """

    api = _api()
    gateway = CapitalGateway(database_path=str(db_path), clock=clock)
    if seal is None:
        seal = _seal(api)
    if permit is None:
        permit = _permit(api)
    expected_versions = _gateway_expected_versions(api)
    gateway.publish_entry(
        seal,
        expected_versions=expected_versions,
        context=AdmissionContext(
            available_cash_cents=1_000_000,
            active_authorization_id=AUTHORIZATION_ID,
            active_authorization_version=AUTHORIZATION_VERSION,
            active_envelope_hash=seal.authorization_envelope_hash,
            policy_activation_hash=seal.policy_activation_hash,
            authorization_status_version=seal.authorization_status_version,
            authorization_status_hash=seal.authorization_status_hash,
            writer_fencing_epoch=seal.writer_fencing_epoch,
        ),
    )
    issue_context = _truth_context(api, permit.evaluation_state)
    gateway.issue_permit(permit, context=issue_context)
    gateway.make_outbox_durable(permit)
    send_expected = permit.send_claim_expected_versions
    claim_context = _claim_context(api, send_expected)
    return ClaimedGateway(
        gateway=gateway,
        api=api,
        seal=seal,
        permit=permit,
        claimed=None,
        claim_context=claim_context,
    )


def drive_to_claimed(
    db_path: Path | str,
    clock: Clock,
    *,
    seal=None,
    permit=None,
) -> ClaimedGateway:
    """Publish → permit → outbox → claim_send on a fresh gateway store."""

    rig = drive_to_outbox(db_path, clock, seal=seal, permit=permit)
    send_expected = rig.permit.send_claim_expected_versions
    claimed = rig.gateway.claim_send(
        rig.permit, send_expected, context=rig.claim_context
    )
    rig.claimed = claimed
    return rig
