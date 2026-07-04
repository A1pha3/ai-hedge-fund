"""TDD red test: early-runner intraday confirmation must not propagate NaN
close into runtime inputs (R83 same-class drain — ``float(x or 0.0)`` does NOT
catch NaN because NaN is truthy in Python; the author's own ``fillna(0.0)``
pattern on sibling vwap/amount lines proves NaN is expected in intraday data).

``_build_realtime_intraday_inputs`` (early_runner_intraday_confirmation.py:164)
computes ``current_price = float(first_window.iloc[-1].get("close") or 0.0)``.
A NaN close on the last minute bar (thinly-traded stock with no prints in the
final bar, or a partial/incomplete live feed) → ``NaN or 0.0`` returns NaN
(NaN is truthy) → ``current_price = NaN`` → propagates into runtime_inputs
(stock_pct_change, vwap, ema30 fallback, day_low, failed_breakout all NaN) →
``confirm_buy_signal`` receives NaN inputs → the early-runner intraday
confirmation decision is silently corrupted.

The sibling vwap/amount lines (170-171) already use ``.fillna(0.0)`` which
DOES catch NaN — inconsistent guarding within the same function. Fix: use the
author's own ``fillna`` pattern so NaN close → 0.0 (matching the documented
``or 0.0`` fallback intent for None/missing), not NaN propagation.
"""

from __future__ import annotations

import math

import pandas as pd

import src.targets.early_runner_intraday_confirmation as confirmation_module
from src.targets.early_runner_intraday_confirmation import compute_confirm_assessment


def _base_row() -> dict[str, float]:
    return {
        "next_open_return": 0.01,
        "next_open_to_close_return": 0.02,
        "next_high_return": 0.05,
        "next_close_return": 0.03,
        "gap_to_limit": 0.04,
        "sector_resonance": 0.62,
        "catalyst_theme_score": 0.85,
        "estimated_amount_1d_wan_yuan": 15000.0,
        "pre_score_rank_quality": 0.80,
    }


def test_nan_open_first_bar_does_not_propagate_nan_open_price(monkeypatch) -> None:
    """A NaN open on the first bar (valid close, passes _normalize's
    dropna(subset=['close'])) must not propagate NaN into runtime inputs.
    ``float(NaN or close or 0.0)`` = NaN because NaN is truthy and short-
    circuits the ``or`` chain — so open_price, breakout_anchor, and
    failed_breakout all become NaN/corrupted. The sibling vwap/amount lines
    use ``fillna`` which catches NaN; line 161's ``or`` chain does not."""
    # 3 bars: NaN open on FIRST bar (iloc[0]), valid close → passes dropna
    bars = pd.DataFrame(
        {
            "时间": ["2026-03-31 09:30:00", "2026-03-31 09:31:00", "2026-03-31 09:32:00"],
            "开盘": [float("nan"), 10.1, 10.2],  # first bar NaN open
            "收盘": [10.1, 10.2, 10.3],  # valid close → passes dropna(subset=["close"])
            "最高": [10.1, 10.25, 10.35],
            "最低": [9.98, 10.05, 10.18],
            "成交额": [1_000_000.0, 1_200_000.0, 1_400_000.0],
            "成交量": [100_000.0, 110_000.0, 120_000.0],
        }
    )
    monkeypatch.setattr(confirmation_module, "get_intraday_bars", lambda ticker, trade_date: bars)
    monkeypatch.setattr(
        confirmation_module,
        "confirm_buy_signal",
        lambda **kwargs: {
            "confirmed": True,
            "passed_checks": 4,
            "checks": {"open_gap_ok": True, "vwap_hold": True, "volume_ok": True, "theme_ok": True},
            "hard_failures": {},
        },
    )
    monkeypatch.setattr(confirmation_module, "build_intraday_short_trade_metrics", lambda ticker, trade_date: {"vwap_gap": 0.03})

    assessment = compute_confirm_assessment(
        _base_row(),
        ticker="300001",
        confirm_trade_date="2026-03-31",
        max_open_gap=0.05,
        low_liquidity_threshold_wan_yuan=5000.0,
    )

    assert assessment["provenance"] == "intraday_live"
    inputs = assessment["inputs"]
    # open_price must be finite — NaN open must not propagate via 'or' chain
    open_price = inputs["open_price"]
    assert isinstance(open_price, (int, float))
    assert math.isfinite(open_price), f"NaN open on first bar must not propagate to NaN open_price; " f"got {open_price} (float(NaN or close or 0.0) = NaN because NaN is " f"truthy and short-circuits the 'or' chain; sibling vwap lines use " f"fillna which catches NaN — inconsistent)"
    # breakout_anchor (max(prev_close, open_price)) must also be finite
    assert math.isfinite(float(inputs["breakout_anchor"])), "breakout_anchor must be finite — NaN open_price propagates here too"
