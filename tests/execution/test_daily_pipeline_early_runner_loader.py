"""BH-033 / R57-R60 BH-017 同族续集: execution pipeline early-runner runtime
artifact loader observability guards.

`_load_early_runner_runtime_entries` feeds early-runner promoted entries into
`short_trade_candidate_diagnostics.tickers`, which drives trading decisions.
When the artifact JSON is corrupt / unreadable, the loader previously returned
``[]`` silently with no diagnostic — same silent-degradation pattern as the
BH-017 family (campaigns 25-30) but in the execution-pipeline data-loading
dimension. These guards assert the degradation is now observable via
``logger.debug`` (behavior preserved: still returns ``[]``).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

import src.execution.daily_pipeline as daily_pipeline_module
from src.execution.daily_pipeline import _load_early_runner_runtime_entries


def _write_artifact(tmp_path: Path, payload: object) -> Path:
    """Write payload to the early-runner runtime artifact path and patch the
    module constant to point at it."""
    artifact = tmp_path / "btst_early_runner_v1_latest.json"
    if isinstance(payload, str):
        artifact.write_text(payload, encoding="utf-8")
    else:
        artifact.write_text(json.dumps(payload), encoding="utf-8")
    return artifact


def test_corrupt_artifact_logs_debug_and_returns_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    """BH-033: corrupt JSON must return [] AND emit a debug diagnostic.

    Without the diagnostic, an ops engineer debugging "why did early-runner
    promoted entries silently disappear from today's short-trade candidates"
    has no signal to trace the corrupt-artifact root cause.
    """
    artifact = _write_artifact(tmp_path, "{not valid json")
    monkeypatch.setattr(daily_pipeline_module, "_EARLY_RUNNER_RUNTIME_ARTIFACT", artifact)

    with caplog.at_level(logging.DEBUG, logger="src.execution.daily_pipeline"):
        result = _load_early_runner_runtime_entries("20260617")

    # Behavior preserved: corrupt artifact → empty list (graceful degradation).
    assert result == []
    # Observability: degradation must be logged (the BH-033 fix).
    assert any("early" in rec.message.lower() and ("runner" in rec.message.lower() or "artifact" in rec.message.lower()) for rec in caplog.records), "BH-033: corrupt early-runner artifact must emit a debug diagnostic; " f"got records: {[r.message for r in caplog.records]}"


def test_missing_artifact_returns_empty_silently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Missing artifact (common first-run / no-prior-day case) returns [] quietly.

    This is the expected live state on a fresh machine; it should NOT emit a
    degradation warning (no failure occurred). Guards against over-warning.
    """
    missing = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(daily_pipeline_module, "_EARLY_RUNNER_RUNTIME_ARTIFACT", missing)
    result = _load_early_runner_runtime_entries("20260617")
    assert result == []


def test_malformed_shadow_strategy_signal_logs_debug(caplog: pytest.LogCaptureFixture):
    """BH-033 same-class drain: malformed shadow strategy signal must emit debug.

    `_coerce_upstream_shadow_strategy_signal` drops malformed signals silently in
    the shadow-watchlist promotion path. Without a diagnostic, ops cannot trace
    why a promotion's strategy_signals shrank. Behavior preserved (returns None).
    """
    from src.execution.daily_pipeline_upstream_shadow_helpers import (
        _coerce_upstream_shadow_strategy_signal,
    )

    # A dict missing required StrategySignal fields → ValidationError → None.
    malformed = {"unknown_key": "not a valid strategy signal"}

    with caplog.at_level(
        logging.DEBUG,
        logger="src.execution.daily_pipeline_upstream_shadow_helpers",
    ):
        result = _coerce_upstream_shadow_strategy_signal(malformed)

    assert result is None
    assert any("shadow" in rec.message.lower() and "signal" in rec.message.lower() for rec in caplog.records), "BH-033 same-class: malformed shadow signal must emit a debug diagnostic; " f"got records: {[r.message for r in caplog.records]}"
