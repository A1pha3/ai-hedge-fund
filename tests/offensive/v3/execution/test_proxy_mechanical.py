"""Task 8: the shared mechanical shrink resolver.

The gateway and the shadow adapter must agree on how a sealed T0 quantity
shrinks to its T+1 permitted quantity: same caps, same priority, same
lot-floor, same reason. That logic currently lives duplicated inside
``PermitLineMechanicalBinding`` (``limiting_cap`` / ``limiting_reason``)
and the ``_validate_permit_lines`` lot-floor branch. This suite drives the
shared pure resolver directly and proves an ``ExecutionPermit`` that
passes its own validation produces the exact same resolution, so the
shadow adapter can call the same function without re-deriving it.

RED today: ``resolve_mechanical_quantity`` and ``MechanicalQuantityResolution``
do not exist in the contracts module.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.screening.offensive.v3.contracts import (
    MechanicalQuantityResolution,  # RED target
    PermitLineMechanicalBinding,
    PermitReasonCode,
    resolve_mechanical_quantity,  # RED target
)
from src.screening.offensive.v3.contracts.evidence import NonEmptyStr

SEALED = 300
LOT = 100
AS_OF = datetime(2026, 7, 29, 8, 2, tzinfo=timezone.utc)


def _binding(caps: dict[str, int], *, order_line_id: str = "line-1"):
    """Build a mechanical binding directly from the five cap values.

    The resolver is authority-neutral: it only reads the five integer caps,
    so we construct the binding without going through the full permit
    builder (which would itself duplicate the resolver we are extracting).
    """

    fields = {
        "availability_cap_units",
        "price_cap_units",
        "capacity_cap_units",
        "cash_cap_units",
        "capital_risk_cap_units",
    }
    missing = fields - set(caps)
    assert not missing, f"caps missing {missing}"
    return PermitLineMechanicalBinding(
        order_line_id=NonEmptyStr(order_line_id),
        predicate_policy_version="t1-open-t10-open-slippage.v2",
        preopen_fact_snapshot_id="preopen-facts-1",
        preopen_fact_snapshot_hash="a" * 64,
        preopen_fact_as_of=AS_OF,
        **caps,
    )


def _all_at(value: int) -> dict[str, int]:
    return {
        "availability_cap_units": value,
        "price_cap_units": value,
        "capacity_cap_units": value,
        "cash_cap_units": value,
        "capital_risk_cap_units": value,
    }


def test_all_caps_above_sealed_is_unchanged() -> None:
    binding = _binding(_all_at(SEALED))
    resolution = resolve_mechanical_quantity(SEALED, LOT, binding)
    assert isinstance(resolution, MechanicalQuantityResolution)
    assert resolution.permitted_quantity_units == SEALED
    assert resolution.reason_code is PermitReasonCode.UNCHANGED


@pytest.mark.parametrize(
    ("cap_field", "reason"),
    [
        ("availability_cap_units", PermitReasonCode.AVAILABILITY_REDUCTION),
        ("price_cap_units", PermitReasonCode.PRICE_REDUCTION),
        ("capacity_cap_units", PermitReasonCode.CAPACITY_REDUCTION),
        ("cash_cap_units", PermitReasonCode.CASH_REDUCTION),
        ("capital_risk_cap_units", PermitReasonCode.CAPITAL_RISK_REDUCTION),
    ],
)
def test_each_cap_priority_shrinks_with_its_reason(cap_field, reason) -> None:
    caps = _all_at(SEALED)
    # Only the named cap is binding (300 -> 200, an exact whole lot).
    caps[cap_field] = 200
    binding = _binding(caps)
    resolution = resolve_mechanical_quantity(SEALED, LOT, binding)
    assert resolution.permitted_quantity_units == 200
    assert resolution.reason_code is reason


def test_priority_order_when_two_caps_tie_at_the_minimum() -> None:
    """Priority is AVAILABILITY > PRICE > CAPACITY > CASH > RISK.

    When two caps coincide at the binding minimum, the first one in priority
    order wins the reason label (mirrors ``limiting_reason`` today).
    """

    caps = _all_at(SEALED)
    caps["availability_cap_units"] = 200
    caps["price_cap_units"] = 200
    binding = _binding(caps)
    resolution = resolve_mechanical_quantity(SEALED, LOT, binding)
    assert resolution.permitted_quantity_units == 200
    # Availability comes before price in priority, so it owns the label.
    assert resolution.reason_code is PermitReasonCode.AVAILABILITY_REDUCTION


def test_lot_floor_rounds_raw_cap_down_to_a_whole_lot() -> None:
    # A 250-unit availability cap is below the 300 sealed quantity but is not
    # an exact whole lot (2.5 lots). The resolver must floor it to 200.
    caps = _all_at(SEALED)
    caps["availability_cap_units"] = 250
    binding = _binding(caps)
    resolution = resolve_mechanical_quantity(SEALED, LOT, binding)
    assert resolution.permitted_quantity_units == 200
    assert resolution.reason_code is PermitReasonCode.AVAILABILITY_REDUCTION


def test_lot_floor_of_a_sub_lot_cap_is_zero_quantity() -> None:
    # A 50-unit cap (half a lot) floors to zero executable quantity.
    caps = _all_at(SEALED)
    caps["availability_cap_units"] = 50
    binding = _binding(caps)
    resolution = resolve_mechanical_quantity(SEALED, LOT, binding)
    assert resolution.permitted_quantity_units == 0
    # The binding cap still owns the reason even when floored to zero.
    assert resolution.reason_code is PermitReasonCode.AVAILABILITY_REDUCTION


def test_input_cap_above_sealed_clamps_to_sealed() -> None:
    # A cap may never increase the T0 sealed quantity: a 500 cap above the
    # 300 sealed line resolves unchanged at 300.
    caps = _all_at(SEALED)
    caps["availability_cap_units"] = 500
    binding = _binding(caps)
    resolution = resolve_mechanical_quantity(SEALED, LOT, binding)
    assert resolution.permitted_quantity_units == SEALED
    assert resolution.reason_code is PermitReasonCode.UNCHANGED


def test_smallest_cap_wins_even_if_not_in_priority_first_position() -> None:
    # Cash is the tightest cap (150), below availability (300). Priority only
    # breaks ties; the actual minimum always selects the quantity.
    caps = _all_at(SEALED)
    caps["cash_cap_units"] = 150
    binding = _binding(caps)
    resolution = resolve_mechanical_quantity(SEALED, LOT, binding)
    assert resolution.permitted_quantity_units == 100
    assert resolution.reason_code is PermitReasonCode.CASH_REDUCTION


def test_permit_validation_matches_direct_resolver() -> None:
    """An ``ExecutionPermit`` that passes its own validation resolves its
    line quantities and reasons identically to the shared resolver.

    This is the contract that lets the shadow adapter call the same resolver
    without re-deriving it from a permit: the gateway's validation IS the
    resolver. We use the checkpoint-2 default builders (mode-agnostic for
    the resolver, which only reads the mechanical binding's caps).
    """

    from tests.offensive.v3.contracts.checkpoint2_helpers import (
        _api,
        _permit,
        _permit_line,
        _seal,
    )

    api = _api()
    seal = _seal(api)
    sealed_lines = seal.proposal.order_lines
    # line-2 seals 200 (two lots); shrink it to one lot via a cash cap.
    # line-1 seals 100 (one lot) and stays unchanged.
    shrunk = _permit_line(
        api,
        sealed_lines[1],
        permitted_quantity=sealed_lines[1].lot_size_units,
        reason_code=api.PermitReasonCode.CASH_REDUCTION,
    )
    intact = _permit_line(api, sealed_lines[0])
    permit = _permit(api, seal=seal, permit_lines=(intact, shrunk))
    # Construction success already proves gateway == resolver for these lines.
    for permit_line in permit.permit_lines:
        sealed_line = next(
            line
            for line in seal.proposal.order_lines
            if line.order_line_id == permit_line.order_line_id
        )
        assert permit_line.mechanical_binding is not None
        resolution = resolve_mechanical_quantity(
            sealed_line.sealed_quantity_units,
            sealed_line.lot_size_units,
            permit_line.mechanical_binding,
        )
        assert resolution.permitted_quantity_units == int(
            permit_line.permitted_quantity_units
        )
        assert resolution.reason_code is permit_line.reason_code
