from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_catalyst_theme_frontier import analyze_catalyst_theme_frontier, render_catalyst_theme_frontier_markdown


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_analyze_catalyst_theme_frontier_promotes_shadow_candidates(tmp_path: Path) -> None:
    report_dir = tmp_path / "paper_trading_20260331_20260331_live_m2_7_short_trade_only"
    _write_json(
        report_dir / "selection_artifacts" / "2026-03-31" / "selection_snapshot.json",
        {
            "trade_date": "20260331",
            "catalyst_theme_candidates": [
                {
                    "ticker": "300999",
                    "decision": "catalyst_theme",
                    "score_target": 0.4126,
                    "candidate_source": "catalyst_theme",
                    "gate_status": {"data": "pass", "structural": "fail", "score": "proxy_only"},
                    "metrics": {
                        "breakout_freshness": 0.31,
                        "trend_acceleration": 0.26,
                        "close_strength": 0.57,
                        "sector_resonance": 0.25,
                        "catalyst_freshness": 0.84,
                    },
                }
            ],
            "catalyst_theme_shadow_candidates": [
                {
                    "ticker": "301001",
                    "decision": "catalyst_theme_shadow",
                    "score_target": 0.32,
                    "candidate_source": "catalyst_theme_shadow",
                    "filter_reason": "sector_resonance_below_catalyst_theme_floor",
                    "threshold_shortfalls": {"candidate_score": 0.02, "sector_resonance": 0.03},
                    "failed_threshold_count": 2,
                    "total_shortfall": 0.05,
                    "gate_status": {"data": "pass", "structural": "fail", "score": "shadow"},
                    "metrics": {
                        "breakout_freshness": 0.14,
                        "trend_acceleration": 0.21,
                        "close_strength": 0.41,
                        "sector_resonance": 0.22,
                        "catalyst_freshness": 0.82,
                    },
                },
                {
                    "ticker": "301002",
                    "decision": "catalyst_theme_shadow",
                    "score_target": 0.29,
                    "candidate_source": "catalyst_theme_shadow",
                    "filter_reason": "close_strength_below_catalyst_theme_floor",
                    "threshold_shortfalls": {"candidate_score": 0.05, "close_strength": 0.05, "catalyst_freshness": 0.04},
                    "failed_threshold_count": 3,
                    "total_shortfall": 0.14,
                    "gate_status": {"data": "pass", "structural": "fail", "score": "shadow"},
                    "metrics": {
                        "breakout_freshness": 0.12,
                        "trend_acceleration": 0.19,
                        "close_strength": 0.15,
                        "sector_resonance": 0.21,
                        "catalyst_freshness": 0.41,
                    },
                },
            ],
        },
    )

    analysis = analyze_catalyst_theme_frontier(
        report_dir,
        candidate_score_min_grid=[0.34, 0.32],
        breakout_min_grid=[0.10],
        close_min_grid=[0.20],
        sector_min_grid=[0.25, 0.22],
        catalyst_min_grid=[0.45],
        max_candidates_per_trade_date=8,
    )

    assert analysis["baseline_selected_count"] == 1
    assert analysis["shadow_candidate_count"] == 2
    assert analysis["baseline_variant"]["promoted_shadow_count"] == 0
    assert analysis["recommended_variant"]["promoted_shadow_count"] == 1
    assert analysis["recommended_variant"]["top_promoted_rows"][0]["ticker"] == "301001"
    assert "sector_resonance_below_catalyst_theme_floor" in analysis["recommended_variant"]["promoted_filter_reason_counts"]

    markdown = render_catalyst_theme_frontier_markdown(analysis)
    assert "# Catalyst Theme Frontier Review" in markdown
    assert "## Recommended Variant" in markdown
    assert "301001" in markdown
    assert "## Promoted Shadow Examples" in markdown
