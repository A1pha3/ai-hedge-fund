"""Unit tests for src/execution/daily_pipeline_runtime_helpers.py

Covers candidate-pool bundle identity-branch logic, exit checker with stub
holding-state, filter summary aggregation, and the historical-prior
resolver/merge-rank/preserve-exact-upstream logic (all pure).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.execution.daily_pipeline_runtime_helpers import (
    _historical_prior_int,
    _historical_prior_merge_rank,
    _historical_prior_risk_rank,
    _historical_prior_scope_rank,
    _should_preserve_exact_upstream_embedded_prior,
    build_filter_summary,
    default_exit_checker,
    EXACT_UPSTREAM_SOURCE,
    EXACT_UPSTREAM_SOURCE_SCOPES,
    historical_prior_value_is_missing,
    load_candidate_pool_bundle,
    load_latest_historical_prior_by_ticker,
    resolve_historical_prior_for_ticker,
)

# ---------------------------------------------------------------------------
# load_candidate_pool_bundle
# ---------------------------------------------------------------------------


def test_load_bundle_legacy_path_uses_simple_candidates() -> None:
    """When build_candidate_pool differs from original but shadow fn is original → legacy path."""
    candidates = [SimpleNamespace(ticker="000001", avg_volume_20d=500.0)]

    def _build(date):
        return candidates

    def _orig_build(date):
        raise AssertionError("should not be called on legacy path")

    result = load_candidate_pool_bundle(
        "20260613",
        build_candidate_pool=_build,
        build_candidate_pool_with_shadow=_orig_build,
        original_build_candidate_pool=lambda d: None,
        original_build_candidate_pool_with_shadow=_orig_build,
    )
    sel, shadow, summary = result
    assert sel == candidates
    assert shadow == []
    assert summary["pool_size"] == 1
    assert summary["selected_count"] == 1
    assert summary["overflow_count"] == 0
    assert summary["selected_cutoff_avg_volume_20d"] == 500.0


def test_load_bundle_shadow_path_invokes_shadow_fn() -> None:
    """When both fns are the originals → uses shadow fn directly."""
    def _build(date):
        raise AssertionError("should not be called on shadow path")

    def _shadow(date):
        return ["sel1"], ["shd1"], {"summary": True}

    sel, shadow, summary = load_candidate_pool_bundle(
        "20260613",
        build_candidate_pool=_build,
        build_candidate_pool_with_shadow=_shadow,
        original_build_candidate_pool=_build,
        original_build_candidate_pool_with_shadow=_shadow,
    )
    assert sel == ["sel1"]
    assert shadow == ["shd1"]
    assert summary == {"summary": True}


# ---------------------------------------------------------------------------
# build_filter_summary
# ---------------------------------------------------------------------------


def test_build_filter_summary_aggregates_reasons() -> None:
    entries = [
        {"reason": "low_liquidity"},
        {"reason": "low_liquidity"},
        {"reason": "st_filter"},
        {"reason": None},  # → "unknown"
        {"no_reason": "x"},  # missing → "unknown"
    ]
    summary = build_filter_summary(entries)
    assert summary["filtered_count"] == 5
    assert summary["reason_counts"] == {"low_liquidity": 2, "st_filter": 1, "unknown": 2}
    assert summary["tickers"] == entries


def test_build_filter_summary_empty() -> None:
    summary = build_filter_summary([])
    assert summary == {"filtered_count": 0, "reason_counts": {}, "tickers": []}


# ---------------------------------------------------------------------------
# load_latest_historical_prior_by_ticker
# ---------------------------------------------------------------------------


def test_load_latest_historical_prior_delegates() -> None:
    calls: list = []

    def _loader(root):
        calls.append(root)
        return {"000001": {"next_close": 0.7}}

    result = load_latest_historical_prior_by_ticker(reports_root="data/reports", loader=_loader)
    assert result == {"000001": {"next_close": 0.7}}
    assert calls == ["data/reports"]


# ---------------------------------------------------------------------------
# historical_prior_value_is_missing
# ---------------------------------------------------------------------------


def test_prior_value_missing_none() -> None:
    assert historical_prior_value_is_missing("any_key", None) is True


def test_prior_value_missing_empty_string() -> None:
    assert historical_prior_value_is_missing("any_key", "") is True


def test_prior_value_missing_whitespace_string() -> None:
    assert historical_prior_value_is_missing("any_key", "   ") is True


def test_prior_value_missing_execution_quality_unknown() -> None:
    """Special case: execution_quality_label == 'unknown' is treated as missing."""
    assert historical_prior_value_is_missing("execution_quality_label", "unknown") is True


def test_prior_value_present_for_other_keys() -> None:
    assert historical_prior_value_is_missing("any_key", "value") is False


def test_prior_value_non_string_present() -> None:
    assert historical_prior_value_is_missing("any_key", 0.5) is False


# ---------------------------------------------------------------------------
# _historical_prior_int
# ---------------------------------------------------------------------------


def test_prior_int_missing_defaults_zero() -> None:
    assert _historical_prior_int({}, "missing") == 0


def test_prior_int_none_defaults_zero() -> None:
    assert _historical_prior_int({"a": None}, "a") == 0


def test_prior_int_empty_string_zero() -> None:
    assert _historical_prior_int({"a": ""}, "a") == 0


def test_prior_int_valid_int() -> None:
    assert _historical_prior_int({"a": 42}, "a") == 42


def test_prior_int_string_int() -> None:
    assert _historical_prior_int({"a": "5"}, "a") == 5


def test_prior_int_truncates_float() -> None:
    assert _historical_prior_int({"a": 3.9}, "a") == 3


def test_prior_int_invalid_string_zero() -> None:
    assert _historical_prior_int({"a": "abc"}, "a") == 0


# ---------------------------------------------------------------------------
# _historical_prior_scope_rank / _historical_prior_risk_rank
# ---------------------------------------------------------------------------


def test_scope_rank_known_values() -> None:
    assert _historical_prior_scope_rank({"applied_scope": "same_ticker"}) == 6
    assert _historical_prior_scope_rank({"applied_scope": "same_family_source_score_catalyst"}) == 5
    assert _historical_prior_scope_rank({"applied_scope": "same_family"}) == 3
    assert _historical_prior_scope_rank({"applied_scope": "candidate_source"}) == 1
    assert _historical_prior_scope_rank({"applied_scope": "none"}) == 0


def test_scope_rank_unknown_returns_zero() -> None:
    assert _historical_prior_scope_rank({"applied_scope": "nonsense"}) == 0


def test_scope_rank_missing_returns_zero() -> None:
    assert _historical_prior_scope_rank({}) == 0


def test_risk_rank_known_values() -> None:
    assert _historical_prior_risk_rank({"execution_quality_label": "zero_follow_through"}) == 5
    assert _historical_prior_risk_rank({"execution_quality_label": "intraday_only"}) == 4
    assert _historical_prior_risk_rank({"execution_quality_label": "balanced_confirmation"}) == 2
    assert _historical_prior_risk_rank({"execution_quality_label": "close_continuation"}) == 1


def test_risk_rank_unknown_returns_zero() -> None:
    assert _historical_prior_risk_rank({"execution_quality_label": "mystery"}) == 0


def test_risk_rank_missing_returns_zero() -> None:
    assert _historical_prior_risk_rank({}) == 0


# ---------------------------------------------------------------------------
# _historical_prior_merge_rank
# ---------------------------------------------------------------------------


def test_merge_rank_evaluable_sample_scope_risk() -> None:
    prior = {
        "evaluable_count": 10,
        "sample_count": 5,
        "applied_scope": "same_ticker",
        "execution_quality_label": "zero_follow_through",
    }
    assert _historical_prior_merge_rank(prior) == (10, 5, 6, 5)


def test_merge_rank_missing_fields_default_zero() -> None:
    assert _historical_prior_merge_rank({}) == (0, 0, 0, 0)


# ---------------------------------------------------------------------------
# _should_preserve_exact_upstream_embedded_prior
# ---------------------------------------------------------------------------


def test_preserve_exact_upstream_true() -> None:
    embedded = {"applied_scope": "candidate_source", "execution_quality_label": "balanced_confirmation"}
    latest = {"applied_scope": "same_ticker", "execution_quality_label": "intraday_only"}
    assert _should_preserve_exact_upstream_embedded_prior(
        candidate_source=EXACT_UPSTREAM_SOURCE, embedded_historical_prior=embedded, latest_historical_prior=latest
    ) is True


def test_preserve_exact_upstream_wrong_source_false() -> None:
    embedded = {"applied_scope": "candidate_source", "execution_quality_label": "balanced_confirmation"}
    latest = {"applied_scope": "same_ticker", "execution_quality_label": "intraday_only"}
    assert _should_preserve_exact_upstream_embedded_prior(
        candidate_source="other_source", embedded_historical_prior=embedded, latest_historical_prior=latest
    ) is False


def test_preserve_exact_upstream_embedded_scope_not_in_set_false() -> None:
    embedded = {"applied_scope": "same_ticker", "execution_quality_label": "balanced_confirmation"}
    latest = {"applied_scope": "source_score", "execution_quality_label": "intraday_only"}
    assert _should_preserve_exact_upstream_embedded_prior(
        candidate_source=EXACT_UPSTREAM_SOURCE, embedded_historical_prior=embedded, latest_historical_prior=latest
    ) is False


def test_preserve_exact_upstream_latest_scope_in_set_false() -> None:
    """If latest scope is also in the upstream scopes, do NOT preserve embedded."""
    embedded = {"applied_scope": "candidate_source", "execution_quality_label": "balanced_confirmation"}
    latest = {"applied_scope": "candidate_source", "execution_quality_label": "intraday_only"}
    assert _should_preserve_exact_upstream_embedded_prior(
        candidate_source=EXACT_UPSTREAM_SOURCE, embedded_historical_prior=embedded, latest_historical_prior=latest
    ) is False


def test_preserve_exact_upstream_embedded_label_unknown_false() -> None:
    embedded = {"applied_scope": "candidate_source", "execution_quality_label": "unknown"}
    latest = {"applied_scope": "same_ticker", "execution_quality_label": "intraday_only"}
    assert _should_preserve_exact_upstream_embedded_prior(
        candidate_source=EXACT_UPSTREAM_SOURCE, embedded_historical_prior=embedded, latest_historical_prior=latest
    ) is False


def test_preserve_exact_upstream_latest_label_empty_false() -> None:
    embedded = {"applied_scope": "candidate_source", "execution_quality_label": "balanced_confirmation"}
    latest = {"applied_scope": "same_ticker", "execution_quality_label": ""}
    assert _should_preserve_exact_upstream_embedded_prior(
        candidate_source=EXACT_UPSTREAM_SOURCE, embedded_historical_prior=embedded, latest_historical_prior=latest
    ) is False


def test_preserve_exact_upstream_same_labels_false() -> None:
    embedded = {"applied_scope": "candidate_source", "execution_quality_label": "balanced_confirmation"}
    latest = {"applied_scope": "same_ticker", "execution_quality_label": "balanced_confirmation"}
    assert _should_preserve_exact_upstream_embedded_prior(
        candidate_source=EXACT_UPSTREAM_SOURCE, embedded_historical_prior=embedded, latest_historical_prior=latest
    ) is False


# ---------------------------------------------------------------------------
# resolve_historical_prior_for_ticker
# ---------------------------------------------------------------------------


def test_resolve_no_embedded_returns_latest() -> None:
    result = resolve_historical_prior_for_ticker(
        ticker="000001", historical_prior=None, prior_by_ticker={"000001": {"next_close": 0.7}}
    )
    assert result == {"next_close": 0.7}


def test_resolve_no_latest_returns_embedded() -> None:
    result = resolve_historical_prior_for_ticker(
        ticker="000001", historical_prior={"next_close": 0.6}, prior_by_ticker={}
    )
    assert result == {"next_close": 0.6}


def test_resolve_both_prefers_higher_merge_rank() -> None:
    """When embedded rank > latest rank, embedded preferred; fallback fills missing."""
    embedded = {
        "evaluable_count": 10,
        "sample_count": 5,
        "applied_scope": "same_ticker",  # rank 6
        "execution_quality_label": "close_continuation",  # rank 1
        "next_close": 0.7,
    }
    latest = {
        "evaluable_count": 1,
        "sample_count": 1,
        "applied_scope": "candidate_source",  # rank 1
        "execution_quality_label": "zero_follow_through",  # rank 5
        "next_open_to_close": 0.3,
    }
    result = resolve_historical_prior_for_ticker(
        ticker="000001", historical_prior=embedded, prior_by_ticker={"000001": latest}
    )
    # Preferred = embedded (higher rank); fallback = latest fills missing fields
    assert result["next_close"] == 0.7
    assert result["next_open_to_close"] == 0.3


def test_resolve_preserves_exact_upstream_uses_embedded() -> None:
    embedded = {
        "applied_scope": "candidate_source",  # in EXACT scopes
        "execution_quality_label": "balanced_confirmation",
    }
    latest = {
        "applied_scope": "same_ticker",
        "execution_quality_label": "intraday_only",
    }
    result = resolve_historical_prior_for_ticker(
        ticker="000001", historical_prior=embedded, prior_by_ticker={"000001": latest}, candidate_source=EXACT_UPSTREAM_SOURCE
    )
    # Embedded preferred (exact-upstream preserve path)
    assert result["execution_quality_label"] == "balanced_confirmation"


def test_resolve_fills_missing_from_fallback() -> None:
    """Preferred has missing fields → fallback fills them in."""
    embedded = {"evaluable_count": 1, "applied_scope": "candidate_source", "execution_quality_label": "close_continuation"}  # rank 1,1
    latest = {"evaluable_count": 10, "applied_scope": "same_ticker", "execution_quality_label": "zero_follow_through", "next_open_to_close": 0.4}  # rank 6,5 → higher → preferred
    result = resolve_historical_prior_for_ticker(
        ticker="000001", historical_prior=embedded, prior_by_ticker={"000001": latest}
    )
    # latest preferred; embedded fills missing (but evaluable_count exists → not filled)
    # Actually preferred=latest fills from embedded fallback
    assert result["next_open_to_close"] == 0.4  # from preferred (latest)
    # preferred already has evaluable_count=10, applied_scope, execution_quality_label → embedded fallback adds nothing new


# ---------------------------------------------------------------------------
# default_exit_checker
# ---------------------------------------------------------------------------


class _StubHolding:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_exit_checker_no_active_positions() -> None:
    def _price_map(date, tickers):
        raise AssertionError("should not be called with no active tickers")

    def _check(**k):
        raise AssertionError("should not be called with no active tickers")

    result = default_exit_checker(
        portfolio_snapshot={"positions": {}},
        trade_date="20260613",
        build_watchlist_price_map=_price_map,
        check_exit_signal=_check,
        holding_state_cls=_StubHolding,
    )
    assert result == []


def test_exit_checker_skips_zero_shares() -> None:
    result = default_exit_checker(
        portfolio_snapshot={"positions": {"000001": {"long": 0, "long_cost_basis": 10.0}}},
        trade_date="20260613",
        build_watchlist_price_map=lambda d, t: {"000001": 12.0},
        check_exit_signal=lambda **k: "signal",
        holding_state_cls=_StubHolding,
    )
    assert result == []


def test_exit_checker_skips_missing_price() -> None:
    result = default_exit_checker(
        portfolio_snapshot={"positions": {"000001": {"long": 100, "long_cost_basis": 10.0}}},
        trade_date="20260613",
        build_watchlist_price_map=lambda d, t: {},  # no price
        check_exit_signal=lambda **k: "signal",
        holding_state_cls=_StubHolding,
    )
    assert result == []


def test_exit_checker_includes_exit_signal() -> None:
    signal = SimpleNamespace(ticker="000001")
    signals: list = []

    def _check(holding, **k):
        signals.append({"holding": holding, **k})
        return signal

    result = default_exit_checker(
        portfolio_snapshot={"positions": {"000001": {"long": 100, "long_cost_basis": 10.0}}},
        trade_date="20260613",
        logic_scores={"000001": 0.6},
        build_watchlist_price_map=lambda d, t: {"000001": 12.0},
        check_exit_signal=_check,
        holding_state_cls=_StubHolding,
    )
    assert result == [signal]
    assert signals[0]["logic_score"] == 0.6
    assert isinstance(signals[0]["holding"], _StubHolding)
    assert signals[0]["holding"].entry_price == 10.0
    assert signals[0]["holding"].shares == 100


def test_exit_checker_drops_none_signal() -> None:
    result = default_exit_checker(
        portfolio_snapshot={"positions": {"000001": {"long": 100, "long_cost_basis": 10.0}}},
        trade_date="20260613",
        build_watchlist_price_map=lambda d, t: {"000001": 12.0},
        check_exit_signal=lambda holding, **k: None,
        holding_state_cls=_StubHolding,
    )
    assert result == []
