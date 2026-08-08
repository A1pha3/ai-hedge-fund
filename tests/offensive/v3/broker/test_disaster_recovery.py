"""Plan 07 Task 8 (RED): disaster recovery restore + old-writer fencing.

锁定约束:
1. restore 只能由签名 DisasterRecoveryManifest 驱动; 全 CapabilityVerifier
   链校验, 篡改 payload => TrustVerificationError (签名失效).
2. backup root hash 必须与 manifest 绑定精确相等; 陈旧/篡改备份 =>
   BACKUP_ROOT_MISMATCH.
3. broker_account_fingerprint 必须与 portfolio 绑定相等; 否则 ACCOUNT_MISMATCH.
4. durable inbox/outbox/broker cursor 必须存在且与 manifest cursor proof 绑定;
   缺失 => MISSING_CURSOR; 不一致 => *_CURSOR_MISMATCH.
5. reconcile_before_entry: 进入前必须 reconcile 完整 broker 状态并重证 conservation;
   live/ambiguous order 未清零 = LIVE/AMBIGUOUS_ORDER_REMAINS; 守恒未证 =
   CONSERVATION_NOT_PROVEN.
6. recovery/fencing epoch 必须严格超过 live epoch; 陈旧/重放 manifest (epoch 不前进)
   = RECOVERY_EPOCH_NOT_ADVANCED (epoch race).
7. lost credential: 旧凭证不可复用; complete 前必须 present 新 fence proof
   (credential_re_bound + session re-severed + network re-fenced); 否则
   NO_FENCE_PROOF / CREDENTIAL_NOT_RE_BOUND / SESSION_NOT_RE_SEVERED.
8. old writer resurrection: DR 完成后旧 writer 在旧 epoch 下 send 被拒
   (WRITER_NOT_AUTHORITY / EPOCH_SUPERSEDED); 完成前 entry fenced.
9. RECOVERY_COMPLETE 前 entry 全程 fenced, 仅 exit/tightening/query/reconcile 继续.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.screening.offensive.v3.broker.disaster_recovery import (
    DisasterRecoveryCoordinator,
    DisasterRecoveryError,
    RecoveredStores,
    RecoveryFenceProof,
    RecoveryState,
)
from src.screening.offensive.v3.contracts import (
    ArtifactKind,
    Capability,
    DisasterRecoveryManifest,
    ExecutionMode,
)
from src.screening.offensive.v3.trust import TrustVerificationError

from tests.offensive.v3.migration.helpers import (
    HASH_A,
    HASH_B,
    HASH_C,
    HASH_D,
    HASH_E,
    HASH_F,
    NOW,
    TrustFabric,
    make_issuer,
    sign_payload,
)

FINGERPRINT = "a" * 64
RECOVERY_NAMESPACE = "capital.disaster-recovery"
RECOVERY_CAPABILITY_VERSION = "governance.disaster.recovery.v1"


# -- manifest / trust-fabric helpers ----------------------------------------


def _recovery_capability() -> Capability:
    return Capability(
        artifact=ArtifactKind.DISASTER_RECOVERY_MANIFEST,
        namespace=RECOVERY_NAMESPACE,
        mode=ExecutionMode.BROKER_CONFIRMED,
        schema_major=2,
        capability_version=RECOVERY_CAPABILITY_VERSION,
        scope="disaster-recovery",
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=30),
        revoked_at=None,
    )


def _fabric_and_key():
    key = Ed25519PrivateKey.generate()
    cap = _recovery_capability()
    fabric = TrustFabric(
        (
            make_issuer(
                key,
                cap,
                issuer_id="governance-recovery",
                key_id="governance-recovery-key-1",
            ),
        ),
        trusted_at=NOW,
    )
    return fabric, key, cap


def _signed_envelope(fabric, key, cap, manifest) -> object:
    return sign_payload(
        key,
        cap,
        issuer_id="governance-recovery",
        key_id="governance-recovery-key-1",
        payload=manifest.canonical_bytes(),
    )


def _dr_proposal(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "manifest_id": "dr-1",
        "portfolio_id": "portfolio-1",
        "broker_account_id": "acct-001",
        "issued_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
        "one_shot": True,
        "issuer_id": "governance-recovery",
        "issuer_capability": RECOVERY_CAPABILITY_VERSION,
        "schema_major": 2,
        "broker_account_fingerprint": FINGERPRINT,
        "trust_bundle_hash": HASH_A,
        "registry_epoch": 1,
        "policy_activation_hash": HASH_B,
        "policy_epoch": 1,
        "authority_epoch": 1,
        "risk_epoch": 1,
        "authorization_status_hash": HASH_C,
        "authorization_status_version": 1,
        "entry_fence_hash": HASH_D,
        "entry_fence_version": 1,
        "backup_root_hash": HASH_E,
        "durable_inbox_cursor": "inbox-1",
        "durable_outbox_cursor": "outbox-1",
        "broker_cursor": "broker-1",
        "durable_cursor_proof_hash": HASH_F,
        "source_writer_id": "writer-1",
        "target_writer_id": "writer-2",
        "recovery_epoch": 2,
        "fencing_epoch": 3,
        "reconciliation_proof_hash": HASH_A,
        "reconcile_before_entry": True,
    }
    values.update(overrides)
    return values


def _attestations_at(preimage_hash: str, stamp: object) -> tuple[dict[str, object], ...]:
    base: dict[str, object] = {
        "approved_manifest_preimage_hash": preimage_hash,
        "approval_capability": "governance.manifest.approve.v1",
        "approval_scope": "DISASTER_RECOVERY_MANIFEST",
        "schema_major": 2,
    }
    return (
        dict(
            base,
            approver_id="alice",
            key_id="alice-key",
            approval_artifact_hash=HASH_B,
            approved_at=stamp,
        ),
        dict(
            base,
            approver_id="bob",
            key_id="bob-key",
            approval_artifact_hash=HASH_C,
            approved_at=stamp,
        ),
    )


def _dr_manifest(**overrides: object) -> DisasterRecoveryManifest:
    proposal = _dr_proposal(**overrides)
    preimage = DisasterRecoveryManifest.approval_preimage_hash_for_proposal(proposal)
    payload = dict(proposal)
    payload["approval_attestations"] = _attestations_at(
        preimage, proposal["issued_at"]
    )
    return DisasterRecoveryManifest.model_validate(payload)


def _recovered_stores(**overrides: object) -> RecoveredStores:
    values: dict[str, object] = dict(
        backup_root_hash=HASH_E,
        inbox_cursor="inbox-1",
        outbox_cursor="outbox-1",
        broker_cursor="broker-1",
    )
    values.update(overrides)
    return RecoveredStores(**values)  # type: ignore[arg-type]


def _fence_proof(
    *,
    credential_re_bound: bool = True,
    session_re_severed: bool = True,
    network_egress_re_fenced: bool = True,
    termination_proof: bool = False,
    network_policy_proof: bool = False,
) -> RecoveryFenceProof:
    return RecoveryFenceProof(
        credential_re_bound=credential_re_bound,
        session_re_severed=session_re_severed,
        network_egress_re_fenced=network_egress_re_fenced,
        proven_at=NOW,
        termination_proof=termination_proof,
        network_policy_proof=network_policy_proof,
    )


def _verify_backup(
    coordinator: DisasterRecoveryCoordinator,
    envelope,
    fabric,
    cap,
    **overrides: object,
):
    kwargs: dict[str, object] = dict(
        verifier=fabric.verifier,
        current_head=fabric.head,
        required_capability=cap,
        trusted_at=NOW,
        recovered_backup_root_hash=HASH_E,
        current_recovery_epoch=1,
        current_fencing_epoch=2,
        expected_account_fingerprint=FINGERPRINT,
    )
    kwargs.update(overrides)
    return coordinator.verify_backup(envelope, **kwargs)


def _full_restore() -> DisasterRecoveryCoordinator:
    fabric, key, cap = _fabric_and_key()
    manifest = _dr_manifest()
    envelope = _signed_envelope(fabric, key, cap, manifest)
    coordinator = DisasterRecoveryCoordinator()
    _verify_backup(coordinator, envelope, fabric, cap)
    coordinator.restore_stores(_recovered_stores())
    coordinator.reconcile(
        live_orders=0, ambiguous_orders=0, conservation_proven=True
    )
    coordinator.present_fence_proof(_fence_proof())
    coordinator.complete(new_writer_id="writer-2")
    return coordinator


# -- happy path --------------------------------------------------------------


def test_restore_happy_path_advances_epoch_and_re_enables_entry() -> None:
    coordinator = _full_restore()
    assert coordinator.state is RecoveryState.RECOVERY_COMPLETE
    assert coordinator.recovery_epoch == 2
    assert coordinator.fencing_epoch == 3
    assert coordinator.entry_permitted is True
    # New writer at the recovered epoch is permitted.
    coordinator.fence_send(writer_id="writer-2", epoch=3)


def test_entry_fenced_until_recovery_complete() -> None:
    fabric, key, cap = _fabric_and_key()
    manifest = _dr_manifest()
    envelope = _signed_envelope(fabric, key, cap, manifest)
    coordinator = DisasterRecoveryCoordinator()
    assert coordinator.entry_permitted is False
    _verify_backup(coordinator, envelope, fabric, cap)
    assert coordinator.entry_permitted is False  # still fenced after backup verify
    with pytest.raises(DisasterRecoveryError) as excinfo:
        coordinator.fence_send(writer_id="writer-2", epoch=3)
    assert excinfo.value.code == "ENTRY_FENCED"
    coordinator.restore_stores(_recovered_stores())
    coordinator.reconcile(
        live_orders=0, ambiguous_orders=0, conservation_proven=True
    )
    with pytest.raises(DisasterRecoveryError) as excinfo:
        coordinator.fence_send(writer_id="writer-2", epoch=3)
    assert excinfo.value.code == "ENTRY_FENCED"


# -- tampered / stale manifest -----------------------------------------------


def test_tampered_manifest_rejected_by_trust_chain() -> None:
    fabric, key, cap = _fabric_and_key()
    manifest = _dr_manifest()
    envelope = _signed_envelope(fabric, key, cap, manifest)
    # Flip one payload byte and recompute the payload hash; the signature still
    # covers the original hash so the trust chain rejects it.
    original: bytes = envelope.payload  # type: ignore[union-attr]
    tampered = original[:-1] + bytes([original[-1] ^ 0x01])
    forged = _signed_envelope(fabric, key, cap, manifest)
    object.__setattr__(forged, "payload", tampered)
    object.__setattr__(
        forged, "payload_hash", hashlib.sha256(tampered).hexdigest()
    )
    coordinator = DisasterRecoveryCoordinator()
    with pytest.raises(TrustVerificationError):
        _verify_backup(coordinator, forged, fabric, cap)


def test_stale_backup_root_mismatch_rejected() -> None:
    fabric, key, cap = _fabric_and_key()
    manifest = _dr_manifest()
    envelope = _signed_envelope(fabric, key, cap, manifest)
    coordinator = DisasterRecoveryCoordinator()
    with pytest.raises(DisasterRecoveryError) as excinfo:
        _verify_backup(
            coordinator,
            envelope,
            fabric,
            cap,
            recovered_backup_root_hash="0" * 64,  # not HASH_E
        )
    assert excinfo.value.code == "BACKUP_ROOT_MISMATCH"
    assert coordinator.state is RecoveryState.PRE_RESTORE


def test_window_inactive_rejected() -> None:
    fabric, key, cap = _fabric_and_key()
    manifest = _dr_manifest()
    envelope = _signed_envelope(fabric, key, cap, manifest)
    coordinator = DisasterRecoveryCoordinator()
    with pytest.raises(DisasterRecoveryError) as excinfo:
        _verify_backup(
            coordinator, envelope, fabric, cap, trusted_at=NOW + timedelta(hours=2)
        )
    assert excinfo.value.code == "RECOVERY_WINDOW_INACTIVE"


# -- account binding ---------------------------------------------------------


def test_wrong_account_rejected() -> None:
    fabric, key, cap = _fabric_and_key()
    manifest = _dr_manifest()
    envelope = _signed_envelope(fabric, key, cap, manifest)
    coordinator = DisasterRecoveryCoordinator()
    with pytest.raises(DisasterRecoveryError) as excinfo:
        _verify_backup(
            coordinator,
            envelope,
            fabric,
            cap,
            expected_account_fingerprint="9" * 64,
        )
    assert excinfo.value.code == "ACCOUNT_MISMATCH"


# -- epoch race --------------------------------------------------------------


def test_recovery_epoch_race_rejected() -> None:
    # A stale/replayed manifest whose recovery epoch does not advance the live
    # epoch must be rejected (epoch race / replay).
    fabric, key, cap = _fabric_and_key()
    manifest = _dr_manifest(recovery_epoch=1)  # not > live recovery epoch 1
    envelope = _signed_envelope(fabric, key, cap, manifest)
    coordinator = DisasterRecoveryCoordinator()
    with pytest.raises(DisasterRecoveryError) as excinfo:
        _verify_backup(coordinator, envelope, fabric, cap)
    assert excinfo.value.code == "RECOVERY_EPOCH_NOT_ADVANCED"


def test_fencing_epoch_not_advanced_rejected() -> None:
    fabric, key, cap = _fabric_and_key()
    manifest = _dr_manifest(fencing_epoch=2)  # not > live fencing epoch 2
    envelope = _signed_envelope(fabric, key, cap, manifest)
    coordinator = DisasterRecoveryCoordinator()
    with pytest.raises(DisasterRecoveryError) as excinfo:
        _verify_backup(coordinator, envelope, fabric, cap)
    assert excinfo.value.code == "FENCING_EPOCH_NOT_ADVANCED"


# -- cursor restoration ------------------------------------------------------


def _backed_up(coordinator: DisasterRecoveryCoordinator) -> None:
    fabric, key, cap = _fabric_and_key()
    manifest = _dr_manifest()
    envelope = _signed_envelope(fabric, key, cap, manifest)
    _verify_backup(coordinator, envelope, fabric, cap)


def test_missing_inbox_cursor_rejected() -> None:
    coordinator = DisasterRecoveryCoordinator()
    _backed_up(coordinator)
    with pytest.raises(DisasterRecoveryError) as excinfo:
        coordinator.restore_stores(_recovered_stores(inbox_cursor=""))
    assert excinfo.value.code == "MISSING_CURSOR"


def test_missing_outbox_cursor_rejected() -> None:
    coordinator = DisasterRecoveryCoordinator()
    _backed_up(coordinator)
    with pytest.raises(DisasterRecoveryError) as excinfo:
        coordinator.restore_stores(_recovered_stores(outbox_cursor=""))
    assert excinfo.value.code == "MISSING_CURSOR"


def test_inbox_cursor_mismatch_rejected() -> None:
    coordinator = DisasterRecoveryCoordinator()
    _backed_up(coordinator)
    with pytest.raises(DisasterRecoveryError) as excinfo:
        coordinator.restore_stores(_recovered_stores(inbox_cursor="inbox-other"))
    assert excinfo.value.code == "INBOX_CURSOR_MISMATCH"


def test_outbox_cursor_mismatch_rejected() -> None:
    coordinator = DisasterRecoveryCoordinator()
    _backed_up(coordinator)
    with pytest.raises(DisasterRecoveryError) as excinfo:
        coordinator.restore_stores(_recovered_stores(outbox_cursor="outbox-other"))
    assert excinfo.value.code == "OUTBOX_CURSOR_MISMATCH"


# -- reconcile before entry --------------------------------------------------


def test_live_order_blocks_reconciliation() -> None:
    coordinator = DisasterRecoveryCoordinator()
    _backed_up(coordinator)
    coordinator.restore_stores(_recovered_stores())
    with pytest.raises(DisasterRecoveryError) as excinfo:
        coordinator.reconcile(
            live_orders=1, ambiguous_orders=0, conservation_proven=True
        )
    assert excinfo.value.code == "LIVE_ORDER_REMAINS"
    assert coordinator.state is RecoveryState.STORES_RESTORED


def test_ambiguous_order_blocks_reconciliation() -> None:
    coordinator = DisasterRecoveryCoordinator()
    _backed_up(coordinator)
    coordinator.restore_stores(_recovered_stores())
    with pytest.raises(DisasterRecoveryError) as excinfo:
        coordinator.reconcile(
            live_orders=0, ambiguous_orders=2, conservation_proven=True
        )
    assert excinfo.value.code == "AMBIGUOUS_ORDER_REMAINS"


def test_conservation_not_proven_blocks_reconciliation() -> None:
    coordinator = DisasterRecoveryCoordinator()
    _backed_up(coordinator)
    coordinator.restore_stores(_recovered_stores())
    with pytest.raises(DisasterRecoveryError) as excinfo:
        coordinator.reconcile(
            live_orders=0, ambiguous_orders=0, conservation_proven=False
        )
    assert excinfo.value.code == "CONSERVATION_NOT_PROVEN"


def test_complete_requires_reconcile_first() -> None:
    coordinator = DisasterRecoveryCoordinator()
    _backed_up(coordinator)
    coordinator.restore_stores(_recovered_stores())
    with pytest.raises(DisasterRecoveryError) as excinfo:
        coordinator.complete(new_writer_id="writer-2")
    assert excinfo.value.code == "ILLEGAL_RECOVERY_TRANSITION"


# -- lost credential / fence proof -------------------------------------------


def test_lost_credential_requires_re_binding() -> None:
    coordinator = DisasterRecoveryCoordinator()
    _backed_up(coordinator)
    coordinator.restore_stores(_recovered_stores())
    coordinator.reconcile(
        live_orders=0, ambiguous_orders=0, conservation_proven=True
    )
    # complete() before any fence proof => the lost credential is not re-bound.
    with pytest.raises(DisasterRecoveryError) as excinfo:
        coordinator.complete(new_writer_id="writer-2")
    assert excinfo.value.code == "NO_FENCE_PROOF"
    # Credential not re-bound => rejected.
    with pytest.raises(DisasterRecoveryError) as excinfo:
        coordinator.present_fence_proof(_fence_proof(credential_re_bound=False))
    assert excinfo.value.code == "CREDENTIAL_NOT_RE_BOUND"


def test_network_egress_not_re_fenced_rejected() -> None:
    coordinator = DisasterRecoveryCoordinator()
    _backed_up(coordinator)
    coordinator.restore_stores(_recovered_stores())
    coordinator.reconcile(
        live_orders=0, ambiguous_orders=0, conservation_proven=True
    )
    with pytest.raises(DisasterRecoveryError) as excinfo:
        coordinator.present_fence_proof(_fence_proof(network_egress_re_fenced=False))
    assert excinfo.value.code == "NETWORK_EGRESS_NOT_RE_FENCED"


def test_irrevocable_session_requires_termination_and_policy_proof() -> None:
    coordinator = DisasterRecoveryCoordinator()
    _backed_up(coordinator)
    coordinator.restore_stores(_recovered_stores())
    coordinator.reconcile(
        live_orders=0, ambiguous_orders=0, conservation_proven=True
    )
    with pytest.raises(DisasterRecoveryError) as excinfo:
        coordinator.present_fence_proof(
            _fence_proof(
                session_re_severed=False,
                termination_proof=False,
                network_policy_proof=False,
            )
        )
    assert excinfo.value.code == "SESSION_NOT_RE_SEVERED"
    # Termination proof + network-policy proof substitutes for session sever.
    coordinator.present_fence_proof(
        _fence_proof(
            session_re_severed=False,
            termination_proof=True,
            network_policy_proof=True,
        )
    )


# -- old writer resurrection -------------------------------------------------


def test_old_writer_resurrection_fenced() -> None:
    coordinator = _full_restore()
    # The old writer (writer-1) at the old fencing epoch is permanently invalid.
    with pytest.raises(DisasterRecoveryError) as excinfo:
        coordinator.fence_send(writer_id="writer-1", epoch=2)
    assert excinfo.value.code == "WRITER_NOT_AUTHORITY"
    # The new writer presenting the stale old epoch is also rejected.
    with pytest.raises(DisasterRecoveryError) as excinfo:
        coordinator.fence_send(writer_id="writer-2", epoch=2)
    assert excinfo.value.code == "EPOCH_SUPERSEDED"


def test_illegal_transition_rejected() -> None:
    coordinator = DisasterRecoveryCoordinator()
    # restore_stores before verify_backup.
    with pytest.raises(DisasterRecoveryError) as excinfo:
        coordinator.restore_stores(_recovered_stores())
    assert excinfo.value.code == "ILLEGAL_RECOVERY_TRANSITION"
