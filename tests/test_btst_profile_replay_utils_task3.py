from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scripts.btst_profile_replay_utils import _build_replayed_rows


def test_build_replayed_rows_surfaces_metric_source_fields_from_watchlist() -> None:
    """Test that _build_replayed_rows extracts flow_60_source, persist_120_source, close_support_30_source from watchlist entry metrics."""
    payload = {
        "watchlist": [
            {
                "ticker": "000001",
                "score_c": 0.85,
                "candidate_source": "layer_c_watchlist",
                "metrics": {
                    "flow_60_source": "momentum_60",
                    "persist_120_source": "persistence_120",
                    "close_support_30_source": "support_30",
                },
            }
        ],
        "selection_targets": {
            "000001": {
                "candidate_source": "watchlist",
                "short_trade": {"decision": "selected"},
            },
        },
        "buy_order_tickers": [],
    }

    mock_replayed_snapshots = {
        "000001": {
            "decision": "selected",
            "score_target": 0.85,
            "blockers": [],
            "gate_status": {},
            "metrics_payload": {},
            "explainability_payload": {
                "candidate_source": "watchlist",
            },
        },
    }

    with patch("scripts.btst_profile_replay_utils.build_selection_targets") as mock_build_targets, patch("scripts.btst_profile_replay_utils._extract_short_trade_snapshot_map") as mock_extract_snapshots, patch("scripts.btst_profile_replay_utils._extract_btst_price_outcome") as mock_price_outcome:
        mock_build_targets.return_value = ({}, None)
        mock_extract_snapshots.return_value = mock_replayed_snapshots
        mock_price_outcome.return_value = {}

        rows = _build_replayed_rows(
            payload=payload,
            trade_date="2024-01-15",
            target_mode="short_trade_only",
            rejected_entries=[],
            supplemental_entries=[],
            profile_name="test_profile",
            label=None,
            replay_input_path=Path("/test.json"),
            price_cache={},
        )

    assert len(rows) == 1
    row = rows[0]
    assert row["flow_60_source"] == "momentum_60"
    assert row["persist_120_source"] == "persistence_120"
    assert row["close_support_30_source"] == "support_30"


def test_build_replayed_rows_surfaces_metric_source_fields_from_rejected() -> None:
    """Test that _build_replayed_rows extracts source fields from rejected entry metrics."""
    payload = {
        "watchlist": [],
        "selection_targets": {
            "000002": {
                "candidate_source": "rejected_shadow",
                "short_trade": {"decision": "blocked"},
            },
        },
        "buy_order_tickers": [],
    }

    rejected_entries = [
        {
            "ticker": "000002",
            "metrics": {
                "flow_60_source": "flow_rejected",
                "persist_120_source": "persist_rejected",
                "close_support_30_source": "support_rejected",
            },
        }
    ]

    mock_replayed_snapshots = {
        "000002": {
            "decision": "blocked",
            "score_target": 0.45,
            "blockers": ["low_score"],
            "gate_status": {},
            "metrics_payload": {},
            "explainability_payload": {
                "candidate_source": "rejected_shadow",
            },
        },
    }

    with patch("scripts.btst_profile_replay_utils.build_selection_targets") as mock_build_targets, patch("scripts.btst_profile_replay_utils._extract_short_trade_snapshot_map") as mock_extract_snapshots, patch("scripts.btst_profile_replay_utils._extract_btst_price_outcome") as mock_price_outcome:
        mock_build_targets.return_value = ({}, None)
        mock_extract_snapshots.return_value = mock_replayed_snapshots
        mock_price_outcome.return_value = {}

        rows = _build_replayed_rows(
            payload=payload,
            trade_date="2024-01-15",
            target_mode="short_trade_only",
            rejected_entries=rejected_entries,
            supplemental_entries=[],
            profile_name="test_profile",
            label=None,
            replay_input_path=Path("/test.json"),
            price_cache={},
        )

    assert len(rows) == 1
    row = rows[0]
    assert row["flow_60_source"] == "flow_rejected"
    assert row["persist_120_source"] == "persist_rejected"
    assert row["close_support_30_source"] == "support_rejected"


def test_build_replayed_rows_prefers_watchlist_metric_sources_when_ticker_overlaps() -> None:
    payload = {
        "watchlist": [
            {
                "ticker": "000003",
                "score_c": 0.91,
                "metrics": {
                    "flow_60_source": "watchlist_flow",
                    "persist_120_source": "watchlist_persist",
                    "close_support_30_source": "watchlist_support",
                },
            }
        ],
        "selection_targets": {
            "000003": {
                "candidate_source": "watchlist",
                "short_trade": {"decision": "selected"},
            },
        },
        "buy_order_tickers": [],
    }
    rejected_entries = [
        {
            "ticker": "000003",
            "metrics": {
                "flow_60_source": "rejected_flow",
                "persist_120_source": "rejected_persist",
                "close_support_30_source": "rejected_support",
            },
        }
    ]
    mock_replayed_snapshots = {
        "000003": {
            "decision": "selected",
            "score_target": 0.91,
            "blockers": [],
            "gate_status": {},
            "metrics_payload": {},
            "explainability_payload": {
                "candidate_source": "watchlist",
            },
        },
    }

    with patch("scripts.btst_profile_replay_utils.build_selection_targets") as mock_build_targets, patch("scripts.btst_profile_replay_utils._extract_short_trade_snapshot_map") as mock_extract_snapshots, patch("scripts.btst_profile_replay_utils._extract_btst_price_outcome") as mock_price_outcome:
        mock_build_targets.return_value = ({}, None)
        mock_extract_snapshots.return_value = mock_replayed_snapshots
        mock_price_outcome.return_value = {}

        rows = _build_replayed_rows(
            payload=payload,
            trade_date="2024-01-15",
            target_mode="short_trade_only",
            rejected_entries=rejected_entries,
            supplemental_entries=[],
            profile_name="test_profile",
            label=None,
            replay_input_path=Path("/test.json"),
            price_cache={},
        )

    row = rows[0]
    assert row["flow_60_source"] == "watchlist_flow"
    assert row["persist_120_source"] == "watchlist_persist"
    assert row["close_support_30_source"] == "watchlist_support"


def test_summarize_source_coverage_aggregates_row_level_sources() -> None:
    """Test that _summarize_source_coverage aggregates flow/persist/close_support source counts."""
    from scripts.btst_profile_replay_utils import _summarize_source_coverage

    rows = [
        {
            "flow_60_source": "momentum_60",
            "persist_120_source": "persistence_120",
            "close_support_30_source": "support_30",
            "explainability_payload": {},
        },
        {
            "flow_60_source": "momentum_60",
            "persist_120_source": "persistence_variant",
            "close_support_30_source": None,
            "explainability_payload": {},
        },
        {
            "flow_60_source": None,
            "persist_120_source": "persistence_120",
            "close_support_30_source": "support_30",
            "explainability_payload": {},
        },
    ]

    summary = _summarize_source_coverage(rows)

    assert summary["flow_60_source_counts"] == {"momentum_60": 2}
    assert summary["persist_120_source_counts"] == {"persistence_120": 2, "persistence_variant": 1}
    assert summary["close_support_30_source_counts"] == {"support_30": 2}


def test_summarize_source_coverage_reads_committee_component_sources_from_explainability_payload() -> None:
    """Test that _summarize_source_coverage reads committee component_sources from explainability_payload -> committee -> component_sources."""
    from scripts.btst_profile_replay_utils import _summarize_source_coverage

    rows = [
        {
            "flow_60_source": None,
            "persist_120_source": None,
            "close_support_30_source": None,
            "explainability_payload": {
                "committee": {
                    "component_sources": ["momentum_agent", "volume_agent"],
                }
            },
        },
        {
            "flow_60_source": None,
            "persist_120_source": None,
            "close_support_30_source": None,
            "explainability_payload": {
                "committee": {
                    "component_sources": ["momentum_agent", "catalyst_agent"],
                }
            },
        },
        {
            "flow_60_source": None,
            "persist_120_source": None,
            "close_support_30_source": None,
            "explainability_payload": {},
        },
    ]

    summary = _summarize_source_coverage(rows)

    assert summary["committee_component_sources_counts"] == {
        "momentum_agent": 2,
        "volume_agent": 1,
        "catalyst_agent": 1,
    }


def test_analyze_btst_profile_replay_window_includes_source_coverage_summary() -> None:
    """Test that analyze_btst_profile_replay_window includes source_coverage_summary in the returned analysis payload."""
    from collections import Counter
    from unittest.mock import MagicMock, patch

    from scripts.btst_profile_replay_utils import analyze_btst_profile_replay_window

    mock_rows = [
        {
            "ticker": "000001",
            "decision": "selected",
            "score_target": 0.85,
            "flow_60_source": "momentum_60",
            "persist_120_source": "persistence_120",
            "close_support_30_source": "support_30",
            "explainability_payload": {
                "committee": {
                    "component_sources": ["momentum_agent", "volume_agent"],
                }
            },
        },
    ]

    mock_replay_results = {
        "rows": mock_rows,
        "decision_counts": Counter(),
        "candidate_source_counts": Counter(),
        "cycle_status_counts": Counter(),
        "data_status_counts": Counter(),
        "target_modes": Counter({"short_trade_only": 1}),
        "candidate_entry_filter_observability": {},
        "filtered_candidate_entry_rows": [],
        "filtered_candidate_entry_counts": Counter(),
    }

    with patch("scripts.btst_profile_replay_utils._iter_replay_input_sources") as mock_iter, patch("scripts.btst_profile_replay_utils.build_short_trade_target_profile") as mock_profile, patch("scripts.btst_profile_replay_utils._override_short_trade_thresholds"), patch("scripts.btst_profile_replay_utils._process_replay_input_sources") as mock_process:
        mock_iter.return_value = [("fake_path", {})]
        mock_profile.return_value = MagicMock(name="test_profile")
        mock_process.return_value = mock_replay_results

        analysis = analyze_btst_profile_replay_window(
            "fake_path",
            profile_name="watchlist_zero_catalyst_guard_relief",
            next_high_hit_threshold=0.02,
        )

    assert "source_coverage_summary" in analysis
    assert "flow_60_source_counts" in analysis["source_coverage_summary"]
    assert "persist_120_source_counts" in analysis["source_coverage_summary"]
    assert "close_support_30_source_counts" in analysis["source_coverage_summary"]
    assert "committee_component_sources_counts" in analysis["source_coverage_summary"]
    assert analysis["source_coverage_summary"]["flow_60_source_counts"]["momentum_60"] == 1
    assert analysis["source_coverage_summary"]["persist_120_source_counts"]["persistence_120"] == 1
    assert analysis["source_coverage_summary"]["close_support_30_source_counts"]["support_30"] == 1
    assert analysis["source_coverage_summary"]["committee_component_sources_counts"]["momentum_agent"] == 1
    assert analysis["source_coverage_summary"]["committee_component_sources_counts"]["volume_agent"] == 1


def test_analyze_btst_multi_window_profile_validation_propagates_source_coverage_summaries() -> None:
    """Test that multi-window validation propagates baseline_source_coverage_summary and variant_source_coverage_summary into rows."""
    from unittest.mock import patch

    import scripts.analyze_btst_multi_window_profile_validation as multi_window_validation

    def _fake_replay_window(input_path, *, profile_name, label, next_high_hit_threshold, select_threshold=None, near_miss_threshold=None, profile_overrides=None):
        _ = (input_path, label, next_high_hit_threshold, profile_overrides)
        baseline_source_coverage = {
            "flow_60_source_counts": {"momentum_60": 3},
            "persist_120_source_counts": {"persistence_120": 3},
            "close_support_30_source_counts": {"support_30": 3},
            "committee_component_sources_counts": {"momentum_agent": 3, "volume_agent": 3},
        }
        variant_source_coverage = {
            "flow_60_source_counts": {"momentum_60": 5, "flow_alt": 1},
            "persist_120_source_counts": {"persistence_120": 4, "persist_alt": 2},
            "close_support_30_source_counts": {"support_30": 5, "support_alt": 1},
            "committee_component_sources_counts": {"momentum_agent": 6, "volume_agent": 5, "catalyst_agent": 1},
        }
        if select_threshold is None:
            source_coverage = baseline_source_coverage
        else:
            source_coverage = variant_source_coverage
        return {
            "label": label,
            "profile_name": profile_name,
            "trade_dates": ["2026-03-24"],
            "surface_summaries": {
                "tradeable": {
                    "total_count": 3 if select_threshold is None else 6,
                    "closed_cycle_count": 3 if select_threshold is None else 6,
                    "next_high_hit_rate_at_threshold": 0.80,
                    "next_close_positive_rate": 0.80,
                    "t_plus_2_close_positive_rate": 0.80,
                    "next_high_return_distribution": {"mean": 0.05},
                    "next_close_return_distribution": {"mean": 0.02, "median": 0.025, "p10": 0.01},
                    "t_plus_2_close_return_distribution": {"mean": 0.025, "median": 0.02, "p10": 0.005},
                }
            },
            "false_negative_proxy_summary": {"count": 0, "surface_metrics": {}},
            "source_coverage_summary": source_coverage,
        }

    with patch.object(multi_window_validation, "discover_report_dirs") as mock_discover, patch.object(multi_window_validation, "analyze_btst_profile_replay_window") as mock_replay:
        mock_discover.return_value = [Path("/fake/window_a")]
        mock_replay.side_effect = _fake_replay_window

        analysis = multi_window_validation.analyze_btst_multi_window_profile_validation(
            "/fake/reports",
            baseline_profile="baseline_profile",
            variant_profile="variant_profile",
            variant_select_threshold=0.35,
        )

    assert len(analysis["rows"]) == 1
    row = analysis["rows"][0]
    assert "baseline_source_coverage_summary" in row
    assert "variant_source_coverage_summary" in row
    assert row["baseline_source_coverage_summary"]["flow_60_source_counts"]["momentum_60"] == 3
    assert row["variant_source_coverage_summary"]["flow_60_source_counts"]["momentum_60"] == 5
    assert row["variant_source_coverage_summary"]["flow_60_source_counts"]["flow_alt"] == 1
    assert row["variant_source_coverage_summary"]["committee_component_sources_counts"]["catalyst_agent"] == 1


def test_render_btst_multi_window_profile_validation_markdown_includes_source_coverage_summary() -> None:
    """Test that markdown rendering includes source coverage summary information."""
    from unittest.mock import patch

    import scripts.analyze_btst_multi_window_profile_validation as multi_window_validation

    def _fake_replay_window(input_path, *, profile_name, label, next_high_hit_threshold, select_threshold=None, near_miss_threshold=None, profile_overrides=None):
        _ = (input_path, label, next_high_hit_threshold, profile_overrides)
        baseline_source_coverage = {
            "flow_60_source_counts": {"momentum_60": 3},
            "persist_120_source_counts": {"persistence_120": 3},
            "close_support_30_source_counts": {"support_30": 3},
            "committee_component_sources_counts": {"momentum_agent": 3, "volume_agent": 3},
        }
        variant_source_coverage = {
            "flow_60_source_counts": {"momentum_60": 5, "flow_alt": 1},
            "persist_120_source_counts": {"persistence_120": 4, "persist_alt": 2},
            "close_support_30_source_counts": {"support_30": 5, "support_alt": 1},
            "committee_component_sources_counts": {"momentum_agent": 6, "volume_agent": 5, "catalyst_agent": 1},
        }
        if select_threshold is None:
            source_coverage = baseline_source_coverage
        else:
            source_coverage = variant_source_coverage
        return {
            "label": label,
            "profile_name": profile_name,
            "trade_dates": ["2026-03-24"],
            "surface_summaries": {
                "tradeable": {
                    "total_count": 3 if select_threshold is None else 6,
                    "closed_cycle_count": 3 if select_threshold is None else 6,
                    "next_high_hit_rate_at_threshold": 0.80,
                    "next_close_positive_rate": 0.80,
                    "t_plus_2_close_positive_rate": 0.80,
                    "next_high_return_distribution": {"mean": 0.05},
                    "next_close_return_distribution": {"mean": 0.02, "median": 0.025, "p10": 0.01},
                    "t_plus_2_close_return_distribution": {"mean": 0.025, "median": 0.02, "p10": 0.005},
                }
            },
            "false_negative_proxy_summary": {"count": 0, "surface_metrics": {}},
            "source_coverage_summary": source_coverage,
        }

    with patch.object(multi_window_validation, "discover_report_dirs") as mock_discover, patch.object(multi_window_validation, "analyze_btst_profile_replay_window") as mock_replay:
        mock_discover.return_value = [Path("/fake/window_a")]
        mock_replay.side_effect = _fake_replay_window

        analysis = multi_window_validation.analyze_btst_multi_window_profile_validation(
            "/fake/reports",
            baseline_profile="baseline_profile",
            variant_profile="variant_profile",
            variant_select_threshold=0.35,
        )

    markdown = multi_window_validation.render_btst_multi_window_profile_validation_markdown(analysis)

    assert "## Source Coverage" in markdown or "source_coverage" in markdown.lower()
    assert "momentum_60" in markdown
    assert "momentum_agent" in markdown
    assert "flow_alt" in markdown or "catalyst_agent" in markdown
