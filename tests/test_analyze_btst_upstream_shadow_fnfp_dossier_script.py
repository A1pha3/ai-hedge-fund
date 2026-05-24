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


def test_classify_upstream_shadow_row_does_not_flag_balanced_confirmation_without_outcomes():
    assert (
        _classify_upstream_shadow_row(
            {
                "decision": "selected",
                "historical_execution_quality_label": "balanced_confirmation",
                "data_status": "missing_price_frame",
                "cycle_status": "missing_next_day",
            }
        )
        is None
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
    assert [row["ticker"] for row in analysis["false_negative_rows"]] == ["300683", "300683", "300999"]
    assert analysis["false_negative_rows"][0]["trade_date"] == "2026-04-01"
    assert analysis["false_positive_rows"][0]["ticker"] == "301188"
    assert analysis["false_positive_rows"][0]["trade_date"] == "2026-04-02"
    assert analysis["quality_label_split"] == {"close_continuation": 3, "balanced_confirmation": 2}
    assert analysis["trend_acceleration_band_split"]["gte_0_80"]["count"] == 2
    assert analysis["trend_acceleration_band_split"]["lt_0_80"]["count"] == 3
    assert analysis["close_strength_band_split"]["gte_0_85"]["count"] == 2
    assert analysis["close_strength_band_split"]["lt_0_85"]["count"] == 3
    assert analysis["repeat_ticker_board"][0]["ticker"] == "300683"
    assert analysis["repeat_ticker_board"][0]["count"] == 2
    assert analysis["blocker_clusters"][0]["blocker"] == "trend_not_constructive"
    assert analysis["blocker_clusters"][0]["count"] == 3
    assert {"blocker": "late_extension", "count": 1} in analysis["blocker_clusters"]


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


def test_analyze_btst_upstream_shadow_fnfp_dossier_deduplicates_rows_and_builds_band_splits(monkeypatch, tmp_path):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts" / "2026-04-02"
    selection_root.mkdir(parents=True)

    (selection_root / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-04-02",
                "selection_targets": {
                    "300683": {
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "short_trade": {
                            "decision": "near_miss",
                            "score_target": 0.57,
                            "blockers": ["trend_not_constructive"],
                            "top_reasons": ["score_short=0.57"],
                            "metrics_payload": {"trend_acceleration": 0.82, "close_strength": 0.87},
                            "historical_prior": {"execution_quality_label": "close_continuation", "evaluable_count": 3},
                        },
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (selection_root / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "upstream_shadow_observation_entries": [
                    {
                        "ticker": "300683",
                        "decision": "observation",
                        "score_target": 0.18,
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "blockers": ["trend_not_constructive"],
                        "top_reasons": ["candidate_score=0.18"],
                        "short_trade_boundary_metrics": {"trend_acceleration": 0.82, "close_strength": 0.87},
                    }
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "scripts.analyze_btst_upstream_shadow_fnfp_dossier.extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {"next_close_return": -0.02, "t_plus_2_close_return": -0.03, "cycle_status": "closed"},
    )

    analysis = analyze_btst_upstream_shadow_fnfp_dossier(tmp_path)

    assert analysis["cohort_count"] == 1
    assert analysis["false_positive_count"] == 1
    assert analysis["repeat_ticker_board"] == [{"ticker": "300683", "count": 1}]
    assert analysis["trend_acceleration_band_split"]["gte_0_80"]["count"] == 1
    assert analysis["close_strength_band_split"]["gte_0_85"]["count"] == 1


def test_analyze_btst_upstream_shadow_fnfp_dossier_handles_missing_outcomes_and_unknown_quality(monkeypatch, tmp_path):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts" / "2026-04-03"
    selection_root.mkdir(parents=True)

    (selection_root / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-04-03",
                "selection_targets": {
                    "301188": {
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "short_trade": {
                            "decision": "blocked",
                            "score_target": 0.22,
                            "blockers": ["trend_not_constructive"],
                            "top_reasons": ["score_short=0.22"],
                            "metrics_payload": {"trend_acceleration": 0.11, "close_strength": 0.41},
                        },
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "scripts.analyze_btst_upstream_shadow_fnfp_dossier.extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {"data_status": "missing_price_frame", "cycle_status": "missing_next_day"},
    )

    analysis = analyze_btst_upstream_shadow_fnfp_dossier(tmp_path)

    assert analysis["cohort_count"] == 1
    assert analysis["false_negative_count"] == 0
    assert analysis["false_positive_count"] == 0
    assert analysis["quality_label_split"] == {"unknown": 1}
    assert analysis["recommendation"] == "Collect more upstream-shadow outcome history before ranking FN/FP rows."


def test_analyze_btst_upstream_shadow_fnfp_dossier_ranks_false_negatives_by_repeat_ticker_frequency(monkeypatch, tmp_path):
    report_dir = tmp_path / "report"
    first_selection_root = report_dir / "selection_artifacts" / "2026-04-01"
    first_selection_root.mkdir(parents=True)
    (first_selection_root / "selection_snapshot.json").write_text(
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
                            "metrics_payload": {"trend_acceleration": 0.82, "close_strength": 0.86},
                            "historical_prior": {"execution_quality_label": "close_continuation", "evaluable_count": 4, "next_close_positive_rate": 0.72},
                        },
                    }
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
                    "300683": {
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "short_trade": {
                            "decision": "near_miss",
                            "score_target": 0.56,
                            "blockers": ["trend_not_constructive"],
                            "top_reasons": ["score_short=0.56"],
                            "metrics_payload": {"trend_acceleration": 0.79, "close_strength": 0.81},
                            "historical_prior": {"execution_quality_label": "close_continuation", "evaluable_count": 3, "next_close_positive_rate": 0.67},
                        },
                    },
                    "300999": {
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "short_trade": {
                            "decision": "rejected",
                            "score_target": 0.52,
                            "blockers": ["weak_close_confirmation"],
                            "top_reasons": ["score_short=0.52"],
                            "metrics_payload": {"trend_acceleration": 0.7, "close_strength": 0.78},
                            "historical_prior": {"execution_quality_label": "close_continuation", "evaluable_count": 5, "next_close_positive_rate": 0.79},
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
        outcomes = {
            ("300683", "2026-04-01"): {"next_close_return": 0.037, "t_plus_2_close_return": 0.072, "cycle_status": "closed"},
            ("300683", "2026-04-02"): {"next_close_return": 0.034, "t_plus_2_close_return": 0.061, "cycle_status": "closed"},
            ("300999", "2026-04-02"): {"next_close_return": 0.043, "t_plus_2_close_return": 0.089, "cycle_status": "closed"},
        }
        return outcomes[(ticker, trade_date)]

    monkeypatch.setattr(
        "scripts.analyze_btst_upstream_shadow_fnfp_dossier.extract_btst_price_outcome",
        _fake_extract_btst_price_outcome,
    )

    analysis = analyze_btst_upstream_shadow_fnfp_dossier(tmp_path)

    assert [row["ticker"] for row in analysis["false_negative_rows"]] == ["300683", "300683", "300999"]
    assert [row["trade_date"] for row in analysis["false_negative_rows"][:2]] == ["2026-04-01", "2026-04-02"]


def test_analyze_btst_upstream_shadow_fnfp_dossier_ranks_false_positives_by_blocker_severity(monkeypatch, tmp_path):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts" / "2026-04-03"
    selection_root.mkdir(parents=True)
    (selection_root / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-04-03",
                "selection_targets": {
                    "301188": {
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "short_trade": {
                            "decision": "selected",
                            "score_target": 0.63,
                            "blockers": ["late_extension"],
                            "top_reasons": ["score_short=0.63"],
                            "metrics_payload": {"trend_acceleration": 0.48, "close_strength": 0.58},
                            "historical_prior": {"execution_quality_label": "balanced_confirmation", "evaluable_count": 4, "next_close_positive_rate": 0.31},
                        },
                    },
                    "300111": {
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "short_trade": {
                            "decision": "selected",
                            "score_target": 0.61,
                            "blockers": ["trend_not_constructive", "weak_close_confirmation"],
                            "top_reasons": ["score_short=0.61"],
                            "metrics_payload": {"trend_acceleration": 0.44, "close_strength": 0.55},
                            "historical_prior": {"execution_quality_label": "balanced_confirmation", "evaluable_count": 5, "next_close_positive_rate": 0.29},
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
        outcomes = {
            ("301188", "2026-04-03"): {"next_close_return": -0.018, "t_plus_2_close_return": -0.028, "cycle_status": "closed"},
            ("300111", "2026-04-03"): {"next_close_return": -0.011, "t_plus_2_close_return": -0.012, "cycle_status": "closed"},
        }
        return outcomes[(ticker, trade_date)]

    monkeypatch.setattr(
        "scripts.analyze_btst_upstream_shadow_fnfp_dossier.extract_btst_price_outcome",
        _fake_extract_btst_price_outcome,
    )

    analysis = analyze_btst_upstream_shadow_fnfp_dossier(tmp_path)

    assert [row["ticker"] for row in analysis["false_positive_rows"]] == ["300111", "301188"]


def test_analyze_btst_upstream_shadow_fnfp_dossier_ranks_false_positives_by_penalty_severity(monkeypatch, tmp_path):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts" / "2026-04-04"
    selection_root.mkdir(parents=True)
    (selection_root / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-04-04",
                "selection_targets": {
                    "300123": {
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "short_trade": {
                            "decision": "selected",
                            "score_target": 0.62,
                            "blockers": ["late_extension"],
                            "top_reasons": ["score_short=0.62"],
                            "metrics_payload": {
                                "trend_acceleration": 0.45,
                                "close_strength": 0.57,
                                "overhead_supply_penalty": 0.18,
                                "extension_without_room_penalty": 0.24,
                            },
                            "historical_prior": {"execution_quality_label": "balanced_confirmation", "evaluable_count": 4, "next_close_positive_rate": 0.31},
                        },
                    },
                    "300456": {
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "short_trade": {
                            "decision": "selected",
                            "score_target": 0.61,
                            "blockers": ["late_extension"],
                            "top_reasons": ["score_short=0.61"],
                            "metrics_payload": {
                                "trend_acceleration": 0.44,
                                "close_strength": 0.56,
                                "overhead_supply_penalty": 0.05,
                                "extension_without_room_penalty": 0.08,
                            },
                            "historical_prior": {"execution_quality_label": "balanced_confirmation", "evaluable_count": 5, "next_close_positive_rate": 0.29},
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
        outcomes = {
            ("300123", "2026-04-04"): {"next_close_return": -0.02, "t_plus_2_close_return": -0.03, "cycle_status": "closed"},
            ("300456", "2026-04-04"): {"next_close_return": -0.02, "t_plus_2_close_return": -0.03, "cycle_status": "closed"},
        }
        return outcomes[(ticker, trade_date)]

    monkeypatch.setattr(
        "scripts.analyze_btst_upstream_shadow_fnfp_dossier.extract_btst_price_outcome",
        _fake_extract_btst_price_outcome,
    )

    analysis = analyze_btst_upstream_shadow_fnfp_dossier(tmp_path)

    assert [row["ticker"] for row in analysis["false_positive_rows"]] == ["300123", "300456"]
    assert analysis["false_positive_rows"][0]["overhead_supply_penalty"] == 0.18
    assert analysis["false_positive_rows"][0]["extension_without_room_penalty"] == 0.24


def test_analyze_btst_upstream_shadow_fnfp_dossier_keeps_missing_outcome_balanced_confirmation_out_of_false_positives(monkeypatch, tmp_path):
    report_dir = tmp_path / "report"
    selection_root = report_dir / "selection_artifacts" / "2026-04-05"
    selection_root.mkdir(parents=True)
    (selection_root / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-04-05",
                "selection_targets": {
                    "301188": {
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "short_trade": {
                            "decision": "selected",
                            "score_target": 0.63,
                            "blockers": ["late_extension"],
                            "top_reasons": ["score_short=0.63"],
                            "metrics_payload": {
                                "trend_acceleration": 0.48,
                                "close_strength": 0.58,
                                "overhead_supply_penalty": 0.17,
                                "extension_without_room_penalty": 0.19,
                            },
                            "historical_prior": {"execution_quality_label": "balanced_confirmation", "evaluable_count": 4, "next_close_positive_rate": 0.31},
                        },
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "scripts.analyze_btst_upstream_shadow_fnfp_dossier.extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {"data_status": "missing_price_frame", "cycle_status": "missing_next_day"},
    )

    analysis = analyze_btst_upstream_shadow_fnfp_dossier(tmp_path)

    assert analysis["cohort_count"] == 1
    assert analysis["quality_label_split"] == {"balanced_confirmation": 1}
    assert analysis["false_positive_count"] == 0
    assert analysis["false_positive_rows"] == []
    assert analysis["recommendation"] == "Collect more upstream-shadow outcome history before ranking FN/FP rows."
