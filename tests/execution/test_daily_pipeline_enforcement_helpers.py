"""Unit tests for src/execution/daily_pipeline_enforcement_helpers.py

Covers the pure mode-resolver functions and the extract_frozen_prior_by_ticker
helper that pulls historical prior data from a plan's risk_metrics or
reconstructs it from selection_targets. Skips the complex P3/P5/P6 enforce
integrations (those depend on router internals and are out of scope for
focused unit tests).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.execution.daily_pipeline_enforcement_helpers import (
    BTST_0422_P3_PRIOR_QUALITY_MODE_ENV,
    BTST_0422_P4_PRIOR_SHRINKAGE_MODE_ENV,
    BTST_0422_P5_EXECUTION_CONTRACT_MODE_ENV,
    BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE_ENV,
    BTST_0422_P6_RISK_BUDGET_MODE_ENV,
    extract_frozen_prior_by_ticker,
    resolve_btst_execution_contract_p5_mode,
    resolve_btst_prior_quality_p3_mode,
    resolve_btst_win_rate_first_precision_mode,
)
from src.execution.models import ExecutionPlan
from src.targets.models import DualTargetEvaluation, TargetEvaluationResult


def _dte(ticker: str, historical_prior: dict | None = None) -> DualTargetEvaluation:
    short_trade = None
    if historical_prior is not None:
        short_trade = TargetEvaluationResult(target_type="short_trade", metrics_payload={"historical_prior": historical_prior})
    return DualTargetEvaluation(ticker=ticker, trade_date="20260613", short_trade=short_trade)


# ---------------------------------------------------------------------------
# resolve_btst_prior_quality_p3_mode
# ---------------------------------------------------------------------------


def test_p3_mode_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BTST_0422_P3_PRIOR_QUALITY_MODE_ENV, raising=False)
    assert resolve_btst_prior_quality_p3_mode() == "off"


def test_p3_mode_enforce(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P3_PRIOR_QUALITY_MODE_ENV, "enforce")
    assert resolve_btst_prior_quality_p3_mode() == "enforce"


def test_p3_mode_invalid_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P3_PRIOR_QUALITY_MODE_ENV, "nonsense")
    assert resolve_btst_prior_quality_p3_mode() == "off"


def test_p3_mode_empty_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P3_PRIOR_QUALITY_MODE_ENV, "")
    assert resolve_btst_prior_quality_p3_mode() == "off"


# ---------------------------------------------------------------------------
# resolve_btst_execution_contract_p5_mode
# ---------------------------------------------------------------------------


def test_p5_mode_default_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BTST_0422_P5_EXECUTION_CONTRACT_MODE_ENV, raising=False)
    assert resolve_btst_execution_contract_p5_mode() == "off"


def test_p5_mode_enforce(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P5_EXECUTION_CONTRACT_MODE_ENV, "enforce")
    assert resolve_btst_execution_contract_p5_mode() == "enforce"


def test_p5_mode_invalid_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P5_EXECUTION_CONTRACT_MODE_ENV, "shadow")
    assert resolve_btst_execution_contract_p5_mode() == "off"


# ---------------------------------------------------------------------------
# resolve_btst_win_rate_first_precision_mode
# ---------------------------------------------------------------------------


def test_win_rate_first_mode_default_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE_ENV, raising=False)
    assert resolve_btst_win_rate_first_precision_mode() is False


def test_win_rate_first_mode_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE_ENV, "true")
    assert resolve_btst_win_rate_first_precision_mode() is True


def test_win_rate_first_mode_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    for val in ("1", "yes", "on", "TRUE", "YES", "On"):
        monkeypatch.setenv(BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE_ENV, val)
        assert resolve_btst_win_rate_first_precision_mode() is True, val


def test_win_rate_first_mode_invalid_false(monkeypatch: pytest.MonkeyPatch) -> None:
    for val in ("nonsense", "0", "no", "off", "false"):
        monkeypatch.setenv(BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE_ENV, val)
        assert resolve_btst_win_rate_first_precision_mode() is False, val


# ---------------------------------------------------------------------------
# extract_frozen_prior_by_ticker
# ---------------------------------------------------------------------------


def _plan(**overrides: Any) -> ExecutionPlan:
    base: dict[str, Any] = dict(
        date="20260613",
        risk_metrics={},
        selection_targets={},
    )
    base.update(overrides)
    return ExecutionPlan(**base)


def test_extract_prior_prefers_explicit_mapping_in_risk_metrics() -> None:
    explicit = {"000001": {"next_close_positive_rate": 0.7}}
    plan = _plan(risk_metrics={"historical_prior_by_ticker": explicit}, selection_targets={})
    assert extract_frozen_prior_by_ticker(plan) == explicit


def test_extract_prior_recovers_from_selection_targets_when_no_explicit() -> None:
    """When risk_metrics has no explicit mapping, recover from selection_targets.short_trade.metrics_payload.historical_prior."""
    plan = _plan(selection_targets={"000001": _dte("000001", historical_prior={"next_close": 0.6})})
    result = extract_frozen_prior_by_ticker(plan)
    assert result == {"000001": {"next_close": 0.6}}


def test_extract_prior_skips_evaluations_without_short_trade() -> None:
    plan = _plan(selection_targets={"000001": _dte("000001", historical_prior=None)})
    assert extract_frozen_prior_by_ticker(plan) == {}


def test_extract_prior_skips_evaluations_with_empty_historical_prior() -> None:
    plan = _plan(selection_targets={"000001": _dte("000001", historical_prior={})})
    assert extract_frozen_prior_by_ticker(plan) == {}


def test_extract_prior_explicit_mapping_wins_over_recovery() -> None:
    """Explicit mapping in risk_metrics takes precedence even if selection_targets has data."""
    plan = _plan(
        risk_metrics={"historical_prior_by_ticker": {"000001": {"from_explicit": True}}},
        selection_targets={"000001": _dte("000001", historical_prior={"from_recovery": True})},
    )
    result = extract_frozen_prior_by_ticker(plan)
    assert result == {"000001": {"from_explicit": True}}


def test_extract_prior_skips_blank_ticker_keys_in_explicit_mapping() -> None:
    plan = _plan(risk_metrics={"historical_prior_by_ticker": {"": {"x": 1}, "   ": {"x": 1}, "000001": {"valid": 1}}})
    result = extract_frozen_prior_by_ticker(plan)
    # Only "000001" has a non-blank ticker
    assert result == {"000001": {"valid": 1}}


def test_extract_prior_no_selection_targets_returns_explicit() -> None:
    plan = _plan(risk_metrics={"historical_prior_by_ticker": {"000001": {"x": 1}}}, selection_targets={})
    assert extract_frozen_prior_by_ticker(plan) == {"000001": {"x": 1}}


def test_extract_prior_empty_explicit_falls_back_to_recovery() -> None:
    """Empty explicit dict ({}) is falsy → fall back to recovery path."""
    plan = _plan(
        risk_metrics={"historical_prior_by_ticker": {}},
        selection_targets={"000001": _dte("000001", historical_prior={"next_close": 0.5})},
    )
    result = extract_frozen_prior_by_ticker(plan)
    assert result == {"000001": {"next_close": 0.5}}


def test_extract_prior_mixed_explicit_and_recovery() -> None:
    """Explicit mapping wins; selection_targets only contributes tickers NOT in explicit."""
    plan = _plan(
        risk_metrics={"historical_prior_by_ticker": {"000001": {"explicit": True}}},
        selection_targets={"000002": _dte("000002", historical_prior={"recovered": True})},
    )
    result = extract_frozen_prior_by_ticker(plan)
    # 000001 from explicit; 000002 NOT in explicit → recovery path used → but explicit branch returned early
    # So only 000001 should appear
    assert result == {"000001": {"explicit": True}}
