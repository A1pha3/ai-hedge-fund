from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_prepared_breakout_residual_surface import (
    analyze_btst_prepared_breakout_residual_surface,
    render_btst_prepared_breakout_residual_surface_markdown,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_analyze_btst_prepared_breakout_residual_surface_marks_600988_non_actionable(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_live"
    report_dir.mkdir(parents=True)
    cohort_path = reports_root / "btst_prepared_breakout_cohort_latest.json"
    _write_json(
        cohort_path,
        {
            "next_candidate": {"ticker": "600988"},
            "candidates": [
                {
                    "ticker": "300505",
                    "rows": [{"report_dir": str(report_dir)}],
                },
                {
                    "ticker": "600988",
                    "rows": [{"report_dir": str(report_dir)}],
                },
            ],
        },
    )
    monkeypatch.setattr(
        "scripts.analyze_btst_prepared_breakout_residual_surface.load_selection_target_replay_sources",
        lambda report_dir: [(report_dir / "selection_artifacts" / "2026-03-24" / "selection_target_replay_input.json", {"selection_targets": {"300505": {}, "600988": {}}})],
    )
    monkeypatch.setattr(
        "scripts.analyze_btst_prepared_breakout_residual_surface.analyze_selection_target_replay_sources",
        lambda replay_sources, profile_name="default", focus_tickers=None: {
            "focused_score_diagnostics": [
                {
                    "ticker": "600988",
                    "trade_date": "2026-03-24",
                    "replayed_decision": "rejected",
                    "replayed_score_target": 0.3666,
                    "replayed_gap_to_near_miss": 0.0934,
                    "replayed_gap_to_selected": 0.2134,
                    "replayed_gate_status": {"score": "fail", "structural": "pass", "execution": "pass", "data": "pass"},
                    "replayed_top_reasons": ["trend_acceleration=0.56", "prepared_breakout", "score_short=0.37"],
                    "replay_input_path": str(report_dir / "selection_artifacts" / "2026-03-24" / "selection_target_replay_input.json"),
                    "replayed_weighted_positive_contributions": {
                        "breakout_freshness": 0.0675,
                        "trend_acceleration": 0.1003,
                        "volume_expansion_quality": 0.0307,
                        "close_strength": 0.1233,
                        "sector_resonance": 0.048,
                        "catalyst_freshness": 0.0,
                        "layer_c_alignment": 0.0761,
                    },
                    "replayed_weighted_negative_contributions": {
                        "stale_trend_repair_penalty": 0.0484,
                        "overhead_supply_penalty": 0.0,
                        "extension_without_room_penalty": 0.031,
                        "layer_c_avoid_penalty": 0.0,
                        "watchlist_zero_catalyst_penalty": 0.0,
                        "watchlist_zero_catalyst_crowded_penalty": 0.0,
                        "watchlist_zero_catalyst_flat_trend_penalty": 0.0,
                    },
                    "replayed_metrics_payload": {
                        "breakout_stage": "prepared_breakout",
                        "breakout_freshness": 0.307,
                        "trend_acceleration": 0.557,
                        "volume_expansion_quality": 0.1919,
                        "close_strength": 0.8807,
                        "sector_resonance": 0.4,
                        "catalyst_freshness": 0.0,
                        "layer_c_alignment": 0.761,
                        "long_trend_strength": 0.0,
                    },
                    "replayed_explainability_payload": {
                        "prepared_breakout_penalty_relief": {
                            "eligible": False,
                            "applied": False,
                            "gate_hits": {"breakout_freshness_cap": False, "long_trend_strength": False},
                        },
                        "prepared_breakout_catalyst_relief": {
                            "eligible": False,
                            "applied": False,
                            "gate_hits": {"breakout_freshness_cap": False, "long_trend_strength": False},
                        },
                        "prepared_breakout_volume_relief": {
                            "eligible": False,
                            "applied": False,
                            "gate_hits": {"breakout_freshness_cap": False, "volatility_regime": False, "atr_ratio": False},
                        },
                        "prepared_breakout_continuation_relief": {
                            "eligible": False,
                            "applied": False,
                            "gate_hits": {"breakout_freshness_cap": False, "trend_acceleration_cap": False, "long_trend_strength": False},
                        },
                        "prepared_breakout_selected_catalyst_relief": {
                            "eligible": False,
                            "applied": False,
                            "gate_hits": {"trend_acceleration_min": False, "volume_expansion_quality": False, "long_trend_strength": False},
                        },
                    },
                },
                {
                    "ticker": "300505",
                    "trade_date": "2026-03-24",
                    "replayed_decision": "selected",
                    "replayed_score_target": 0.6056,
                    "replayed_gap_to_near_miss": -0.1456,
                    "replayed_gap_to_selected": -0.0256,
                    "replayed_gate_status": {"score": "pass", "structural": "pass", "execution": "pass", "data": "pass"},
                    "replayed_top_reasons": ["trend_acceleration=0.78", "prepared_breakout_penalty_relief"],
                    "replay_input_path": str(report_dir / "selection_artifacts" / "2026-03-24" / "selection_target_replay_input.json"),
                    "replayed_weighted_positive_contributions": {
                        "breakout_freshness": 0.028,
                        "trend_acceleration": 0.156,
                        "volume_expansion_quality": 0.07,
                        "close_strength": 0.0413,
                        "sector_resonance": 0.0123,
                        "catalyst_freshness": 0.2,
                        "layer_c_alignment": 0.1478,
                    },
                    "replayed_weighted_negative_contributions": {
                        "stale_trend_repair_penalty": 0.0318,
                        "overhead_supply_penalty": 0.0,
                        "extension_without_room_penalty": 0.018,
                        "layer_c_avoid_penalty": 0.0,
                        "watchlist_zero_catalyst_penalty": 0.0,
                        "watchlist_zero_catalyst_crowded_penalty": 0.0,
                        "watchlist_zero_catalyst_flat_trend_penalty": 0.0,
                    },
                    "replayed_metrics_payload": {
                        "breakout_stage": "prepared_breakout",
                        "breakout_freshness": 0.127,
                        "trend_acceleration": 0.8665,
                        "volume_expansion_quality": 0.4375,
                        "close_strength": 0.295,
                        "sector_resonance": 0.1026,
                        "catalyst_freshness": 1.0,
                        "layer_c_alignment": 1.478,
                        "long_trend_strength": 1.0,
                    },
                    "replayed_explainability_payload": {
                        "prepared_breakout_penalty_relief": {"eligible": True, "applied": True, "gate_hits": {"breakout_freshness_cap": True}},
                        "prepared_breakout_catalyst_relief": {"eligible": True, "applied": True, "gate_hits": {"breakout_freshness_cap": True}},
                        "prepared_breakout_volume_relief": {"eligible": True, "applied": True, "gate_hits": {"volatility_regime": True}},
                        "prepared_breakout_continuation_relief": {"eligible": True, "applied": True, "gate_hits": {"trend_acceleration_cap": True}},
                        "prepared_breakout_selected_catalyst_relief": {"eligible": True, "applied": True, "gate_hits": {"trend_acceleration_min": True}},
                    },
                },
            ]
        },
    )

    analysis = analyze_btst_prepared_breakout_residual_surface(reports_root, cohort_path=cohort_path)

    assert analysis["focus_ticker"] == "600988"
    assert analysis["verdict"] == "non_actionable_score_surface"
    assert analysis["focus_surface"]["decision_counts"] == {"rejected": 1}
    assert analysis["focus_surface"]["relief_eligible_window_counts"]["prepared_breakout_penalty_relief"] == 0
    assert analysis["focus_surface"]["relief_gate_miss_counts"]["prepared_breakout_penalty_relief"]["breakout_freshness_cap"] == 1
    assert analysis["comparison_vs_reference"]["score_target_mean_delta"] < 0
    assert analysis["priority_residual_candidates"][0]["ticker"] == "600988"

    markdown = render_btst_prepared_breakout_residual_surface_markdown(analysis)
    assert "# BTST Prepared-Breakout Residual Surface" in markdown
    assert "non_actionable_score_surface" in markdown
    assert "600988" in markdown
