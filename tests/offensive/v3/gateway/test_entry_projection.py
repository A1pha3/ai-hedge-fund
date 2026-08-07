"""Plan 04 Task 9: integrated entry projection verification.

Locks the read-only projection contract that reconciles the kernel's planned
entries to the gateway's active seals and makes every entry lifecycle outcome
separately visible. The gateway exposes no portfolio-wide listing by design:
every read is keyed (``active_seal`` by economic key, ``entry_state`` by seal
id). This test composes those keyed reads the way an operator projection would
and asserts the Task 9 properties:

- a planned entry reconciles to its active seal by economic key, and an
  unplanned key has none;
- the distinct lifecycle outcomes - shadow (sealed, not yet executable),
  executable, tombstoned, ambiguous - are each separately visible on
  ``entry_state().status`` via one classifier;
- a halt BLOCKS an entry from leaving shadow (``issue_permit`` rejects and the
  status stays SEALED) - the gateway-level block. There is intentionally no
  per-seal "blocked" projection field; portfolio-level fence blocking is
  covered by ``test_authority.py``'s ``open_fence_count``.

No network delivery occurs anywhere; the gateway only linearizes the right to
send one immutable payload under one client id.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

import pytest

from src.screening.offensive.v3.contracts import RiskLatchState
from src.screening.offensive.v3.gateway.decisions import (
    CapitalGateway,
    CapitalGatewayError,
    DeliveryOutcome,
)
from tests.offensive.v3.contracts.checkpoint2_helpers import (
    _api,
    _permit,
    _permit_evaluation_state,
    _permit_line,
    _seal,
    HASH_A,
    PERMIT_DEADLINE,
)
from tests.offensive.v3.gateway.test_entry_state import (
    _claim_context,
    _issue,
    _publish,
    _truth_context,
)

# Statuses past SEALED carry a live send right: the entry is executable.
_EXECUTABLE_STATUSES = frozenset(
    {"PERMITTED", "OUTBOX_DURABLE", "SEND_CLAIMED", "BROKER_ACK"}
)


def _classify_entry(status: str) -> str:
    """Map a gateway entry status to its Task 9 projection label.

    One status maps to exactly one label, so the four observable outcomes are
    always separately visible. A halt never produces a status (it rejects the
    transition), so "blocked" is asserted as a rejected transition plus an
    unchanged status, not as a label here.
    """

    if status == "SEALED":
        return "shadow"
    if status == "TOMBSTONED":
        return "tombstoned"
    if status == "SUBMISSION_AMBIGUOUS":
        return "ambiguous"
    if status in _EXECUTABLE_STATUSES:
        return "executable"
    raise ValueError(f"unclassified entry status: {status!r}")


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now_value = start

    def __call__(self) -> datetime:
        return self.now_value


@pytest.fixture()
def api():
    return _api()


@pytest.fixture()
def clock() -> _Clock:
    return _Clock(PERMIT_DEADLINE)


@pytest.fixture()
def gateway(tmp_path, clock) -> CapitalGateway:
    return CapitalGateway(
        database_path=str(tmp_path / "gateway-projection.sqlite3"),
        clock=clock,
    )


def test_planned_entry_reconciles_to_active_seal_by_economic_key(
    gateway, api
) -> None:
    # A planned entry (a sealed decision) is reachable by its economic key
    # while it is still sealed: active_seal is the keyed lookup that owns a
    # planned entry to its single active seal.
    seal = _publish(gateway, api)
    assert gateway.active_seal(seal.logical_key) == (
        seal.seal_id,
        seal.seal_revision,
    )
    # An unplanned economic key has no active seal: planned entry rows and
    # active seals reconcile one-to-one by key, with no orphans either way.
    unplanned = seal.logical_key.model_copy(
        update={"decision_cycle_id": "daily-t1-open-v9"}
    )
    assert gateway.active_seal(unplanned) is None


def test_entry_projection_classifies_each_lifecycle_stage(gateway, api) -> None:
    # One entry driven through its progression: each stage projects a distinct,
    # separately-visible classification on entry_state().status.
    seal = _publish(gateway, api)
    assert _classify_entry(gateway.entry_state(seal.seal_id).status) == "shadow"

    permit = _permit(api)
    _issue(gateway, api, permit)
    gateway.make_outbox_durable(permit)
    expected = permit.send_claim_expected_versions
    gateway.claim_send(permit, expected, context=_claim_context(api, expected))
    assert _classify_entry(gateway.entry_state(seal.seal_id).status) == (
        "executable"
    )

    gateway.record_delivery_outcome(
        seal.seal_id, DeliveryOutcome.SUBMISSION_AMBIGUOUS
    )
    assert _classify_entry(gateway.entry_state(seal.seal_id).status) == (
        "ambiguous"
    )


def test_cancelled_entry_projects_tombstoned(gateway, api) -> None:
    seal = _publish(gateway, api)
    cancelled_state = _permit_evaluation_state(
        api,
        seal,
        authorization_lifecycle=api.AuthorizationLifecycle.REVOKED,
        authorization_status_version=seal.authorization_status_version + 1,
        authorization_status_hash=HASH_A,
    )
    cancel_lines = tuple(
        _permit_line(
            api,
            sealed_line,
            disposition=api.PermitDisposition.CANCEL,
            permitted_quantity=0,
        )
        for sealed_line in seal.proposal.order_lines
    )
    cancel = _permit(
        api,
        disposition=api.PermitDisposition.CANCEL,
        evaluation_state=cancelled_state,
        permit_lines=cancel_lines,
    )
    gateway.issue_permit(cancel, context=_truth_context(api, cancelled_state))
    state = gateway.entry_state(seal.seal_id)
    assert state.status == "TOMBSTONED"
    assert _classify_entry(state.status) == "tombstoned"


def test_halt_blocks_entry_from_leaving_shadow(gateway, api) -> None:
    # "blocked" has no per-seal projection field: a halt rejects the
    # shadow -> executable transition and the entry stays shadow, so the block
    # is observed as a raised CapitalGatewayError plus an unchanged status.
    seal = _publish(gateway, api)
    halted = dataclasses.replace(
        _truth_context(api, _permit(api).evaluation_state),
        risk_latch=RiskLatchState.RISK_HALTED,
    )
    with pytest.raises(CapitalGatewayError) as excinfo:
        _issue(gateway, api, context=halted)
    assert excinfo.value.code == "risk_halt_blocks_send"
    # The blocked entry never left shadow.
    assert _classify_entry(gateway.entry_state(seal.seal_id).status) == "shadow"
