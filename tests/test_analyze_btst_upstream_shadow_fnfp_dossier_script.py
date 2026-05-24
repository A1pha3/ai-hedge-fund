from __future__ import annotations

import json

from scripts.analyze_btst_upstream_shadow_fnfp_dossier import (
    analyze_btst_upstream_shadow_fnfp_dossier,
    render_btst_upstream_shadow_fnfp_dossier_markdown,
)


def test_analyze_btst_upstream_shadow_fnfp_dossier_splits_false_negative_and_false_positive(monkeypatch, tmp_path):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts" / "2026-04-01"
    selection_root.mkdir(parents=True)

    (selection_root / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-04-01",
                "selection_targets": {
                    "300683": {
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.54,
                            "blockers": ["trend_not_constructive"],
                            "top_reasons": ["score_short=0.54"],
                            "metrics_payload": {"trend_acceleration": 0.86, "close_strength": 0.88},
                            "historical_prior": {
                                "execution_quality_label": "close_continuation",
                                "evaluable_count": 4,
                                "next_close_positive_rate": 0.75,
                            },
                        },
                    },
                    "301188": {
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "short_trade": {
                            "decision": "selected",
                            "score_target": 0.63,
                            "blockers": [],
                            "top_reasons": ["score_short=0.63"],
                            "metrics_payload": {"trend_acceleration": 0.42, "close_strength": 0.52},
                            "historical_prior": {
                                "execution_quality_label": "balanced_confirmation",
                                "evaluable_count": 6,
                                "next_close_positive_rate": 0.33,
                            },
                        },
                    },
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    def _fake_extract_btst_price_outcome(ticker: str, trade_date: str, price_cache):
        assert trade_date == "2026-04-01"
        if ticker == "300683":
            return {"next_close_return": 0.041, "t_plus_2_close_return": 0.082, "cycle_status": "closed"}
        return {"next_close_return": -0.031, "t_plus_2_close_return": -0.054, "cycle_status": "closed"}

    monkeypatch.setattr(
        "scripts.analyze_btst_upstream_shadow_fnfp_dossier.extract_btst_price_outcome",
        _fake_extract_btst_price_outcome,
    )

    analysis = analyze_btst_upstream_shadow_fnfp_dossier(tmp_path)

    assert analysis["cohort_count"] == 2
    assert analysis["false_negative_count"] == 1
    assert analysis["false_positive_count"] == 1
    assert analysis["false_negative_rows"][0]["ticker"] == "300683"
    assert analysis["false_positive_rows"][0]["ticker"] == "301188"
    assert analysis["quality_label_split"] == {"close_continuation": 1, "balanced_confirmation": 1}


def test_render_btst_upstream_shadow_fnfp_dossier_markdown_renders_summary_blocks():
    markdown = render_btst_upstream_shadow_fnfp_dossier_markdown(
        {
            "cohort_count": 2,
            "false_negative_count": 1,
            "false_positive_count": 1,
            "candidate_source_counts": {"upstream_liquidity_corridor_shadow": 2},
            "quality_label_split": {"close_continuation": 1, "balanced_confirmation": 1},
            "trend_acceleration_band_split": {"gte_0_80": {"count": 1}},
            "close_strength_band_split": {"gte_0_85": {"count": 1}},
            "repeat_ticker_board": [{"ticker": "300683", "count": 2}],
            "blocker_clusters": [{"blocker": "trend_not_constructive", "count": 1}],
            "false_negative_rows": [{"trade_date": "2026-04-01", "ticker": "300683"}],
            "false_positive_rows": [{"trade_date": "2026-04-01", "ticker": "301188"}],
            "recommendation": "Prioritize close_continuation upstream-shadow rows that narrowly missed selection.",
        }
    )

    assert "# Upstream Shadow FN/FP Dossier" in markdown
    assert "false_negative_count: 1" in markdown
    assert "300683" in markdown
    assert "trend_not_constructive" in markdown
