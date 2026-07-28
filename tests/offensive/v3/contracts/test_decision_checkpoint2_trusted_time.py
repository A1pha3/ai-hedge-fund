"""Checkpoint 2 RED: trusted-time and deadline semantics."""

from __future__ import annotations

# Explicit shared fixture surface; individual focused files intentionally use subsets.
# ruff: noqa: F401
from datetime import timedelta, timezone
from decimal import Decimal
import hashlib

import pytest
from pydantic import ValidationError

from tests.offensive.v3.contracts.checkpoint2_helpers import (
    APPROVED_SERIALIZATION_DIGESTS,
    BROKER_CUTOFF,
    CHECKPOINT2_NAMES,
    CLOSE_FINALIZED,
    DIFFERENT_LOGICAL_KEY,
    HASH_A,
    HASH_B,
    HASH_C,
    HASH_D,
    HASH_E,
    HASH_F,
    PERMIT_DEADLINE,
    PERMIT_EXPIRES,
    SEAL_CREATED,
    SEAL_DEADLINE,
    SEND_DEADLINE,
    SIGNAL_SESSION,
    TARGET_SESSION,
    _api,
    _gateway_expected_versions,
    _gateway_issuer,
    _permit,
    _permit_line,
    _permit_payload,
    _prior_seal_eligibility,
    _proposal,
    _proposal_line,
    _reserve_bindings,
    _seal,
    _seal_payload,
    _send_claim_versions,
    _shadow,
    _shadow_line,
    _shadow_payload,
    _shadow_stage_binding,
    _stage_binding,
    _stage_expected_version,
    _window,
    _window_payload,
)


def test_trusted_execution_window_has_exact_semantic_fields() -> None:
    api = _api()

    assert set(api.TrustedExecutionWindow.model_fields) == {
        "signal_session",
        "target_entry_session",
        "exchange_id",
        "calendar_snapshot_id",
        "calendar_snapshot_hash",
        "calendar_snapshot_version",
        "cutoff_snapshot_id",
        "cutoff_snapshot_hash",
        "cutoff_snapshot_version",
        "cutoff_snapshot_session",
        "cutoff_snapshot_exchange_id",
        "execution_policy_version",
        "cutoff_policy_version",
        "clock_observation_id",
        "clock_observation_hash",
        "wall_clock_observed_at",
        "monotonic_observation_ns",
        "monotonic_sequence",
        "clock_health",
        "t0_close_finalized_at",
        "seal_creation_deadline",
        "permit_issue_deadline",
        "gateway_send_deadline",
        "broker_auction_submission_cutoff",
    }
    assert set(api.ClockHealth) == {
        api.ClockHealth.HEALTHY,
        api.ClockHealth.UNKNOWN,
        api.ClockHealth.EXCESSIVE_SKEW,
        api.ClockHealth.ROLLBACK_DETECTED,
    }
    assert "deadline" not in api.PortfolioDecisionSeal.model_fields
    assert "deadline" not in api.ExecutionPermit.model_fields


@pytest.mark.parametrize(
    "drift",
    [
        {"t0_close_finalized_at": SEAL_DEADLINE},
        {"seal_creation_deadline": PERMIT_DEADLINE},
        {"permit_issue_deadline": SEND_DEADLINE},
        {"gateway_send_deadline": BROKER_CUTOFF},
    ],
)
def test_trusted_execution_window_rejects_every_strict_boundary_equality(
    drift,
) -> None:
    api = _api()
    with pytest.raises(ValidationError, match="close|seal|permit|send|broker|deadline"):
        api.TrustedExecutionWindow.model_validate(_window_payload(api, **drift))


def test_seal_created_at_may_equal_creation_deadline_but_must_follow_close() -> None:
    api = _api()
    seal = _seal(api, created_at=SEAL_DEADLINE)
    assert seal.created_at == seal.execution_window.seal_creation_deadline

    for created_at in (CLOSE_FINALIZED, SEAL_DEADLINE + timedelta(microseconds=1)):
        with pytest.raises(ValidationError, match="close|created|deadline"):
            api.PortfolioDecisionSeal.model_validate(
                _seal_payload(api, created_at=created_at)
            )


def test_permit_time_boundaries_are_exact() -> None:
    api = _api()
    permit = _permit(api)
    assert permit.issued_at == permit.execution_window.permit_issue_deadline
    assert permit.permit_expires_at == permit.execution_window.gateway_send_deadline

    for drift in (
        {"issued_at": SEAL_CREATED},
        {"issued_at": PERMIT_DEADLINE + timedelta(microseconds=1)},
        {"permit_expires_at": PERMIT_DEADLINE},
        {"permit_expires_at": SEND_DEADLINE + timedelta(microseconds=1)},
    ):
        with pytest.raises(ValidationError, match="issued|expires|seal|deadline"):
            api.ExecutionPermit.model_validate(_permit_payload(api, **drift))


def test_unhealthy_or_rollback_clock_blocks_seal_and_permit() -> None:
    api = _api()
    for health in (
        api.ClockHealth.UNKNOWN,
        api.ClockHealth.EXCESSIVE_SKEW,
        api.ClockHealth.ROLLBACK_DETECTED,
    ):
        unhealthy = _window(api, clock_health=health)
        with pytest.raises(ValidationError, match="clock"):
            api.PortfolioDecisionSeal.model_validate(
                _seal_payload(api, execution_window=unhealthy)
            )
        with pytest.raises(ValidationError, match="clock"):
            api.ExecutionPermit.model_validate(
                _permit_payload(api, execution_window=unhealthy)
            )


def test_cutoff_snapshot_session_exchange_and_observation_are_bounded() -> None:
    api = _api()
    for drift in (
        {"cutoff_snapshot_session": SIGNAL_SESSION},
        {"cutoff_snapshot_exchange_id": "SZSE"},
        {"wall_clock_observed_at": SEAL_DEADLINE + timedelta(microseconds=1)},
    ):
        with pytest.raises(
            ValidationError, match="cutoff|session|exchange|clock|deadline"
        ):
            api.TrustedExecutionWindow.model_validate(_window_payload(api, **drift))
