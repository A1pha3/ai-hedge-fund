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
