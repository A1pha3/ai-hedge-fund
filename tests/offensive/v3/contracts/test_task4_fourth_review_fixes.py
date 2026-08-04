"""Fourth-review regressions for the Task 4 nested trust boundary."""

from __future__ import annotations

from base64 import b64encode
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from tests.offensive.v3.contracts.test_trust_registry import (
    NOW,
    _api,
    _capability,
    _current_head,
    _issuer,
    _root_verified_bundle,
    _signed,
)


def _invalid_root_signature_context() -> tuple[Any, ...]:
    api = _api()
    issuer_key = Ed25519PrivateKey.generate()
    required = _capability(api)
    issuer = _issuer(api, issuer_key, required)
    signed = _signed(api, issuer_key, required)
    trust_verifier, signed_chain = _root_verified_bundle(
        api,
        api.TrustedRegistry(issuers=(issuer,)),
        return_context=True,
    )
    invalid_chain = (
        signed_chain[0].model_copy(
            update={"signature": b64encode(b"\0" * 64).decode("ascii")}
        ),
    )
    return api, required, signed, trust_verifier, invalid_chain


def test_capability_verifier_rejects_inner_subclass_before_root_override_dispatch() -> (
    None
):
    api, required, signed, trust_verifier, invalid_chain = (
        _invalid_root_signature_context()
    )

    class ForgingTrustVerifier(api.TrustBundleVerifier):
        override_called = False

        def verify_chain(
            self,
            signed_chain: tuple[Any, ...],
            *,
            trusted_at: Any,
        ) -> Any:
            self.override_called = True
            candidate = signed_chain[-1]
            return api.VerifiedTrustBundle(
                bundle=candidate.bundle,
                registry=candidate.registry,
                trusted_at=trusted_at,
            )

    forged_inner = ForgingTrustVerifier(trust_verifier._root_anchors)
    constructor_error: TypeError | None = None
    verified: Any | None = None
    try:
        verifier = api.CapabilityVerifier(forged_inner, invalid_chain)
    except TypeError as exc:
        constructor_error = exc
    else:
        verified = verifier.verify(
            signed,
            required,
            current_head=_current_head(api, verifier),
            trusted_at=NOW,
        )

    assert constructor_error is not None
    assert "exact TrustBundleVerifier" in str(constructor_error)
    assert forged_inner.override_called is False
    assert verified is None


def test_exact_inner_verifier_rejects_invalid_root_signature() -> None:
    api, required, signed, trust_verifier, invalid_chain = (
        _invalid_root_signature_context()
    )
    verifier = api.CapabilityVerifier(trust_verifier, invalid_chain)

    with pytest.raises(api.TrustVerificationError, match="root signature"):
        verifier.verify(
            signed,
            required,
            current_head=_current_head(api, verifier),
            trusted_at=NOW,
        )


def test_capability_verifier_uses_base_root_chain_dispatch() -> None:
    api, required, signed, trust_verifier, invalid_chain = (
        _invalid_root_signature_context()
    )
    override_called = False

    def forge_chain(
        signed_chain: tuple[Any, ...],
        *,
        trusted_at: Any,
    ) -> Any:
        nonlocal override_called
        override_called = True
        candidate = signed_chain[-1]
        return api.VerifiedTrustBundle(
            bundle=candidate.bundle,
            registry=candidate.registry,
            trusted_at=trusted_at,
        )

    trust_verifier.verify_chain = forge_chain
    verifier = api.CapabilityVerifier(trust_verifier, invalid_chain)

    with pytest.raises(api.TrustVerificationError, match="root signature"):
        verifier.verify(
            signed,
            required,
            current_head=_current_head(api, verifier),
            trusted_at=NOW,
        )
    assert override_called is False


def test_trust_bundle_verifier_uses_base_helper_dispatch() -> None:
    api, _, _, trust_verifier, invalid_chain = _invalid_root_signature_context()
    verify_link_called = False
    root_lookup_called = False

    def forge_link(
        signed: Any,
        *,
        predecessor: Any | None,
    ) -> Any:
        nonlocal verify_link_called
        verify_link_called = True
        return api.VerifiedTrustBundle(
            bundle=signed.bundle,
            registry=signed.registry,
            trusted_at=signed.bundle.issued_at,
        )

    def replace_root_lookup(bundle: Any) -> Any:
        nonlocal root_lookup_called
        root_lookup_called = True
        return trust_verifier._root_anchors[0]

    trust_verifier._verify_link = forge_link
    trust_verifier._root_anchor_for = replace_root_lookup

    with pytest.raises(api.TrustVerificationError, match="root signature"):
        trust_verifier.verify_chain(invalid_chain, trusted_at=NOW)
    assert verify_link_called is False
    assert root_lookup_called is False
