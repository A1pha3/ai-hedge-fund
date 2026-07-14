from datetime import date

import pytest

from src.screening.offensive.trade_lifecycle import (
    ExecutionMode,
    FillSource,
    TradeIdentity,
    TradeState,
    assert_transition,
    deterministic_trade_id,
)


def test_trade_id_is_deterministic_and_versioned() -> None:
    identity = TradeIdentity(
        ledger_id="paper-v2",
        setup="btst_breakout",
        setup_version="sha:abc123",
        ticker="300001",
        signal_date=date(2026, 7, 10),
        planned_entry_date=date(2026, 7, 13),
    )
    assert deterministic_trade_id(identity) == deterministic_trade_id(identity)
    assert deterministic_trade_id(identity) != deterministic_trade_id(
        identity.__class__(**{**identity.__dict__, "setup_version": "sha:def456"})
    )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (TradeState.PLANNED, TradeState.OPEN),
        (TradeState.PLANNED, TradeState.SKIPPED),
        (TradeState.OPEN, TradeState.EXIT_PENDING),
        (TradeState.EXIT_PENDING, TradeState.CLOSED),
    ],
)
def test_legal_transitions(before: TradeState, after: TradeState) -> None:
    assert_transition(before, after)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (before, after)
        for before in TradeState
        for after in TradeState
        if after not in {
            TradeState.PLANNED: {TradeState.OPEN, TradeState.SKIPPED},
            TradeState.OPEN: {TradeState.EXIT_PENDING},
            TradeState.EXIT_PENDING: {TradeState.CLOSED},
            TradeState.CLOSED: set(),
            TradeState.SKIPPED: set(),
        }[before]
    ],
)
def test_illegal_lifecycle_transition_matrix(before, after) -> None:
    with pytest.raises(ValueError, match="illegal transition"):
        assert_transition(before, after)


def test_fill_source_matches_execution_mode() -> None:
    assert FillSource.SYNTHETIC_OPEN.allowed_mode is ExecutionMode.PAPER
    assert FillSource.MANUAL_CONFIRMATION.allowed_mode is ExecutionMode.BROKER_CONFIRMED
    assert FillSource.BROKER_IMPORT.allowed_mode is ExecutionMode.BROKER_CONFIRMED
