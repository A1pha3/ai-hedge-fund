"""Plan 07 Task 2 (RED): broker capability certification + enablement gate.

锁定约束:
1. BrokerCapabilityProfile 每个能力区是 fail-closed: 未证明 (UNPROVEN) /
   截断/回退/超容差 在 profile 构造时即拒绝, 不拖到 enablement.
2. verify_broker_enablement 全链: CapabilityVerifier -> 严格 manifest 解析
   -> 激活窗口 -> 逐字段绑定 (account/env/currency/clock/raw/idempotency/
   auction/pagination/exit/fencing). 任一漂移拒绝并命名违规区.
3. 账号/环境/币种/endpoint 不一致 = ACCOUNT/ENVIRONMENT/CURRENCY_MISMATCH.
4. 未证明 client-ID scope = IDEMPOTENCY_UNPROVEN; 重复 create 行为必须
   显式 (idempotent_replay / duplicate_reject), UNPROVEN 不可启.
5. 不支持的 auction order type/TIF 不可认证; 模糊 cutoff (soft/unknown)
   不可启 (CUTOFF_AMBIGUOUS).
6. 分页 cursor 回退/截断/留存过短 = PAGINATION_GAP / RETENTION_TOO_SHORT.
7. clock skew 超容差 = CLOCK_SKEW_EXCEEDS_TOLERANCE.
8. late-fill 静默丢弃 / 未证明 = LATE_FILL_DROPPED / LATE_FILL_UNPROVEN.
9. production adapter 只能加载 hash 被有效 manifest 绑定的冻结 profile;
   缺失/未知字段保持禁用 (BROKER_ADAPTER_NOT_CERTIFIED).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib

import pytest
from pydantic import ValidationError

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.screening.offensive.v3.broker.capabilities import (
    AuthenticatedRawEnvelopeProfile,
    AuctionTifCutoffProfile,
    BrokerCapabilityProfile,
    BrokerEnablementError,
    ClientOrderIdempotencyProfile,
    CredentialSessionNetworkFencingProfile,
    CutoffSemantics,
    CursorContinuity,
    DuplicateCreateBehavior,
    ExecutionSemanticsProfile,
    ExitRateLimitProfile,
    IdempotencyScope,
    LateFillSemantics,
    PaginationCursorRetentionProfile,
    TrustedClockProfile,
    VerifiedBrokerEnablement,
    VersionHash,
    certify_auction_tif_cutoff,
    certify_client_order_idempotency,
    certify_credential_session_network_fencing,
    certify_execution_semantics,
    certify_pagination_cursor_retention,
    certify_trusted_clock,
    verify_broker_enablement,
)
from src.screening.offensive.v3.broker.ports import BrokerAccountBinding
from src.screening.offensive.v3.contracts import (
    ArtifactKind,
    BrokerEnablementManifest,
)
from src.screening.offensive.v3.contracts.governance import (
    ApprovalAttestationBinding,
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
    build_trust_fabric,
    make_issuer,
    sign_payload,
)

UTC = timezone.utc
FINGERPRINT = "a" * 64
BROKER_NAMESPACE = "capital.broker.enablement"
BROKER_CAPABILITY_VERSION = "governance.broker.enablement.v1"


def _binding(
    *,
    account_id: str = "acct-001",
    environment: str = "sandbox",
    currency: str = "CNY",
    endpoint: str = FINGERPRINT,
) -> BrokerAccountBinding:
    return BrokerAccountBinding(
        account_id=account_id,
        environment=environment,
        currency=currency,
        endpoint_fingerprint=endpoint,
    )


def _clock(**overrides) -> TrustedClockProfile:
    kwargs = dict(
        max_observed_skew_ms=50,
        tolerance_ms=500,
        proven_at=NOW,
    )
    kwargs.update(overrides)
    return certify_trusted_clock(**kwargs)


def _raw_envelope_profile() -> AuthenticatedRawEnvelopeProfile:
    return AuthenticatedRawEnvelopeProfile(
        parser_version="v1",
        auth_mechanism="ed25519-signed-jws",
        redacted_secret_fields=("session_token", "api_key"),
    )


def _idempotency(
    *,
    behavior: DuplicateCreateBehavior = DuplicateCreateBehavior.IDEMPOTENT_REPLAY,
    scopes=None,
) -> ClientOrderIdempotencyProfile:
    if scopes is None:
        scopes = (
            IdempotencyScope(
                trading_day_scope="2026-08-07",
                duplicate_create_behavior=behavior,
            ),
        )
    return certify_client_order_idempotency(scopes, proven_at=NOW)


def _auction(**overrides) -> AuctionTifCutoffProfile:
    kwargs = dict(
        supported_order_types=("LIMIT", "MARKET"),
        supported_time_in_force=("DAY", "GTC"),
        cutoff_semantics=CutoffSemantics.HARD_REJECT_AFTER,
        cutoff_instant_description="15:00:00 Asia/Shanghai",
        proven_at=NOW,
    )
    kwargs.update(overrides)
    return certify_auction_tif_cutoff(**kwargs)


def _pagination(**overrides) -> PaginationCursorRetentionProfile:
    kwargs = dict(
        page_count_proof=3,
        cursor_continuity=CursorContinuity.CONTINUOUS_MONOTONE,
        retention_calendar_days=30,
        proven_at=NOW,
    )
    kwargs.update(overrides)
    return certify_pagination_cursor_retention(**kwargs)


def _execution(
    *,
    late_fill: LateFillSemantics = LateFillSemantics.APPENDS_INVERSE_OR_DELTA,
) -> ExecutionSemanticsProfile:
    return certify_execution_semantics(
        partial_fill_supported=True,
        cancel_semantics="cancel_reduces_leaves",
        expiry_semantics="expire_at_session_end",
        late_fill_semantics=late_fill,
        proven_at=NOW,
    )


def _exit_rate() -> ExitRateLimitProfile:
    return ExitRateLimitProfile(
        exit_budget_per_minute=10,
        query_budget_per_minute=30,
    )


def _fencing(**overrides) -> CredentialSessionNetworkFencingProfile:
    kwargs = dict(
        session_revocable=True,
        network_egress_revocable=True,
        termination_proof_required=False,
    )
    kwargs.update(overrides)
    return certify_credential_session_network_fencing(**kwargs)


def _version(name: str) -> VersionHash:
    return VersionHash(
        name=name,
        version="1.0.0",
        source_hash=hashlib.sha256(name.encode()).hexdigest(),
    )


def _profile(
    *,
    binding: BrokerAccountBinding | None = None,
    idempotency: ClientOrderIdempotencyProfile | None = None,
    auction: AuctionTifCutoffProfile | None = None,
    pagination: PaginationCursorRetentionProfile | None = None,
    clock: TrustedClockProfile | None = None,
    execution: ExecutionSemanticsProfile | None = None,
    fencing: CredentialSessionNetworkFencingProfile | None = None,
    currency_definition_fingerprint: str = HASH_A,
) -> BrokerCapabilityProfile:
    return BrokerCapabilityProfile(
        profile_id="profile-1",
        account=binding or _binding(),
        currency_definition_fingerprint=currency_definition_fingerprint,
        trusted_clock=clock or _clock(),
        authenticated_raw_envelope=_raw_envelope_profile(),
        client_order_idempotency=idempotency or _idempotency(),
        auction_tif_cutoff=auction or _auction(),
        pagination_cursor_retention=pagination or _pagination(),
        execution_semantics=execution or _execution(),
        exit_rate_limit=_exit_rate(),
        credential_session_network_fencing=fencing or _fencing(),
        api_version_hashes=(_version("broker-api"),),
        sdk_version_hashes=(_version("broker-sdk"),),
        docs_version_hashes=(_version("broker-docs"),),
    )


# -- manifest proposal builder (mirrors migration helpers) ------------------


def enablement_proposal(
    profile: BrokerCapabilityProfile,
    **overrides: object,
) -> dict[str, object]:
    area = profile.area_hashes()
    values: dict[str, object] = {
        "manifest_id": "broker-enablement-1",
        "portfolio_id": "portfolio-1",
        "broker_account_id": profile.account.account_id,
        "issued_at": NOW,
        "expires_at": NOW + timedelta(hours=1),
        "one_shot": True,
        "issuer_id": "governance-broker",
        "issuer_capability": BROKER_CAPABILITY_VERSION,
        "schema_major": 2,
        "broker_account_fingerprint": area["broker_account_fingerprint"],
        "broker_environment_fingerprint": area["broker_environment_fingerprint"],
        "base_currency": profile.account.currency,
        "currency_definition_fingerprint": (
            profile.currency_definition_fingerprint
        ),
        "trusted_clock_hash": area["trusted_clock_hash"],
        "authenticated_raw_envelope_hash": area["authenticated_raw_envelope_hash"],
        "pagination_cursor_retention_hash": area[
            "pagination_cursor_retention_hash"
        ],
        "client_order_idempotency_hash": area["client_order_idempotency_hash"],
        "auction_tif_cutoff_hash": area["auction_tif_cutoff_hash"],
        "exit_rate_limit_hash": area["exit_rate_limit_hash"],
        "credential_session_network_fencing_hash": area[
            "credential_session_network_fencing_hash"
        ],
    }
    values.update(overrides)
    return values


def _attestations_at(
    preimage_hash: str, stamp: datetime
) -> tuple[dict[str, object], ...]:
    base = {
        "approved_manifest_preimage_hash": preimage_hash,
        "approval_capability": "governance.manifest.approve.v1",
        "approval_scope": "BROKER_ENABLEMENT_MANIFEST",
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


def approved_enablement_manifest(
    profile: BrokerCapabilityProfile,
    **overrides: object,
) -> BrokerEnablementManifest:
    proposal = enablement_proposal(profile, **overrides)
    preimage = BrokerEnablementManifest.approval_preimage_hash_for_proposal(
        proposal
    )
    payload = dict(proposal)
    payload["approval_attestations"] = _attestations_at(
        preimage, proposal["issued_at"]  # type: ignore[arg-type]
    )
    return BrokerEnablementManifest.model_validate(payload)


def _capability():
    from src.screening.offensive.v3.contracts import (
        Capability,
        ExecutionMode,
    )

    return Capability(
        artifact=ArtifactKind.BROKER_ENABLEMENT_MANIFEST,
        namespace=BROKER_NAMESPACE,
        mode=ExecutionMode.BROKER_CONFIRMED,
        schema_major=2,
        capability_version=BROKER_CAPABILITY_VERSION,
        scope="broker-enablement",
        valid_from=NOW - timedelta(days=1),
        valid_until=NOW + timedelta(days=30),
        revoked_at=None,
    )


def _fabric_and_key():
    key = Ed25519PrivateKey.generate()
    cap = _capability()
    fabric = TrustFabric(
        (
            make_issuer(
                key,
                cap,
                issuer_id="governance-broker",
                key_id="governance-broker-key-1",
            ),
        ),
        trusted_at=NOW,
    )
    return fabric, key, cap


def _signed_envelope(fabric, key, cap, manifest) -> object:
    return sign_payload(
        key,
        cap,
        issuer_id="governance-broker",
        key_id="governance-broker-key-1",
        payload=manifest.canonical_bytes(),
    )


def _verify(envelope, fabric, cap, profile, *, trusted_at=NOW):
    return verify_broker_enablement(
        envelope,
        profile=profile,
        verifier=fabric.verifier,
        current_head=fabric.head,
        required_capability=cap,
        trusted_at=trusted_at,
    )


# ===========================================================================
# profile-area fail-closed validation
# ===========================================================================


def test_idempotency_profile_rejects_unproven_scope() -> None:
    with pytest.raises(BrokerEnablementError) as excinfo:
        _idempotency(behavior=DuplicateCreateBehavior.UNPROVEN)
    assert excinfo.value.code == "IDEMPOTENCY_UNPROVEN"


def test_idempotency_profile_rejects_empty_scopes() -> None:
    with pytest.raises(BrokerEnablementError) as excinfo:
        certify_client_order_idempotency((), proven_at=NOW)
    assert excinfo.value.code == "IDEMPOTENCY_UNPROVEN"


def test_duplicate_create_behavior_must_be_explicit() -> None:
    assert DuplicateCreateBehavior.UNPROVEN not in {
        DuplicateCreateBehavior.IDEMPOTENT_REPLAY,
        DuplicateCreateBehavior.DUPLICATE_REJECT,
    }


def test_auction_profile_rejects_unsupported_empty() -> None:
    with pytest.raises(BrokerEnablementError) as excinfo:
        certify_auction_tif_cutoff(
            supported_order_types=(),
            supported_time_in_force=("DAY",),
            cutoff_semantics=CutoffSemantics.HARD_REJECT_AFTER,
            cutoff_instant_description="x",
            proven_at=NOW,
        )
    assert excinfo.value.code == "AUCTION_TIF_EMPTY"


def test_auction_profile_rejects_ambiguous_cutoff() -> None:
    with pytest.raises(BrokerEnablementError) as excinfo:
        certify_auction_tif_cutoff(
            supported_order_types=("LIMIT",),
            supported_time_in_force=("DAY",),
            cutoff_semantics=CutoffSemantics.SOFT_ACCEPT_UNKNOWN,
            cutoff_instant_description="x",
            proven_at=NOW,
        )
    assert excinfo.value.code == "CUTOFF_AMBIGUOUS"
    with pytest.raises(BrokerEnablementError) as excinfo:
        certify_auction_tif_cutoff(
            supported_order_types=("LIMIT",),
            supported_time_in_force=("DAY",),
            cutoff_semantics=CutoffSemantics.UNPROVEN,
            cutoff_instant_description="x",
            proven_at=NOW,
        )
    assert excinfo.value.code == "CUTOFF_AMBIGUOUS"


def test_auction_supports_check() -> None:
    auction = _auction()
    assert auction.supports(order_type="LIMIT", time_in_force="DAY")
    assert not auction.supports(order_type="STOP", time_in_force="DAY")
    assert not auction.supports(order_type="LIMIT", time_in_force="IOC")


def test_pagination_rejects_rollback_and_gap() -> None:
    with pytest.raises(BrokerEnablementError) as excinfo:
        certify_pagination_cursor_retention(
            page_count_proof=3,
            cursor_continuity=CursorContinuity.ROLLED_BACK,
            retention_calendar_days=30,
            proven_at=NOW,
        )
    assert excinfo.value.code == "PAGINATION_GAP"
    with pytest.raises(BrokerEnablementError) as excinfo:
        certify_pagination_cursor_retention(
            page_count_proof=3,
            cursor_continuity=CursorContinuity.GAPPED,
            retention_calendar_days=30,
            proven_at=NOW,
        )
    assert excinfo.value.code == "PAGINATION_GAP"


def test_pagination_rejects_short_retention() -> None:
    with pytest.raises(BrokerEnablementError) as excinfo:
        certify_pagination_cursor_retention(
            page_count_proof=3,
            cursor_continuity=CursorContinuity.CONTINUOUS_MONOTONE,
            retention_calendar_days=0,
            proven_at=NOW,
        )
    assert excinfo.value.code == "RETENTION_TOO_SHORT"


def test_clock_skew_exceeding_tolerance_rejected() -> None:
    with pytest.raises(BrokerEnablementError) as excinfo:
        _clock(max_observed_skew_ms=1000, tolerance_ms=500)
    assert excinfo.value.code == "CLOCK_SKEW_EXCEEDS_TOLERANCE"


def test_execution_rejects_dropped_and_unproven_late_fill() -> None:
    with pytest.raises(BrokerEnablementError) as excinfo:
        _execution(late_fill=LateFillSemantics.SILENTLY_DROPPED)
    assert excinfo.value.code == "LATE_FILL_DROPPED"
    with pytest.raises(BrokerEnablementError) as excinfo:
        _execution(late_fill=LateFillSemantics.UNPROVEN)
    assert excinfo.value.code == "LATE_FILL_UNPROVEN"


def test_fencing_rejects_non_revocable_egress_without_termination() -> None:
    with pytest.raises(BrokerEnablementError) as excinfo:
        _fencing(
            session_revocable=False,
            network_egress_revocable=False,
            termination_proof_required=False,
        )
    assert excinfo.value.code == "FENCING_UNPROVEN"


# ===========================================================================
# verify_broker_enablement: happy path + window + tamper
# ===========================================================================


def test_valid_signed_manifest_verifies_and_binds_profile() -> None:
    profile = _profile()
    fabric, key, cap = _fabric_and_key()
    manifest = approved_enablement_manifest(profile)
    envelope = _signed_envelope(fabric, key, cap, manifest)
    result = _verify(envelope, fabric, cap, profile)
    assert isinstance(result, VerifiedBrokerEnablement)
    assert result.manifest.artifact_hash() == manifest.artifact_hash()
    assert result.verified_issuer.issuer_id == "governance-broker"
    assert result.activation_window == (manifest.issued_at, manifest.expires_at)
    assert result.profile.profile_id == "profile-1"


def test_tampered_payload_rejected() -> None:
    profile = _profile()
    fabric, key, cap = _fabric_and_key()
    manifest = approved_enablement_manifest(profile)
    envelope = _signed_envelope(fabric, key, cap, manifest)
    # Flip one payload byte at the byte level (bypassing the manifest's
    # two-person preimage binding) and recompute the payload hash. The
    # signature still covers the original payload hash, so the trust chain
    # rejects the tampered envelope.
    original: bytes = envelope.payload  # type: ignore[union-attr]
    tampered = original[:-1] + bytes([original[-1] ^ 0x01])
    forged = _signed_envelope(fabric, key, cap, manifest)
    object.__setattr__(forged, "payload", tampered)
    object.__setattr__(
        forged, "payload_hash", hashlib.sha256(tampered).hexdigest()
    )
    with pytest.raises(TrustVerificationError):
        _verify(forged, fabric, cap, profile)


def test_window_inactive_rejected() -> None:
    profile = _profile()
    fabric, key, cap = _fabric_and_key()
    manifest = approved_enablement_manifest(profile)
    envelope = _signed_envelope(fabric, key, cap, manifest)
    with pytest.raises(BrokerEnablementError) as excinfo:
        _verify(
            envelope, fabric, cap, profile, trusted_at=NOW + timedelta(hours=2)
        )
    assert excinfo.value.code == "ENABLEMENT_WINDOW_INACTIVE"


# ===========================================================================
# account / environment / currency / area binding mismatches
# ===========================================================================


def test_account_mismatch_rejected() -> None:
    profile = _profile()
    fabric, key, cap = _fabric_and_key()
    manifest = approved_enablement_manifest(profile)
    envelope = _signed_envelope(fabric, key, cap, manifest)
    other = _profile(binding=_binding(account_id="acct-999"))
    with pytest.raises(BrokerEnablementError) as excinfo:
        _verify(envelope, fabric, cap, other)
    assert excinfo.value.code == "ACCOUNT_MISMATCH"


def test_environment_mismatch_rejected() -> None:
    profile = _profile()
    fabric, key, cap = _fabric_and_key()
    manifest = approved_enablement_manifest(profile)
    envelope = _signed_envelope(fabric, key, cap, manifest)
    other = _profile(binding=_binding(environment="production"))
    with pytest.raises(BrokerEnablementError) as excinfo:
        _verify(envelope, fabric, cap, other)
    assert excinfo.value.code == "ENVIRONMENT_MISMATCH"


def test_currency_mismatch_rejected() -> None:
    profile = _profile()
    fabric, key, cap = _fabric_and_key()
    manifest = approved_enablement_manifest(profile)
    envelope = _signed_envelope(fabric, key, cap, manifest)
    other = _profile(binding=_binding(currency="USD"))
    with pytest.raises(BrokerEnablementError) as excinfo:
        _verify(envelope, fabric, cap, other)
    assert excinfo.value.code == "CURRENCY_MISMATCH"


def test_endpoint_mismatch_rejected() -> None:
    profile = _profile()
    fabric, key, cap = _fabric_and_key()
    manifest = approved_enablement_manifest(profile)
    envelope = _signed_envelope(fabric, key, cap, manifest)
    other = _profile(binding=_binding(endpoint="b" * 64))
    with pytest.raises(BrokerEnablementError) as excinfo:
        _verify(envelope, fabric, cap, other)
    assert excinfo.value.code == "ACCOUNT_MISMATCH"


def test_idempotency_area_mismatch_rejected() -> None:
    profile = _profile()
    fabric, key, cap = _fabric_and_key()
    manifest = approved_enablement_manifest(profile)
    envelope = _signed_envelope(fabric, key, cap, manifest)
    other = _profile(
        idempotency=_idempotency(
            behavior=DuplicateCreateBehavior.DUPLICATE_REJECT
        )
    )
    with pytest.raises(BrokerEnablementError) as excinfo:
        _verify(envelope, fabric, cap, other)
    assert excinfo.value.code == "IDEMPOTENCY_MISMATCH"


def test_auction_area_mismatch_rejected() -> None:
    profile = _profile()
    fabric, key, cap = _fabric_and_key()
    manifest = approved_enablement_manifest(profile)
    envelope = _signed_envelope(fabric, key, cap, manifest)
    other = _profile(
        auction=AuctionTifCutoffProfile(
            supported_order_types=tuple(sorted({"MARKET"})),
            supported_time_in_force=tuple(sorted({"DAY"})),
            cutoff_semantics=CutoffSemantics.HARD_REJECT_AFTER,
            cutoff_instant_description="x",
            proven_at=NOW,
        )
    )
    with pytest.raises(BrokerEnablementError) as excinfo:
        _verify(envelope, fabric, cap, other)
    assert excinfo.value.code == "AUCTION_TIF_CUTOFF_MISMATCH"


def test_pagination_area_mismatch_rejected() -> None:
    profile = _profile()
    fabric, key, cap = _fabric_and_key()
    manifest = approved_enablement_manifest(profile)
    envelope = _signed_envelope(fabric, key, cap, manifest)
    other = _profile(
        pagination=PaginationCursorRetentionProfile(
            page_count_proof=4,
            cursor_continuity=CursorContinuity.CONTINUOUS_MONOTONE,
            retention_calendar_days=30,
            proven_at=NOW,
        )
    )
    with pytest.raises(BrokerEnablementError) as excinfo:
        _verify(envelope, fabric, cap, other)
    assert excinfo.value.code == "PAGINATION_MISMATCH"


def test_clock_area_mismatch_rejected() -> None:
    profile = _profile()
    fabric, key, cap = _fabric_and_key()
    manifest = approved_enablement_manifest(profile)
    envelope = _signed_envelope(fabric, key, cap, manifest)
    other = _profile(
        clock=TrustedClockProfile(
            max_observed_skew_ms=10,
            tolerance_ms=500,
            proven_at=NOW,
        )
    )
    with pytest.raises(BrokerEnablementError) as excinfo:
        _verify(envelope, fabric, cap, other)
    assert excinfo.value.code == "TRUSTED_CLOCK_MISMATCH"


def test_currency_definition_mismatch_rejected() -> None:
    profile = _profile()
    fabric, key, cap = _fabric_and_key()
    manifest = approved_enablement_manifest(profile)
    envelope = _signed_envelope(fabric, key, cap, manifest)
    other = _profile(currency_definition_fingerprint=HASH_B)
    with pytest.raises(BrokerEnablementError) as excinfo:
        _verify(envelope, fabric, cap, other)
    assert excinfo.value.code == "CURRENCY_DEFINITION_MISMATCH"


# ===========================================================================
# production adapter stays disabled until a bound profile loads
# ===========================================================================


def test_production_adapter_requires_verified_enablement() -> None:
    from src.screening.offensive.v3.broker.adapters.production import (
        ProductionAdapterError,
        ProductionBrokerAdapter,
    )

    # Even with a fully-proven profile, no verified enablement has been
    # presented at construction -> the adapter stays disabled.
    profile = _profile()
    with pytest.raises(ProductionAdapterError) as excinfo:
        ProductionBrokerAdapter.from_profile(profile)
    assert excinfo.value.code == "BROKER_ADAPTER_NOT_CERTIFIED"
