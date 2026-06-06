from __future__ import annotations

import json
from pathlib import Path

import scripts.analyze_btst_tplus1_tplus2_objective_monitor as objective_monitor


def _write_snapshot(report_dir: Path, trade_date: str, rows: dict[str, dict]) -> None:
    snapshot_dir = report_dir / "selection_artifacts" / trade_date
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "trade_date": trade_date.replace("-", ""),
        "selection_targets": rows,
    }
    (snapshot_dir / "selection_snapshot.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_analyze_btst_tplus1_tplus2_objective_monitor_ranks_tradeable_and_false_negative_cases(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    window_a = reports_root / "paper_trading_window_20260323_20260326_live_m2_7_1"
    window_b = reports_root / "paper_trading_window_20260327_20260328_live_m2_7_2"

    _write_snapshot(
        window_a,
        "2026-03-24",
        {
            "001309": {
                "candidate_source": "short_trade_boundary",
                "short_trade": {"decision": "selected", "score_target": 0.58},
            },
            "300383": {
                "candidate_source": "short_trade_boundary",
                "short_trade": {"decision": "rejected", "score_target": 0.42},
            },
        },
    )
    _write_snapshot(
        window_b,
        "2026-03-27",
        {
            "001309": {
                "candidate_source": "short_trade_boundary",
                "short_trade": {"decision": "near_miss", "score_target": 0.56},
            },
            "600821": {
                "candidate_source": "short_trade_boundary",
                "short_trade": {"decision": "blocked", "score_target": 0.39},
            },
        },
    )

    outcomes = {
        ("001309", "2026-03-24"): {"data_status": "ok", "cycle_status": "closed_cycle", "t_plus_2_close_return": 0.071},
        ("300383", "2026-03-24"): {"data_status": "ok", "cycle_status": "closed_cycle", "t_plus_2_close_return": 0.063},
        ("001309", "2026-03-27"): {"data_status": "ok", "cycle_status": "closed_cycle", "t_plus_2_close_return": 0.055},
        ("600821", "2026-03-27"): {"data_status": "ok", "cycle_status": "closed_cycle", "t_plus_2_close_return": -0.013},
    }

    def _fake_outcome(ticker: str, trade_date: str, price_cache: dict) -> dict:
        payload = dict(outcomes[(ticker, trade_date)])
        payload.setdefault("trade_close", 10.0)
        payload.setdefault("next_trade_date", "2026-03-25")
        payload.setdefault("next_open", 10.1)
        payload.setdefault("next_high", 10.8)
        payload.setdefault("next_close", 10.4)
        payload.setdefault("next_open_return", 0.01)
        payload.setdefault("next_high_return", 0.08)
        payload.setdefault("next_close_return", 0.04)
        payload.setdefault("next_open_to_close_return", 0.03)
        payload.setdefault("t_plus_2_trade_date", "2026-03-26")
        payload.setdefault("t_plus_2_close", 10.5)
        return payload

    monkeypatch.setattr(objective_monitor, "_extract_btst_price_outcome", _fake_outcome)

    analysis = objective_monitor.analyze_btst_tplus1_tplus2_objective_monitor(reports_root, leaderboard_min_closed_cycle_count=1)

    assert analysis["report_dir_count"] == 2
    assert analysis["tradeable_surface"]["closed_cycle_count"] == 2
    assert analysis["tradeable_surface"]["t_plus_2_positive_rate"] == 1.0
    assert analysis["tradeable_surface"]["t_plus_2_return_hit_rate_at_target"] == 1.0
    assert analysis["tradeable_surface"]["verdict"] == "meets_strict_btst_objective"
    assert analysis["decision_leaderboard"][0]["group_label"] in {"selected", "near_miss"}
    assert analysis["ticker_leaderboard"][0]["group_label"] == "001309"
    assert analysis["strict_goal_rows"][0]["ticker"] in {"001309", "300383"}
    assert analysis["false_negative_strict_goal_rows"][0]["ticker"] == "300383"

    markdown = objective_monitor.render_btst_tplus1_tplus2_objective_monitor_markdown(analysis)
    assert "# BTST T+1 Buy / T+2 Sell Objective Monitor" in markdown
    assert "001309" in markdown
    assert "300383" in markdown
    assert "False Negative Strict Goal Cases" in markdown