from __future__ import annotations

from pathlib import Path

import scripts.analyze_btst_candidate_entry_payoff_validation as payoff_validation


def test_build_variant_structural_overrides_returns_custom_weak_structure_filter() -> None:
    overrides = payoff_validation.build_variant_structural_overrides(
        breakout_freshness_max=0.05,
        trend_acceleration_max=0.37,
        volume_expansion_quality_max=0.05,
        catalyst_freshness_max=0.05,
    )

    assert overrides == {
        "exclude_candidate_entries": [
            {
                "name": "watchlist_avoid_boundary_weak_structure_entry",
                "candidate_sources": ["watchlist_filter_diagnostics"],
                "all_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
                "metric_max_thresholds": {
                    "breakout_freshness": 0.05,
                    "trend_acceleration": 0.37,
                    "volume_expansion_quality": 0.05,
                    "catalyst_freshness": 0.05,
                },
            }
        ]
    }


def test_analyze_btst_candidate_entry_payoff_validation_flags_cleanup_without_actionable_delta(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_window_a"
    (report_dir / "selection_artifacts" / "2026-03-24").mkdir(parents=True)
    (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(payoff_validation, "discover_report_dirs", lambda *_args, **_kwargs: [report_dir])

    def _fake_replay_window(
        input_path,
        *,
        profile_name,
        label,
        next_high_hit_threshold,
        structural_variant="baseline",
        structural_overrides=None,
    ):
        _ = (input_path, profile_name, label, next_high_hit_threshold, structural_overrides)
        is_baseline = structural_overrides is None
        return {
            "label": label,
            "profile_name": profile_name,
            "structural_variant": structural_variant,
            "structural_overrides": structural_overrides,
            "trade_dates": ["2026-03-24"],
            "surface_summaries": {
                "tradeable": {
                    "total_count": 3,
                    "closed_cycle_count": 3,
                    "next_high_hit_rate_at_threshold": 0.6667,
                    "next_close_positive_rate": 0.6667,
                    "t_plus_2_close_positive_rate": 0.6667,
                    "next_high_return_distribution": {"mean": 0.041},
                    "next_close_return_distribution": {"mean": 0.012, "median": 0.011, "p10": -0.017},
                    "t_plus_2_close_return_distribution": {"mean": 0.014, "median": 0.013, "p10": -0.004},
                },
                "selected": {
                    "total_count": 1,
                    "closed_cycle_count": 1,
                    "next_high_hit_rate_at_threshold": 1.0,
                    "next_close_positive_rate": 1.0,
                    "t_plus_2_close_positive_rate": 1.0,
                    "next_high_return_distribution": {"mean": 0.052},
                    "next_close_return_distribution": {"mean": 0.021, "median": 0.021, "p10": 0.021},
                    "t_plus_2_close_return_distribution": {"mean": 0.024, "median": 0.024, "p10": 0.024},
                },
                "execution_eligible": {
                    "total_count": 1,
                    "closed_cycle_count": 1,
                    "next_high_hit_rate_at_threshold": 1.0,
                    "next_close_positive_rate": 1.0,
                    "t_plus_2_close_positive_rate": 1.0,
                    "next_high_return_distribution": {"mean": 0.052},
                    "next_close_return_distribution": {"mean": 0.021, "median": 0.021, "p10": 0.021},
                    "t_plus_2_close_return_distribution": {"mean": 0.024, "median": 0.024, "p10": 0.024},
                },
            },
            "false_negative_proxy_summary": {
                "count": 1,
                "surface_metrics": {
                    "next_high_hit_rate_at_threshold": 1.0,
                    "next_close_positive_rate": 1.0,
                },
            },
            "filtered_candidate_entry_summary": {
                "count": 0 if is_baseline else 2,
                "matched_filter_counts": {} if is_baseline else {"watchlist_avoid_boundary_weak_structure_entry": 2},
                "surface_metrics": {
                    "closed_cycle_count": 0 if is_baseline else 2,
                    "next_high_hit_rate_at_threshold": None if is_baseline else 0.0,
                    "next_close_positive_rate": None if is_baseline else 0.0,
                },
            },
            "candidate_entry_filter_observability": {} if is_baseline else {"watchlist_avoid_boundary_weak_structure_entry": {"precondition_match_count": 3, "metric_data_pass_count": 3, "metric_threshold_match_count": 2}},
        }

    monkeypatch.setattr(payoff_validation, "analyze_btst_profile_replay_window", _fake_replay_window)

    variant_structural_overrides = payoff_validation.build_variant_structural_overrides(
        breakout_freshness_max=0.05,
        trend_acceleration_max=0.37,
        volume_expansion_quality_max=0.05,
        catalyst_freshness_max=0.05,
    )
    analysis = payoff_validation.analyze_btst_candidate_entry_payoff_validation(
        reports_root,
        profile_name="trend_continuation_strength_v2",
        variant_structural_variant="baseline",
        variant_structural_overrides=variant_structural_overrides,
    )

    assert analysis["report_dir_count"] == 1
    assert analysis["variant_structural_overrides"] == variant_structural_overrides
    assert analysis["cleanup_only_count"] == 1
    assert analysis["variant_supports_t1_count"] == 0
    assert analysis["rows"][0]["payoff_classification"] == "entry_cleanup_without_actionable_delta"
    assert analysis["rows"][0]["filtered_candidate_entry_delta"] == 2
    assert analysis["rows"][0]["variant_structural_overrides"] == variant_structural_overrides
    assert analysis["recommendation"].startswith("Weak-structure candidate-entry rule is currently behaving like entry cleanup")


def test_render_btst_candidate_entry_payoff_validation_markdown_includes_filtered_delta(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_window_a"
    (report_dir / "selection_artifacts" / "2026-03-24").mkdir(parents=True)
    (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(payoff_validation, "discover_report_dirs", lambda *_args, **_kwargs: [report_dir])

    def _fake_replay_window(
        input_path,
        *,
        profile_name,
        label,
        next_high_hit_threshold,
        structural_variant="baseline",
        structural_overrides=None,
    ):
        _ = (input_path, profile_name, label, next_high_hit_threshold, structural_overrides)
        is_baseline = structural_overrides is None
        return {
            "label": label,
            "profile_name": profile_name,
            "structural_variant": structural_variant,
            "structural_overrides": structural_overrides,
            "trade_dates": ["2026-03-24"],
            "surface_summaries": {
                "tradeable": {
                    "total_count": 2,
                    "closed_cycle_count": 2,
                    "next_high_hit_rate_at_threshold": 0.5,
                    "next_close_positive_rate": 0.5,
                    "t_plus_2_close_positive_rate": 0.5,
                    "next_high_return_distribution": {"mean": 0.03},
                    "next_close_return_distribution": {"mean": 0.01, "median": 0.01, "p10": -0.02},
                    "t_plus_2_close_return_distribution": {"mean": 0.012, "median": 0.012, "p10": -0.01},
                },
                "selected": {"total_count": 1, "closed_cycle_count": 1, "next_high_hit_rate_at_threshold": 1.0, "next_close_positive_rate": 1.0, "t_plus_2_close_positive_rate": 1.0, "next_high_return_distribution": {"mean": 0.04}, "next_close_return_distribution": {"mean": 0.02, "median": 0.02, "p10": 0.02}, "t_plus_2_close_return_distribution": {"mean": 0.02, "median": 0.02, "p10": 0.02}},
                "execution_eligible": {"total_count": 1, "closed_cycle_count": 1, "next_high_hit_rate_at_threshold": 1.0, "next_close_positive_rate": 1.0, "t_plus_2_close_positive_rate": 1.0, "next_high_return_distribution": {"mean": 0.04}, "next_close_return_distribution": {"mean": 0.02, "median": 0.02, "p10": 0.02}, "t_plus_2_close_return_distribution": {"mean": 0.02, "median": 0.02, "p10": 0.02}},
            },
            "false_negative_proxy_summary": {"count": 0, "surface_metrics": {}},
            "filtered_candidate_entry_summary": {
                "count": 0 if is_baseline else 1,
                "matched_filter_counts": {} if is_baseline else {"watchlist_avoid_boundary_weak_structure_entry": 1},
                "surface_metrics": {} if is_baseline else {"closed_cycle_count": 1, "next_high_hit_rate_at_threshold": 0.0, "next_close_positive_rate": 0.0},
            },
            "candidate_entry_filter_observability": {},
        }

    monkeypatch.setattr(payoff_validation, "analyze_btst_profile_replay_window", _fake_replay_window)

    variant_structural_overrides = payoff_validation.build_variant_structural_overrides(
        breakout_freshness_max=0.05,
        trend_acceleration_max=0.37,
        volume_expansion_quality_max=0.05,
        catalyst_freshness_max=0.05,
    )
    analysis = payoff_validation.analyze_btst_candidate_entry_payoff_validation(
        reports_root,
        profile_name="trend_continuation_strength_v2",
        variant_structural_variant="baseline",
        variant_structural_overrides=variant_structural_overrides,
    )

    markdown = payoff_validation.render_btst_candidate_entry_payoff_validation_markdown(analysis)
    assert "# BTST Candidate Entry Payoff Validation" in markdown
    assert "filtered_candidate_entry_delta=1" in markdown
    assert "entry_cleanup_without_actionable_delta" in markdown
    assert "variant_structural_overrides" in markdown
