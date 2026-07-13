"""Pure fixed-parameter exit policy for research and shadow evaluation only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
from numbers import Real


ACTIVATION_RETURN = 0.10
ATR_MULTIPLE = 2.5
PLAN_EXIT_SESSION = 9


@dataclass(frozen=True)
class ExitPolicyState:
    entry_price: float
    armed_at: date | None
    highest_close: float | None
    exit_line: float | None

    @classmethod
    def unarmed(cls, *, entry_price: float) -> ExitPolicyState:
        return cls(
            entry_price=entry_price,
            armed_at=None,
            highest_close=None,
            exit_line=None,
        )


@dataclass(frozen=True)
class ExitObservation:
    session_date: date
    holding_session: int
    close: float
    atr: float


@dataclass(frozen=True)
class ExitDecision:
    state: ExitPolicyState
    should_exit_next_open: bool
    reason: str


def evaluate_shadow_exit(
    state: ExitPolicyState,
    observation: ExitObservation,
) -> ExitDecision:
    """Evaluate one completed A-share session without execution side effects."""

    _validate_inputs(state, observation)

    highest_close = max(
        observation.close,
        state.highest_close if state.highest_close is not None else observation.close,
    )

    if observation.holding_session == 1:
        return _hold(
            ExitPolicyState(
                entry_price=state.entry_price,
                armed_at=None,
                highest_close=highest_close,
                exit_line=None,
            )
        )

    next_state = state
    if state.armed_at is None and observation.close / state.entry_price - 1.0 >= ACTIVATION_RETURN:
        next_state = ExitPolicyState(
            entry_price=state.entry_price,
            armed_at=observation.session_date,
            highest_close=highest_close,
            exit_line=highest_close - ATR_MULTIPLE * observation.atr,
        )
    elif state.armed_at is None:
        next_state = ExitPolicyState(
            entry_price=state.entry_price,
            armed_at=None,
            highest_close=highest_close,
            exit_line=None,
        )
    else:
        assert state.exit_line is not None
        next_state = ExitPolicyState(
            entry_price=state.entry_price,
            armed_at=state.armed_at,
            highest_close=highest_close,
            exit_line=max(
                state.exit_line,
                highest_close - ATR_MULTIPLE * observation.atr,
            ),
        )

    if observation.holding_session == PLAN_EXIT_SESSION:
        return ExitDecision(next_state, True, "maximum_holding_session")

    if (
        next_state.armed_at is not None
        and next_state.exit_line is not None
        and observation.close < next_state.exit_line
    ):
        return ExitDecision(next_state, True, "close_below_trailing_line")

    return _hold(next_state)


def _hold(state: ExitPolicyState) -> ExitDecision:
    return ExitDecision(state, False, "hold")


def _validate_inputs(state: ExitPolicyState, observation: ExitObservation) -> None:
    _require_positive_finite("entry_price", state.entry_price)
    _require_positive_finite("close", observation.close)
    _require_positive_finite("atr", observation.atr)

    if not isinstance(observation.session_date, date):
        raise ValueError("session_date must be present")
    if (
        isinstance(observation.holding_session, bool)
        or not isinstance(observation.holding_session, int)
        or observation.holding_session < 1
    ):
        raise ValueError("holding_session must be an integer at least 1")

    if state.highest_close is not None:
        _require_positive_finite("highest_close", state.highest_close)
    if state.exit_line is not None and not _is_finite_number(state.exit_line):
        raise ValueError("exit_line must be finite")

    armed_values = (state.armed_at, state.highest_close, state.exit_line)
    if state.armed_at is None and state.exit_line is not None:
        raise ValueError("unarmed state cannot have an exit_line")
    if state.armed_at is not None:
        if not isinstance(state.armed_at, date):
            raise ValueError("armed_at must be a date")
        if any(value is None for value in armed_values):
            raise ValueError("armed state requires armed_at, highest_close, and exit_line")


def _require_positive_finite(name: str, value: object) -> None:
    if not _is_finite_number(value) or value <= 0:
        raise ValueError(f"{name} must be positive and finite")


def _is_finite_number(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)
