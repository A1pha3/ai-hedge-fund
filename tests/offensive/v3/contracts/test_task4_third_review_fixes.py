"""Third-review regressions for the Task 4 compatibility and policy boundary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import math
from typing import Any

import pytest
from pydantic import ValidationError


UTC = timezone.utc
NOW = datetime(2026, 7, 29, 8, 0, tzinfo=UTC)


def _verify_policy_candidate(
    policy: Any,
    signed: Any,
    required: Any,
    verifier: Any,
    *,
    predecessor: Any | None,
) -> Any:
    from src.screening.offensive.v3 import policy as policy_api
    from src.screening.offensive.v3 import trust
    from tests.offensive.v3.contracts.test_policy import _current_trust_head

    return policy_api.verify_policy_activation(
        signed,
        policy,
        verifier,
        required,
        current_trust_head=_current_trust_head(verifier),
        trusted_at=NOW,
        predecessor=predecessor,
        expected_portfolio_id="paper-v3",
        expected_broker_account_id="manual-account-1",
        expected_broker_account_fingerprint=None,
        expected_mode=trust.ExecutionMode.MANUAL_CONFIRMED,
    )


def test_revision1_primitives_are_local_and_enum_members_remain_exact() -> None:
    from src.screening.offensive.v3.contracts import base as current
    from src.screening.offensive.v3.contracts import revision1

    assert revision1.CanonicalModel is not current.CanonicalModel
    assert revision1.ExecutionMode is not current.ExecutionMode
    assert revision1.EvidenceScope is not current.EvidenceScope
    assert revision1.canonical_json_bytes is not current.canonical_json_bytes
    assert revision1.content_hash is not current.content_hash
    assert revision1.CanonicalModel.__module__.endswith("revision1_primitives")
    assert revision1.ExecutionMode.__module__.endswith("revision1_primitives")
    assert revision1.EvidenceScope.__module__.endswith("revision1_primitives")
    assert revision1.canonical_json_bytes.__module__.endswith("revision1_primitives")
    assert [mode.value for mode in revision1.ExecutionMode] == [
        "research_reconstruction",
        "daily_bar_proxy",
        "manual_confirmed",
        "broker_confirmed",
    ]
    assert [scope.value for scope in revision1.EvidenceScope] == [
        "global",
        "strategy_lineage",
    ]


def test_revision1_canonical_json_keeps_legacy_finite_float_behavior() -> None:
    from src.screening.offensive.v3.contracts import revision1

    class LegacyMetric(revision1.CanonicalModel):
        legacy_metric: float

    metric = LegacyMetric(legacy_metric=1.5)
    expected = b'{"legacy_metric":1.5}'
    assert metric.canonical_bytes() == expected
    assert metric.content_hash() == hashlib.sha256(expected).hexdigest()
    for nonfinite in (math.nan, math.inf, -math.inf):
        with pytest.raises(ValueError, match="finite float"):
            revision1.canonical_json_bytes({"legacy_metric": nonfinite})


def test_active_policy_witness_rejects_effective_time_after_observation() -> None:
    from src.screening.offensive.v3 import policy as policy_api
    from src.screening.offensive.v3 import trust

    with pytest.raises(ValidationError, match="effective_from.*observed_at"):
        policy_api.ActivePolicyActivationWitness(
            active_policy_activation_hash="f" * 64,
            portfolio_id="paper-v3",
            broker_account_id="manual-account-1",
            broker_account_fingerprint=None,
            mode=trust.ExecutionMode.MANUAL_CONFIRMED,
            trust_bundle_hash="a" * 64,
            registry_epoch=1,
            policy_epoch=1,
            authority_epoch=1,
            risk_epoch=1,
            effective_from=NOW + timedelta(minutes=1),
            store_version=1,
            observed_at=NOW,
        )


def test_policy_verification_rejects_unchecked_impossible_predecessor_time() -> None:
    from src.screening.offensive.v3 import policy as policy_api
    from src.screening.offensive.v3 import trust
    from tests.offensive.v3.contracts.test_policy import _signed_policy_activation

    policy, activation, signed, required, verifier = _signed_policy_activation(
        policy_updates={"policy_epoch": 2},
        activation_updates={
            "predecessor_policy_activation_hash": "f" * 64,
            "effective_from": NOW + timedelta(minutes=2),
        },
    )
    unchecked = policy_api.ActivePolicyActivationWitness.model_construct(
        active_policy_activation_hash="f" * 64,
        portfolio_id="paper-v3",
        broker_account_id="manual-account-1",
        broker_account_fingerprint=None,
        mode=trust.ExecutionMode.MANUAL_CONFIRMED,
        trust_bundle_hash=activation.trust_bundle_hash,
        registry_epoch=1,
        policy_epoch=1,
        authority_epoch=1,
        risk_epoch=1,
        effective_from=NOW + timedelta(minutes=1),
        store_version=1,
        observed_at=NOW,
    )

    with pytest.raises(
        policy_api.PolicyActivationVerificationError,
        match="effective_from.*observed_at",
    ):
        _verify_policy_candidate(
            policy,
            signed,
            required,
            verifier,
            predecessor=unchecked,
        )


def test_policy_verification_rejects_capability_verifier_subclass_override() -> None:
    from src.screening.offensive.v3 import trust
    from tests.offensive.v3.contracts.test_policy import _signed_policy_activation

    policy, _, signed, required, verifier = _signed_policy_activation()

    class OverrideVerifier(trust.CapabilityVerifier):
        def verify(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError("subclass override reached the verifier boundary")

    override = OverrideVerifier(verifier._trust_verifier, verifier._signed_chain)
    with pytest.raises(TypeError, match="CapabilityVerifier"):
        _verify_policy_candidate(
            policy,
            signed,
            required,
            override,
            predecessor=None,
        )


def test_exit_mandate_binds_the_entry_evidence_record_artifact_hash() -> None:
    from src.screening.offensive.v3 import contracts as api
    from tests.offensive.v3.contracts.checkpoint2_helpers import _proposal
    from tests.offensive.v3.contracts.test_capital import _exit_mandate_payload

    record = _proposal(api).order_lines[0].plan_evidence
    payload = _exit_mandate_payload(api)
    payload["entry_plan_evidence_artifact_hash"] = record.artifact_hash()

    mandate = api.ExitMandate(**payload)

    assert "entry_plan_evidence_hash" not in api.ExitMandate.model_fields
    assert "entry_plan_evidence_artifact_hash" in api.ExitMandate.model_fields
    assert mandate.entry_plan_evidence_artifact_hash == record.artifact_hash()
