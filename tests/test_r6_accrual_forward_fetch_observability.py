"""c317c (loop 51) — forward-window fetch failure observability in the R6
multi-horizon accrual diagnostic.

The c315 accrual diagnostic is the DIRECT INSTRUMENT for the R6 direction-sign
verdict the owner used to decide A/keep (2026-07-03). Its own docstring (L19,
L98) warns that silent data gaps could 'fake N' and flip the direction delta.
Yet ``_collect_one_date``'s forward-window fetch (L155-162) had a bare
``except Exception:`` that swallowed ANY pro.daily() error (rate-limit, network,
auth, parse) into ``fwd_cache[td] = {}`` — indistinguishable from a genuine
empty trading day. A transient API failure would silently reduce per-horizon
maturity, and the operator would only see 'fewer mature rows' with no clue it
was an API error. Same NS-17 disease class as c267-c295 / c317b.

This test asserts the failure is now OBSERVABLE (a warning fires naming the
failed date + exception), without hitting the network (monkeypatches pro.daily).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

import scripts._diag_r6_multihorizon_accrual as m  # noqa: E402


def test_forward_fetch_failure_is_logged_not_silent(caplog):
    """A pro.daily() failure in the forward-window fetch must emit a warning
    naming the failed trade_date + the exception (NS-17 drain). Pre-fix the
    bare ``except Exception:`` swallowed it silently into fwd_cache[td]={}."""
    trade_dates = ["20260601", "20260602", "20260603", "20260604",
                   "20260605", "20260606", "20260607"]

    class _BoomPro:
        """Fake pro whose daily() always raises (simulates API rate-limit/timeout)."""
        def daily(self, trade_date: str):
            raise RuntimeError("simulated API rate-limit")

    fwd_cache: dict = {}
    with caplog.at_level(logging.WARNING, logger=m.logger.name):
        # di=0 → forward window is trade_dates[1..6]; each fetch should fail+log.
        # NOTE: _collect_one_date also calls get_universe_for_date(pro, ...) after
        # the forward-fetch loop, which our _BoomPro doesn't support and will raise
        # — that's fine; we only care that the forward-fetch warnings fired FIRST.
        try:
            m._collect_one_date(
                _BoomPro(), test_date="20260601", di=0,
                trade_dates=trade_dates, horizons=(1, 5, 10),
                stock_basic=pd.DataFrame({"ts_code": ["000001.SZ"]}),
                fwd_cache=fwd_cache,
            )
        except Exception:
            pass  # downstream universe-fetch crash expected with fake pro
    # The failed forward dates must each have triggered a warning (not silent).
    warnings_about_fetch = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "fetch" in r.getMessage().lower()
    ]
    assert warnings_about_fetch, (
        "forward-window fetch failure must emit a WARNING (was silent pre-fix); "
        f"got records: {[r.getMessage() for r in caplog.records]}"
    )
    # The warning must name a failed trade_date (so operator can locate it).
    joined = " ".join(r.getMessage() for r in warnings_about_fetch)
    assert any(d in joined for d in trade_dates[1:]), (
        f"warning should name the failed trade_date, got: {joined!r}"
    )
