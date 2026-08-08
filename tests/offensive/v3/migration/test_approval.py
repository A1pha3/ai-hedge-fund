"""Plan 06 Task 1 (RED): 签名 MigrationApprovalManifest 验证 — verify_migration_approval().

锁定约束:
1. 合法 envelope (GOVERNANCE issuer + MIGRATION capability + 完整双人 attestations)
   必须通过, 返回绑定 manifest 哈希与签发者指纹的结果对象.
2. payload 篡改 (manifest 与 payload_hash 不符) 拒绝.
3. 签名无效 (错误私钥 / 伪造 signature) 拒绝.
4. 错误 artifact / namespace / mode / capability_version / scope 拒绝
   (envelope 声明必须与 required capability context 完全一致).
5. issuer 不在 registry / 生命周期失效 / capability 超窗 拒绝.
6. 时间窗: trusted_at 早于 allowed_from 或晚于 allowed_until 拒绝
   (短时批准窗口在 verification time 强制).
7. 结构性绑定 (contract 层已保证, 这里锁 migration 语义): 源/目 portfolio/account、
   schema major、writer、fencing epoch、时间窗、conservation/adoption/credential/
   rollback 哈希、双 cursor 缺一/被改即 ValidationError — 重申而非替代.
8. 双人批准: 同一 approver 双签、preimage 不符、scope 错误、非规范排序均拒绝.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib

import pytest
from pydantic import ValidationError

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.screening.offensive.v3.contracts import (
    ArtifactKind,
    MigrationApprovalManifest,
)
from src.screening.offensive.v3.trust import (
    CapabilityVerifier,
    TrustVerificationError,
)

from tests.offensive.v3.migration.helpers import (
    HASH_A,
    HASH_B,
    HASH_C,
    HASH_D,
    HASH_E,
    HASH_F,
    MIGRATION_CAPABILITY_VERSION,
    MIGRATION_MODE,
    MIGRATION_NAMESPACE,
    MIGRATION_SCOPE,
    NOW,
    TrustFabric,
    build_trust_fabric,
    make_migration_capability,
    make_issuer,
    sign_payload,
)

UTC = timezone.utc


def migration_proposal(**overrides: object) -> dict[str, object]:
    """与 test_governance_remediation_b._migration_manifest 对齐的完整提案."""

    values: dict[str, object] = {
        "manifest_id": "migration-approval-manifest-1",
        "portfolio_id": "portfolio-1",
        "broker_account_id": "account-1",
        "issued_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
        "one_shot": True,
        "issuer_id": "governance-migration",
        "issuer_capability": MIGRATION_CAPABILITY_VERSION,
        "schema_major": 2,
        "source_portfolio_id": "legacy-portfolio",
        "target_portfolio_id": "portfolio-1",
        "source_broker_account_id": "legacy-account",
        "target_broker_account_id": "account-1",
        "source_schema_major": 2,
        "target_schema_major": 3,
        "source_writer_id": "v2-writer",
        "target_writer_id": "v3-writer",
        "migration_program_hash": HASH_A,
        "allowed_from": NOW,
        "allowed_until": NOW + timedelta(minutes=30),
        "source_trust_bundle_hash": HASH_A,
        "target_trust_bundle_hash": HASH_B,
        "source_registry_epoch": 2,
        "target_registry_epoch": 3,
        "source_policy_activation_hash": HASH_A,
        "target_policy_activation_hash": HASH_B,
        "source_policy_epoch": 2,
        "target_policy_epoch": 3,
        "source_authority_epoch": 2,
        "target_authority_epoch": 3,
        "source_risk_epoch": 2,
        "target_risk_epoch": 3,
        "source_capital_root_hash": HASH_A,
        "target_capital_root_hash": HASH_B,
        "source_capital_version": 20,
        "target_capital_version": 1,
        "source_stream_root_hash": HASH_A,
        "target_stream_root_hash": HASH_B,
        "source_stream_version": 20,
        "target_stream_version": 1,
        "source_active_authorization_id": "v2-auth",
        "target_active_authorization_id": "v3-auth",
        "source_active_authorization_version": 5,
        "target_active_authorization_version": 1,
        "source_active_authorization_envelope_hash": HASH_A,
        "target_active_authorization_envelope_hash": HASH_B,
        "source_active_authorization_status_hash": HASH_A,
        "target_active_authorization_status_hash": HASH_B,
        "source_active_authorization_status_version": 5,
        "target_active_authorization_status_version": 1,
        "source_entry_fence_version": 4,
        "target_entry_fence_version": 1,
        "source_entry_fence_hash": HASH_A,
        "target_entry_fence_hash": HASH_B,
        "source_writer_fencing_epoch": 8,
        "target_writer_fencing_epoch": 9,
        "shared_inbox_cursor": "shared-1",
        "handoff_cursor": "handoff-1",
        "conservation_formula_hash": HASH_C,
        "live_order_adoption_hash": HASH_D,
        "credential_fencing_hash": HASH_E,
        "rollback_dr_hash": HASH_F,
    }
    values.update(overrides)
    return values


def _attestations_at(
    preimage_hash: str,
    stamp: datetime,
    *,
    scope: str = "MIGRATION_APPROVAL_MANIFEST",
) -> tuple[dict[str, object], ...]:
    base = {
        "approved_manifest_preimage_hash": preimage_hash,
        "approval_capability": "governance.manifest.approve.v1",
        "approval_scope": scope,
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


def _attestations(
    preimage_hash: str, *, scope: str = "MIGRATION_APPROVAL_MANIFEST"
) -> tuple[dict[str, object], ...]:
    return _attestations_at(
        preimage_hash, NOW - timedelta(minutes=2), scope=scope
    )


def approved_manifest(**overrides: object) -> MigrationApprovalManifest:
    proposal = migration_proposal(**overrides)
    proposal["issued_at"] = proposal["allowed_from"]
    proposal["expires_at"] = proposal["allowed_until"] + timedelta(minutes=30)  # type: ignore[operator]
    preimage = MigrationApprovalManifest.approval_preimage_hash_for_proposal(proposal)
    payload = dict(proposal)
    payload["approval_attestations"] = _attestations_at(
        preimage, proposal["issued_at"]  # type: ignore[arg-type]
    )
    return MigrationApprovalManifest.model_validate(payload)


def signed_envelope_for(
    fabric: TrustFabric,
    key: Ed25519PrivateKey,
    capability,
    manifest: MigrationApprovalManifest,
    *,
    payload: bytes | None = None,
):
    return sign_payload(
        key,
        capability,
        issuer_id="governance-migration",
        key_id="governance-migration-key-1",
        payload=payload if payload is not None else manifest.canonical_bytes(),
    )


def _verify(envelope, fabric: TrustFabric, capability, *, trusted_at=NOW):
    from src.screening.offensive.v3.migration.approval import (
        verify_migration_approval,
    )

    return verify_migration_approval(
        envelope,
        verifier=fabric.verifier,
        current_head=fabric.head,
        required_capability=capability,
        trusted_at=trusted_at,
    )


# ---------------------------------------------------------------------------
# 合法路径
# ---------------------------------------------------------------------------


def test_valid_signed_manifest_verifies_and_binds_hash() -> None:
    fabric, key, capability = build_trust_fabric()
    manifest = approved_manifest()
    envelope = signed_envelope_for(fabric, key, capability, manifest)

    result = _verify(envelope, fabric, capability)

    assert result.manifest.artifact_hash() == manifest.artifact_hash()
    assert result.manifest.manifest_id == "migration-approval-manifest-1"
    assert result.verified_issuer.issuer_id == "governance-migration"
    assert result.verified_issuer.capability.artifact == (
        ArtifactKind.MIGRATION_APPROVAL_MANIFEST
    )
    assert result.approval_window == (manifest.allowed_from, manifest.allowed_until)


# ---------------------------------------------------------------------------
# 篡改 / 伪造
# ---------------------------------------------------------------------------


def test_tampered_payload_rejected() -> None:
    fabric, key, capability = build_trust_fabric()
    manifest = approved_manifest()
    envelope = signed_envelope_for(fabric, key, capability, manifest)
    other = approved_manifest(manifest_id="migration-approval-manifest-2")
    tampered = envelope.model_copy(update={"payload": other.canonical_bytes()})
    with pytest.raises(TrustVerificationError):
        _verify(tampered, fabric, capability)


def test_signature_by_wrong_key_rejected() -> None:
    fabric, _key, capability = build_trust_fabric()
    manifest = approved_manifest()
    forged = sign_payload(
        Ed25519PrivateKey.generate(),
        capability,
        issuer_id="governance-migration",
        key_id="governance-migration-key-1",
        payload=manifest.canonical_bytes(),
    )
    with pytest.raises(TrustVerificationError):
        _verify(forged, fabric, capability)


def test_payload_hash_mismatch_rejected() -> None:
    fabric, key, capability = build_trust_fabric()
    manifest = approved_manifest()
    envelope = signed_envelope_for(fabric, key, capability, manifest)
    corrupted = envelope.model_copy(update={"payload_hash": HASH_F})
    with pytest.raises(TrustVerificationError):
        _verify(corrupted, fabric, capability)


# ---------------------------------------------------------------------------
# 上下文错位: artifact / namespace / mode / version / scope
# ---------------------------------------------------------------------------


def test_wrong_required_namespace_rejected() -> None:
    fabric, key, capability = build_trust_fabric()
    manifest = approved_manifest()
    envelope = signed_envelope_for(fabric, key, capability, manifest)
    wrong = make_migration_capability(namespace="capital.migration.other")
    with pytest.raises(TrustVerificationError):
        _verify(envelope, fabric, wrong)


def test_wrong_artifact_rejected() -> None:
    fabric, key, capability = build_trust_fabric()
    manifest = approved_manifest()
    envelope = signed_envelope_for(fabric, key, capability, manifest)
    wrong = make_migration_capability(
        artifact=ArtifactKind.DISASTER_RECOVERY_MANIFEST
    )
    with pytest.raises(TrustVerificationError):
        _verify(envelope, fabric, wrong)


def test_wrong_capability_version_rejected() -> None:
    fabric, key, capability = build_trust_fabric()
    manifest = approved_manifest()
    envelope = signed_envelope_for(fabric, key, capability, manifest)
    wrong = make_migration_capability(capability_version="governance.migration.approval.v0")
    with pytest.raises(TrustVerificationError):
        _verify(envelope, fabric, wrong)


# ---------------------------------------------------------------------------
# issuer 生命周期
# ---------------------------------------------------------------------------


def test_unknown_issuer_rejected() -> None:
    fabric, key, capability = build_trust_fabric()
    manifest = approved_manifest()
    envelope = signed_envelope_for(fabric, key, capability, manifest)
    stranger_key = Ed25519PrivateKey.generate()
    stranger = make_issuer(
        stranger_key, capability, issuer_id="stranger", key_id="stranger-key"
    )
    stranger_fabric = TrustFabric((stranger,))
    with pytest.raises(TrustVerificationError):
        _verify(envelope, stranger_fabric, capability)


def test_revoked_issuer_key_rejected() -> None:
    key = Ed25519PrivateKey.generate()
    capability = make_migration_capability()
    issuer = make_issuer(key, capability, revoked_at=NOW - timedelta(hours=1))
    fabric = TrustFabric((issuer,))
    manifest = approved_manifest()
    envelope = sign_payload(
        key,
        capability,
        issuer_id="governance-migration",
        key_id="governance-migration-key-1",
        payload=manifest.canonical_bytes(),
    )
    with pytest.raises(TrustVerificationError):
        _verify(envelope, fabric, capability)


def test_expired_capability_rejected() -> None:
    fabric, key, _capability = build_trust_fabric()
    manifest = approved_manifest()
    capability = make_migration_capability()
    envelope = signed_envelope_for(fabric, key, capability, manifest)
    with pytest.raises(TrustVerificationError):
        _verify(envelope, fabric, capability, trusted_at=NOW + timedelta(days=60))


# ---------------------------------------------------------------------------
# 短时批准窗口
# ---------------------------------------------------------------------------


def test_window_not_yet_open_rejected() -> None:
    fabric, key, capability = build_trust_fabric()
    manifest = approved_manifest(
        allowed_from=NOW + timedelta(minutes=5),
        allowed_until=NOW + timedelta(minutes=35),
    )
    envelope = signed_envelope_for(fabric, key, capability, manifest)
    with pytest.raises(TrustVerificationError, match="window|allowed"):
        _verify(envelope, fabric, capability, trusted_at=NOW)


def test_window_expired_rejected() -> None:
    fabric, key, capability = build_trust_fabric()
    manifest = approved_manifest(
        allowed_from=NOW - timedelta(minutes=40),
        allowed_until=NOW - timedelta(minutes=10),
    )
    envelope = signed_envelope_for(fabric, key, capability, manifest)
    with pytest.raises(TrustVerificationError, match="window|allowed"):
        _verify(envelope, fabric, capability, trusted_at=NOW)


# ---------------------------------------------------------------------------
# 结构性绑定 (migration 语义重申)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    (
        {"target_portfolio_id": "other-portfolio"},
        {"target_broker_account_id": "other-account"},
        {"target_schema_major": 2},
        {"source_writer_fencing_epoch": 9, "target_writer_fencing_epoch": 9},
    ),
)
def test_structural_binding_mutation_rejected(override: dict[str, object]) -> None:
    proposal = migration_proposal(**override)
    with pytest.raises(ValidationError):
        MigrationApprovalManifest.approval_preimage_hash_for_proposal(proposal)


@pytest.mark.parametrize(
    "override",
    (
        {"migration_program_hash": HASH_F},
        {"conservation_formula_hash": HASH_F},
        {"live_order_adoption_hash": HASH_F},
        {"credential_fencing_hash": HASH_F},
        {"handoff_cursor": "different-cursor"},
        {"shared_inbox_cursor": "different-cursor"},
    ),
)
def test_hash_and_cursor_binding_flips_preimage(override: dict[str, object]) -> None:
    """哈希/游标字段仍被双人批准绑定: 变更必须翻转批准 preimage."""

    baseline = MigrationApprovalManifest.approval_preimage_hash_for_proposal(
        migration_proposal()
    )
    mutated = MigrationApprovalManifest.approval_preimage_hash_for_proposal(
        migration_proposal(**override)
    )
    assert mutated != baseline


def test_one_shot_and_two_distinct_approvers_required() -> None:
    proposal = migration_proposal()
    preimage = MigrationApprovalManifest.approval_preimage_hash_for_proposal(proposal)
    alice, bob = _attestations(preimage)
    doubled = dict(proposal, approval_attestations=(alice, alice))
    with pytest.raises(ValidationError):
        MigrationApprovalManifest.model_validate(doubled)

    foreign_scope = dict(
        proposal,
        approval_attestations=_attestations(
            preimage, scope="DISASTER_RECOVERY_MANIFEST"
        ),
    )
    with pytest.raises(ValidationError):
        MigrationApprovalManifest.model_validate(foreign_scope)

    reversed_order = dict(proposal, approval_attestations=(bob, alice))
    with pytest.raises(ValidationError):
        MigrationApprovalManifest.model_validate(reversed_order)


def test_payload_must_decode_as_migration_manifest() -> None:
    fabric, key, capability = build_trust_fabric()
    envelope = sign_payload(
        key,
        capability,
        issuer_id="governance-migration",
        key_id="governance-migration-key-1",
        payload=b'{"not": "a manifest"}',
    )
    with pytest.raises((TrustVerificationError, ValidationError, ValueError)):
        _verify(envelope, fabric, capability)
