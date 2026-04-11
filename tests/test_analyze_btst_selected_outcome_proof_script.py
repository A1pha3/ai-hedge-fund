from __future__ import annotations

import json

import pandas as pd

from scripts.analyze_btst_selected_outcome_proof import _build_recommendation, _extract_holding_outcome, _summarize_evidence_rows, analyze_btst_selected_outcome_proof, render_btst_selected_outcome_proof_markdown


def test_analyze_btst_selected_outcome_proof_uses_primary_selected_recent_examples(monkeypatch, tmp_path):
    report_dir = tmp_path / "report"
    trade_dir = report_dir / "selection_artifacts" / "2026-04-09"
    trade_dir.mkdir(parents=True)

    snapshot = {
        "trade_date": "2026-04-09",
        "selection_targets": {
            "002001": {
                "short_trade": {
                    "decision": "selected",
                    "score_target": 0.4493418197,
                    "effective_select_threshold": 0.45,
                    "selected_score_tolerance": 0.001,
                    "candidate_source": "catalyst_theme",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "top_reasons": ["catalyst_theme_short_trade_carryover", "historical_close_continuation"],
                    "rank_hint": 1,
                    "explainability_payload": {
                        "upstream_shadow_catalyst_relief": {
                            "applied": True,
                            "reason": "catalyst_theme_short_trade_carryover",
                        },
                        "historical_prior": {
                            "sample_count": 3,
                            "evaluable_count": 3,
                            "execution_quality_label": "close_continuation",
                            "entry_timing_bias": "confirm_then_hold",
                            "next_high_hit_threshold": 0.02,
                            "next_high_hit_rate_at_threshold": 1.0,
                            "next_close_positive_rate": 1.0,
                            "next_close_return_mean": 0.041,
                            "recent_examples": [
                                {"trade_date": "2026-03-27", "ticker": "002001", "candidate_source": "layer_c_watchlist"},
                                {"trade_date": "2026-03-27", "ticker": "002001", "candidate_source": "layer_c_watchlist", "score_target": 0.3131},
                                {"trade_date": "2026-03-28", "ticker": "002001", "candidate_source": "layer_c_watchlist"},
                            ],
                        },
                    },
                }
            }
        },
    }
    (trade_dir / "selection_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False) + "\n", encoding="utf-8")

    def _fake_extract_holding_outcome(ticker: str, trade_date: str, price_cache):
        assert ticker == "002001"
        if trade_date == "2026-03-27":
            return {
                "data_status": "ok",
                "cycle_status": "t_plus_4_closed",
                "next_high_return": 0.0537,
                "next_close_return": 0.045,
                "next_open_to_close_return": 0.0393,
                "t_plus_2_close_return": 0.061,
                "t_plus_3_close_return": 0.072,
                "t_plus_4_close_return": 0.068,
            }
        return {
            "data_status": "ok",
            "cycle_status": "t_plus_4_closed",
            "next_high_return": 0.028,
            "next_close_return": 0.012,
            "next_open_to_close_return": 0.019,
            "t_plus_2_close_return": -0.006,
            "t_plus_3_close_return": 0.014,
            "t_plus_4_close_return": 0.021,
        }

    monkeypatch.setattr("scripts.analyze_btst_selected_outcome_proof._extract_holding_outcome", _fake_extract_holding_outcome)

    analysis = analyze_btst_selected_outcome_proof(report_dir)
    markdown = render_btst_selected_outcome_proof_markdown(analysis)

    assert analysis["ticker"] == "002001"
    assert analysis["selected_within_tolerance"] is True
    assert analysis["raw_recent_example_count"] == 3
    assert analysis["deduplicated_recent_example_count"] == 2
    assert analysis["summary"]["evidence_case_count"] == 2
    assert analysis["summary"]["next_close_positive_rate"] == 1.0
    assert analysis["summary"]["t_plus_2_close_positive_rate"] == 0.5
    assert analysis["summary"]["t_plus_3_close_positive_rate"] == 1.0
    assert analysis["relief_reason"] == "catalyst_theme_short_trade_carryover"
    assert "confirm_then_hold" in markdown
    assert "002001" in markdown


def test_analyze_btst_selected_outcome_proof_flags_explicit_non_selected_ticker(monkeypatch, tmp_path):
    report_dir = tmp_path / "report"
    trade_dir = report_dir / "selection_artifacts" / "2026-04-09"
    trade_dir.mkdir(parents=True)

    snapshot = {
        "trade_date": "2026-04-09",
        "selection_targets": {
            "002001": {
                "short_trade": {
                    "decision": "near_miss",
                    "score_target": 0.4493418197,
                    "effective_select_threshold": 0.45,
                    "selected_score_tolerance": 0.001,
                    "candidate_source": "catalyst_theme",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "top_reasons": ["catalyst_theme_short_trade_carryover", "historical_close_continuation"],
                    "explainability_payload": {
                        "upstream_shadow_catalyst_relief": {
                            "applied": True,
                            "reason": "catalyst_theme_short_trade_carryover",
                        },
                        "historical_prior": {
                            "sample_count": 2,
                            "evaluable_count": 2,
                            "execution_quality_label": "close_continuation",
                            "entry_timing_bias": "confirm_then_hold",
                            "next_high_hit_threshold": 0.02,
                            "recent_examples": [
                                {"trade_date": "2026-03-27", "ticker": "002001", "candidate_source": "layer_c_watchlist"},
                            ],
                        },
                    },
                }
            }
        },
    }
    (trade_dir / "selection_snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False) + "\n", encoding="utf-8")

    monkeypatch.setattr(
        "scripts.analyze_btst_selected_outcome_proof._extract_holding_outcome",
        lambda ticker, trade_date, price_cache: {
            "data_status": "ok",
            "cycle_status": "t_plus_2_closed",
            "next_high_return": 0.0537,
            "next_close_return": 0.045,
            "next_open_to_close_return": 0.0393,
            "t_plus_2_close_return": 0.0029,
        },
    )

    analysis = analyze_btst_selected_outcome_proof(report_dir, ticker="002001")

    assert analysis["decision"] == "near_miss"
    assert analysis["is_formal_selected"] is False
    assert analysis["current_contract_status"] == "non_selected_explicit_ticker"
    assert "不属于当前 formal selected" in analysis["recommendation"]


def test_analyze_btst_selected_outcome_proof_uses_latest_selected_snapshot_from_reports_root(monkeypatch, tmp_path):
    older_report_dir = tmp_path / "paper_trading_2026-04-08_demo"
    older_trade_dir = older_report_dir / "selection_artifacts" / "2026-04-08"
    older_trade_dir.mkdir(parents=True)
    older_snapshot = {
        "trade_date": "2026-04-08",
        "selection_targets": {
            "002001": {
                "short_trade": {
                    "decision": "selected",
                    "score_target": 0.451,
                    "effective_select_threshold": 0.45,
                    "candidate_source": "catalyst_theme",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "rank_hint": 1,
                    "explainability_payload": {"historical_prior": {"recent_examples": []}},
                }
            }
        },
    }
    (older_trade_dir / "selection_snapshot.json").write_text(json.dumps(older_snapshot, ensure_ascii=False) + "\n", encoding="utf-8")

    newer_report_dir = tmp_path / "paper_trading_2026-04-09_demo"
    newer_trade_dir = newer_report_dir / "selection_artifacts" / "2026-04-09"
    newer_trade_dir.mkdir(parents=True)
    newer_snapshot = {
        "trade_date": "2026-04-09",
        "selection_targets": {
            "300757": {
                "short_trade": {
                    "decision": "selected",
                    "score_target": 0.462,
                    "effective_select_threshold": 0.45,
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "preferred_entry_mode": "confirm_then_hold_breakout",
                    "rank_hint": 1,
                    "explainability_payload": {"historical_prior": {"recent_examples": []}},
                }
            }
        },
    }
    (newer_trade_dir / "selection_snapshot.json").write_text(json.dumps(newer_snapshot, ensure_ascii=False) + "\n", encoding="utf-8")

    monkeypatch.setattr(
        "scripts.analyze_btst_selected_outcome_proof._extract_holding_outcome",
        lambda ticker, trade_date, price_cache: {"data_status": "missing_next_trade_day_bar", "trade_close": 10.0, "cycle_status": "missing_next_day"},
    )

    analysis = analyze_btst_selected_outcome_proof(tmp_path)

    assert analysis["ticker"] == "300757"
    assert analysis["trade_date"] == "2026-04-09"
    assert analysis["report_dir"] == str(newer_report_dir)


def test_analyze_btst_selected_outcome_proof_threads_final_payload(monkeypatch):
    monkeypatch.setattr(
        "scripts.analyze_btst_selected_outcome_proof._resolve_snapshot",
        lambda input_path: (
            {"trade_date": "2026-04-09"},
            "/tmp/selection_snapshot.json",
            "/tmp/report",
        ),
    )
    monkeypatch.setattr(
        "scripts.analyze_btst_selected_outcome_proof._resolve_selected_entry",
        lambda snapshot, ticker=None: (
            "002001",
            {
                "decision": "selected",
                "candidate_source": "catalyst_theme",
                "preferred_entry_mode": "confirm_then_hold_breakout",
                "score_target": 0.449,
                "effective_select_threshold": 0.45,
            },
        ),
    )
    monkeypatch.setattr(
        "scripts.analyze_btst_selected_outcome_proof._resolve_historical_prior",
        lambda short_trade: {
            "recent_examples": [{"trade_date": "2026-03-27", "ticker": "002001", "candidate_source": "layer_c_watchlist"}],
            "next_high_hit_threshold": 0.02,
        },
    )
    monkeypatch.setattr(
        "scripts.analyze_btst_selected_outcome_proof._resolve_relief_context",
        lambda short_trade: {"relief_reason": "catalyst_theme_short_trade_carryover", "relief_applied": True},
    )
    monkeypatch.setattr("scripts.analyze_btst_selected_outcome_proof._resolve_selected_score_tolerance", lambda short_trade: 0.001)
    monkeypatch.setattr("scripts.analyze_btst_selected_outcome_proof._deduplicate_recent_examples", lambda recent_examples: list(recent_examples))
    monkeypatch.setattr(
        "scripts.analyze_btst_selected_outcome_proof._extract_holding_outcome",
        lambda ticker, trade_date, price_cache: {"cycle_status": "t_plus_2_closed", "next_close_return": 0.03},
    )
    monkeypatch.setattr(
        "scripts.analyze_btst_selected_outcome_proof._summarize_evidence_rows",
        lambda evidence_rows, next_high_hit_threshold: {"evidence_case_count": 1, "next_close_positive_rate": 1.0, "t_plus_2_close_positive_rate": 1.0},
    )
    monkeypatch.setattr("scripts.analyze_btst_selected_outcome_proof._build_recommendation", lambda summary: "keep selected bias")
    monkeypatch.setattr(
        "scripts.analyze_btst_selected_outcome_proof._apply_current_contract_guardrail",
        lambda recommendation, decision, ticker_explicitly_requested: (recommendation, "formal_selected", True),
    )

    analysis = analyze_btst_selected_outcome_proof("/tmp/report")

    assert analysis["ticker"] == "002001"
    assert analysis["trade_date"] == "2026-04-09"
    assert analysis["summary"] == {"evidence_case_count": 1, "next_close_positive_rate": 1.0, "t_plus_2_close_positive_rate": 1.0}
    assert analysis["evidence_rows"] == [
        {
            "trade_date": "2026-03-27",
            "ticker": "002001",
            "candidate_source": "layer_c_watchlist",
            "cycle_status": "t_plus_2_closed",
            "next_close_return": 0.03,
        }
    ]
    assert analysis["recommendation"] == "keep selected bias"


def test_extract_holding_outcome_returns_missing_next_day_when_future_bar_absent(monkeypatch):
    frame = pd.DataFrame(
        [{"open": 10.0, "high": 10.4, "close": 10.2}],
        index=pd.to_datetime(["2026-03-27"]),
    )
    monkeypatch.setattr("scripts.analyze_btst_selected_outcome_proof.fetch_price_frame", lambda ticker, trade_date, price_cache: frame)

    outcome = _extract_holding_outcome("002001", "2026-03-27", {})

    assert outcome == {
        "data_status": "missing_next_trade_day_bar",
        "trade_close": 10.2,
        "trade_anchor_date": "2026-03-27",
        "trade_date_was_non_trading": False,
        "cycle_status": "missing_next_day",
    }


def test_extract_holding_outcome_builds_full_t_plus_four_window(monkeypatch):
    frame = pd.DataFrame(
        [
            {"open": 10.0, "high": 10.4, "close": 10.0},
            {"open": 10.1, "high": 10.6, "close": 10.3},
            {"open": 10.2, "high": 10.5, "close": 10.4},
            {"open": 10.3, "high": 10.7, "close": 10.2},
            {"open": 10.4, "high": 10.8, "close": 10.5},
        ],
        index=pd.to_datetime(["2026-03-27", "2026-03-28", "2026-03-31", "2026-04-01", "2026-04-02"]),
    )
    monkeypatch.setattr("scripts.analyze_btst_selected_outcome_proof.fetch_price_frame", lambda ticker, trade_date, price_cache: frame)

    outcome = _extract_holding_outcome("002001", "2026-03-27", {})

    assert outcome["data_status"] == "ok"
    assert outcome["cycle_status"] == "t_plus_4_closed"
    assert outcome["next_trade_date"] == "2026-03-28"
    assert outcome["next_open_return"] == 0.01
    assert outcome["next_high_return"] == 0.06
    assert outcome["next_close_return"] == 0.03
    assert outcome["t_plus_2_trade_date"] == "2026-03-31"
    assert outcome["t_plus_2_close_return"] == 0.04
    assert outcome["t_plus_3_close_return"] == 0.02
    assert outcome["t_plus_4_close_return"] == 0.05


def test_extract_holding_outcome_falls_back_to_prior_trade_day_when_trade_date_is_non_trading(monkeypatch):
    frame = pd.DataFrame(
        [
            {"open": 10.0, "high": 10.4, "close": 10.0},
            {"open": 10.1, "high": 10.6, "close": 10.3},
            {"open": 10.2, "high": 10.5, "close": 10.4},
        ],
        index=pd.to_datetime(["2026-04-03", "2026-04-07", "2026-04-08"]),
    )
    monkeypatch.setattr("scripts.analyze_btst_selected_outcome_proof.fetch_price_frame", lambda ticker, trade_date, price_cache: frame)

    outcome = _extract_holding_outcome("300720", "2026-04-06", {})

    assert outcome["data_status"] == "ok"
    assert outcome["trade_anchor_date"] == "2026-04-03"
    assert outcome["trade_date_was_non_trading"] is True
    assert outcome["cycle_status"] == "t_plus_2_closed"
    assert outcome["next_trade_date"] == "2026-04-07"
    assert outcome["next_close_return"] == 0.03
    assert outcome["t_plus_2_close_return"] == 0.04


def test_summarize_evidence_rows_tracks_horizon_counts_and_positive_rates():
    summary = _summarize_evidence_rows(
        [
            {
                "next_high_return": 0.05,
                "next_close_return": 0.03,
                "next_open_to_close_return": 0.02,
                "t_plus_2_close_return": 0.01,
                "t_plus_3_close_return": -0.02,
            },
            {
                "next_high_return": 0.01,
                "next_close_return": -0.01,
                "next_open_to_close_return": -0.02,
                "t_plus_2_close_return": 0.04,
                "t_plus_4_close_return": 0.03,
            },
        ],
        next_high_hit_threshold=0.02,
    )

    assert summary["evidence_case_count"] == 2
    assert summary["next_day_available_count"] == 2
    assert summary["t_plus_2_available_count"] == 2
    assert summary["t_plus_3_available_count"] == 1
    assert summary["t_plus_4_available_count"] == 1
    assert summary["next_high_hit_rate_at_threshold"] == 0.5
    assert summary["next_close_positive_rate"] == 0.5
    assert summary["t_plus_2_close_positive_rate"] == 1.0
    assert summary["t_plus_3_close_positive_rate"] == 0.0
    assert summary["t_plus_4_close_positive_rate"] == 1.0


def test_summarize_evidence_rows_returns_none_rates_without_available_rows():
    summary = _summarize_evidence_rows([], next_high_hit_threshold=0.02)

    assert summary["evidence_case_count"] == 0
    assert summary["next_high_hit_rate_at_threshold"] is None
    assert summary["next_close_positive_rate"] is None
    assert summary["t_plus_2_close_positive_rate"] is None


def test_build_recommendation_returns_t_plus_two_bias_when_t_plus_three_is_weak():
    recommendation = _build_recommendation(
        {
            "evidence_case_count": 3,
            "next_close_positive_rate": 1.0,
            "t_plus_2_close_positive_rate": 0.67,
            "t_plus_3_close_positive_rate": 0.33,
        }
    )

    assert "T+2" in recommendation
    assert "T+3" in recommendation


def test_build_recommendation_requires_cohort_expansion_when_evidence_is_weak():
    recommendation = _build_recommendation(
        {
            "evidence_case_count": 2,
            "next_close_positive_rate": 0.5,
            "t_plus_2_close_positive_rate": 0.0,
            "t_plus_3_close_positive_rate": None,
        }
    )

    assert "扩充 carryover cohort" in recommendation
