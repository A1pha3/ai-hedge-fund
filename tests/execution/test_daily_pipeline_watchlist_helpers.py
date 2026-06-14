"""Unit tests for src/execution/daily_pipeline_watchlist_helpers.py

Covers the pure helper functions in the watchlist diagnostics pipeline:
ticker index, filter entry classification, ranked-shadow entry builder,
sorted append with cap, selection/prefilter threshold builders,
selected/released-shadow summaries, threshold summary aggregator.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.execution.daily_pipeline_watchlist_helpers import (
    _append_ranked_watchlist_shadow_entries,
    _build_ranked_watchlist_shadow_entry,
    _build_watchlist_filtered_entry,
    _build_watchlist_prefilter_thresholds,
    _build_watchlist_released_shadow_summary,
    _build_watchlist_selected_summary,
    _build_watchlist_selection_thresholds,
    _build_watchlist_threshold_summaries,
    _build_watchlist_ticker_index,
    build_merge_approved_watchlist,
    tag_merge_approved_layer_c_results,
    WatchlistDiagnosticsConfig,
)


def _config(**overrides: Any) -> WatchlistDiagnosticsConfig:
    base: dict[str, Any] = dict(
        watchlist_score_threshold=0.2,
        shadow_release_max_tickers=3,
        shadow_release_score_b_min=0.18,
        shadow_release_score_final_min=0.18,
        shadow_release_score_c_min=-0.08,
        shadow_release_conflicts=frozenset({"b_positive_c_strong_bearish"}),
    )
    base.update(overrides)
    return WatchlistDiagnosticsConfig(**base)


def _layer_c(ticker: str, **overrides: Any) -> Any:
    """For tests that need SimpleNamespace (e.g. _build_watchlist_ticker_index)."""
    base: dict[str, Any] = dict(ticker=ticker, score_c=0.5, score_final=0.3, score_b=0.3, decision="buy")
    base.update(overrides)
    return SimpleNamespace(**base)


def _real_layer_c(ticker: str, **overrides: Any) -> Any:
    """Real LayerCResult for tests that invoke model_copy."""
    from src.execution.models import LayerCResult

    base: dict[str, Any] = dict(ticker=ticker, score_c=0.5, score_final=0.3, decision="buy")
    base.update(overrides)
    return LayerCResult(**base)


# ---------------------------------------------------------------------------
# _build_watchlist_ticker_index
# ---------------------------------------------------------------------------


def test_build_watchlist_ticker_index_empty() -> None:
    selected_set, ordered = _build_watchlist_ticker_index([])
    assert selected_set == set()
    assert ordered == []


def test_build_watchlist_ticker_index_preserves_order() -> None:
    items = [_layer_c("000001"), _layer_c("000002"), _layer_c("000003")]
    selected_set, ordered = _build_watchlist_ticker_index(items)
    assert selected_set == {"000001", "000002", "000003"}
    assert ordered == ["000001", "000002", "000003"]


# ---------------------------------------------------------------------------
# _build_watchlist_filtered_entry
# ---------------------------------------------------------------------------


def test_filtered_entry_appends_reasons() -> None:
    payload = {"ticker": "000001", "score_final": 0.05}
    item = _layer_c("000001", score_final=0.05, decision="avoid")

    def _classify(c):
        return "decision_avoid", ["decision_avoid", "score_final_below_watchlist_threshold"]

    entry, primary, reasons = _build_watchlist_filtered_entry(
        item=item, payload=payload, classify_watchlist_filter=_classify
    )
    assert entry["ticker"] == "000001"
    assert entry["reason"] == "decision_avoid"
    assert entry["reasons"] == ["decision_avoid", "score_final_below_watchlist_threshold"]
    assert primary == "decision_avoid"
    assert reasons == ["decision_avoid", "score_final_below_watchlist_threshold"]


# ---------------------------------------------------------------------------
# _build_ranked_watchlist_shadow_entry
# ---------------------------------------------------------------------------


def test_ranked_shadow_entry_scores_and_dict() -> None:
    item = _real_layer_c("000001", score_final=0.8, score_b=0.6)
    entry_reasons = ["x"]
    config = _config()

    score_final, score_b, entry = _build_ranked_watchlist_shadow_entry(
        item=item, reasons=entry_reasons, release_reason="test_reason", config=config
    )
    assert score_final == 0.8
    assert score_b == 0.6
    assert isinstance(entry, dict)


# ---------------------------------------------------------------------------
# _append_ranked_watchlist_shadow_entries
# ---------------------------------------------------------------------------


def test_append_shadow_entries_sorts_by_score_descending() -> None:
    released: list = []
    ranked = [
        (0.2, 0.1, {"ticker": "000003"}),
        (0.8, 0.3, {"ticker": "000001"}),
        (0.5, 0.2, {"ticker": "000002"}),
    ]
    _append_ranked_watchlist_shadow_entries(
        ranked_entries=ranked, released_shadow_entries=released, shadow_release_max_tickers=3
    )
    tickers = [e["ticker"] for e in released]
    assert tickers == ["000001", "000002", "000003"]
    # Ranks assigned 1..3
    assert [e["rank"] for e in released] == [1, 2, 3]


def test_append_shadow_entries_caps_at_max() -> None:
    released: list = []
    ranked = [(float(i), float(i), {"ticker": f"{i:06d}"}) for i in range(1, 6)]
    _append_ranked_watchlist_shadow_entries(
        ranked_entries=ranked, released_shadow_entries=released, shadow_release_max_tickers=2
    )
    assert len(released) == 2
    assert released[0]["ticker"] == "000005"  # highest score
    assert released[1]["ticker"] == "000004"
    assert [e["rank"] for e in released] == [1, 2]


def test_append_shadow_entries_tiebreak_by_ticker_descending() -> None:
    """Same score → tied → sorted by ticker descending (str reverse)."""
    released: list = []
    ranked = [
        (0.5, 0.3, {"ticker": "000001"}),
        (0.5, 0.3, {"ticker": "000002"}),
    ]
    _append_ranked_watchlist_shadow_entries(
        ranked_entries=ranked, released_shadow_entries=released, shadow_release_max_tickers=2
    )
    # reverse=True on string → "000002" > "000001" → 000002 first
    assert released[0]["ticker"] == "000002"
    assert released[1]["ticker"] == "000001"


# ---------------------------------------------------------------------------
# _build_watchlist_selection_thresholds
# ---------------------------------------------------------------------------


def test_selection_thresholds_no_merge_approved() -> None:
    result = _build_watchlist_selection_thresholds(
        merge_approved_tickers=set(), threshold_relaxation=0.05, watchlist_score_threshold=0.2
    )
    assert result == {
        "default_score_final_min": 0.2,
        "merge_approved_score_final_min": 0.15,  # 0.2 - 0.05
        "merge_approved_tickers": [],
        "merge_approved_threshold_relaxation": 0.05,
    }


def test_selection_thresholds_merge_approved_sorted() -> None:
    result = _build_watchlist_selection_thresholds(
        merge_approved_tickers={"000002", "000001"},
        threshold_relaxation=0.0,
        watchlist_score_threshold=0.2,
    )
    assert result["merge_approved_tickers"] == ["000001", "000002"]


def test_selection_thresholds_floors_at_zero() -> None:
    """merge_approved_score = max(0, watchlist - relaxation)."""
    result = _build_watchlist_selection_thresholds(
        merge_approved_tickers={"000001"},
        threshold_relaxation=0.5,  # > watchlist → would be negative → floored to 0
        watchlist_score_threshold=0.2,
    )
    assert result["merge_approved_score_final_min"] == 0.0


# ---------------------------------------------------------------------------
# _build_watchlist_prefilter_thresholds
# ---------------------------------------------------------------------------


def test_prefilter_thresholds_rounds_and_sorts() -> None:
    config = _config(
        shadow_release_score_b_min=0.181,
        shadow_release_score_final_min=0.182,
        shadow_release_score_c_min=-0.083,
        shadow_release_conflicts=frozenset({"z_conflict", "a_conflict"}),
    )
    result = _build_watchlist_prefilter_thresholds(config)
    assert result["score_b_min"] == 0.181
    assert result["score_final_min"] == 0.182
    assert result["score_c_min"] == -0.083
    assert result["conflicts"] == ["a_conflict", "z_conflict"]


# ---------------------------------------------------------------------------
# _build_watchlist_selected_summary
# ---------------------------------------------------------------------------


def test_selected_summary_passthrough() -> None:
    result = _build_watchlist_selected_summary(
        selected_tickers=["000001"], selected_entries=[{"ticker": "000001"}]
    )
    assert result == {"selected_tickers": ["000001"], "selected_entries": [{"ticker": "000001"}]}


# ---------------------------------------------------------------------------
# _build_watchlist_released_shadow_summary
# ---------------------------------------------------------------------------


def test_released_shadow_summary_basic() -> None:
    released_entries = [{"ticker": "000001", "rank": 1}, {"ticker": "000002", "rank": 2}]
    result = _build_watchlist_released_shadow_summary(released_entries)
    assert result["released_shadow_count"] == 2
    assert result["released_shadow_tickers"] == ["000001", "000002"]
    assert result["released_shadow_entries"] == released_entries


def test_released_shadow_summary_empty() -> None:
    result = _build_watchlist_released_shadow_summary([])
    assert result == {"released_shadow_count": 0, "released_shadow_tickers": [], "released_shadow_entries": []}


# ---------------------------------------------------------------------------
# _build_watchlist_threshold_summaries (integration of prefilter + selection)
# ---------------------------------------------------------------------------


def test_threshold_summaries_combines_both() -> None:
    config = _config()
    result = _build_watchlist_threshold_summaries(
        merge_approved_tickers={"000001"}, threshold_relaxation=0.05, config=config
    )
    assert "prefilter_thresholds" in result
    assert "selection_thresholds" in result
    assert result["selection_thresholds"]["merge_approved_tickers"] == ["000001"]


# ---------------------------------------------------------------------------
# build_merge_approved_watchlist (integration of threshold + filter)
# ---------------------------------------------------------------------------


def test_build_merge_approved_watchlist_basic() -> None:
    items = [
        _layer_c("000001", score_final=0.5, decision="buy"),
        _layer_c("000002", score_final=0.1, decision="buy"),  # below threshold
        _layer_c("000003", score_final=0.5, decision="avoid"),  # avoid
    ]
    result = build_merge_approved_watchlist(
        items, merge_approved_tickers=set(), threshold_relaxation=0.0, watchlist_score_threshold=0.2
    )
    assert [item.ticker for item in result] == ["000001"]


def test_build_merge_approved_watchlist_relaxes_for_approved() -> None:
    """merge_approved tickers get lower threshold (0.2 - 0.05 = 0.15)."""
    items = [
        _layer_c("000001", score_final=0.18, decision="buy"),  # 0.18 >= 0.15, in approved
        _layer_c("000002", score_final=0.18, decision="buy"),  # 0.18 < 0.2, not approved
    ]
    result = build_merge_approved_watchlist(
        items,
        merge_approved_tickers={"000001"},
        threshold_relaxation=0.05,
        watchlist_score_threshold=0.2,
    )
    assert [item.ticker for item in result] == ["000001"]


def test_build_merge_approved_watchlist_excludes_avoid() -> None:
    items = [
        _layer_c("000001", score_final=0.5, decision="avoid"),  # exclude even if merge_approved
    ]
    result = build_merge_approved_watchlist(
        items, merge_approved_tickers={"000001"}, threshold_relaxation=0.0, watchlist_score_threshold=0.2
    )
    assert result == []


# ---------------------------------------------------------------------------
# tag_merge_approved_layer_c_results
# ---------------------------------------------------------------------------


def test_tag_no_merge_approved_returns_unchanged() -> None:
    items = [_real_layer_c("000001"), _real_layer_c("000002")]
    result = tag_merge_approved_layer_c_results(items, merge_approved_tickers=set())
    assert result == items


def test_tag_non_approved_unchanged() -> None:
    items = [_real_layer_c("000001")]
    result = tag_merge_approved_layer_c_results(items, merge_approved_tickers={"999999"})
    assert result == items


def test_tag_approved_tagged() -> None:
    items = [_real_layer_c("000001")]
    result = tag_merge_approved_layer_c_results(items, merge_approved_tickers={"000001"})
    assert result[0] is not items[0]  # model_copy → new instance
    assert result[0].ticker == "000001"
