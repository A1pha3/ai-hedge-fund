from __future__ import annotations

from pathlib import Path

import scripts.analyze_btst_multi_window_profile_validation as multi_window_validation


def test_analyze_btst_multi_window_profile_validation_recommends_baseline_when_variant_hurts_t1(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    window_a = reports_root / "paper_trading_window_a"
    window_b = reports_root / "paper_trading_window_b"
    for report_dir in (window_a, window_b):
        (report_dir / "selection_artifacts" / "2026-03-24").mkdir(parents=True)
        (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(multi_window_validation, "discover_report_dirs", lambda *_args, **_kwargs: [window_a, window_b])

    def _fake_replay_window(input_path, *, profile_name, label, next_high_hit_threshold, select_threshold=None, near_miss_threshold=None, profile_overrides=None):
        report_name = Path(input_path).name
        if report_name == "paper_trading_window_a" and select_threshold is None:
            tradeable = {
                "total_count": 5,
                "closed_cycle_count": 5,
                "next_high_hit_rate_at_threshold": 0.80,
                "next_close_positive_rate": 0.80,
                "t_plus_2_close_positive_rate": 0.80,
                "next_high_return_distribution": {"mean": 0.05},
                "next_close_return_distribution": {"mean": 0.0215, "median": 0.0267, "p10": -0.0137},
                "t_plus_2_close_return_distribution": {"mean": 0.0221, "median": 0.0152, "p10": 0.0027},
            }
        elif report_name == "paper_trading_window_a":
            tradeable = {
                "total_count": 6,
                "closed_cycle_count": 6,
                "next_high_hit_rate_at_threshold": 0.6667,
                "next_close_positive_rate": 0.6667,
                "t_plus_2_close_positive_rate": 0.8333,
                "next_high_return_distribution": {"mean": 0.0473},
                "next_close_return_distribution": {"mean": 0.0135, "median": 0.0183, "p10": -0.0282},
                "t_plus_2_close_return_distribution": {"mean": 0.0248, "median": 0.0239, "p10": 0.0042},
            }
        elif report_name == "paper_trading_window_b" and select_threshold is None:
            tradeable = {
                "total_count": 4,
                "closed_cycle_count": 4,
                "next_high_hit_rate_at_threshold": 0.75,
                "next_close_positive_rate": 0.75,
                "t_plus_2_close_positive_rate": 0.75,
                "next_high_return_distribution": {"mean": 0.044},
                "next_close_return_distribution": {"mean": 0.018, "median": 0.02, "p10": -0.01},
                "t_plus_2_close_return_distribution": {"mean": 0.019, "median": 0.017, "p10": 0.001},
            }
        else:
            tradeable = {
                "total_count": 5,
                "closed_cycle_count": 5,
                "next_high_hit_rate_at_threshold": 0.75,
                "next_close_positive_rate": 0.75,
                "t_plus_2_close_positive_rate": 0.80,
                "next_high_return_distribution": {"mean": 0.045},
                "next_close_return_distribution": {"mean": 0.018, "median": 0.02, "p10": -0.01},
                "t_plus_2_close_return_distribution": {"mean": 0.021, "median": 0.02, "p10": 0.002},
            }
        return {
            "label": label,
            "profile_name": profile_name,
            "trade_dates": ["2026-03-24", "2026-03-25"],
            "surface_summaries": {"tradeable": tradeable},
            "false_negative_proxy_summary": {"count": 0, "surface_metrics": {}},
        }

    monkeypatch.setattr(multi_window_validation, "analyze_btst_profile_replay_window", _fake_replay_window)

    analysis = multi_window_validation.analyze_btst_multi_window_profile_validation(
        reports_root,
        baseline_profile="watchlist_zero_catalyst_guard_relief",
        variant_profile="watchlist_zero_catalyst_guard_relief",
        variant_select_threshold=0.34,
        variant_near_miss_threshold=0.40,
    )

    assert analysis["report_dir_count"] == 2
    assert analysis["keep_baseline_count"] == 1
    assert analysis["variant_improves_t2_only_count"] == 1
    assert analysis["variant_supports_t1_count"] == 0
    assert analysis["recommendation"].startswith("Baseline should remain the default")

    markdown = multi_window_validation.render_btst_multi_window_profile_validation_markdown(analysis)
    assert "# BTST Multi-Window Profile Validation" in markdown
    assert "paper_trading_window_a" in markdown
    assert "keep_baseline_default" in markdown


def test_render_btst_multi_window_profile_validation_markdown_includes_frontier_source_summary(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_window_a"
    (report_dir / "selection_artifacts" / "2026-03-24").mkdir(parents=True)
    (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(multi_window_validation, "discover_report_dirs", lambda *_args, **_kwargs: [report_dir])

    def _fake_replay_window(input_path, *, profile_name, label, next_high_hit_threshold, select_threshold=None, near_miss_threshold=None, profile_overrides=None):
        _ = (input_path, next_high_hit_threshold, select_threshold, near_miss_threshold, profile_overrides)
        return {
            "label": label,
            "profile_name": profile_name,
            "trade_dates": ["2026-03-24"],
            "surface_summaries": {
                "tradeable": {
                    "total_count": 1,
                    "closed_cycle_count": 1,
                    "next_high_hit_rate_at_threshold": 1.0,
                    "next_close_positive_rate": 1.0,
                    "t_plus_2_close_positive_rate": 1.0,
                    "next_high_return_distribution": {"mean": 0.05},
                    "next_close_return_distribution": {"mean": 0.03, "median": 0.03, "p10": 0.01},
                    "t_plus_2_close_return_distribution": {"mean": 0.04, "median": 0.04, "p10": 0.02},
                }
            },
            "false_negative_proxy_summary": {"count": 0, "surface_metrics": {}},
            "frontier_source_family_summaries": {
                "upstream_liquidity_corridor_shadow": {
                    "tradeable": {"total_count": 1},
                    "selected": {"total_count": 1},
                }
            },
        }

    monkeypatch.setattr(multi_window_validation, "analyze_btst_profile_replay_window", _fake_replay_window)

    analysis = multi_window_validation.analyze_btst_multi_window_profile_validation(
        reports_root,
        baseline_profile="btst_precision_v2",
        variant_profile="btst_candidate_pool_frontier",
    )

    assert analysis["rows"][0]["variant_frontier_source_family_summaries"]["upstream_liquidity_corridor_shadow"]["tradeable"]["total_count"] == 1

    markdown = multi_window_validation.render_btst_multi_window_profile_validation_markdown(analysis)
    assert "upstream_liquidity_corridor_shadow" in markdown


def test_analyze_btst_multi_window_profile_validation_flags_threshold_probe_without_runtime_activation_delta(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_window_a"
    (report_dir / "selection_artifacts" / "2026-03-24").mkdir(parents=True)
    (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(multi_window_validation, "discover_report_dirs", lambda *_args, **_kwargs: [report_dir])

    def _fake_replay_window(input_path, *, profile_name, label, next_high_hit_threshold, select_threshold=None, near_miss_threshold=None, profile_overrides=None):
        _ = (input_path, label, next_high_hit_threshold, profile_overrides)
        is_baseline = profile_name == "trend_continuation_strength_v2"
        return {
            "label": label,
            "profile_name": profile_name,
            "profile_config": {
                "name": profile_name,
                "select_threshold": 0.46 if is_baseline else 0.34,
                "near_miss_threshold": 0.34 if is_baseline else 0.24,
            },
            "profile_overrides": {} if is_baseline else {"select_threshold": 0.34, "near_miss_threshold": 0.24},
            "trade_dates": ["2026-03-24"],
            "decision_counts": {"selected": 1, "near_miss": 2, "rejected": 3},
            "surface_summaries": {
                "tradeable": {
                    "total_count": 3,
                    "closed_cycle_count": 3,
                    "next_high_hit_rate_at_threshold": 0.80,
                    "next_close_positive_rate": 0.80,
                    "t_plus_2_close_positive_rate": 0.80,
                    "next_high_return_distribution": {"mean": 0.05},
                    "next_close_return_distribution": {"mean": 0.02, "median": 0.025, "p10": 0.01},
                    "t_plus_2_close_return_distribution": {"mean": 0.025, "median": 0.02, "p10": 0.005},
                },
                "selected": {"total_count": 1},
                "near_miss": {"total_count": 2},
            },
            "false_negative_proxy_summary": {"count": 0, "surface_metrics": {}},
        }

    monkeypatch.setattr(multi_window_validation, "analyze_btst_profile_replay_window", _fake_replay_window)

    analysis = multi_window_validation.analyze_btst_multi_window_profile_validation(
        reports_root,
        baseline_profile="trend_continuation_strength_v2",
        variant_profile="trend_continuation_strength_v3",
        variant_select_threshold=0.34,
        variant_near_miss_threshold=0.24,
    )

    attribution = analysis["rows"][0]["runtime_activation_attribution"]
    assert attribution["selected_count_delta"] == 0
    assert attribution["near_miss_count_delta"] == 0
    assert attribution["tradeable_count_delta"] == 0
    assert attribution["guardrail_status_changed"] is False
    assert attribution["threshold_delta"] == {
        "select_threshold": -0.12,
        "near_miss_threshold": -0.10,
    }
    assert attribution["zero_delta_reason"] == "threshold_probe_without_runtime_activation_delta"


def test_analyze_btst_multi_window_profile_validation_flags_execution_eligible_runtime_activation_delta(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_window_a"
    (report_dir / "selection_artifacts" / "2026-03-24").mkdir(parents=True)
    (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(multi_window_validation, "discover_report_dirs", lambda *_args, **_kwargs: [report_dir])

    def _fake_replay_window(input_path, *, profile_name, label, next_high_hit_threshold, select_threshold=None, near_miss_threshold=None, profile_overrides=None):
        _ = (input_path, label, next_high_hit_threshold, profile_overrides)
        is_baseline = profile_name == "trend_continuation_strength_v2"
        return {
            "label": label,
            "profile_name": profile_name,
            "profile_config": {
                "name": profile_name,
                "select_threshold": 0.46 if is_baseline else 0.34,
                "near_miss_threshold": 0.34 if is_baseline else 0.24,
            },
            "profile_overrides": {} if is_baseline else {"select_threshold": 0.34, "near_miss_threshold": 0.24},
            "trade_dates": ["2026-03-24"],
            "decision_counts": {"selected": 1, "near_miss": 2, "rejected": 3},
            "surface_summaries": {
                "tradeable": {
                    "total_count": 3,
                    "closed_cycle_count": 3,
                    "next_high_hit_rate_at_threshold": 0.80,
                    "next_close_positive_rate": 0.80,
                    "t_plus_2_close_positive_rate": 0.80,
                    "next_high_return_distribution": {"mean": 0.05},
                    "next_close_return_distribution": {"mean": 0.02, "median": 0.025, "p10": 0.01},
                    "t_plus_2_close_return_distribution": {"mean": 0.025, "median": 0.02, "p10": 0.005},
                },
                "selected": {"total_count": 1},
                "near_miss": {"total_count": 2},
                "execution_eligible": {"total_count": 0 if is_baseline else 1},
            },
            "false_negative_proxy_summary": {"count": 0, "surface_metrics": {}},
        }

    monkeypatch.setattr(multi_window_validation, "analyze_btst_profile_replay_window", _fake_replay_window)

    analysis = multi_window_validation.analyze_btst_multi_window_profile_validation(
        reports_root,
        baseline_profile="trend_continuation_strength_v2",
        variant_profile="trend_continuation_strength_v3",
        variant_select_threshold=0.34,
        variant_near_miss_threshold=0.24,
    )

    attribution = analysis["rows"][0]["runtime_activation_attribution"]
    assert attribution["execution_eligible_count_delta"] == 1
    assert "execution_eligible_surface" in attribution["activation_change_labels"]


def test_analyze_btst_multi_window_profile_validation_surfaces_upstream_shadow_runtime_activation_delta(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_window_a"
    (report_dir / "selection_artifacts" / "2026-03-24").mkdir(parents=True)
    (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(multi_window_validation, "discover_report_dirs", lambda *_args, **_kwargs: [report_dir])

    def _fake_replay_window(input_path, *, profile_name, label, next_high_hit_threshold, select_threshold=None, near_miss_threshold=None, profile_overrides=None):
        _ = (input_path, label, next_high_hit_threshold, select_threshold, near_miss_threshold, profile_overrides)
        is_baseline = not profile_overrides
        return {
            "label": label,
            "profile_name": profile_name,
            "profile_config": {"name": profile_name, "select_threshold": 0.4, "near_miss_threshold": 0.34},
            "profile_overrides": {} if is_baseline else {"liquidity_shadow_source_specific_rank_cap_require_relief_applied": False},
            "surface_summaries": {
                "tradeable": {
                    "total_count": 3 if is_baseline else 6,
                    "closed_cycle_count": 3 if is_baseline else 6,
                    "next_high_hit_rate_at_threshold": 0.50,
                    "next_close_positive_rate": 0.50,
                    "t_plus_2_close_positive_rate": 0.50,
                    "next_high_return_distribution": {"mean": 0.04},
                    "next_close_return_distribution": {"mean": 0.01, "median": 0.01, "p10": -0.02},
                    "t_plus_2_close_return_distribution": {"mean": 0.02, "median": 0.02, "p10": -0.01},
                },
                "selected": {"total_count": 1 if is_baseline else 3},
                "near_miss": {"total_count": 2 if is_baseline else 3},
                "execution_eligible": {"total_count": 1 if is_baseline else 2},
            },
            "false_negative_proxy_summary": {"count": 0, "surface_metrics": {}},
            "frontier_source_family_summaries": {
                "upstream_liquidity_corridor_shadow": {
                    "tradeable": {"total_count": 1 if is_baseline else 4},
                    "selected": {"total_count": 0 if is_baseline else 2},
                    "near_miss": {"total_count": 1 if is_baseline else 2},
                    "execution_eligible": {"total_count": 0 if is_baseline else 1},
                }
            },
        }

    monkeypatch.setattr(multi_window_validation, "analyze_btst_profile_replay_window", _fake_replay_window)

    analysis = multi_window_validation.analyze_btst_multi_window_profile_validation(
        reports_root,
        baseline_profile="btst_precision_v2_liquidity_shadow_release_probe",
        variant_profile="btst_precision_v2_liquidity_shadow_release_probe",
        variant_profile_overrides={"liquidity_shadow_source_specific_rank_cap_require_relief_applied": False},
        next_high_hit_threshold=0.15,
    )

    row = analysis["rows"][0]
    upstream_delta = row["upstream_shadow_runtime_activation_attribution"]
    assert upstream_delta["selected_count_delta"] == 2
    assert upstream_delta["near_miss_count_delta"] == 1
    assert upstream_delta["tradeable_count_delta"] == 3
    assert upstream_delta["execution_eligible_count_delta"] == 1
    assert row["baseline_upstream_shadow_tradeable"]["total_count"] == 1
    assert row["variant_upstream_shadow_tradeable"]["total_count"] == 4


def test_analyze_btst_multi_window_profile_validation_identifies_watchlist_shrink_without_boundary_overlap(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_window_a"
    (report_dir / "selection_artifacts" / "2026-03-24").mkdir(parents=True)
    (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(multi_window_validation, "discover_report_dirs", lambda *_args, **_kwargs: [report_dir])

    def _fake_replay_window(input_path, *, profile_name, label, next_high_hit_threshold, select_threshold=None, near_miss_threshold=None, profile_overrides=None):
        _ = (input_path, label, next_high_hit_threshold, profile_overrides)
        is_baseline = profile_name == "trend_continuation_strength_v2"
        rows = [
            {
                "ticker": "601869",
                "candidate_source": "watchlist_filter_diagnostics",
                "decision": "selected" if is_baseline else "selected",
                "score_target": 0.60,
                "metrics_payload": {
                    "effective_select_threshold": 0.46 if is_baseline else 0.51,
                    "watchlist_filter_diagnostics_selected_only_shrink_guard": {
                        "applied": not is_baseline,
                        "eligible": not is_baseline,
                        "select_threshold_lift": 0.05 if not is_baseline else 0.0,
                        "gate_hits": {
                            "candidate_source": True,
                            "catalyst_freshness": True,
                            "trend_acceleration": True,
                            "close_strength": True,
                        },
                    },
                },
            },
            {
                "ticker": "300502",
                "candidate_source": "watchlist_filter_diagnostics",
                "decision": "rejected",
                "score_target": 0.18,
                "metrics_payload": {
                    "effective_select_threshold": 0.46 if is_baseline else 0.46,
                    "watchlist_filter_diagnostics_selected_only_shrink_guard": {
                        "applied": not is_baseline,
                        "eligible": not is_baseline,
                        "select_threshold_lift": 0.05 if not is_baseline else 0.0,
                        "gate_hits": {
                            "candidate_source": True,
                            "catalyst_freshness": True,
                            "trend_acceleration": True,
                            "close_strength": True,
                        },
                    },
                },
            },
        ]
        return {
            "label": label,
            "profile_name": profile_name,
            "profile_config": {
                "name": profile_name,
                "select_threshold": 0.46 if is_baseline else 0.46,
                "near_miss_threshold": 0.34 if is_baseline else 0.34,
            },
            "profile_overrides": {},
            "trade_dates": ["2026-03-24"],
            "rows": rows,
            "decision_counts": {"selected": 1, "rejected": 1},
            "surface_summaries": {
                "tradeable": {
                    "total_count": 1,
                    "closed_cycle_count": 1,
                    "next_high_hit_rate_at_threshold": 0.80,
                    "next_close_positive_rate": 0.80,
                    "t_plus_2_close_positive_rate": 0.80,
                    "next_high_return_distribution": {"mean": 0.05},
                    "next_close_return_distribution": {"mean": 0.02, "median": 0.025, "p10": 0.01},
                    "t_plus_2_close_return_distribution": {"mean": 0.025, "median": 0.02, "p10": 0.005},
                },
                "selected": {"total_count": 1},
                "near_miss": {"total_count": 0},
                "execution_eligible": {"total_count": 0},
            },
            "false_negative_proxy_summary": {"count": 0, "surface_metrics": {}},
        }

    monkeypatch.setattr(multi_window_validation, "analyze_btst_profile_replay_window", _fake_replay_window)

    analysis = multi_window_validation.analyze_btst_multi_window_profile_validation(
        reports_root,
        baseline_profile="trend_continuation_strength_v2",
        variant_profile="trend_continuation_strength_v3",
    )

    attribution = analysis["rows"][0]["runtime_activation_attribution"]
    assert attribution["watchlist_shrink_guard_applied_count"] == 2
    assert attribution["watchlist_shrink_selected_gate_pass_count"] == 1
    assert attribution["watchlist_shrink_selected_boundary_overlap_count"] == 0
    assert attribution["watchlist_shrink_selected_above_lift_count"] == 1
    assert attribution["zero_delta_reason"] == "watchlist_shrink_guard_without_selected_boundary_overlap"


def test_render_btst_multi_window_profile_validation_markdown_includes_runtime_activation_attribution(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_window_a"
    (report_dir / "selection_artifacts" / "2026-03-24").mkdir(parents=True)
    (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(multi_window_validation, "discover_report_dirs", lambda *_args, **_kwargs: [report_dir])

    def _fake_replay_window(input_path, *, profile_name, label, next_high_hit_threshold, select_threshold=None, near_miss_threshold=None, profile_overrides=None):
        _ = (input_path, label, next_high_hit_threshold, profile_overrides)
        is_baseline = profile_name == "trend_continuation_strength_v2"
        return {
            "label": label,
            "profile_name": profile_name,
            "profile_config": {
                "name": profile_name,
                "select_threshold": 0.46 if is_baseline else 0.34,
                "near_miss_threshold": 0.34 if is_baseline else 0.24,
            },
            "profile_overrides": {} if is_baseline else {"select_threshold": 0.34, "near_miss_threshold": 0.24},
            "trade_dates": ["2026-03-24"],
            "decision_counts": {"selected": 1, "near_miss": 2, "rejected": 3},
            "surface_summaries": {
                "tradeable": {
                    "total_count": 3,
                    "closed_cycle_count": 3,
                    "next_high_hit_rate_at_threshold": 0.80,
                    "next_close_positive_rate": 0.80,
                    "t_plus_2_close_positive_rate": 0.80,
                    "next_high_return_distribution": {"mean": 0.05},
                    "next_close_return_distribution": {"mean": 0.02, "median": 0.025, "p10": 0.01},
                    "t_plus_2_close_return_distribution": {"mean": 0.025, "median": 0.02, "p10": 0.005},
                },
                "selected": {"total_count": 1},
                "near_miss": {"total_count": 2},
            },
            "false_negative_proxy_summary": {"count": 0, "surface_metrics": {}},
        }

    monkeypatch.setattr(multi_window_validation, "analyze_btst_profile_replay_window", _fake_replay_window)

    analysis = multi_window_validation.analyze_btst_multi_window_profile_validation(
        reports_root,
        baseline_profile="trend_continuation_strength_v2",
        variant_profile="trend_continuation_strength_v3",
        variant_select_threshold=0.34,
        variant_near_miss_threshold=0.24,
    )

    markdown = multi_window_validation.render_btst_multi_window_profile_validation_markdown(analysis)
    assert "activation_attribution=threshold_probe_without_runtime_activation_delta" in markdown
    assert "selected_delta=0" in markdown
    assert "near_miss_delta=0" in markdown


def test_render_btst_multi_window_profile_validation_markdown_includes_watchlist_shrink_diagnostics(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_window_a"
    (report_dir / "selection_artifacts" / "2026-03-24").mkdir(parents=True)
    (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(multi_window_validation, "discover_report_dirs", lambda *_args, **_kwargs: [report_dir])

    def _fake_replay_window(input_path, *, profile_name, label, next_high_hit_threshold, select_threshold=None, near_miss_threshold=None, profile_overrides=None):
        _ = (input_path, label, next_high_hit_threshold, profile_overrides)
        is_baseline = profile_name == "trend_continuation_strength_v2"
        rows = [
            {
                "ticker": "601869",
                "candidate_source": "watchlist_filter_diagnostics",
                "decision": "selected",
                "score_target": 0.60,
                "metrics_payload": {
                    "effective_select_threshold": 0.46 if is_baseline else 0.51,
                    "watchlist_filter_diagnostics_selected_only_shrink_guard": {
                        "applied": not is_baseline,
                        "eligible": not is_baseline,
                        "select_threshold_lift": 0.05 if not is_baseline else 0.0,
                        "gate_hits": {
                            "candidate_source": True,
                            "catalyst_freshness": True,
                            "trend_acceleration": True,
                            "close_strength": True,
                        },
                    },
                },
            }
        ]
        return {
            "label": label,
            "profile_name": profile_name,
            "profile_config": {
                "name": profile_name,
                "select_threshold": 0.46,
                "near_miss_threshold": 0.34,
            },
            "profile_overrides": {},
            "trade_dates": ["2026-03-24"],
            "rows": rows,
            "decision_counts": {"selected": 1},
            "surface_summaries": {
                "tradeable": {
                    "total_count": 1,
                    "closed_cycle_count": 1,
                    "next_high_hit_rate_at_threshold": 0.80,
                    "next_close_positive_rate": 0.80,
                    "t_plus_2_close_positive_rate": 0.80,
                    "next_high_return_distribution": {"mean": 0.05},
                    "next_close_return_distribution": {"mean": 0.02, "median": 0.025, "p10": 0.01},
                    "t_plus_2_close_return_distribution": {"mean": 0.025, "median": 0.02, "p10": 0.005},
                },
                "selected": {"total_count": 1},
                "near_miss": {"total_count": 0},
                "execution_eligible": {"total_count": 0},
            },
            "false_negative_proxy_summary": {"count": 0, "surface_metrics": {}},
        }

    monkeypatch.setattr(multi_window_validation, "analyze_btst_profile_replay_window", _fake_replay_window)

    analysis = multi_window_validation.analyze_btst_multi_window_profile_validation(
        reports_root,
        baseline_profile="trend_continuation_strength_v2",
        variant_profile="trend_continuation_strength_v3",
    )

    markdown = multi_window_validation.render_btst_multi_window_profile_validation_markdown(analysis)
    assert "watchlist_shrink_applied=1" in markdown
    assert "watchlist_shrink_selected_boundary_overlap=0" in markdown


def test_render_btst_multi_window_profile_validation_markdown_includes_execution_eligible_delta(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_window_a"
    (report_dir / "selection_artifacts" / "2026-03-24").mkdir(parents=True)
    (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(multi_window_validation, "discover_report_dirs", lambda *_args, **_kwargs: [report_dir])

    def _fake_replay_window(input_path, *, profile_name, label, next_high_hit_threshold, select_threshold=None, near_miss_threshold=None, profile_overrides=None):
        _ = (input_path, label, next_high_hit_threshold, profile_overrides)
        is_baseline = select_threshold is None
        return {
            "label": label,
            "profile_name": profile_name,
            "profile_config": {
                "name": profile_name,
                "select_threshold": 0.46 if is_baseline else 0.34,
                "near_miss_threshold": 0.34 if is_baseline else 0.24,
            },
            "profile_overrides": {} if is_baseline else {"select_threshold": 0.34, "near_miss_threshold": 0.24},
            "trade_dates": ["2026-03-24"],
            "decision_counts": {"selected": 1, "near_miss": 2, "rejected": 3},
            "surface_summaries": {
                "tradeable": {
                    "total_count": 3,
                    "closed_cycle_count": 3,
                    "next_high_hit_rate_at_threshold": 0.80,
                    "next_close_positive_rate": 0.80,
                    "t_plus_2_close_positive_rate": 0.80,
                    "next_high_return_distribution": {"mean": 0.05},
                    "next_close_return_distribution": {"mean": 0.02, "median": 0.025, "p10": 0.01},
                    "t_plus_2_close_return_distribution": {"mean": 0.025, "median": 0.02, "p10": 0.005},
                },
                "selected": {"total_count": 1},
                "near_miss": {"total_count": 2},
                "execution_eligible": {"total_count": 0 if is_baseline else 1},
            },
            "false_negative_proxy_summary": {"count": 0, "surface_metrics": {}},
        }

    monkeypatch.setattr(multi_window_validation, "analyze_btst_profile_replay_window", _fake_replay_window)

    analysis = multi_window_validation.analyze_btst_multi_window_profile_validation(
        reports_root,
        baseline_profile="trend_continuation_strength_v2",
        variant_profile="trend_continuation_strength_v3",
        variant_select_threshold=0.34,
        variant_near_miss_threshold=0.24,
    )

    markdown = multi_window_validation.render_btst_multi_window_profile_validation_markdown(analysis)
    assert "execution_eligible_delta=1" in markdown
