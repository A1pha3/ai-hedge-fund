"""Fifth-review regression for the Task 4 policy verifier dispatch boundary."""

from __future__ import annotations

from base64 import b64encode
from typing import Any

from tests.offensive.v3.contracts.test_policy import (
    NOW,
    _current_trust_head,
    _signed_policy_activation,
)


def test_policy_activation_uses_base_capability_verifier_dispatch() -> None:
    from src.screening.offensive.v3 import policy as policy_api
    from src.screening.offensive.v3 import trust

    policy, _, signed, required, verifier = _signed_policy_activation()
    current_head = _current_trust_head(verifier)
    genuinely_verified = trust.CapabilityVerifier.verify(
        verifier,
        signed,
        required,
        current_head=current_head,
        trusted_at=NOW,
    )
    forged_issuer = trust.VerifiedIssuer.model_validate(
        genuinely_verified.model_dump(mode="python", round_trip=True),
        strict=True,
    )
    invalid_signed = signed.model_copy(
        update={"signature": b64encode(b"\0" * 64).decode("ascii")}
    )
    wrong_current_head = current_head.model_copy(
        update={"active_trust_bundle_hash": "f" * 64}
    )
    shadow_called = False

    def forge_verification(*args: Any, **kwargs: Any) -> Any:
        nonlocal shadow_called
        shadow_called = True
        return forged_issuer

    verifier.verify = forge_verification
    verification_error: policy_api.PolicyActivationVerificationError | None = None
    verified_candidate: Any | None = None
    try:
        verified_candidate = policy_api.verify_policy_activation(
            invalid_signed,
            policy,
            verifier,
            required,
            current_trust_head=wrong_current_head,
            trusted_at=NOW,
            predecessor=None,
            expected_portfolio_id="paper-v3",
            expected_broker_account_id="manual-account-1",
            expected_broker_account_fingerprint=None,
            expected_mode=trust.ExecutionMode.MANUAL_CONFIRMED,
        )
    except policy_api.PolicyActivationVerificationError as exc:
        verification_error = exc

    assert verification_error is not None
    assert "current head" in str(verification_error) or "signature" in str(
        verification_error
    )
    assert shadow_called is False
    assert verified_candidate is None
