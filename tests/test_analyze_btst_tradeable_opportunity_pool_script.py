from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import scripts.analyze_btst_tradeable_opportunity_pool as tradeable_pool


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _build_price_outcome(*, next_open_return: float, next_high_return: float, next_close_return: float, t_plus_2_close_return: float | None) -> dict[str, object]:
    trade_close = 10.0
    next_open = round(trade_close * (1.0 + next_open_return), 4)
    next_high = round(trade_close * (1.0 + next_high_return), 4)
    next_close = round(trade_close * (1.0 + next_close_return), 4)
    payload: dict[str, object] = {
        "data_status": "ok" if t_plus_2_close_return is not None else "missing_t_plus_2_bar",
        "cycle_status": "closed_cycle" if t_plus_2_close_return is not None else "t1_only",
        "trade_close": trade_close,
        "next_trade_date": "2026-03-04",
        "next_open": next_open,
        "next_high": next_high,
        "next_close": next_close,
        "next_open_return": round(next_open_return, 4),
        "next_high_return": round(next_high_return, 4),
        "next_close_return": round(next_close_return, 4),
        "next_open_to_close_return": round((next_close / next_open) - 1.0, 4),
        "t_plus_2_trade_date": "2026-03-05" if t_plus_2_close_return is not None else None,
        "t_plus_2_close": round(trade_close * (1.0 + t_plus_2_close_return), 4) if t_plus_2_close_return is not None else None,
        "t_plus_2_close_return": round(t_plus_2_close_return, 4) if t_plus_2_close_return is not None else None,
    }
    return payload


def _build_daily_price_batches(stock_basic: pd.DataFrame, price_outcomes: dict[str, dict[str, object]]) -> dict[str, pd.DataFrame]:
    trade_rows: list[dict[str, object]] = []
    next_rows: list[dict[str, object]] = []
    t_plus_2_rows: list[dict[str, object]] = []
    for _, stock_row in stock_basic.iterrows():
        ticker = str(stock_row["symbol"])
        ts_code = str(stock_row["ts_code"])
        price_outcome = price_outcomes[ticker]
        trade_close = float(price_outcome["trade_close"])
        next_open = float(price_outcome["next_open"])
        next_high = float(price_outcome["next_high"])
        next_close = float(price_outcome["next_close"])
        trade_rows.append(
            {
                "ts_code": ts_code,
                "trade_date": "20260303",
                "open": trade_close,
                "high": trade_close,
                "low": trade_close,
                "close": trade_close,
                "pre_close": trade_close,
                "vol": 1000,
                "amount": 10000,
                "pct_chg": 0.0,
            }
        )
        next_rows.append(
            {
                "ts_code": ts_code,
                "trade_date": "20260304",
                "open": next_open,
                "high": next_high,
                "low": min(next_open, next_close),
                "close": next_close,
                "pre_close": trade_close,
                "vol": 1000,
                "amount": 10000,
                "pct_chg": round(((next_close / trade_close) - 1.0) * 100, 4),
            }
        )
        if price_outcome.get("t_plus_2_close") is not None:
            t_plus_2_close = float(price_outcome["t_plus_2_close"])
            t_plus_2_rows.append(
                {
                    "ts_code": ts_code,
                    "trade_date": "20260305",
                    "open": t_plus_2_close,
                    "high": t_plus_2_close,
                    "low": t_plus_2_close,
                    "close": t_plus_2_close,
                    "pre_close": next_close,
                    "vol": 1000,
                    "amount": 10000,
                    "pct_chg": round(((t_plus_2_close / next_close) - 1.0) * 100, 4),
                }
            )
    return {
        "20260303": pd.DataFrame(trade_rows),
        "20260304": pd.DataFrame(next_rows),
        "20260305": pd.DataFrame(t_plus_2_rows),
    }


def _prepare_report_dir(reports_root: Path) -> Path:
    report_dir = reports_root / "paper_trading_20260303_20260303_live_m2_7_short_trade_only_20260303"
    day_dir = report_dir / "selection_artifacts" / "2026-03-03"
    day_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        report_dir / "session_summary.json",
        {
            "plan_generation": {
                "selection_target": "short_trade_only",
                "mode": "live_pipeline",
            },
            "selection_target": "short_trade_only",
        },
    )
    _write_json(
        day_dir / "selection_snapshot.json",
        {
            "trade_date": "20260303",
            "selection_targets": {
                "000001": {
                    "candidate_source": "short_trade_boundary",
                    "candidate_reason_codes": ["short_trade_prequalified"],
                    "short_trade": {
                        "decision": "near_miss",
                        "score_target": 0.47,
                        "preferred_entry_mode": "next_day_breakout_confirmation",
                        "gate_status": {"data": "pass", "structural": "pass", "score": "near_miss"},
                        "blockers": [],
                    },
                },
                "000003": {
                    "candidate_source": "short_trade_boundary",
                    "short_trade": {
                        "decision": "rejected",
                        "score_target": 0.22,
                        "preferred_entry_mode": "next_day_breakout_confirmation",
                        "gate_status": {"data": "pass", "structural": "pass", "score": "fail"},
                        "blockers": [],
                    },
                },
                "000004": {
                    "candidate_source": "short_trade_boundary",
                    "short_trade": {
                        "decision": "blocked",
                        "score_target": 0.25,
                        "preferred_entry_mode": "next_day_breakout_confirmation",
                        "gate_status": {"data": "pass", "structural": "fail", "score": "fail"},
                        "blockers": ["layer_c_bearish_conflict"],
                    },
                },
                "000008": {
                    "candidate_source": "short_trade_boundary",
                    "short_trade": {
                        "decision": "selected",
                        "score_target": 0.61,
                        "preferred_entry_mode": "next_day_breakout_confirmation",
                        "gate_status": {"data": "pass", "structural": "pass", "score": "pass"},
                        "blockers": [],
                    },
                },
                "000010": {
                    "candidate_source": "short_trade_boundary",
                    "short_trade": {
                        "decision": "selected",
                        "score_target": 0.63,
                        "preferred_entry_mode": "next_day_breakout_confirmation",
                        "gate_status": {"data": "pass", "structural": "pass", "score": "pass"},
                        "blockers": [],
                    },
                },
            },
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {
                        "tickers": [
                            {
                                "ticker": "000002",
                                "reason": "score_final_below_watchlist_threshold",
                                "reasons": ["score_final_below_watchlist_threshold"],
                            }
                        ]
                    },
                    "layer_b": {"tickers": []},
                    "short_trade_candidates": {"tickers": []},
                    "buy_orders": {
                        "tickers": [
                            {
                                "ticker": "000010",
                                "reason": "exit_reentry_cooldown",
                                "constraint_binding": "cooldown",
                            }
                        ]
                    },
                },
                "blocked_buy_tickers": {
                    "000010": {
                        "trigger_reason": "exit_reentry_cooldown",
                        "blocked_until": "2026-03-10",
                    }
                },
            },
        },
    )
    _write_json(
        day_dir / "selection_target_replay_input.json",
        {
            "trade_date": "2026-03-03",
            "buy_order_tickers": ["000010"],
            "rejected_entries": [
                {
                    "ticker": "000002",
                    "candidate_source": "watchlist_filter_diagnostics",
                    "candidate_reason_codes": ["score_final_below_watchlist_threshold"],
                }
            ],
            "supplemental_short_trade_entries": [
                {"ticker": "000003", "candidate_source": "short_trade_boundary"},
                {"ticker": "000004", "candidate_source": "short_trade_boundary"},
                {"ticker": "000008", "candidate_source": "short_trade_boundary"},
                {"ticker": "000010", "candidate_source": "short_trade_boundary"},
            ],
        },
    )
    return report_dir


def test_analyze_btst_tradeable_opportunity_pool_classifies_truth_pool_and_kill_switches(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    _prepare_report_dir(reports_root)

    stock_basic = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "Alpha", "industry": "AI", "market": "SZ", "list_date": "20200101"},
            {"ts_code": "000002.SZ", "symbol": "000002", "name": "Beta", "industry": "Robot", "market": "SZ", "list_date": "20200101"},
            {"ts_code": "000003.SZ", "symbol": "000003", "name": "Gamma", "industry": "Robot", "market": "SZ", "list_date": "20200101"},
            {"ts_code": "000004.SZ", "symbol": "000004", "name": "Delta", "industry": "Chip", "market": "SZ", "list_date": "20200101"},
            {"ts_code": "000005.SZ", "symbol": "000005", "name": "Epsilon", "industry": "Chip", "market": "SZ", "list_date": "20200101"},
            {"ts_code": "000006.SZ", "symbol": "000006", "name": "ST Zeta", "industry": "Steel", "market": "SZ", "list_date": "20200101"},
            {"ts_code": "000007.SZ", "symbol": "000007", "name": "Eta", "industry": "Power", "market": "SZ", "list_date": "20200101"},
            {"ts_code": "000008.SZ", "symbol": "000008", "name": "Theta", "industry": "Power", "market": "SZ", "list_date": "20200101"},
            {"ts_code": "920375.BJ", "symbol": "920375", "name": "Beijing Alpha", "industry": "Robot", "market": "北交所", "list_date": "20200101"},
            {"ts_code": "000010.SZ", "symbol": "000010", "name": "Iota", "industry": "AI", "market": "SZ", "list_date": "20200101"},
        ]
    )
    daily_basic = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "turnover_rate": 5.0, "circ_mv": 100000.0},
            {"ts_code": "000002.SZ", "turnover_rate": 5.0, "circ_mv": 100000.0},
            {"ts_code": "000003.SZ", "turnover_rate": 5.0, "circ_mv": 100000.0},
            {"ts_code": "000004.SZ", "turnover_rate": 5.0, "circ_mv": 100000.0},
            {"ts_code": "000005.SZ", "turnover_rate": 5.0, "circ_mv": 100000.0},
            {"ts_code": "000006.SZ", "turnover_rate": 5.0, "circ_mv": 100000.0},
            {"ts_code": "000007.SZ", "turnover_rate": 5.0, "circ_mv": 100000.0},
            {"ts_code": "000008.SZ", "turnover_rate": 5.0, "circ_mv": 100000.0},
            {"ts_code": "920375.BJ", "turnover_rate": 5.0, "circ_mv": 100000.0},
            {"ts_code": "000010.SZ", "turnover_rate": 5.0, "circ_mv": 100000.0},
        ]
    )
    price_outcomes = {
        "000001": _build_price_outcome(next_open_return=0.01, next_high_return=0.06, next_close_return=0.04, t_plus_2_close_return=0.05),
        "000002": _build_price_outcome(next_open_return=0.01, next_high_return=0.07, next_close_return=0.02, t_plus_2_close_return=0.02),
        "000003": _build_price_outcome(next_open_return=0.01, next_high_return=0.08, next_close_return=0.01, t_plus_2_close_return=0.01),
        "000004": _build_price_outcome(next_open_return=0.01, next_high_return=0.06, next_close_return=0.01, t_plus_2_close_return=0.01),
        "000005": _build_price_outcome(next_open_return=0.01, next_high_return=0.06, next_close_return=0.01, t_plus_2_close_return=0.01),
        "000006": _build_price_outcome(next_open_return=0.01, next_high_return=0.07, next_close_return=0.04, t_plus_2_close_return=0.05),
        "000007": _build_price_outcome(next_open_return=0.01, next_high_return=0.10, next_close_return=0.09, t_plus_2_close_return=0.08),
        "000008": _build_price_outcome(next_open_return=0.10, next_high_return=0.10, next_close_return=0.10, t_plus_2_close_return=0.11),
        "920375": _build_price_outcome(next_open_return=0.01, next_high_return=0.07, next_close_return=0.02, t_plus_2_close_return=0.01),
        "000010": _build_price_outcome(next_open_return=0.01, next_high_return=0.09, next_close_return=0.05, t_plus_2_close_return=0.06),
    }
    daily_price_batches = _build_daily_price_batches(stock_basic, price_outcomes)

    monkeypatch.setattr(tradeable_pool, "get_all_stock_basic", lambda: stock_basic.copy())
    monkeypatch.setattr(tradeable_pool, "get_daily_basic_batch", lambda trade_date: daily_basic.copy())
    monkeypatch.setattr(tradeable_pool, "get_open_trade_dates", lambda start_date, end_date: ["20260303", "20260304", "20260305"])
    monkeypatch.setattr(tradeable_pool, "get_daily_price_batch", lambda trade_date: daily_price_batches.get(trade_date, pd.DataFrame()))
    monkeypatch.setattr(tradeable_pool, "get_limit_list", lambda trade_date: pd.DataFrame([{"ts_code": "000007.SZ", "limit": "U"}]))
    monkeypatch.setattr(tradeable_pool, "get_suspend_list", lambda trade_date: pd.DataFrame())
    monkeypatch.setattr(tradeable_pool, "get_cooled_tickers", lambda trade_date: set())
    monkeypatch.setattr(
        tradeable_pool,
        "extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: (_ for _ in ()).throw(AssertionError("fallback price extraction should not run when batched prices are available")),
    )

    analysis = tradeable_pool.analyze_btst_tradeable_opportunity_pool(
        reports_root,
        trade_dates={"2026-03-03"},
    )

    rows_by_ticker = {row["ticker"]: row for row in analysis["rows"]}
    assert rows_by_ticker["000001"]["first_kill_switch"] == "selected_or_near_miss"
    assert rows_by_ticker["000002"]["first_kill_switch"] == "candidate_entry_filtered"
    assert rows_by_ticker["000003"]["first_kill_switch"] == "score_fail"
    assert rows_by_ticker["000004"]["first_kill_switch"] == "structural_block"
    assert rows_by_ticker["000005"]["first_kill_switch"] == "no_candidate_entry"
    assert rows_by_ticker["000006"]["first_kill_switch"] == "universe_prefilter"
    assert rows_by_ticker["000007"]["first_kill_switch"] == "day0_limit_up_excluded"
    assert rows_by_ticker["000008"]["first_kill_switch"] == "execution_contract_only"
    assert rows_by_ticker["920375"]["first_kill_switch"] == "universe_prefilter"
    assert rows_by_ticker["920375"]["universe_prefilter_reasons"] == ["beijing_market"]
    assert rows_by_ticker["000010"]["first_kill_switch"] == "execution_contract_only"

    assert analysis["result_truth_pool_count"] == 10
    assert analysis["tradeable_opportunity_pool_count"] == 6
    assert analysis["system_recall_count"] == 5
    assert analysis["selected_or_near_miss_count"] == 2
    assert analysis["main_execution_pool_count"] == 1
    assert analysis["strict_goal_case_count"] == 5
    assert analysis["strict_goal_false_negative_count"] == 1
    assert analysis["tradeable_pool_capture_rate"] == 0.8333
    assert analysis["tradeable_pool_selected_or_near_miss_rate"] == 0.3333
    assert analysis["tradeable_pool_main_execution_rate"] == 0.1667
    assert analysis["first_kill_switch_counts"]["execution_contract_only"] == 2
    assert analysis["tradeable_pool_first_kill_switch_counts"] == {
        "selected_or_near_miss": 1,
        "candidate_entry_filtered": 1,
        "score_fail": 1,
        "structural_block": 1,
        "no_candidate_entry": 1,
        "execution_contract_only": 1,
    }
    assert analysis["candidate_source_false_negative_counts"] == {
        "watchlist_filter_diagnostics": 1,
        "short_trade_boundary": 3,
        "unseen": 1,
    }
    assert analysis["no_candidate_entry_summary"] == {
        "count": 1,
        "share_of_tradeable_pool": 0.1667,
        "strict_goal_case_count": 0,
        "strict_goal_case_share": 0.0,
        "industry_counts": {"Chip": 1},
        "trade_date_counts": {"2026-03-03": 1},
        "estimated_amount_bucket_counts": {"5000w_to_10000w": 1},
        "truth_pattern_counts": {"intraday_only": 1},
        "top_ticker_rows": [
            {
                "ticker": "000005",
                "occurrence_count": 1,
                "strict_goal_case_count": 0,
                "industry": "Chip",
                "latest_trade_date": "2026-03-03",
                "trade_dates": ["2026-03-03"],
                "mean_next_high_return": 0.06,
                "mean_next_close_return": 0.01,
                "mean_t_plus_2_close_return": 0.01,
                "lead_truth_pattern": "intraday_only",
            }
        ],
        "top_priority_rows": [rows_by_ticker["000005"]],
        "recommendation": "no_candidate_entry 机会主要集中在 ['Chip']，优先围绕 ['000005'] 回查 candidate entry semantics / watchlist 召回，而不是继续放松 score。",
    }
    assert analysis["trade_date_contexts"]["2026-03-03"] == {
        "report_dir": "paper_trading_20260303_20260303_live_m2_7_short_trade_only_20260303",
        "selection_target": "short_trade_only",
        "mode": "live_pipeline",
    }
    assert analysis["top_strict_goal_false_negative_rows"][0]["ticker"] == "000010"

    result = tradeable_pool.generate_btst_tradeable_opportunity_pool_artifacts(
        reports_root,
        trade_dates={"2026-03-03"},
    )
    assert Path(result["json_path"]).exists()
    assert Path(result["markdown_path"]).exists()
    assert Path(result["csv_path"]).exists()
    assert Path(result["waterfall_json_path"]).exists()
    assert Path(result["waterfall_markdown_path"]).exists()
    waterfall = json.loads(Path(result["waterfall_json_path"]).read_text(encoding="utf-8"))
    assert [row["kill_switch"] for row in waterfall["top_tradeable_kill_switches"]] == [
        "no_candidate_entry",
        "candidate_entry_filtered",
        "score_fail",
    ]
    assert "BTST Tradeable Opportunity Pool Review" in Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "## No Candidate Entry Breakdown" in Path(result["markdown_path"]).read_text(encoding="utf-8")
    assert "BTST Tradeable Opportunity Reason Waterfall" in Path(result["waterfall_markdown_path"]).read_text(encoding="utf-8")


def test_analyze_btst_tradeable_opportunity_pool_handles_missing_report_context(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    reports_root.mkdir(parents=True, exist_ok=True)

    stock_basic = pd.DataFrame(
        [{"ts_code": "000001.SZ", "symbol": "000001", "name": "Alpha", "industry": "AI", "market": "SZ", "list_date": "20200101"}]
    )
    daily_basic = pd.DataFrame([{"ts_code": "000001.SZ", "turnover_rate": 5.0, "circ_mv": 100000.0}])

    monkeypatch.setattr(tradeable_pool, "get_all_stock_basic", lambda: stock_basic.copy())
    monkeypatch.setattr(tradeable_pool, "get_open_trade_dates", lambda start_date, end_date: [])
    monkeypatch.setattr(tradeable_pool, "get_daily_basic_batch", lambda trade_date: daily_basic.copy())
    monkeypatch.setattr(tradeable_pool, "get_limit_list", lambda trade_date: pd.DataFrame())
    monkeypatch.setattr(tradeable_pool, "get_suspend_list", lambda trade_date: pd.DataFrame())
    monkeypatch.setattr(tradeable_pool, "get_cooled_tickers", lambda trade_date: set())
    monkeypatch.setattr(
        tradeable_pool,
        "extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: _build_price_outcome(next_open_return=0.01, next_high_return=0.06, next_close_return=0.04, t_plus_2_close_return=0.05),
    )

    analysis = tradeable_pool.analyze_btst_tradeable_opportunity_pool(
        reports_root,
        trade_dates={"2026-03-03"},
    )

    assert analysis["trade_date_contexts"]["2026-03-03"] == {
        "report_dir": None,
        "selection_target": None,
        "mode": None,
    }
    assert analysis["rows"][0]["first_kill_switch"] == "no_candidate_entry"
    assert analysis["system_recall_count"] == 0
    assert analysis["tradeable_pool_capture_rate"] == 0.0