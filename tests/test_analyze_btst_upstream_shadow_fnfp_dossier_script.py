from __future__ import annotations

import json

from scripts.analyze_btst_upstream_shadow_fnfp_dossier import (
    _classify_upstream_shadow_row,
    analyze_btst_upstream_shadow_fnfp_dossier,
    render_btst_upstream_shadow_fnfp_dossier_markdown,
)


def test_classify_upstream_shadow_row_does_not_flag_balanced_confirmation_with_strong_positive_returns():
    assert (
        _classify_upstream_shadow_row(
            {
                "decision": "selected",
                "historical_execution_quality_label": "balanced_confirmation",
                "next_close_return": 0.034,
                "t_plus_2_close_return": 0.061,
            }
        )
        is None
    )


def test_classify_upstream_shadow_row_flags_balanced_confirmation_when_follow_through_stays_weak():
    assert (
        _classify_upstream_shadow_row(
            {
                "decision": "near_miss",
                "historical_execution_quality_label": "balanced_confirmation",
                "next_close_return": 0.012,
                "t_plus_2_close_return": 0.021,
            }
        )
        == "false_positive"
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

    second_selection_root = report_dir / "selection_artifacts" / "2026-04-02"
    second_selection_root.mkdir(parents=True)
    (second_selection_root / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-04-02",
                "selection_targets": {
                    "300999": {
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "short_trade": {
                            "decision": "near_miss",
                            "score_target": 0.57,
                            "blockers": ["trend_not_constructive", "weak_close_confirmation"],
                            "top_reasons": ["score_short=0.57"],
                            "metrics_payload": {"trend_acceleration": 0.67, "close_strength": 0.83},
                            "historical_prior": {
                                "execution_quality_label": "close_continuation",
                                "evaluable_count": 5,
                                "next_close_positive_rate": 0.8,
                            },
                        },
                    },
                    "300683": {
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.51,
                            "blockers": ["trend_not_constructive"],
                            "top_reasons": ["score_short=0.51"],
                            "metrics_payload": {"trend_acceleration": 0.91, "close_strength": 0.9},
                            "historical_prior": {
                                "execution_quality_label": "close_continuation",
                                "evaluable_count": 3,
                                "next_close_positive_rate": 0.67,
                            },
                        },
                    },
                    "301188": {
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "short_trade": {
                            "decision": "selected",
                            "score_target": 0.61,
                            "blockers": ["late_extension"],
                            "top_reasons": ["score_short=0.61"],
                            "metrics_payload": {"trend_acceleration": 0.59, "close_strength": 0.61},
                            "historical_prior": {
                                "execution_quality_label": "balanced_confirmation",
                                "evaluable_count": 4,
                                "next_close_positive_rate": 0.25,
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
        assert trade_date in {"2026-04-01", "2026-04-02"}
        if (ticker, trade_date) == ("300683", "2026-04-01"):
            return {"next_close_return": 0.041, "t_plus_2_close_return": 0.082, "cycle_status": "closed"}
        if (ticker, trade_date) == ("300999", "2026-04-02"):
            return {"next_close_return": 0.055, "t_plus_2_close_return": 0.11, "cycle_status": "closed"}
        if (ticker, trade_date) == ("300683", "2026-04-02"):
            return {"next_close_return": 0.034, "t_plus_2_close_return": 0.061, "cycle_status": "closed"}
        if (ticker, trade_date) == ("301188", "2026-04-01"):
            return {"next_close_return": -0.031, "t_plus_2_close_return": -0.054, "cycle_status": "closed"}
        return {"next_close_return": -0.022, "t_plus_2_close_return": -0.031, "cycle_status": "closed"}

    monkeypatch.setattr(
        "scripts.analyze_btst_upstream_shadow_fnfp_dossier.extract_btst_price_outcome",
        _fake_extract_btst_price_outcome,
    )

    analysis = analyze_btst_upstream_shadow_fnfp_dossier(tmp_path)

    assert analysis["cohort_count"] == 5
    assert analysis["false_negative_count"] == 3
    assert analysis["false_positive_count"] == 2
    assert [row["ticker"] for row in analysis["false_negative_rows"]] == ["300999", "300683", "300683"]
    assert analysis["false_negative_rows"][0]["trade_date"] == "2026-04-02"
    assert analysis["false_positive_rows"][0]["ticker"] == "301188"
    assert analysis["false_positive_rows"][0]["trade_date"] == "2026-04-01"
    assert analysis["quality_label_split"] == {"close_continuation": 3, "balanced_confirmation": 2}
    assert analysis["trend_acceleration_band_split"]["gte_0_80"]["count"] == 2
    assert analysis["trend_acceleration_band_split"]["gte_0_60_lt_0_80"]["count"] == 1
    assert analysis["close_strength_band_split"]["gte_0_85"]["count"] == 2
    assert analysis["close_strength_band_split"]["gte_0_60_lt_0_85"]["count"] == 2
    assert analysis["repeat_ticker_board"][0]["ticker"] == "300683"
    assert analysis["repeat_ticker_board"][0]["count"] == 2
    assert analysis["blocker_clusters"][0]["blocker"] == "trend_not_constructive"
    assert analysis["blocker_clusters"][0]["count"] == 3
    assert analysis["blocker_clusters"][1]["blocker"] == "late_extension"
    assert analysis["blocker_clusters"][1]["count"] == 1


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
    assert "## Repeat Ticker Board" in markdown
