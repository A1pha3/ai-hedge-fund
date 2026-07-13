from dataclasses import FrozenInstanceError
from datetime import date
import math

import pytest

from src.screening.offensive.exit_policy import (
    ExitObservation,
    ExitPolicyState,
    evaluate_shadow_exit,
)


def test_policy_arms_at_ten_percent_close_return() -> None:
    state = ExitPolicyState.unarmed(entry_price=10.0)
    decision = evaluate_shadow_exit(
        state,
        ExitObservation(date(2026, 7, 14), holding_session=2, close=11.0, atr=0.4),
    )
    assert decision.state.armed_at == date(2026, 7, 14)
    assert decision.should_exit_next_open is False


def test_exit_line_never_moves_down_when_atr_expands() -> None:
    state = ExitPolicyState(entry_price=10.0, armed_at=date(2026, 7, 14), highest_close=12.0, exit_line=11.0)
    decision = evaluate_shadow_exit(
        state,
        ExitObservation(date(2026, 7, 15), holding_session=3, close=12.1, atr=1.0),
    )
    assert decision.state.exit_line == 11.0


def test_close_below_line_requests_next_open_exit() -> None:
    state = ExitPolicyState(entry_price=10.0, armed_at=date(2026, 7, 14), highest_close=12.0, exit_line=11.0)
    decision = evaluate_shadow_exit(
        state,
        ExitObservation(date(2026, 7, 15), holding_session=3, close=10.9, atr=0.4),
    )
    assert decision.should_exit_next_open is True
    assert decision.reason == "close_below_trailing_line"


def test_session_nine_forces_session_ten_open_plan() -> None:
    state = ExitPolicyState.unarmed(entry_price=10.0)
    decision = evaluate_shadow_exit(
        state,
        ExitObservation(date(2026, 7, 23), holding_session=9, close=10.2, atr=0.3),
    )
    assert decision.should_exit_next_open is True
    assert decision.reason == "maximum_holding_session"


def test_entry_session_holds_without_arming() -> None:
    state = ExitPolicyState.unarmed(entry_price=10.0)

    decision = evaluate_shadow_exit(
        state,
        ExitObservation(date(2026, 7, 13), holding_session=1, close=12.0, atr=0.4),
    )

    assert decision.state.armed_at is None
    assert decision.should_exit_next_open is False
    assert decision.reason == "hold"


def test_trailing_line_uses_only_observed_close_and_fixed_atr_multiple() -> None:
    state = ExitPolicyState(entry_price=10.0, armed_at=date(2026, 7, 14), highest_close=11.0, exit_line=10.0)

    decision = evaluate_shadow_exit(
        state,
        ExitObservation(date(2026, 7, 15), holding_session=3, close=12.0, atr=0.4),
    )

    assert decision.state.highest_close == 12.0
    assert decision.state.exit_line == 11.0


def test_close_equal_to_line_holds() -> None:
    state = ExitPolicyState(entry_price=10.0, armed_at=date(2026, 7, 14), highest_close=12.0, exit_line=11.0)

    decision = evaluate_shadow_exit(
        state,
        ExitObservation(date(2026, 7, 15), holding_session=3, close=11.0, atr=0.4),
    )

    assert decision.should_exit_next_open is False
    assert decision.reason == "hold"


def test_arming_close_below_line_requests_next_open_exit() -> None:
    state = ExitPolicyState(
        entry_price=10.0,
        armed_at=None,
        highest_close=13.0,
        exit_line=None,
    )

    decision = evaluate_shadow_exit(
        state,
        ExitObservation(date(2026, 7, 14), holding_session=2, close=11.0, atr=0.4),
    )

    assert decision.state.armed_at == date(2026, 7, 14)
    assert decision.state.exit_line == 12.0
    assert decision.should_exit_next_open is True
    assert decision.reason == "close_below_trailing_line"


def test_policy_values_are_immutable() -> None:
    state = ExitPolicyState.unarmed(entry_price=10.0)
    observation = ExitObservation(date(2026, 7, 14), holding_session=2, close=11.0, atr=0.4)
    decision = evaluate_shadow_exit(state, observation)

    with pytest.raises(FrozenInstanceError):
        state.entry_price = 11.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        observation.close = 12.0  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        decision.reason = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("entry_price", [0.0, -1.0, math.nan, math.inf, -math.inf, None])
def test_policy_rejects_invalid_entry_price(entry_price: float | None) -> None:
    state = ExitPolicyState.unarmed(entry_price=entry_price)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="entry_price"):
        evaluate_shadow_exit(
            state,
            ExitObservation(date(2026, 7, 14), holding_session=2, close=11.0, atr=0.4),
        )


@pytest.mark.parametrize("field,value", [("close", 0.0), ("close", math.nan), ("atr", -1.0), ("atr", math.inf)])
def test_policy_rejects_invalid_observed_prices(field: str, value: float) -> None:
    values = {"close": 11.0, "atr": 0.4, field: value}

    with pytest.raises(ValueError, match=field):
        evaluate_shadow_exit(
            ExitPolicyState.unarmed(entry_price=10.0),
            ExitObservation(date(2026, 7, 14), holding_session=2, **values),
        )


@pytest.mark.parametrize("holding_session", [0, -1])
def test_policy_rejects_holding_sessions_below_one(holding_session: int) -> None:
    with pytest.raises(ValueError, match="holding_session"):
        evaluate_shadow_exit(
            ExitPolicyState.unarmed(entry_price=10.0),
            ExitObservation(date(2026, 7, 14), holding_session=holding_session, close=11.0, atr=0.4),
        )
