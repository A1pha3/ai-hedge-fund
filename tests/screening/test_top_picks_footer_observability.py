"""BH-017 footer diagnostic observability tests (c267).

The --top-picks footer renders the owner's NS-4 factor-feedback diagnostics
(monotonicity, significance, power, period/horizon breakdown, holding period,
payoff, pruning, bootstrap CI) — each wrapped in ``except Exception: pass``.
A regression in any compute function (e.g. a rank_monotonicity refactor) would
silently drop that diagnostic line with NO log, and the owner would not know
the factor-inversion detail they rely on went missing.

This pins: a failing footer compute fn emits a WARNING (naming the block), is
NOT silent, and does NOT abort sibling blocks / the front door.
"""

from __future__ import annotations

import logging
from pathlib import Path

import src.screening.rank_monotonicity as rm
from src.screening.top_picks import _print_monotonicity_block


def _raise(*_args: object, **_kw: object) -> None:
    raise ValueError("simulated refactor regression (c267 test)")


def test_monotonicity_footer_warns_on_significance_failure(caplog: object) -> None:
    """When compute_high_vs_low_significance_from_loaded raises, the footer logs
    a WARNING naming the significance block (was a silent except:pass before c267)."""
    import pytest

    report_dir = Path("data/reports")
    if not (report_dir / "tracking_history.json").exists():
        pytest.skip("data/reports/tracking_history.json not available in this environment")

    original = rm.compute_high_vs_low_significance_from_loaded
    rm.compute_high_vs_low_significance_from_loaded = _raise
    try:
        with caplog.at_level(logging.WARNING, logger="src.screening.top_picks"):
            _print_monotonicity_block(report_dir)  # must NOT raise (best-effort)
    finally:
        rm.compute_high_vs_low_significance_from_loaded = original

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "expected a WARNING when the significance footer block fails (was silent before c267)"
    assert any("significance" in r.getMessage() for r in warnings), (
        "warning should name the failing block so the owner can diagnose which diagnostic dropped"
    )


def test_monotonicity_footer_never_raises_on_diagnostic_failure(caplog: object) -> None:
    """A failing footer diagnostic must never propagate (best-effort; never breaks
    the front door) — the headline monotonicity line still renders."""
    import pytest

    report_dir = Path("data/reports")
    if not (report_dir / "tracking_history.json").exists():
        pytest.skip("data/reports/tracking_history.json not available in this environment")

    original_sig = rm.compute_high_vs_low_significance_from_loaded
    rm.compute_high_vs_low_significance_from_loaded = _raise
    try:
        with caplog.at_level(logging.WARNING, logger="src.screening.top_picks"):
            # Must not raise even though a diagnostic compute fn raises.
            _print_monotonicity_block(report_dir)
    finally:
        rm.compute_high_vs_low_significance_from_loaded = original_sig
    # If we got here, the footer did not propagate the exception.
