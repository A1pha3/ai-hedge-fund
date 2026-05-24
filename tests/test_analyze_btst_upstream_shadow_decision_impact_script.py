from __future__ import annotations

from pathlib import Path

import scripts.analyze_btst_upstream_shadow_decision_impact as decision_impact


def test_analyze_upstream_shadow_decision_impact_ranks_quality_gate_variant(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir()

    fake_rows = {
        "current_probe_control": {
            "report_dir_count": 1,
            "rows": [
                {
                    "report_label": "paper_trading_window_a",
                    "window_recommendation": "mixed",
                    "tradeable_surface_delta": {
                        "next_close_positive_rate": 0.0,
                        "next_close_return_p10": 0.0,
                        "t_plus_2_close_return_median": 0.0,
                    },
                    "upstream_shadow_runtime_activation_attribution": {
                        "selected_count_delta": 0,
                        "near_miss_count_delta": 0,
                        "tradeable_count_delta": 0,
                        "execution_eligible_count_delta": 0,
                    },
                }
            ],
            "keep_baseline_count": 0,
            "variant_supports_t1_count": 0,
            "variant_improves_t2_only_count": 0,
            "recommendation": "mixed",
        },
        "relief_free_quality_gate": {
            "report_dir_count": 1,
            "rows": [
                {
                    "report_label": "paper_trading_window_a",
                    "window_recommendation": "variant_supports_t1_edge",
                    "tradeable_surface_delta": {
                        "next_close_positive_rate": 0.08,
                        "next_close_return_p10": 0.02,
                        "t_plus_2_close_return_median": 0.01,
                    },
                    "upstream_shadow_runtime_activation_attribution": {
                        "selected_count_delta": 2,
                        "near_miss_count_delta": 1,
                        "tradeable_count_delta": 3,
                        "execution_eligible_count_delta": 1,
                    },
                }
            ],
            "keep_baseline_count": 0,
            "variant_supports_t1_count": 1,
            "variant_improves_t2_only_count": 0,
            "recommendation": "Variant is promising across the observed windows and may be ready for a deeper rollout review.",
        },
        "relief_free_shadow_caps": {
            "report_dir_count": 1,
            "rows": [
                {
                    "report_label": "paper_trading_window_a",
                    "window_recommendation": "keep_baseline_default",
                    "tradeable_surface_delta": {
                        "next_close_positive_rate": -0.05,
                        "next_close_return_p10": -0.03,
                        "t_plus_2_close_return_median": 0.0,
                    },
                    "upstream_shadow_runtime_activation_attribution": {
                        "selected_count_delta": 3,
                        "near_miss_count_delta": 2,
                        "tradeable_count_delta": 5,
                        "execution_eligible_count_delta": 1,
                    },
                }
            ],
            "keep_baseline_count": 1,
            "variant_supports_t1_count": 0,
            "variant_improves_t2_only_count": 0,
            "recommendation": "Baseline should remain the default",
        },
        "relief_free_quality_gate_tighter_caps": {
            "report_dir_count": 1,
            "rows": [
                {
                    "report_label": "paper_trading_window_a",
                    "window_recommendation": "variant_supports_t1_edge",
                    "tradeable_surface_delta": {
                        "next_close_positive_rate": 0.03,
                        "next_close_return_p10": 0.01,
                        "t_plus_2_close_return_median": 0.02,
                    },
                    "upstream_shadow_runtime_activation_attribution": {
                        "selected_count_delta": 1,
                        "near_miss_count_delta": 1,
                        "tradeable_count_delta": 2,
                        "execution_eligible_count_delta": 1,
                    },
                }
            ],
            "keep_baseline_count": 0,
            "variant_supports_t1_count": 1,
            "variant_improves_t2_only_count": 0,
            "recommendation": "Variant is promising across the observed windows and may be ready for a deeper rollout review.",
        },
    }

    def _fake_validate(*, experiment_name: str, **kwargs):
        _ = kwargs
        payload = dict(fake_rows[experiment_name])
        payload["experiment_name"] = experiment_name
        return payload

    monkeypatch.setattr(decision_impact, "_run_experiment", _fake_validate)

    analysis = decision_impact.analyze_upstream_shadow_decision_impact(
        reports_root=reports_root,
        output_label="unit-test",
    )

    assert analysis["best_variant"]["experiment_name"] == "relief_free_quality_gate"
    assert analysis["rejected_variants"][0]["experiment_name"] == "relief_free_shadow_caps"
    assert analysis["best_variant"]["aggregate_upstream_shadow_delta"]["selected_count_delta"] == 2


def test_render_upstream_shadow_decision_impact_markdown_includes_best_variant() -> None:
    analysis = {
        "output_label": "unit-test",
        "best_variant": {
            "experiment_name": "relief_free_quality_gate",
            "aggregate_upstream_shadow_delta": {
                "selected_count_delta": 2,
                "near_miss_count_delta": 1,
                "tradeable_count_delta": 3,
                "execution_eligible_count_delta": 1,
            },
            "recommendation": "ready_for_rollout_review",
        },
        "rejected_variants": [],
        "ranked_variants": [],
    }

    markdown = decision_impact.render_upstream_shadow_decision_impact_markdown(analysis)
    assert "# Upstream Shadow Decision Impact" in markdown
    assert "relief_free_quality_gate" in markdown
    assert "selected_count_delta" in markdown
