"""Shared trial-identity and shadow-policy-provenance contracts.

These types are owned in one place so the decision core, the durable arm
decision store, the proxy adapters and the evaluator all refer to the same
``TrialArm`` and the same discriminated ``ShadowPolicyBinding``.

A ``ShadowPolicyBinding`` is a strict union: the Champion arm binds the trial's
baseline policy activation plus its ``PolicySnapshot``; the Challenger arm binds
the target policy registration plus its ``PolicySnapshot``. Both freeze the
policy snapshot hash, the policy fingerprint, the source kind and the source
hash, but neither is an activation token and neither grants execution authority.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from .base import CanonicalModel, Sha256


class TrialArm(StrEnum):
    """The two arms of one paired trial; one TrialManifest already binds both."""

    CHAMPION = "CHAMPION"
    CHALLENGER = "CHALLENGER"


class ShadowPolicySourceKind(StrEnum):
    """Which sealed governance artifact a shadow policy binding refers to."""

    BASELINE_POLICY_ACTIVATION = "BASELINE_POLICY_ACTIVATION"
    TARGET_POLICY_REGISTRATION = "TARGET_POLICY_REGISTRATION"


class BaselineShadowPolicyBinding(CanonicalModel):
    """Champion binding: the trial's baseline policy activation + snapshot."""

    source_kind: Literal[ShadowPolicySourceKind.BASELINE_POLICY_ACTIVATION]
    baseline_policy_activation_hash: Sha256
    policy_snapshot_hash: Sha256
    policy_fingerprint: Sha256


class TargetShadowPolicyBinding(CanonicalModel):
    """Challenger binding: the target policy registration + snapshot."""

    source_kind: Literal[ShadowPolicySourceKind.TARGET_POLICY_REGISTRATION]
    target_policy_registration_hash: Sha256
    policy_snapshot_hash: Sha256
    policy_fingerprint: Sha256


#: Discriminated union; the ``source_kind`` field selects the variant.
ShadowPolicyBinding = Annotated[
    BaselineShadowPolicyBinding | TargetShadowPolicyBinding,
    Field(discriminator="source_kind"),
]


__all__ = [
    "BaselineShadowPolicyBinding",
    "ShadowPolicyBinding",
    "ShadowPolicySourceKind",
    "TargetShadowPolicyBinding",
    "TrialArm",
]
