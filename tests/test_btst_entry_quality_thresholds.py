"""Tests for src.paper_trading._btst_reporting.entry_builders threshold parsing.

R-5 (C170): ``_resolve_selected_execution_quality_thresholds`` previously used
``int(thresholds.get(key) or DEFAULT)`` for the two ``min_evaluable_count``
fields. That truthiness ``or`` silently overrides an explicit ``0`` config
(legitimate "no minimum evaluable-count required — apply demotion regardless of
sample size"). Same falsy-zero class as R107 (carryover_min_historical_evaluable_count).

``resolve_strategy_thresholds`` merges repo config + overrides and itself respects
explicit values via ``is not None`` (scripts/btst_strategy_thresholds.py:99), so the
consumer dropping an explicit 0 is an inconsistency / real config-respect defect.
The sibling field ``selected_intraday_only_max_next_close_positive_rate`` in the same
function already uses the correct ``is not None`` presence-check — the author knew the
right pattern but missed the two count fields.
"""

from __future__ import annotations

import pytest

from src.paper_trading._btst_reporting import entry_builders


def test_explicit_zero_min_evaluable_count_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit 0 config must survive — not be silently overridden by the default 3.

    Operator config ``selected_zero_follow_through_min_evaluable_count: 0`` means
    "demote zero_follow_through entries regardless of evaluable sample size"
    (the demotion check becomes ``evaluable_count >= 0`` = always true). The ``or``
    bug overrode this to the WEAK_NEAR_MISS default (3), silently requiring >= 3
    samples — contradicting the operator's explicit config.
    """
    monkeypatch.setattr(
        entry_builders,
        "resolve_strategy_thresholds",
        lambda: {
            "selected_zero_follow_through_min_evaluable_count": 0,
            "selected_intraday_only_min_evaluable_count": 0,
            "selected_intraday_only_max_next_close_positive_rate": 0.0,
        },
    )
    thresholds = entry_builders._resolve_selected_execution_quality_thresholds()
    assert thresholds["selected_zero_follow_through_min_evaluable_count"] == 0
    assert thresholds["selected_intraday_only_min_evaluable_count"] == 0


def test_missing_keys_fall_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing keys still fall back to the WEAK_NEAR_MISS default (behavior preserved)."""
    from src.paper_trading.btst_reporting_utils import (
        WEAK_NEAR_MISS_DEMOTION_MIN_EVALUABLE_COUNT,
    )

    monkeypatch.setattr(entry_builders, "resolve_strategy_thresholds", lambda: {})
    thresholds = entry_builders._resolve_selected_execution_quality_thresholds()
    assert thresholds["selected_zero_follow_through_min_evaluable_count"] == WEAK_NEAR_MISS_DEMOTION_MIN_EVALUABLE_COUNT
    assert thresholds["selected_intraday_only_min_evaluable_count"] == WEAK_NEAR_MISS_DEMOTION_MIN_EVALUABLE_COUNT


def test_nonzero_config_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    """A normal non-zero config value is honored (regression guard)."""
    monkeypatch.setattr(
        entry_builders,
        "resolve_strategy_thresholds",
        lambda: {
            "selected_zero_follow_through_min_evaluable_count": 5,
            "selected_intraday_only_min_evaluable_count": 7,
        },
    )
    thresholds = entry_builders._resolve_selected_execution_quality_thresholds()
    assert thresholds["selected_zero_follow_through_min_evaluable_count"] == 5
    assert thresholds["selected_intraday_only_min_evaluable_count"] == 7
