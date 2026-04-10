from __future__ import annotations

import json

import pandas as pd

from scripts.analyze_btst_selected_outcome_proof import _extract_holding_outcome, analyze_btst_selected_outcome_proof, render_btst_selected_outcome_proof_markdown


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
