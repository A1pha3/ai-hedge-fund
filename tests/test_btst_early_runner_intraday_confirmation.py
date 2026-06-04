from __future__ import annotations

import pandas as pd

import src.targets.early_runner_intraday_confirmation as confirmation_module
from src.targets.early_runner_intraday_confirmation import (
    compute_confirm_assessment,
    compute_liquidity_score,
    compute_open_gap_quality,
)


def _base_row() -> dict[str, float]:
    """Build a compact early-runner row fixture for confirmation tests."""
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


def test_compute_confirm_assessment_falls_back_to_proxy_when_trade_date_missing() -> None:
    """Missing T+1 trade date should keep the contract on proxy fallback."""
    assessment = compute_confirm_assessment(
        _base_row(),
        ticker="300001",
        confirm_trade_date=None,
        max_open_gap=0.05,
        low_liquidity_threshold_wan_yuan=5000.0,
    )

    assert assessment["provenance"] == "proxy_fallback"
    assert assessment["inputs"] == {}
    assert assessment["intraday_metrics"] == {}
    assert 0.0 <= assessment["score"] <= 1.0


def test_compute_confirm_assessment_uses_intraday_live_payload_when_bars_exist(monkeypatch) -> None:
    """Available minute bars should switch the assessment into the live intraday path."""
    bars = pd.DataFrame(
        {
            "时间": ["2026-03-31 09:30:00", "2026-03-31 09:31:00", "2026-03-31 09:32:00"],
            "开盘": [10.0, 10.1, 10.2],
            "收盘": [10.1, 10.2, 10.3],
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
            "checks": {
                "open_gap_ok": True,
                "vwap_hold": True,
                "volume_ok": True,
                "theme_ok": True,
            },
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
    assert assessment["confirmed"] is True
    assert assessment["checks"]["vwap_hold"] is True
    assert assessment["inputs"]["minutes_since_open"] == 3
    assert assessment["intraday_metrics"] == {"vwap_gap": 0.03}
    assert assessment["score"] >= 0.72


def test_compute_open_gap_quality_fails_closed_for_over_gap_entries() -> None:
    """Over-gapped entries should score zero on the opening-gap quality leg."""
    assert compute_open_gap_quality(0.08, max_open_gap=0.05) == 0.0


def test_compute_liquidity_score_rejects_missing_or_too_thin_liquidity() -> None:
    """Liquidity scoring should fail closed when turnover is absent and stay bounded when thin."""
    assert compute_liquidity_score(None, low_liquidity_threshold_wan_yuan=5000.0) == 0.0
    assert compute_liquidity_score(1000.0, low_liquidity_threshold_wan_yuan=5000.0) == 0.1


def test_compute_confirm_assessment_outputs_are_t_plus_1_data() -> None:
    """P0A (2026-06-04): confirm_assessment outputs (score, provenance, checks) represent T+1 data.

    Downstream post_close_plan consumers must not use these fields directly.
    The _classify_point_in_time_status helper in generate_btst_doc_bundle.py
    is responsible for flagging boards containing these as 'unsafe' for post_close_plan.
    """
    row = _base_row()
    assessment = compute_confirm_assessment(
        row,
        ticker="300001",
        confirm_trade_date=None,  # no confirm date → proxy_fallback (no runtime data needed)
        max_open_gap=0.05,
        low_liquidity_threshold_wan_yuan=5000.0,
    )
    # These fields represent T+1 intraday data and must not be consumed in post_close_plan.
    assert "score" in assessment
    assert "provenance" in assessment
    assert "checks" in assessment
    # When provenance is proxy_fallback, the data is estimated from next_*_return fields
    # which are T+1 data — not available at post_close_plan (signal day close).
    assert assessment["provenance"] == "proxy_fallback"
    assert row.get("next_open_return") is not None
