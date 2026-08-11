"""Contract tests for the frozen regime admission primitives.

Regime is a strict, typed surface: a canonical ``RegimeObservation`` is a valid
shared policy fact, and the only arm behaviour delta admitted by a paired trial
is ``ProducerPolicy.btst_regime_admission_mode``.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from src.screening.offensive.v3.contracts.regime import (
    RegimeAdmissionMode,
    RegimeObservation,
    RegimeObservationReason,
    RegimeSourceRevision,
    RegimeState,
    normalize_regime_state,
)
from src.screening.offensive.v3.policy.models import (
    SUPPORTED_POLICY_SCHEMA_MAJOR,
    ProducerPolicy,
)

UTC = timezone.utc
SESSION = date(2026, 8, 11)
HASH_A = "a" * 64
HASH_B = "b" * 64


def _revision(evidence_id: str, artifact_hash: str = HASH_A) -> RegimeSourceRevision:
    return RegimeSourceRevision(
        evidence_id=evidence_id, revision=1, artifact_hash=artifact_hash
    )


def _observation_kwargs(**overrides):
    base = dict(
        signal_session=SESSION,
        state=RegimeState.NORMAL,
        reason=RegimeObservationReason.CLASSIFIED,
        raw_state="NORMAL",
        source_revisions=(_revision("ev-1"),),
        effective_at=datetime(2026, 8, 11, 15, 0, tzinfo=UTC),
        provider_published_at=datetime(2026, 8, 11, 15, 30, tzinfo=UTC),
        observed_at=datetime(2026, 8, 11, 16, 0, tzinfo=UTC),
        classifier_semver="1.0.0",
        behavior_fingerprint=HASH_B,
        input_schema_hash=HASH_A,
    )
    base.update(overrides)
    return base


def observation(**overrides) -> RegimeObservation:
    return RegimeObservation(**_observation_kwargs(**overrides))


# --------------------------------------------------------------------------- #
# Enum literals
# --------------------------------------------------------------------------- #


def test_regime_state_has_exact_canonical_values() -> None:
    assert [state.value for state in RegimeState] == [
        "NORMAL",
        "RISK_OFF",
        "CRISIS",
        "UNKNOWN",
    ]


def test_regime_observation_reason_has_exact_typed_values() -> None:
    assert [reason.value for reason in RegimeObservationReason] == [
        "CLASSIFIED",
        "MISSING_REQUIRED_INPUT",
        "STALE_REQUIRED_INPUT",
        "UNRECOGNIZED_RAW_STATE",
        "INSUFFICIENT_INPUT",
    ]


def test_regime_admission_mode_has_exact_two_arm_values() -> None:
    assert [mode.value for mode in RegimeAdmissionMode] == [
        "IGNORE",
        "NORMAL_ONLY",
    ]


# --------------------------------------------------------------------------- #
# normalize_regime_state
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw_state", "expected_state"),
    [
        ("NORMAL", RegimeState.NORMAL),
        ("normal", RegimeState.NORMAL),
        ("risk_off", RegimeState.RISK_OFF),
        ("RISK-OFF", RegimeState.RISK_OFF),
        ("crisis", RegimeState.CRISIS),
    ],
)
def test_recognized_raw_regime_normalizes_to_classified(
    raw_state: str, expected_state: RegimeState
) -> None:
    state, reason = normalize_regime_state(
        raw_state, reason_if_missing=RegimeObservationReason.MISSING_REQUIRED_INPUT
    )
    assert state is expected_state
    assert reason is RegimeObservationReason.CLASSIFIED


def test_unrecognized_raw_regime_normalizes_to_unknown() -> None:
    state, reason = normalize_regime_state(
        "euphoria",
        reason_if_missing=RegimeObservationReason.MISSING_REQUIRED_INPUT,
    )
    assert state is RegimeState.UNKNOWN
    assert reason is RegimeObservationReason.UNRECOGNIZED_RAW_STATE


def test_missing_raw_regime_uses_caller_reason() -> None:
    for reason in (
        RegimeObservationReason.MISSING_REQUIRED_INPUT,
        RegimeObservationReason.STALE_REQUIRED_INPUT,
        RegimeObservationReason.INSUFFICIENT_INPUT,
    ):
        state, returned = normalize_regime_state(None, reason_if_missing=reason)
        assert state is RegimeState.UNKNOWN
        assert returned is reason


def test_normalize_never_returns_normal_for_unrecognized_input() -> None:
    for raw in ("", "unknown", "bull", "UNKNOWN"):
        state, reason = normalize_regime_state(
            raw, reason_if_missing=RegimeObservationReason.MISSING_REQUIRED_INPUT
        )
        assert state is RegimeState.UNKNOWN
        assert reason is not RegimeObservationReason.CLASSIFIED


# --------------------------------------------------------------------------- #
# RegimeObservation invariants
# --------------------------------------------------------------------------- #


def test_classified_reason_required_for_canonical_non_unknown_states() -> None:
    for state in (RegimeState.NORMAL, RegimeState.RISK_OFF, RegimeState.CRISIS):
        with pytest.raises(ValidationError, match="classified"):
            observation(state=state, reason=RegimeObservationReason.STALE_REQUIRED_INPUT)


def test_unknown_state_rejects_classified_reason() -> None:
    with pytest.raises(ValidationError, match="classified|unknown"):
        observation(
            state=RegimeState.UNKNOWN,
            reason=RegimeObservationReason.CLASSIFIED,
            raw_state=None,
        )


def test_source_revisions_must_be_ordered_by_evidence_id() -> None:
    unordered = (_revision("ev-2", HASH_A), _revision("ev-1", HASH_B))
    with pytest.raises(ValidationError, match="order|sorted|evidence"):
        observation(source_revisions=unordered)


def test_source_revisions_reject_duplicate_evidence_ids() -> None:
    duplicate = (_revision("ev-1", HASH_A), _revision("ev-1", HASH_B))
    with pytest.raises(ValidationError, match="duplicate|unique"):
        observation(source_revisions=duplicate)


def test_source_revisions_reject_list_binding() -> None:
    with pytest.raises(ValidationError):
        observation(source_revisions=[_revision("ev-1")])


def test_source_evidence_root_is_recomputed_from_sorted_artifact_hashes() -> None:
    from src.screening.offensive.v3.contracts.base import content_hash

    rev_first = _revision("ev-1", HASH_A)
    rev_second = _revision("ev-2", HASH_B)
    observed = observation(source_revisions=(rev_first, rev_second))
    expected_root = content_hash((HASH_A, HASH_B))
    assert observed.source_evidence_root == expected_root
    # order of artifact hashes is canonical, not source order
    swapped_hashes = observation(
        source_revisions=(
            _revision("ev-1", HASH_B),
            _revision("ev-2", HASH_A),
        )
    )
    assert swapped_hashes.source_evidence_root == expected_root


def test_observed_at_cannot_precede_effective_or_published_times() -> None:
    earlier = datetime(2026, 8, 11, 14, 0, tzinfo=UTC)
    with pytest.raises(ValidationError, match="observed_at|effective"):
        observation(effective_at=datetime(2026, 8, 11, 17, 0, tzinfo=UTC))
    with pytest.raises(ValidationError, match="observed_at|published"):
        observation(
            provider_published_at=datetime(2026, 8, 11, 17, 0, tzinfo=UTC)
        )
    with pytest.raises(ValidationError):
        observation(observed_at=earlier)


def test_observation_is_canonical_and_hashable() -> None:
    observed = observation()
    rebuilt = RegimeObservation.model_validate_json(
        observed.canonical_bytes(), strict=True
    )
    assert rebuilt == observed
    assert observed.content_hash() == rebuilt.content_hash()


# --------------------------------------------------------------------------- #
# ProducerPolicy admission field
# --------------------------------------------------------------------------- #


def _producer_kwargs(**overrides):
    base = dict(
        btst_enabled=False,
        oversold_bounce_enabled=False,
        btst_regime_admission_mode=RegimeAdmissionMode.IGNORE,
        regime_sizing_enabled=False,
        streak_sizing_enabled=False,
        trigger_strength_sizing_enabled=False,
        composite_sizing_enabled=False,
    )
    base.update(overrides)
    return base


def test_off_policy_enum_does_not_count_as_enabled() -> None:
    policy = ProducerPolicy(**_producer_kwargs())
    assert not policy.any_enabled()


def test_admission_mode_is_required_and_typed() -> None:
    with pytest.raises(ValidationError, match="btst_regime_admission_mode"):
        ProducerPolicy(
            btst_enabled=False,
            oversold_bounce_enabled=False,
            regime_sizing_enabled=False,
            streak_sizing_enabled=False,
            trigger_strength_sizing_enabled=False,
            composite_sizing_enabled=False,
        )


def test_admission_mode_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        ProducerPolicy(**_producer_kwargs(btst_regime_admission_mode="ALWAYS"))


@pytest.mark.parametrize(
    "enabled_field",
    [
        "btst_enabled",
        "oversold_bounce_enabled",
        "regime_sizing_enabled",
        "streak_sizing_enabled",
        "trigger_strength_sizing_enabled",
        "composite_sizing_enabled",
    ],
)
def test_each_producer_switch_still_drives_any_enabled(enabled_field: str) -> None:
    assert ProducerPolicy(**_producer_kwargs(**{enabled_field: True})).any_enabled()


def test_policy_schema_major_is_two() -> None:
    assert SUPPORTED_POLICY_SCHEMA_MAJOR == 2
