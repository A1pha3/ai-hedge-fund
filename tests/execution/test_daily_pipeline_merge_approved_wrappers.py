"""Unit tests for src/execution/daily_pipeline_merge_approved_wrappers.py

Covers the small, isolated wrapper helpers: arbitration-label append,
breakout/alignment diagnostics lookups, batch summary builders, the
default watchlist classifier, and the layer-b filter diagnostics that
drops already-promoted tickers.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.execution.daily_pipeline_merge_approved_wrappers import (
    _alignment_diagnostics_for_ticker,
    _breakout_diagnostics_for_ticker,
    _build_batch_uplift_summary,
    _build_layer_b_filter_diagnostics,
    _classify_watchlist_entry_default,
    _merge_approved_arbitration_applied,
)


# ---------------------------------------------------------------------------
# _merge_approved_arbitration_applied
# ---------------------------------------------------------------------------


def test_arbitration_applied_adds_label() -> None:
    item = SimpleNamespace(arbitration_applied=["consensus_bonus"])
    result = _merge_approved_arbitration_applied(item, "merge_approved_uplift")
    assert result == ["consensus_bonus", "merge_approved_uplift"]


def test_arbitration_applied_dedupes() -> None:
    item = SimpleNamespace(arbitration_applied=["merge_approved_uplift"])
    result = _merge_approved_arbitration_applied(item, "merge_approved_uplift")
    assert result == ["merge_approved_uplift"]


def test_arbitration_applied_none_initial() -> None:
    item = SimpleNamespace(arbitration_applied=None)
    result = _merge_approved_arbitration_applied(item, "merge_approved_uplift")
    assert result == ["merge_approved_uplift"]


def test_arbitration_applied_empty_list() -> None:
    item = SimpleNamespace(arbitration_applied=[])
    result = _merge_approved_arbitration_applied(item, "merge_approved_uplift")
    assert result == ["merge_approved_uplift"]


# ---------------------------------------------------------------------------
# _breakout_diagnostics_for_ticker / _alignment_diagnostics_for_ticker
# ---------------------------------------------------------------------------


def test_breakout_diagnostics_for_ticker_present() -> None:
    uplift = {"000001": {"boost": 0.05}}
    assert _breakout_diagnostics_for_ticker(uplift, "000001") == {"boost": 0.05}


def test_breakout_diagnostics_for_ticker_missing() -> None:
    assert _breakout_diagnostics_for_ticker({"000001": {"boost": 0.05}}, "000002") == {}


def test_breakout_diagnostics_for_ticker_none_uplift() -> None:
    assert _breakout_diagnostics_for_ticker(None, "000001") == {}


def test_breakout_diagnostics_for_ticker_none_entry() -> None:
    uplift = {"000001": None}
    assert _breakout_diagnostics_for_ticker(uplift, "000001") == {}


def test_alignment_diagnostics_for_ticker_present() -> None:
    uplift = {"000001": {"alignment_score": 0.7}}
    assert _alignment_diagnostics_for_ticker(uplift, "000001") == {"alignment_score": 0.7}


def test_alignment_diagnostics_for_ticker_missing() -> None:
    assert _alignment_diagnostics_for_ticker({"000001": {"x": 1}}, "000002") == {}


def test_alignment_diagnostics_for_ticker_none() -> None:
    assert _alignment_diagnostics_for_ticker(None, "000001") == {}


# ---------------------------------------------------------------------------
# _build_batch_uplift_summary
# ---------------------------------------------------------------------------


def test_build_batch_uplift_summary_collects_keys() -> None:
    result = _build_batch_uplift_summary(
        by_ticker={"000001": {"x": 1}},
        eligible_tickers=["000001"],
        applied_tickers=["000001"],
        extra_ignored="ignored",
    )
    assert result == {"by_ticker": {"000001": {"x": 1}}, "eligible_tickers": ["000001"], "applied_tickers": ["000001"]}


def test_build_batch_uplift_summary_missing_keys_default_empty() -> None:
    result = _build_batch_uplift_summary()
    assert result == {"by_ticker": {}, "eligible_tickers": [], "applied_tickers": []}


# ---------------------------------------------------------------------------
# _classify_watchlist_entry_default
# ---------------------------------------------------------------------------


def _layer_c(decision: str = "neutral", score_final: float = 0.5, bc_conflict: str | None = None) -> Any:
    return SimpleNamespace(decision=decision, score_final=score_final, bc_conflict=bc_conflict)


def test_classify_watchlist_retained_default() -> None:
    primary, reasons = _classify_watchlist_entry_default(_layer_c())
    assert primary == "retained"
    assert reasons == []


def test_classify_watchlist_avoid_decision() -> None:
    primary, reasons = _classify_watchlist_entry_default(_layer_c(decision="avoid"))
    assert primary == "decision_avoid"
    assert "decision_avoid" in reasons


def test_classify_watchlist_low_score() -> None:
    primary, reasons = _classify_watchlist_entry_default(_layer_c(score_final=0.05))
    assert primary == "score_final_below_watchlist_threshold"
    assert "score_final_below_watchlist_threshold" in reasons


def test_classify_watchlist_bc_conflict() -> None:
    primary, reasons = _classify_watchlist_entry_default(_layer_c(bc_conflict="trend_vs_fundamental"))
    assert primary == "bc_conflict"
    assert "bc_conflict" in reasons


def test_classify_watchlist_multiple_reasons() -> None:
    """decision_avoid is checked first; multiple reasons appended; primary = first."""
    item = _layer_c(decision="avoid", score_final=0.05, bc_conflict="x")
    primary, reasons = _classify_watchlist_entry_default(item)
    assert primary == "decision_avoid"
    assert "decision_avoid" in reasons
    assert "score_final_below_watchlist_threshold" in reasons
    assert "bc_conflict" in reasons


# ---------------------------------------------------------------------------
# _build_layer_b_filter_diagnostics
# ---------------------------------------------------------------------------


def test_build_layer_b_filter_diagnostics_drops_high_pool_tickers() -> None:
    fused = [
        SimpleNamespace(ticker="000001", score_b=0.8, decision="buy"),
        SimpleNamespace(ticker="000002", score_b=0.1, decision="watch"),
        SimpleNamespace(ticker="000003", score_b=0.05, decision="avoid"),
    ]
    high_pool = [SimpleNamespace(ticker="000001")]  # already promoted

    received: list = []

    def _build_summary(entries):
        received.append(entries)
        return {"filtered": len(entries)}

    result = _build_layer_b_filter_diagnostics(fused, high_pool, build_filter_summary_fn=_build_summary)
    assert result == {"filtered": 2}
    # The two tickers in high_pool are excluded
    tickers = {e["ticker"] for e in received[0]}
    assert "000001" not in tickers
    assert tickers == {"000002", "000003"}


def test_build_layer_b_filter_diagnostics_all_in_high_pool_empty() -> None:
    fused = [SimpleNamespace(ticker="000001", score_b=0.8, decision="buy")]
    high_pool = [SimpleNamespace(ticker="000001")]

    def _build_summary(entries):
        return {"filtered": len(entries)}

    result = _build_layer_b_filter_diagnostics(fused, high_pool, build_filter_summary_fn=_build_summary)
    assert result == {"filtered": 0}


def test_build_layer_b_filter_diagnostics_empty_high_pool() -> None:
    fused = [SimpleNamespace(ticker="000001", score_b=0.8, decision="buy")]

    received: list = []

    def _build_summary(entries):
        received.append(entries)
        return {"filtered": len(entries)}

    _build_layer_b_filter_diagnostics(fused, [], build_filter_summary_fn=_build_summary)
    assert received[0][0]["score_b"] == 0.8
    assert received[0][0]["decision"] == "buy"
