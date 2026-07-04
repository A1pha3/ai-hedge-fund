"""NS-6 score_decomposition injection — observability + robustness tests.

Background (autodev c266 first-principles audit of the NS-4 flip feedback loop):
- main.py injects ``compute_score_decomposition`` into each ranking_pool rec so
  factor_attribution can attribute returns to factors (which factor is inverted).
- The injection was ``try/except Exception: pass`` (BH-017 silent-degradation):
  if ``compute_score_decomposition`` ever raises (e.g. after a signal_fusion
  refactor), every rec silently loses decomposition → factor_attribution goes
  "insufficient" with NO log, and the owner can't tell why the factor-feedback
  loop broke mid-tuning-iteration.
- Only 12/8005 tracking_history records currently carry decomposition (the feature
  is new); silent failure would mask a regression that blocks the owner's
  NS-4-flip evaluation.

This test pins: (1) success injects + counts; (2) failure logs a warning, leaves
the rec without decomposition, and does NOT block sibling recs.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.main import _inject_score_decomposition

if TYPE_CHECKING:
    import pytest


def test_inject_score_decomposition_success_injects_and_counts() -> None:
    """Happy path: decomposition is written and the success count is returned."""
    fused_a = object()
    fused_b = object()
    fused_by_ticker = {"000001": fused_a, "000002": fused_b}
    recs = [{"ticker": "000001"}, {"ticker": "000002"}]
    # Patch at the source module (the helper imports it lazily).
    import src.screening.signal_fusion as sf

    original = sf.compute_score_decomposition
    sf.compute_score_decomposition = lambda item: {"total": 0.5 if item is fused_a else 0.4}
    try:
        count = _inject_score_decomposition(recs, fused_by_ticker)
    finally:
        sf.compute_score_decomposition = original
    assert count == 2
    assert recs[0]["score_decomposition"] == {"total": 0.5}
    assert recs[1]["score_decomposition"] == {"total": 0.4}


def test_inject_score_decomposition_failure_logs_warning_and_continues(caplog: pytest.LogCaptureFixture) -> None:
    """When compute raises for one rec, a warning is logged, that rec is skipped,
    and sibling recs are still processed (best-effort, NOT silent, NOT blocking)."""

    fused_a = object()
    fused_b = object()
    fused_by_ticker = {"000001": fused_a, "000002": fused_b}
    recs = [{"ticker": "000001"}, {"ticker": "000002"}]

    import src.screening.signal_fusion as sf

    original = sf.compute_score_decomposition

    def _flaky(item: object) -> dict:
        if item is fused_a:
            raise ValueError("boom (simulated signal_fusion refactor regression)")
        return {"total": 0.4}

    sf.compute_score_decomposition = _flaky
    try:
        with caplog.at_level(logging.WARNING, logger="src.main"):
            count = _inject_score_decomposition(recs, fused_by_ticker)
    finally:
        sf.compute_score_decomposition = original

    # Only the second rec succeeded.
    assert count == 1
    # The failed rec has NO decomposition key (not a partial/None value).
    assert "score_decomposition" not in recs[0]
    # The sibling rec still got its decomposition (failure did not abort the loop).
    assert recs[1]["score_decomposition"] == {"total": 0.4}
    # A warning was emitted naming the failing ticker — NOT silent.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "expected a WARNING log when decomposition injection fails (was silent before c266)"
    assert any("000001" in r.getMessage() for r in warnings)


def test_inject_score_decomposition_skips_rec_not_in_fused_map() -> None:
    """A rec whose ticker is absent from fused_by_ticker is skipped silently
    (no fused item to decompose) and is not counted as injected."""
    fused_by_ticker = {"000001": object()}
    recs = [{"ticker": "000001"}, {"ticker": "999999"}]  # 999999 not in fused map
    import src.screening.signal_fusion as sf

    original = sf.compute_score_decomposition
    sf.compute_score_decomposition = lambda item: {"total": 0.5}
    try:
        count = _inject_score_decomposition(recs, fused_by_ticker)
    finally:
        sf.compute_score_decomposition = original
    assert count == 1
    assert recs[0]["score_decomposition"] == {"total": 0.5}
    assert "score_decomposition" not in recs[1]
