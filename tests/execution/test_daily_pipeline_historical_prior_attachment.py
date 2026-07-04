"""Unit tests for src/execution/daily_pipeline_historical_prior_attachment.py

Covers relief refresh logic, entry attachment via DI resolver, and
watchlist attachment via model_copy.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.execution.daily_pipeline_historical_prior_attachment import (
    _refresh_attached_entry_relief,
    attach_historical_prior_to_entries,
    attach_historical_prior_to_watchlist,
)
from src.execution.models import LayerCResult

# ---------------------------------------------------------------------------
# _refresh_attached_entry_relief
# ---------------------------------------------------------------------------


def test_refresh_relief_non_post_gate_lane_unchanged() -> None:
    entry = {
        "candidate_pool_lane": "layer_a_liquidity_corridor",
        "short_trade_catalyst_relief": {"reason": "upstream_shadow_catalyst_relief"},
        "historical_prior": {"next_close_positive_rate": 0.3},
    }
    assert _refresh_attached_entry_relief(entry) == entry


def test_refresh_relief_wrong_reason_unchanged() -> None:
    entry = {
        "candidate_pool_lane": "post_gate_liquidity_competition",
        "short_trade_catalyst_relief": {"reason": "other_reason"},
        "historical_prior": {"next_close_positive_rate": 0.3},
    }
    assert _refresh_attached_entry_relief(entry) == entry


def test_refresh_relief_low_positive_rate_removes_relief() -> None:
    entry = {
        "candidate_pool_lane": "post_gate_liquidity_competition",
        "short_trade_catalyst_relief": {"reason": "upstream_shadow_catalyst_relief"},
        "historical_prior": {"next_close_positive_rate": 0.3},
    }
    result = _refresh_attached_entry_relief(entry)
    assert "short_trade_catalyst_relief" not in result


def test_refresh_relief_high_positive_rate_keeps_relief() -> None:
    entry = {
        "candidate_pool_lane": "post_gate_liquidity_competition",
        "short_trade_catalyst_relief": {"reason": "upstream_shadow_catalyst_relief"},
        "historical_prior": {"next_close_positive_rate": 0.6},
    }
    assert _refresh_attached_entry_relief(entry) == entry


def test_refresh_relief_boundary_0_5_keeps_relief() -> None:
    """0.5 is NOT < 0.5 → relief kept."""
    entry = {
        "candidate_pool_lane": "post_gate_liquidity_competition",
        "short_trade_catalyst_relief": {"reason": "upstream_shadow_catalyst_relief"},
        "historical_prior": {"next_close_positive_rate": 0.5},
    }
    assert _refresh_attached_entry_relief(entry) == entry


def test_refresh_relief_missing_positive_rate_keeps_relief() -> None:
    entry = {
        "candidate_pool_lane": "post_gate_liquidity_competition",
        "short_trade_catalyst_relief": {"reason": "upstream_shadow_catalyst_relief"},
        "historical_prior": {},
    }
    assert _refresh_attached_entry_relief(entry) == entry


def test_refresh_relief_no_existing_relief_unchanged() -> None:
    entry = {
        "candidate_pool_lane": "post_gate_liquidity_competition",
        "historical_prior": {"next_close_positive_rate": 0.3},
    }
    assert _refresh_attached_entry_relief(entry) == entry


def test_refresh_relief_does_not_mutate_input() -> None:
    entry = {
        "candidate_pool_lane": "post_gate_liquidity_competition",
        "short_trade_catalyst_relief": {"reason": "upstream_shadow_catalyst_relief"},
        "historical_prior": {"next_close_positive_rate": 0.3},
    }
    _refresh_attached_entry_relief(entry)
    assert "short_trade_catalyst_relief" in entry  # original unchanged


# ---------------------------------------------------------------------------
# attach_historical_prior_to_entries
# ---------------------------------------------------------------------------


def test_attach_prior_to_entries_uses_resolver() -> None:
    entries = [{"ticker": "000001", "candidate_source": "main"}, {"ticker": "000002", "candidate_source": "shadow"}]
    calls: list[dict] = []

    def _resolve(*, ticker, historical_prior, prior_by_ticker, candidate_source):
        calls.append({"ticker": ticker, "source": candidate_source})
        return {"next_close_positive_rate": 0.7} if ticker == "000001" else None

    result = attach_historical_prior_to_entries(entries, prior_by_ticker={"000001": {"x": 1}}, resolve_historical_prior_for_ticker_fn=_resolve)
    assert len(result) == 2
    assert result[0]["historical_prior"] == {"next_close_positive_rate": 0.7}
    # 000002 resolver returned None → no historical_prior key added
    assert "historical_prior" not in result[1]
    assert calls[0]["ticker"] == "000001"
    assert calls[0]["source"] == "main"


def test_attach_prior_to_entries_preserves_existing_when_resolver_returns_none() -> None:
    entries = [{"ticker": "000001", "historical_prior": {"existing": True}}]

    def _resolve(**k):
        return None

    result = attach_historical_prior_to_entries(entries, prior_by_ticker={}, resolve_historical_prior_for_ticker_fn=_resolve)
    # When resolver returns None, existing historical_prior is preserved (not overwritten)
    assert result[0]["historical_prior"] == {"existing": True}


def test_attach_prior_to_entries_applies_relief_refresh() -> None:
    entries = [
        {
            "ticker": "000001",
            "candidate_pool_lane": "post_gate_liquidity_competition",
            "short_trade_catalyst_relief": {"reason": "upstream_shadow_catalyst_relief"},
        }
    ]

    def _resolve(**k):
        return {"next_close_positive_rate": 0.3}  # low → relief removed

    result = attach_historical_prior_to_entries(entries, prior_by_ticker={}, resolve_historical_prior_for_ticker_fn=_resolve)
    assert "short_trade_catalyst_relief" not in result[0]


def test_attach_prior_to_entries_empty_list() -> None:
    result = attach_historical_prior_to_entries([], prior_by_ticker={}, resolve_historical_prior_for_ticker_fn=lambda **k: None)
    assert result == []


# ---------------------------------------------------------------------------
# attach_historical_prior_to_watchlist
# ---------------------------------------------------------------------------


def _layer_c(ticker: str) -> LayerCResult:
    return LayerCResult(ticker=ticker, score_c=0.5)


def test_attach_prior_to_watchlist_attaches_when_present() -> None:
    watchlist = [_layer_c("000001"), _layer_c("000002")]
    result = attach_historical_prior_to_watchlist(watchlist, prior_by_ticker={"000001": {"next_close_positive_rate": 0.7}})
    assert result[0].historical_prior == {"next_close_positive_rate": 0.7}
    # 000002 not in prior → unchanged (no historical_prior)
    assert result[1].ticker == "000002"


def test_attach_prior_to_watchlist_no_prior_unchanged() -> None:
    watchlist = [_layer_c("000001")]
    result = attach_historical_prior_to_watchlist(watchlist, prior_by_ticker={})
    assert result[0].ticker == "000001"


def test_attach_prior_to_watchlist_empty() -> None:
    result = attach_historical_prior_to_watchlist([], prior_by_ticker={})
    assert result == []


def test_attach_prior_to_watchlist_none() -> None:
    result = attach_historical_prior_to_watchlist(None, prior_by_ticker={})  # type: ignore[arg-type]
    assert result == []
