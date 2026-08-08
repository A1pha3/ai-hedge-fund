"""Plan 06 Task 1: 签名 MigrationApprovalManifest 验证.

`verify_migration_approval()` 是迁移协调器消费治理批准的唯一入口:

1. 经 ``CapabilityVerifier`` 全链验证 (registry、角色边界、生命周期、
   Ed25519 签名、payload 哈希) — 失败抛 ``TrustVerificationError``.
2. payload 必须严格解码为 ``MigrationApprovalManifest`` (双人批准、
   one-shot、结构绑定由契约层保证, 此处重申失败即拒绝).
3. 短时批准窗口在 verification time 强制: ``trusted_at`` 必须落在
   ``[allowed_from, allowed_until]`` 内 — 过期/未到的窗口即使签名有效也拒绝.

验证通过不启动任何迁移动作; 结果对象只绑定 manifest 哈希与签发者指纹.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.screening.offensive.v3.contracts import (
    CanonicalModel,
    Capability,
    CurrentTrustHeadWitness,
    MigrationApprovalManifest,
    SignedEnvelope,
    UtcInstant,
    VerifiedIssuer,
)
from src.screening.offensive.v3.trust import (
    CapabilityVerifier,
    TrustVerificationError,
)


class VerifiedMigrationApproval(CanonicalModel):
    """验证通过的批准: manifest + 签发者 + 生效窗口."""

    manifest: MigrationApprovalManifest
    verified_issuer: VerifiedIssuer
    approval_window: tuple[UtcInstant, UtcInstant]


def verify_migration_approval(
    envelope: SignedEnvelope,
    *,
    verifier: Any,
    current_head: CurrentTrustHeadWitness,
    required_capability: Capability,
    trusted_at: datetime,
) -> VerifiedMigrationApproval:
    """Fail-closed 验证签名批准; 失败抛 TrustVerificationError/ValueError."""

    verified = verifier.verify(
        envelope, required_capability, current_head=current_head,
        trusted_at=trusted_at,
    )
    try:
        manifest = MigrationApprovalManifest.model_validate_json(envelope.payload)
    except ValueError as exc:
        raise TrustVerificationError(
            f"migration approval payload is not a valid manifest: {exc}"
        ) from exc
    if not (manifest.allowed_from <= trusted_at <= manifest.allowed_until):
        raise TrustVerificationError(
            "migration approval window not active at trusted_at "
            f"(allowed {manifest.allowed_from.isoformat()}.."
            f"{manifest.allowed_until.isoformat()})"
        )
    return VerifiedMigrationApproval(
        manifest=manifest,
        verified_issuer=verified,
        approval_window=(manifest.allowed_from, manifest.allowed_until),
    )
