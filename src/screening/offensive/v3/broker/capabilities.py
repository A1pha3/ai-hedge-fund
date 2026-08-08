"""Plan 07 Task 2: broker capability certification and enablement gate.

A production broker adapter may start only when a frozen
``BrokerCapabilityProfile`` — the proven account binding, idempotency,
auction/TIF/cutoff, pagination/cursor/retention, clock, execution, rate,
and fencing semantics — is bound field-for-field by a signed
``BrokerEnablementManifest`` (Plan 03). ``verify_broker_enablement()`` is
the single fail-closed gate: it runs the full ``CapabilityVerifier``
chain, re-parses the manifest, checks the activation window, and then
cross-checks every manifest-bound hash against the presented profile.

Certification (``certify_profile`` and the per-area ``certify_*``
helpers) is a plain function layer, not pydantic validators: semantic
fail-closed checks raise ``BrokerEnablementError(code)`` directly so the
machine-readable code survives. The pydantic sub-profiles are structural
only. The certification probes (``scripts/v3_broker_certify.py``) are
read-only by default; any sandbox/order mutation requires an explicit
signed approval. Redacted raw envelopes and exact API/SDK/docs version
hashes are stored so the profile is reproducible.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Literal

from pydantic import Field, StringConstraints

from src.screening.offensive.v3.broker.ports import BrokerAccountBinding
from src.screening.offensive.v3.contracts import (
    CanonicalModel,
    Capability,
    CurrentTrustHeadWitness,
    Sha256,
    SignedEnvelope,
    UtcInstant,
    VerifiedIssuer,
    content_hash,
    domain_hash,
)
from src.screening.offensive.v3.contracts.governance import (
    BrokerEnablementManifest,
)
from src.screening.offensive.v3.trust import (
    CapabilityVerifier,
    TrustVerificationError,
)

NonEmptyStr = Annotated[str, StringConstraints(min_length=1, pattern=r".*\S.*")]
PositiveInt = Annotated[int, Field(ge=1)]


class BrokerEnablementError(ValueError):
    """Enablement/certification failure with a stable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


class DuplicateCreateBehavior(StrEnum):
    """Proven broker behavior on a duplicate ``client_order_id`` create."""

    IDEMPOTENT_REPLAY = "idempotent_replay"
    DUPLICATE_REJECT = "duplicate_reject"
    UNPROVEN = "unproven"


class CutoffSemantics(StrEnum):
    """How the broker treats the order cutoff boundary."""

    HARD_REJECT_AFTER = "hard_reject_after"
    SOFT_ACCEPT_UNKNOWN = "soft_accept_unknown"
    UNPROVEN = "unproven"


class CursorContinuity(StrEnum):
    """Proven continuity of a paginated query cursor."""

    CONTINUOUS_MONOTONE = "continuous_monotone"
    GAPPED = "gapped"
    ROLLED_BACK = "rolled_back"
    UNPROVEN = "unproven"


class LateFillSemantics(StrEnum):
    """Proven handling of fills arriving after a terminal cancel/expire."""

    APPENDS_INVERSE_OR_DELTA = "appends_inverse_or_delta"
    SILENTLY_DROPPED = "silently_dropped"
    UNPROVEN = "unproven"


class VersionHash(CanonicalModel):
    """A pinned external dependency version with its source hash."""

    name: NonEmptyStr
    version: NonEmptyStr
    source_hash: Sha256


# ---------------------------------------------------------------------------
# structural sub-profiles (certification checks live in certify_* below)
# ---------------------------------------------------------------------------


class _HashedModel(CanonicalModel):
    """Base for a sub-profile that hashes under a fixed domain."""

    HASH_DOMAIN: ClassVar[str]

    def content_hash(self) -> str:
        return domain_hash(self.HASH_DOMAIN, 2, self)


class TrustedClockProfile(_HashedModel):
    HASH_DOMAIN: ClassVar[str] = (
        "ai-hedge-fund.v3.broker.capability.trusted-clock.v1"
    )

    max_observed_skew_ms: PositiveInt
    tolerance_ms: PositiveInt
    proven_at: UtcInstant


class AuthenticatedRawEnvelopeProfile(_HashedModel):
    HASH_DOMAIN: ClassVar[str] = (
        "ai-hedge-fund.v3.broker.capability.authenticated-raw-envelope.v1"
    )

    parser_version: NonEmptyStr
    auth_mechanism: NonEmptyStr
    redacted_secret_fields: tuple[NonEmptyStr, ...]


class IdempotencyScope(_HashedModel):
    HASH_DOMAIN: ClassVar[str] = (
        "ai-hedge-fund.v3.broker.capability.idempotency-scope.v1"
    )

    trading_day_scope: NonEmptyStr
    duplicate_create_behavior: DuplicateCreateBehavior


class ClientOrderIdempotencyProfile(_HashedModel):
    HASH_DOMAIN: ClassVar[str] = (
        "ai-hedge-fund.v3.broker.capability.client-order-idempotency.v1"
    )

    scopes: tuple[IdempotencyScope, ...]
    proven_at: UtcInstant

    def behavior_for(self, trading_day_scope: str) -> DuplicateCreateBehavior:
        for scope in self.scopes:
            if scope.trading_day_scope == trading_day_scope:
                return scope.duplicate_create_behavior
        return DuplicateCreateBehavior.UNPROVEN


class AuctionTifCutoffProfile(_HashedModel):
    HASH_DOMAIN: ClassVar[str] = (
        "ai-hedge-fund.v3.broker.capability.auction-tif-cutoff.v1"
    )

    supported_order_types: tuple[NonEmptyStr, ...]
    supported_time_in_force: tuple[NonEmptyStr, ...]
    cutoff_semantics: CutoffSemantics
    cutoff_instant_description: NonEmptyStr
    proven_at: UtcInstant

    def supports(self, *, order_type: str, time_in_force: str) -> bool:
        return (
            order_type in self.supported_order_types
            and time_in_force in self.supported_time_in_force
        )


class PaginationCursorRetentionProfile(_HashedModel):
    HASH_DOMAIN: ClassVar[str] = (
        "ai-hedge-fund.v3.broker.capability.pagination-cursor-retention.v1"
    )

    page_count_proof: PositiveInt
    cursor_continuity: CursorContinuity
    retention_calendar_days: PositiveInt
    proven_at: UtcInstant


class ExecutionSemanticsProfile(_HashedModel):
    HASH_DOMAIN: ClassVar[str] = (
        "ai-hedge-fund.v3.broker.capability.execution-semantics.v1"
    )

    partial_fill_supported: bool
    cancel_semantics: NonEmptyStr
    expiry_semantics: NonEmptyStr
    late_fill_semantics: LateFillSemantics
    proven_at: UtcInstant


class ExitRateLimitProfile(_HashedModel):
    HASH_DOMAIN: ClassVar[str] = (
        "ai-hedge-fund.v3.broker.capability.exit-rate-limit.v1"
    )

    exit_budget_per_minute: PositiveInt
    query_budget_per_minute: PositiveInt
    independent_buckets: Literal[True] = True


class CredentialSessionNetworkFencingProfile(_HashedModel):
    HASH_DOMAIN: ClassVar[str] = (
        "ai-hedge-fund.v3.broker.capability.credential-session-network-fencing.v1"
    )

    session_revocable: bool
    network_egress_revocable: bool
    termination_proof_required: bool


class BrokerCapabilityProfile(CanonicalModel):
    """One frozen, fully-proven broker capability profile."""

    HASH_DOMAIN: ClassVar[str] = (
        "ai-hedge-fund.v3.broker.capability.profile.v1"
    )

    profile_id: NonEmptyStr
    account: BrokerAccountBinding
    currency_definition_fingerprint: Sha256
    trusted_clock: TrustedClockProfile
    authenticated_raw_envelope: AuthenticatedRawEnvelopeProfile
    client_order_idempotency: ClientOrderIdempotencyProfile
    auction_tif_cutoff: AuctionTifCutoffProfile
    pagination_cursor_retention: PaginationCursorRetentionProfile
    execution_semantics: ExecutionSemanticsProfile
    exit_rate_limit: ExitRateLimitProfile
    credential_session_network_fencing: CredentialSessionNetworkFencingProfile
    api_version_hashes: tuple[VersionHash, ...]
    sdk_version_hashes: tuple[VersionHash, ...]
    docs_version_hashes: tuple[VersionHash, ...]

    def account_fingerprint(self) -> str:
        """Account identity, environment-agnostic.

        The manifest pins account and environment as distinct fields; the
        account fingerprint binds account id, currency, and endpoint while
        ``environment_fingerprint`` independently binds the deployment
        environment, so each manifest field is checkable in isolation.
        """

        return content_hash(
            {
                "account_id": self.account.account_id,
                "currency": self.account.currency,
                "endpoint_fingerprint": self.account.endpoint_fingerprint,
            }
        )

    def environment_fingerprint(self) -> str:
        return content_hash({"environment": self.account.environment})

    def area_hashes(self) -> dict[str, str]:
        """Map every manifest-bound area name to its proven hash."""

        return {
            "broker_account_fingerprint": self.account_fingerprint(),
            "broker_environment_fingerprint": self.environment_fingerprint(),
            "currency_definition_fingerprint": (
                self.currency_definition_fingerprint
            ),
            "trusted_clock_hash": self.trusted_clock.content_hash(),
            "authenticated_raw_envelope_hash": (
                self.authenticated_raw_envelope.content_hash()
            ),
            "pagination_cursor_retention_hash": (
                self.pagination_cursor_retention.content_hash()
            ),
            "client_order_idempotency_hash": (
                self.client_order_idempotency.content_hash()
            ),
            "auction_tif_cutoff_hash": (
                self.auction_tif_cutoff.content_hash()
            ),
            "exit_rate_limit_hash": self.exit_rate_limit.content_hash(),
            "credential_session_network_fencing_hash": (
                self.credential_session_network_fencing.content_hash()
            ),
        }

    def profile_hash(self) -> str:
        return domain_hash(self.HASH_DOMAIN, 2, self)


# ---------------------------------------------------------------------------
# certification: plain-function fail-closed checks (codes survive)
# ---------------------------------------------------------------------------


def certify_trusted_clock(
    *,
    max_observed_skew_ms: int,
    tolerance_ms: int,
    proven_at: datetime,
) -> TrustedClockProfile:
    if max_observed_skew_ms > tolerance_ms:
        raise BrokerEnablementError(
            "CLOCK_SKEW_EXCEEDS_TOLERANCE",
            f"observed {max_observed_skew_ms}ms > tolerance {tolerance_ms}ms",
        )
    return TrustedClockProfile(
        max_observed_skew_ms=max_observed_skew_ms,
        tolerance_ms=tolerance_ms,
        proven_at=proven_at,
    )


def certify_client_order_idempotency(
    scopes: tuple[IdempotencyScope, ...],
    *,
    proven_at: datetime,
) -> ClientOrderIdempotencyProfile:
    if not scopes:
        raise BrokerEnablementError(
            "IDEMPOTENCY_UNPROVEN", "no client-order-id scope certified"
        )
    for scope in scopes:
        if scope.duplicate_create_behavior is DuplicateCreateBehavior.UNPROVEN:
            raise BrokerEnablementError(
                "IDEMPOTENCY_UNPROVEN",
                f"scope {scope.trading_day_scope!r} duplicate behavior unproven",
            )
    return ClientOrderIdempotencyProfile(scopes=scopes, proven_at=proven_at)


def certify_auction_tif_cutoff(
    *,
    supported_order_types: tuple[str, ...],
    supported_time_in_force: tuple[str, ...],
    cutoff_semantics: CutoffSemantics,
    cutoff_instant_description: str,
    proven_at: datetime,
) -> AuctionTifCutoffProfile:
    if not supported_order_types or not supported_time_in_force:
        raise BrokerEnablementError(
            "AUCTION_TIF_EMPTY",
            "at least one order type and TIF must be supported",
        )
    if cutoff_semantics in {
        CutoffSemantics.UNPROVEN,
        CutoffSemantics.SOFT_ACCEPT_UNKNOWN,
    }:
        raise BrokerEnablementError(
            "CUTOFF_AMBIGUOUS",
            f"cutoff semantics {cutoff_semantics.value!r} not enableable",
        )
    return AuctionTifCutoffProfile(
        supported_order_types=tuple(sorted(supported_order_types)),
        supported_time_in_force=tuple(sorted(supported_time_in_force)),
        cutoff_semantics=cutoff_semantics,
        cutoff_instant_description=cutoff_instant_description,
        proven_at=proven_at,
    )


def certify_pagination_cursor_retention(
    *,
    page_count_proof: int,
    cursor_continuity: CursorContinuity,
    retention_calendar_days: int,
    proven_at: datetime,
) -> PaginationCursorRetentionProfile:
    if cursor_continuity is not CursorContinuity.CONTINUOUS_MONOTONE:
        raise BrokerEnablementError(
            "PAGINATION_GAP",
            f"cursor continuity is {cursor_continuity.value},"
            " not continuous_monotone",
        )
    if retention_calendar_days < 1:
        raise BrokerEnablementError(
            "RETENTION_TOO_SHORT",
            "retention window must cover at least one calendar day",
        )
    return PaginationCursorRetentionProfile(
        page_count_proof=page_count_proof,
        cursor_continuity=cursor_continuity,
        retention_calendar_days=retention_calendar_days,
        proven_at=proven_at,
    )


def certify_execution_semantics(
    *,
    partial_fill_supported: bool,
    cancel_semantics: str,
    expiry_semantics: str,
    late_fill_semantics: LateFillSemantics,
    proven_at: datetime,
) -> ExecutionSemanticsProfile:
    if late_fill_semantics is LateFillSemantics.UNPROVEN:
        raise BrokerEnablementError(
            "LATE_FILL_UNPROVEN",
            "late-fill semantics must be proven before enablement",
        )
    if late_fill_semantics is LateFillSemantics.SILENTLY_DROPPED:
        raise BrokerEnablementError(
            "LATE_FILL_DROPPED",
            "a broker that silently drops late fills cannot be enabled",
        )
    return ExecutionSemanticsProfile(
        partial_fill_supported=partial_fill_supported,
        cancel_semantics=cancel_semantics,
        expiry_semantics=expiry_semantics,
        late_fill_semantics=late_fill_semantics,
        proven_at=proven_at,
    )


def certify_credential_session_network_fencing(
    *,
    session_revocable: bool,
    network_egress_revocable: bool,
    termination_proof_required: bool,
) -> CredentialSessionNetworkFencingProfile:
    if not network_egress_revocable:
        raise BrokerEnablementError(
            "FENCING_UNPROVEN", "network egress must be revocable"
        )
    if not session_revocable and not termination_proof_required:
        raise BrokerEnablementError(
            "FENCING_UNPROVEN",
            "non-revocable session requires termination proof",
        )
    return CredentialSessionNetworkFencingProfile(
        session_revocable=session_revocable,
        network_egress_revocable=network_egress_revocable,
        termination_proof_required=termination_proof_required,
    )


# ---------------------------------------------------------------------------
# enablement verification gate
# ---------------------------------------------------------------------------


class VerifiedBrokerEnablement(CanonicalModel):
    """A verified enablement: manifest + profile + issuer + window."""

    manifest: BrokerEnablementManifest
    profile: BrokerCapabilityProfile
    verified_issuer: VerifiedIssuer
    activation_window: tuple[UtcInstant, UtcInstant]


_MANIFEST_HASH_FIELDS: tuple[str, ...] = (
    "broker_account_fingerprint",
    "broker_environment_fingerprint",
    "base_currency",
    "currency_definition_fingerprint",
    "trusted_clock_hash",
    "authenticated_raw_envelope_hash",
    "pagination_cursor_retention_hash",
    "client_order_idempotency_hash",
    "auction_tif_cutoff_hash",
    "exit_rate_limit_hash",
    "credential_session_network_fencing_hash",
)

_AREA_CODES: dict[str, str] = {
    "broker_account_fingerprint": "ACCOUNT_MISMATCH",
    "broker_environment_fingerprint": "ENVIRONMENT_MISMATCH",
    "currency_definition_fingerprint": "CURRENCY_DEFINITION_MISMATCH",
    "trusted_clock_hash": "TRUSTED_CLOCK_MISMATCH",
    "authenticated_raw_envelope_hash": "RAW_ENVELOPE_MISMATCH",
    "pagination_cursor_retention_hash": "PAGINATION_MISMATCH",
    "client_order_idempotency_hash": "IDEMPOTENCY_MISMATCH",
    "auction_tif_cutoff_hash": "AUCTION_TIF_CUTOFF_MISMATCH",
    "exit_rate_limit_hash": "EXIT_RATE_LIMIT_MISMATCH",
    "credential_session_network_fencing_hash": "FENCING_MISMATCH",
}


def verify_broker_enablement(
    envelope: SignedEnvelope,
    *,
    profile: BrokerCapabilityProfile,
    verifier: CapabilityVerifier,
    current_head: CurrentTrustHeadWitness,
    required_capability: Capability,
    trusted_at: datetime,
) -> VerifiedBrokerEnablement:
    """Fail-closed enablement gate.

    1. Full ``CapabilityVerifier`` chain (registry, role boundary, lifecycle,
       Ed25519 signature, payload hash).
    2. Strict re-parse as ``BrokerEnablementManifest``.
    3. Activation window: ``issued_at <= trusted_at <= expires_at``.
    4. Account/currency/area binding: every manifest hash field must equal
       the corresponding proven profile area; any drift is rejected with a
       code naming the offending area.
    5. Umbrella binding (audit Vuln1): the manifest's overall ``profile_hash``
       must equal the profile's own hash, so fields not covered by a named
       area (execution_semantics / *_version_hashes / profile_id) cannot
       drift either. Checked after the area loop so a named-area drift keeps
       its precise diagnostic code.
    """

    verified = verifier.verify(
        envelope,
        required_capability,
        current_head=current_head,
        trusted_at=trusted_at,
    )
    try:
        manifest = BrokerEnablementManifest.model_validate_json(
            envelope.payload
        )
    except ValueError as exc:
        raise TrustVerificationError(
            f"broker enablement payload is not a valid manifest: {exc}"
        ) from exc
    if not (manifest.issued_at <= trusted_at <= manifest.expires_at):
        raise BrokerEnablementError(
            "ENABLEMENT_WINDOW_INACTIVE",
            "trusted_at outside manifest validity window",
        )

    if manifest.base_currency != profile.account.currency:
        raise BrokerEnablementError(
            "CURRENCY_MISMATCH",
            f"manifest base_currency {manifest.base_currency!r} != profile"
            f" currency {profile.account.currency!r}",
        )

    area_hashes = profile.area_hashes()
    for field_name in _MANIFEST_HASH_FIELDS:
        if field_name == "base_currency":
            continue
        manifest_value = getattr(manifest, field_name)
        profile_value = area_hashes.get(field_name)
        if profile_value is None:
            raise BrokerEnablementError(
                "PROFILE_AREA_MISSING",
                f"profile does not cover manifest field {field_name!r}",
            )
        if manifest_value != profile_value:
            raise BrokerEnablementError(
                _AREA_CODES.get(field_name, "AREA_MISMATCH"),
                f"manifest {field_name!r} does not match the proven profile",
            )

    if manifest.profile_hash != profile.profile_hash():
        raise BrokerEnablementError(
            "PROFILE_HASH_MISMATCH",
            "manifest profile_hash does not match the proven profile; a"
            " profile field outside the named areas (execution_semantics,"
            " version hashes, profile_id) has drifted",
        )

    return VerifiedBrokerEnablement(
        manifest=manifest,
        profile=profile,
        verified_issuer=verified,
        activation_window=(manifest.issued_at, manifest.expires_at),
    )


def _area_mismatch_code(field_name: str) -> str:
    return _AREA_CODES.get(field_name, "AREA_MISMATCH")
