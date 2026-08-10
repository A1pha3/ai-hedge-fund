"""Contract tests for the shared trial-identity and shadow-policy bindings."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from src.screening.offensive.v3.contracts.trial import (
    BaselineShadowPolicyBinding,
    ShadowPolicyBinding,
    ShadowPolicySourceKind,
    TargetShadowPolicyBinding,
    TrialArm,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64

_BINDING_ADAPTER = TypeAdapter(ShadowPolicyBinding)


def test_trial_arm_has_exact_two_arm_values() -> None:
    assert [arm.value for arm in TrialArm] == ["CHAMPION", "CHALLENGER"]


def test_shadow_policy_source_kind_has_exact_values() -> None:
    assert [kind.value for kind in ShadowPolicySourceKind] == [
        "BASELINE_POLICY_ACTIVATION",
        "TARGET_POLICY_REGISTRATION",
    ]


def test_baseline_binding_round_trips_and_carries_activation_hash() -> None:
    binding = BaselineShadowPolicyBinding(
        source_kind=ShadowPolicySourceKind.BASELINE_POLICY_ACTIVATION,
        baseline_policy_activation_hash=HASH_A,
        policy_snapshot_hash=HASH_B,
        policy_fingerprint=HASH_C,
    )
    rebuilt = BaselineShadowPolicyBinding.model_validate_json(binding.canonical_bytes(), strict=True)
    assert rebuilt == binding
    assert rebuilt.content_hash() == binding.content_hash()


def test_target_binding_carries_registration_hash() -> None:
    binding = TargetShadowPolicyBinding(
        source_kind=ShadowPolicySourceKind.TARGET_POLICY_REGISTRATION,
        target_policy_registration_hash=HASH_D,
        policy_snapshot_hash=HASH_B,
        policy_fingerprint=HASH_C,
    )
    assert binding.target_policy_registration_hash == HASH_D


def test_discriminated_union_selects_variant_by_source_kind() -> None:
    baseline = _BINDING_ADAPTER.validate_python(
        {
            "source_kind": "BASELINE_POLICY_ACTIVATION",
            "baseline_policy_activation_hash": HASH_A,
            "policy_snapshot_hash": HASH_B,
            "policy_fingerprint": HASH_C,
        }
    )
    target = _BINDING_ADAPTER.validate_python(
        {
            "source_kind": "TARGET_POLICY_REGISTRATION",
            "target_policy_registration_hash": HASH_D,
            "policy_snapshot_hash": HASH_B,
            "policy_fingerprint": HASH_C,
        }
    )
    assert isinstance(baseline, BaselineShadowPolicyBinding)
    assert isinstance(target, TargetShadowPolicyBinding)


def test_baseline_binding_rejects_target_field() -> None:
    with pytest.raises(ValidationError):
        BaselineShadowPolicyBinding.model_validate(
            {
                "source_kind": "BASELINE_POLICY_ACTIVATION",
                "target_policy_registration_hash": HASH_D,
                "policy_snapshot_hash": HASH_B,
                "policy_fingerprint": HASH_C,
            },
            strict=True,
        )


def test_binding_rejects_unknown_source_kind() -> None:
    with pytest.raises(ValidationError):
        _BINDING_ADAPTER.validate_python({"source_kind": "NEITHER", "policy_snapshot_hash": HASH_B})
