"""Schema-major-4 ShadowDecision + read-only legacy compatibility tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.screening.offensive.v3.contracts.compatibility import (
    LegacyShadowDecisionV2,
    LegacyShadowDecisionV3,
    ShadowCompatibilityError,
    read_shadow_decision_json,
)
from src.screening.offensive.v3.contracts.decision import ShadowDecision
from src.screening.offensive.v3.contracts.trial import (
    BaselineShadowPolicyBinding,
    ShadowPolicySourceKind,
    TargetShadowPolicyBinding,
)

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "contracts/fixtures/revision2"
HASH_A = "a" * 64


def _fixture_payload(model_name: str) -> dict:
    hashes = json.loads((FIXTURE_ROOT / "public_model_hashes.json").read_text(encoding="utf-8"))
    return hashes[f"src.screening.offensive.v3.contracts.{model_name}"]["payload"]


def _current_payload(**overrides) -> dict:
    payload = json.loads(json.dumps(_fixture_payload("decision.ShadowDecision")))
    payload.update(overrides)
    return payload


def _validate_current(payload: dict) -> ShadowDecision:
    return ShadowDecision.model_validate_json(json.dumps(payload, separators=(",", ":")), strict=True)


def _legacy_bytes() -> bytes:
    payload = _fixture_payload("compatibility.LegacyShadowDecisionV2")
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def _legacy_v3_bytes() -> bytes:
    payload = _fixture_payload("compatibility.LegacyShadowDecisionV3")
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


# --------------------------------------------------------------------------- #
# Current schema-major-4 ShadowDecision
# --------------------------------------------------------------------------- #


def test_current_shadow_decision_round_trips_with_baseline_binding() -> None:
    decision = _validate_current(_current_payload())
    assert decision.schema_major == 4
    assert decision.artifact_namespace == "growth-kernel.shadow.v3"
    binding = decision.shadow_policy_binding
    assert isinstance(binding, BaselineShadowPolicyBinding)
    schedule = decision.trading_session_schedule_binding
    assert schedule.signal_session == decision.counterfactual_key.signal_session
    assert schedule.following_sessions[0] == decision.target_entry_session
    assert all(
        line.target_exit_session == schedule.following_sessions[9]
        for line in decision.counterfactual_lines
    )
    assert binding.source_kind is ShadowPolicySourceKind.BASELINE_POLICY_ACTIVATION
    rebuilt = ShadowDecision.model_validate_json(decision.canonical_bytes(), strict=True)
    assert rebuilt == decision


def test_current_shadow_decision_accepts_target_binding() -> None:
    payload = _current_payload()
    payload["shadow_policy_binding"] = {
        "source_kind": "TARGET_POLICY_REGISTRATION",
        "target_policy_registration_hash": HASH_A,
        "policy_snapshot_hash": HASH_A,
        "policy_fingerprint": HASH_A,
    }
    decision = _validate_current(payload)
    assert isinstance(decision.shadow_policy_binding, TargetShadowPolicyBinding)


def test_current_shadow_decision_cannot_claim_activation_hash() -> None:
    payload = _current_payload()
    payload["policy_activation_hash"] = HASH_A
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ShadowDecision.model_validate(payload, strict=True)


def test_current_shadow_decision_rejects_schema_major_two() -> None:
    payload = _current_payload()
    payload["schema_major"] = 2
    with pytest.raises(ValidationError):
        _validate_current(payload)


def test_current_shadow_decision_rejects_legacy_namespace() -> None:
    payload = _current_payload()
    payload["artifact_namespace"] = "growth-kernel.shadow.v1"
    with pytest.raises(ValidationError):
        ShadowDecision.model_validate(payload, strict=True)


@pytest.mark.parametrize("mutation", ["entry", "exit", "signal"])
def test_current_shadow_decision_rejects_schedule_divergence(mutation: str) -> None:
    payload = _current_payload()
    if mutation == "entry":
        payload["target_entry_session"] = "2026-07-31"
    elif mutation == "exit":
        payload["counterfactual_lines"][0]["target_exit_session"] = "2026-08-09"
    else:
        payload["trading_session_schedule_binding"]["signal_session"] = "2026-07-28"
    with pytest.raises(ValidationError, match="schedule|session"):
        ShadowDecision.model_validate(payload, strict=True)


def test_current_shadow_decision_hashes_under_domain_v3_schema_four() -> None:
    decision = _validate_current(_current_payload())
    legacy = LegacyShadowDecisionV2.model_validate_json(_legacy_bytes(), strict=True)
    assert decision.HASH_DOMAIN == "ai-hedge-fund.v3.decision.shadow-decision.v3"
    assert decision.schema_major == 4
    # The schema-3 artifact and the historical schema-2 artifact never collide.
    assert decision.artifact_hash() != legacy.artifact_hash()


# --------------------------------------------------------------------------- #
# Read-only legacy compatibility
# --------------------------------------------------------------------------- #


def test_legacy_shadow_is_read_only_and_never_official() -> None:
    legacy_json = _legacy_bytes()
    parsed = read_shadow_decision_json(legacy_json, official_trial=False)
    assert isinstance(parsed, LegacyShadowDecisionV2)
    assert parsed.schema_major == 2
    assert parsed.artifact_namespace == "growth-kernel.shadow.v1"
    assert parsed.policy_activation_hash == HASH_A
    with pytest.raises(ShadowCompatibilityError, match="legacy_shadow_not_official"):
        read_shadow_decision_json(legacy_json, official_trial=True)


def test_legacy_shadow_keeps_historical_bytes_and_hash() -> None:
    legacy_json = _legacy_bytes()
    parsed = LegacyShadowDecisionV2.model_validate_json(legacy_json, strict=True)
    # The schema-2 shape reproduces the exact pre-migration canonical and
    # artifact hashes (the checkpoint-2 digest registry literals) byte for byte.
    assert parsed.content_hash() == ("b184967439c18291684fd8d745bcf0028e987d9754de97da64fc28b59ea37036")
    assert parsed.artifact_hash() == ("c483bc0a4b00069c212384ab4d4dad4584d7ebb1d8a00fbd2551b9ea1f69a307")
    # A legacy artifact decodes without any upgrader and never rewrites itself.
    assert parsed.policy_activation_hash == HASH_A


def test_legacy_shadow_rejects_current_schema_fields() -> None:
    payload = json.loads(_legacy_bytes())
    payload["shadow_policy_binding"] = {
        "source_kind": "BASELINE_POLICY_ACTIVATION",
        "baseline_policy_activation_hash": HASH_A,
        "policy_snapshot_hash": HASH_A,
        "policy_fingerprint": HASH_A,
    }
    with pytest.raises(ValidationError, match="extra_forbidden"):
        LegacyShadowDecisionV2.model_validate(payload, strict=True)


def test_schema_three_shadow_is_read_only_and_keeps_original_domain() -> None:
    payload = _legacy_v3_bytes()
    parsed = read_shadow_decision_json(payload, official_trial=False)
    assert isinstance(parsed, LegacyShadowDecisionV3)
    assert parsed.schema_major == 3
    assert parsed.artifact_namespace == "growth-kernel.shadow.v2"
    assert parsed.HASH_DOMAIN == "ai-hedge-fund.v3.decision.shadow-decision.v2"
    with pytest.raises(ShadowCompatibilityError, match="legacy_shadow_not_official"):
        read_shadow_decision_json(payload, official_trial=True)
