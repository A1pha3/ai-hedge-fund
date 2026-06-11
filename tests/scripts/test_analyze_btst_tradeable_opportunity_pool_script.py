from __future__ import annotations

import json
from collections import Counter
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


def test_analyze_btst_tradeable_opportunity_pool_surfaces_one_word_board_cases(tmp_path: Path, monkeypatch) -> None:
    """Test that one-word-board (一字板) cases are detected and surfaced as a dedicated summary section."""
    reports_root = tmp_path / "data" / "reports"
    _prepare_report_dir(reports_root)

    stock_basic = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "Alpha", "industry": "AI", "market": "SZ", "list_date": "20200101"},
            {"ts_code": "000002.SZ", "symbol": "000002", "name": "Beta", "industry": "Robot", "market": "SZ", "list_date": "20200101"},
            {"ts_code": "000008.SZ", "symbol": "000008", "name": "Theta", "industry": "Power", "market": "SZ", "list_date": "20200101"},
        ]
    )
    daily_basic = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "turnover_rate": 5.0, "circ_mv": 100000.0},
            {"ts_code": "000002.SZ", "turnover_rate": 5.0, "circ_mv": 100000.0},
            {"ts_code": "000008.SZ", "turnover_rate": 5.0, "circ_mv": 100000.0},
        ]
    )

    # 000001: one-word-board case (open=high=close at limit-up)
    # 000002: not a one-word-board (open != close)
    # 000008: selected case (normal)
    price_outcomes = {
        "000001": _build_price_outcome(next_open_return=0.10, next_high_return=0.10, next_close_return=0.10, t_plus_2_close_return=0.08),
        "000002": _build_price_outcome(next_open_return=0.10, next_high_return=0.12, next_close_return=0.08, t_plus_2_close_return=0.05),
        "000008": _build_price_outcome(next_open_return=0.01, next_high_return=0.06, next_close_return=0.04, t_plus_2_close_return=0.05),
    }

    daily_batches = _build_daily_price_batches(stock_basic, price_outcomes)

    monkeypatch.setattr(tradeable_pool, "get_all_stock_basic", lambda: stock_basic.copy())
    monkeypatch.setattr(tradeable_pool, "get_open_trade_dates", lambda start_date, end_date: ["20260303", "20260304", "20260305"])
    monkeypatch.setattr(tradeable_pool, "get_daily_basic_batch", lambda trade_date: daily_basic.copy())
    monkeypatch.setattr(tradeable_pool, "get_daily_price_batch", lambda trade_date: daily_batches.get(trade_date, pd.DataFrame()))
    monkeypatch.setattr(tradeable_pool, "get_limit_list", lambda trade_date: pd.DataFrame())
    monkeypatch.setattr(tradeable_pool, "get_suspend_list", lambda trade_date: pd.DataFrame())
    monkeypatch.setattr(tradeable_pool, "get_cooled_tickers", lambda trade_date: set())
    monkeypatch.setattr(
        tradeable_pool,
        "extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: price_outcomes[ticker],
    )

    analysis = tradeable_pool.analyze_btst_tradeable_opportunity_pool(
        reports_root,
        trade_dates={"2026-03-03"},
    )

    # Check that one-word-board tradeability note was detected
    one_word_board_rows = [row for row in analysis["rows"] if "t_plus_1_one_word_board" in (row.get("tradeability_notes") or [])]
    assert len(one_word_board_rows) == 1, f"Expected 1 one-word-board row, got {len(one_word_board_rows)}"
    assert one_word_board_rows[0]["ticker"] == "000001"

    # Check that the new one_word_board_summary is present and correct
    assert "one_word_board_summary" in analysis, "one_word_board_summary missing from analysis"
    one_word_board_summary = analysis["one_word_board_summary"]

    assert one_word_board_summary["count"] == 1, f"Expected count=1, got {one_word_board_summary['count']}"
    assert one_word_board_summary["share_of_tradeable_pool"] > 0.0
    assert "industry_counts" in one_word_board_summary
    assert one_word_board_summary["industry_counts"]["AI"] == 1
    assert "trade_date_counts" in one_word_board_summary
    assert one_word_board_summary["trade_date_counts"]["2026-03-03"] == 1
    assert "top_ticker_rows" in one_word_board_summary
    assert len(one_word_board_summary["top_ticker_rows"]) == 1
    assert one_word_board_summary["top_ticker_rows"][0]["ticker"] == "000001"
    assert "recommendation" in one_word_board_summary
    assert len(one_word_board_summary["recommendation"]) > 0

    # Check that strict_goal_case fields are present
    assert "strict_goal_case_count" in one_word_board_summary
    assert "strict_goal_case_share" in one_word_board_summary

    # Check markdown rendering includes the new section
    markdown = tradeable_pool.render_btst_tradeable_opportunity_pool_markdown(analysis)
    assert "## One Word Board Entry Failure Breakdown" in markdown, "Markdown should include One Word Board section"
    assert "000001" in markdown


def test_analyze_btst_tradeable_opportunity_pool_one_word_board_recommendation_avoids_empty_list_literals(monkeypatch) -> None:
    class _EmptyMostCommonCounter(Counter):
        def most_common(self, n=None):  # type: ignore[override]
            return []

    monkeypatch.setattr(tradeable_pool, "Counter", _EmptyMostCommonCounter)

    summary = tradeable_pool._build_one_word_board_summary(
        [
            {
                "tradeability_notes": ["t_plus_1_one_word_board"],
                "pool_b_tradeable": True,
                "strict_btst_goal_case": False,
                "ticker": "000001",
                "industry": "AI",
                "trade_date": "2026-03-03",
                "next_high_return": 0.1,
                "next_close_return": 0.1,
                "t_plus_2_close_return": 0.08,
            }
        ]
    )

    assert summary["recommendation"]
    assert "[]" not in summary["recommendation"]

    lines: list[str] = []
    tradeable_pool._append_tradeable_pool_one_word_board_markdown(lines, summary)
    markdown = "\n".join(lines)
    assert "## One Word Board Entry Failure Breakdown" in markdown
    assert "[]" not in markdown


def test_board_aware_extreme_open_gap_detection_main_board() -> None:
    """Test that main board stocks use ~10% threshold for extreme open gap detection."""
    # Main board stock (000xxx) with 9.6% gap should trigger (above 9.5% threshold)
    price_outcome = {
        "next_open_return": 0.096,
        "next_high_return": 0.10,
        "next_close_return": 0.10,
        "next_open": 10.96,
        "next_high": 11.0,
        "next_close": 11.0,
    }
    symbol = "000001"
    market = "SZ"
    
    notes = tradeable_pool._detect_tradeability_notes(price_outcome, symbol=symbol, market=market)
    assert "t_plus_1_extreme_open_gap" in notes


def test_board_aware_extreme_open_gap_detection_chinext_not_triggered() -> None:
    """Test that ChiNext stocks (300xxx) do NOT trigger extreme gap at 9.6% (below 20% limit)."""
    # ChiNext stock with 9.6% gap should NOT trigger (below ~19% threshold for 20% limit)
    price_outcome = {
        "next_open_return": 0.096,
        "next_high_return": 0.10,
        "next_close_return": 0.10,
        "next_open": 10.96,
        "next_high": 11.0,
        "next_close": 11.0,
    }
    symbol = "300724"
    market = "创业板"
    
    notes = tradeable_pool._detect_tradeability_notes(price_outcome, symbol=symbol, market=market)
    assert "t_plus_1_extreme_open_gap" not in notes


def test_board_aware_extreme_open_gap_detection_chinext_triggered() -> None:
    """Test that ChiNext stocks (300xxx) DO trigger extreme gap at 19.1% (near 20% limit)."""
    # ChiNext stock with 19.1% gap should trigger (approaching 20% limit)
    price_outcome = {
        "next_open_return": 0.191,
        "next_high_return": 0.195,
        "next_close_return": 0.195,
        "next_open": 11.91,
        "next_high": 11.95,
        "next_close": 11.95,
    }
    symbol = "300724"
    market = "创业板"
    
    notes = tradeable_pool._detect_tradeability_notes(price_outcome, symbol=symbol, market=market)
    assert "t_plus_1_extreme_open_gap" in notes


def test_board_aware_extreme_open_gap_detection_star_triggered() -> None:
    """Test that STAR Market stocks (688xxx) DO trigger extreme gap at 19.1% (near 20% limit)."""
    # STAR Market stock with 19.1% gap should trigger (approaching 20% limit)
    price_outcome = {
        "next_open_return": 0.191,
        "next_high_return": 0.195,
        "next_close_return": 0.195,
        "next_open": 11.91,
        "next_high": 11.95,
        "next_close": 11.95,
    }
    symbol = "688001"
    market = "科创板"
    
    notes = tradeable_pool._detect_tradeability_notes(price_outcome, symbol=symbol, market=market)
    assert "t_plus_1_extreme_open_gap" in notes


def test_board_aware_one_word_board_detection_main_board() -> None:
    """Test that main board stocks use ~10% threshold for one-word-board detection."""
    # Main board stock at 9.6% one-word-board should trigger
    price_outcome = {
        "next_open_return": 0.096,
        "next_high_return": 0.096,
        "next_close_return": 0.096,
        "next_open": 10.96,
        "next_high": 10.96,
        "next_close": 10.96,
    }
    symbol = "000001"
    market = "SZ"
    
    notes = tradeable_pool._detect_tradeability_notes(price_outcome, symbol=symbol, market=market)
    assert "t_plus_1_one_word_board" in notes


def test_board_aware_one_word_board_detection_chinext_not_triggered() -> None:
    """Test that ChiNext stocks (300xxx) do NOT trigger one-word-board at 9.6% (not at limit)."""
    # ChiNext stock at 9.6% one-word-board should NOT trigger (not at 20% limit)
    price_outcome = {
        "next_open_return": 0.096,
        "next_high_return": 0.096,
        "next_close_return": 0.096,
        "next_open": 10.96,
        "next_high": 10.96,
        "next_close": 10.96,
    }
    symbol = "300724"
    market = "创业板"
    
    notes = tradeable_pool._detect_tradeability_notes(price_outcome, symbol=symbol, market=market)
    assert "t_plus_1_one_word_board" not in notes


def test_board_aware_one_word_board_detection_chinext_triggered() -> None:
    """Test that ChiNext stocks (300xxx) DO trigger one-word-board at 19.1% (near 20% limit)."""
    # ChiNext stock at 19.1% one-word-board should trigger
    price_outcome = {
        "next_open_return": 0.191,
        "next_high_return": 0.191,
        "next_close_return": 0.191,
        "next_open": 11.91,
        "next_high": 11.91,
        "next_close": 11.91,
    }
    symbol = "300724"
    market = "创业板"
    
    notes = tradeable_pool._detect_tradeability_notes(price_outcome, symbol=symbol, market=market)
    assert "t_plus_1_one_word_board" in notes


def test_board_aware_one_word_board_detection_star_triggered() -> None:
    """Test that STAR Market stocks (688xxx) DO trigger one-word-board at 19.1% (near 20% limit)."""
    # STAR Market stock at 19.1% one-word-board should trigger
    price_outcome = {
        "next_open_return": 0.191,
        "next_high_return": 0.191,
        "next_close_return": 0.191,
        "next_open": 11.91,
        "next_high": 11.91,
        "next_close": 11.91,
    }
    symbol = "688001"
    market = "科创板"
    
    notes = tradeable_pool._detect_tradeability_notes(price_outcome, symbol=symbol, market=market)
    assert "t_plus_1_one_word_board" in notes


def test_board_aware_tradeability_integration_with_chinext_stock(tmp_path: Path, monkeypatch) -> None:
    """Test that ChiNext stocks (300xxx) use 20% threshold in full workflow."""
    reports_root = tmp_path / "data" / "reports"
    _prepare_report_dir(reports_root)

    stock_basic = pd.DataFrame(
        [
            {"ts_code": "300724.SZ", "symbol": "300724", "name": "ChiNext Alpha", "industry": "Tech", "market": "创业板", "list_date": "20200101"},
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "Main Board Beta", "industry": "Finance", "market": "SZ", "list_date": "20200101"},
        ]
    )
    daily_basic = pd.DataFrame(
        [
            {"ts_code": "300724.SZ", "turnover_rate": 5.0, "circ_mv": 100000.0},
            {"ts_code": "000001.SZ", "turnover_rate": 5.0, "circ_mv": 100000.0},
        ]
    )
    # ChiNext stock with 9.6% gap - should NOT trigger (under 20% limit)
    # Main board stock with 9.6% gap - should trigger (near 10% limit)
    price_outcomes = {
        "300724": _build_price_outcome(next_open_return=0.096, next_high_return=0.096, next_close_return=0.096, t_plus_2_close_return=0.10),
        "000001": _build_price_outcome(next_open_return=0.096, next_high_return=0.096, next_close_return=0.096, t_plus_2_close_return=0.10),
    }
    daily_price_batches = _build_daily_price_batches(stock_basic, price_outcomes)

    monkeypatch.setattr(tradeable_pool, "get_all_stock_basic", lambda: stock_basic.copy())
    monkeypatch.setattr(tradeable_pool, "get_daily_basic_batch", lambda trade_date: daily_basic.copy())
    monkeypatch.setattr(tradeable_pool, "get_open_trade_dates", lambda start_date, end_date: ["20260303", "20260304", "20260305"])
    monkeypatch.setattr(tradeable_pool, "get_daily_price_batch", lambda trade_date: daily_price_batches.get(trade_date, pd.DataFrame()))
    monkeypatch.setattr(tradeable_pool, "get_limit_list", lambda trade_date: pd.DataFrame())
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
    
    # ChiNext stock should be tradeable (no tradeability notes at 9.6%)
    assert rows_by_ticker["300724"]["pool_b_tradeable"] is True
    assert rows_by_ticker["300724"]["tradeability_notes"] == []
    
    # Main board stock should have tradeability note (one-word-board at 9.6%)
    assert rows_by_ticker["000001"]["pool_b_tradeable"] is False
    assert "t_plus_1_one_word_board" in rows_by_ticker["000001"]["tradeability_notes"]
    assert rows_by_ticker["000001"]["first_kill_switch"] == "execution_contract_only"


def test_execution_cost_summary_exists_in_analysis(tmp_path: Path, monkeypatch) -> None:
    """Test that analyze_btst_tradeable_opportunity_pool includes execution_cost_summary."""
    reports_root = tmp_path / "data" / "reports"
    _prepare_report_dir(reports_root)

    stock_basic = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "Alpha", "industry": "AI", "market": "SZ", "list_date": "20200101"},
            {"ts_code": "000011.SZ", "symbol": "000011", "name": "Beta", "industry": "Robot", "market": "SZ", "list_date": "20200101"},
        ]
    )
    daily_basic = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "turnover_rate": 10.0, "circ_mv": 100000.0},  # 10000 万元 - base liquidity
            {"ts_code": "000011.SZ", "turnover_rate": 2.0, "circ_mv": 100000.0},   # 2000 万元 - low liquidity but >= MIN threshold
        ]
    )
    price_outcomes = {
        "000001": _build_price_outcome(next_open_return=0.03, next_high_return=0.07, next_close_return=0.05, t_plus_2_close_return=0.08),
        "000011": _build_price_outcome(next_open_return=0.02, next_high_return=0.06, next_close_return=0.04, t_plus_2_close_return=0.07),
    }
    daily_price_batches = _build_daily_price_batches(stock_basic, price_outcomes)

    monkeypatch.setattr(tradeable_pool, "get_all_stock_basic", lambda: stock_basic.copy())
    monkeypatch.setattr(tradeable_pool, "get_daily_basic_batch", lambda trade_date: daily_basic.copy())
    monkeypatch.setattr(tradeable_pool, "get_open_trade_dates", lambda start_date, end_date: ["20260303", "20260304", "20260305"])
    monkeypatch.setattr(tradeable_pool, "get_daily_price_batch", lambda trade_date: daily_price_batches.get(trade_date, pd.DataFrame()))
    monkeypatch.setattr(tradeable_pool, "get_limit_list", lambda trade_date: pd.DataFrame())
    monkeypatch.setattr(tradeable_pool, "get_suspend_list", lambda trade_date: pd.DataFrame())
    monkeypatch.setattr(tradeable_pool, "get_cooled_tickers", lambda trade_date: set())
    monkeypatch.setattr(
        tradeable_pool,
        "extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: (_ for _ in ()).throw(AssertionError("fallback price extraction should not run")),
    )

    analysis = tradeable_pool.analyze_btst_tradeable_opportunity_pool(
        reports_root,
        trade_dates={"2026-03-03"},
    )

    # Check that execution_cost_summary exists
    assert "execution_cost_summary" in analysis
    cost_summary = analysis["execution_cost_summary"]
    
    # Check expected fields
    assert "tradeable_row_count" in cost_summary
    assert "base_liquidity_count" in cost_summary
    assert "low_liquidity_count" in cost_summary
    assert "unknown_liquidity_count" in cost_summary
    assert "mean_round_trip_cost_rate" in cost_summary
    assert "mean_slippage_rate" in cost_summary
    assert "positive_gross_next_high_flipped_count" in cost_summary
    assert "positive_gross_next_close_flipped_count" in cost_summary
    assert "positive_gross_t_plus_2_close_flipped_count" in cost_summary
    
    # Should have at least 1 tradeable row
    assert cost_summary["tradeable_row_count"] >= 1
    # Should have cost regime counts that sum to tradeable_row_count
    total_regimes = (
        cost_summary["base_liquidity_count"] 
        + cost_summary["low_liquidity_count"] 
        + cost_summary["unknown_liquidity_count"]
    )
    assert total_regimes == cost_summary["tradeable_row_count"]


def test_cost_regime_classification_aligns_with_backtesting_threshold(tmp_path: Path, monkeypatch) -> None:
    """Test that cost regime classification uses the same threshold as backtesting after unit conversion."""
    reports_root = tmp_path / "data" / "reports"
    _prepare_report_dir(reports_root)

    stock_basic = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "Base Liquidity", "industry": "AI", "market": "SZ", "list_date": "20200101"},
            {"ts_code": "000002.SZ", "symbol": "000002", "name": "Low Liquidity", "industry": "Robot", "market": "SZ", "list_date": "20200101"},
            {"ts_code": "000003.SZ", "symbol": "000003", "name": "Threshold Edge", "industry": "Chip", "market": "SZ", "list_date": "20200101"},
        ]
    )
    # Backtesting threshold is 50_000_000 yuan = 5000 万元
    daily_basic = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "turnover_rate": 10.0, "circ_mv": 100000.0},  # 10000 万元 > 5000 - base
            {"ts_code": "000002.SZ", "turnover_rate": 1.0, "circ_mv": 100000.0},   # 1000 万元 < 5000 - low
            {"ts_code": "000003.SZ", "turnover_rate": 5.0, "circ_mv": 100000.0},   # 5000 万元 = 5000 - edge case (should be base)
        ]
    )
    price_outcomes = {
        "000001": _build_price_outcome(next_open_return=0.03, next_high_return=0.07, next_close_return=0.05, t_plus_2_close_return=0.08),
        "000002": _build_price_outcome(next_open_return=0.03, next_high_return=0.07, next_close_return=0.05, t_plus_2_close_return=0.08),
        "000003": _build_price_outcome(next_open_return=0.03, next_high_return=0.07, next_close_return=0.05, t_plus_2_close_return=0.08),
    }
    daily_price_batches = _build_daily_price_batches(stock_basic, price_outcomes)

    monkeypatch.setattr(tradeable_pool, "get_all_stock_basic", lambda: stock_basic.copy())
    monkeypatch.setattr(tradeable_pool, "get_daily_basic_batch", lambda trade_date: daily_basic.copy())
    monkeypatch.setattr(tradeable_pool, "get_open_trade_dates", lambda start_date, end_date: ["20260303", "20260304", "20260305"])
    monkeypatch.setattr(tradeable_pool, "get_daily_price_batch", lambda trade_date: daily_price_batches.get(trade_date, pd.DataFrame()))
    monkeypatch.setattr(tradeable_pool, "get_limit_list", lambda trade_date: pd.DataFrame())
    monkeypatch.setattr(tradeable_pool, "get_suspend_list", lambda trade_date: pd.DataFrame())
    monkeypatch.setattr(tradeable_pool, "get_cooled_tickers", lambda trade_date: set())
    monkeypatch.setattr(
        tradeable_pool,
        "extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: (_ for _ in ()).throw(AssertionError("fallback should not run")),
    )

    analysis = tradeable_pool.analyze_btst_tradeable_opportunity_pool(
        reports_root,
        trade_dates={"2026-03-03"},
    )

    rows_by_ticker = {row["ticker"]: row for row in analysis["rows"]}
    
    # Check cost regime classification
    assert rows_by_ticker["000001"]["cost_regime"] == "base_liquidity"
    assert rows_by_ticker["000002"]["cost_regime"] == "low_liquidity"
    assert rows_by_ticker["000003"]["cost_regime"] == "base_liquidity"  # >= threshold is base


def test_row_level_cost_fields_populated_correctly(tmp_path: Path, monkeypatch) -> None:
    """Test that row-level cost fields are populated with correct values."""
    reports_root = tmp_path / "data" / "reports"
    _prepare_report_dir(reports_root)

    stock_basic = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "symbol": "000001", "name": "Base Liquidity", "industry": "AI", "market": "SZ", "list_date": "20200101"},
        ]
    )
    # Base liquidity: slippage = 0.0015, commission = 0.00025, stamp_duty = 0.0005
    # Round-trip cost = 2*slippage + 2*commission + stamp_duty = 2*0.0015 + 2*0.00025 + 0.0005 = 0.004
    daily_basic = pd.DataFrame(
        [
            {"ts_code": "000001.SZ", "turnover_rate": 10.0, "circ_mv": 100000.0},  # 10000 万元 - base liquidity
        ]
    )
    price_outcomes = {
        "000001": _build_price_outcome(next_open_return=0.03, next_high_return=0.10, next_close_return=0.05, t_plus_2_close_return=0.08),
    }
    daily_price_batches = _build_daily_price_batches(stock_basic, price_outcomes)

    monkeypatch.setattr(tradeable_pool, "get_all_stock_basic", lambda: stock_basic.copy())
    monkeypatch.setattr(tradeable_pool, "get_daily_basic_batch", lambda trade_date: daily_basic.copy())
    monkeypatch.setattr(tradeable_pool, "get_open_trade_dates", lambda start_date, end_date: ["20260303", "20260304", "20260305"])
    monkeypatch.setattr(tradeable_pool, "get_daily_price_batch", lambda trade_date: daily_price_batches.get(trade_date, pd.DataFrame()))
    monkeypatch.setattr(tradeable_pool, "get_limit_list", lambda trade_date: pd.DataFrame())
    monkeypatch.setattr(tradeable_pool, "get_suspend_list", lambda trade_date: pd.DataFrame())
    monkeypatch.setattr(tradeable_pool, "get_cooled_tickers", lambda trade_date: set())

    analysis = tradeable_pool.analyze_btst_tradeable_opportunity_pool(
        reports_root,
        trade_dates={"2026-03-03"},
    )

    row = analysis["rows"][0]
    
    # Check cost fields
    assert row["cost_regime"] == "base_liquidity"
    assert row["estimated_slippage_rate"] == 0.0015
    assert row["round_trip_cost_rate"] == 0.004
    
    # Check net return fields
    assert row["next_high_return"] == 0.10
    assert row["next_high_return_after_cost"] == round(0.10 - 0.004, 4)
    assert row["next_close_return"] == 0.05
    assert row["next_close_return_after_cost"] == round(0.05 - 0.004, 4)
    assert row["t_plus_2_close_return"] == 0.08
    assert row["t_plus_2_close_return_after_cost"] == round(0.08 - 0.004, 4)


def test_cost_thresholds_exposed_in_analysis(tmp_path: Path, monkeypatch) -> None:
    """Test that cost replay assumptions are exposed in thresholds."""
    reports_root = tmp_path / "data" / "reports"
    _prepare_report_dir(reports_root)

    stock_basic = pd.DataFrame([{"ts_code": "000001.SZ", "symbol": "000001", "name": "Alpha", "industry": "AI", "market": "SZ", "list_date": "20200101"}])
    daily_basic = pd.DataFrame([{"ts_code": "000001.SZ", "turnover_rate": 10.0, "circ_mv": 100000.0}])
    price_outcomes = {"000001": _build_price_outcome(next_open_return=0.03, next_high_return=0.07, next_close_return=0.05, t_plus_2_close_return=0.08)}
    daily_price_batches = _build_daily_price_batches(stock_basic, price_outcomes)

    monkeypatch.setattr(tradeable_pool, "get_all_stock_basic", lambda: stock_basic.copy())
    monkeypatch.setattr(tradeable_pool, "get_daily_basic_batch", lambda trade_date: daily_basic.copy())
    monkeypatch.setattr(tradeable_pool, "get_open_trade_dates", lambda start_date, end_date: ["20260303", "20260304", "20260305"])
    monkeypatch.setattr(tradeable_pool, "get_daily_price_batch", lambda trade_date: daily_price_batches.get(trade_date, pd.DataFrame()))
    monkeypatch.setattr(tradeable_pool, "get_limit_list", lambda trade_date: pd.DataFrame())
    monkeypatch.setattr(tradeable_pool, "get_suspend_list", lambda trade_date: pd.DataFrame())
    monkeypatch.setattr(tradeable_pool, "get_cooled_tickers", lambda trade_date: set())

    analysis = tradeable_pool.analyze_btst_tradeable_opportunity_pool(
        reports_root,
        trade_dates={"2026-03-03"},
    )

    # Check thresholds include cost parameters
    thresholds = analysis["thresholds"]
    assert "commission_rate" in thresholds
    assert thresholds["commission_rate"] == 0.00025
    assert "stamp_duty_rate" in thresholds
    assert thresholds["stamp_duty_rate"] == 0.0005
    assert "base_slippage_rate" in thresholds
    assert thresholds["base_slippage_rate"] == 0.0015
    assert "low_liquidity_slippage_rate" in thresholds
    assert thresholds["low_liquidity_slippage_rate"] == 0.003
    assert "low_liquidity_turnover_threshold_wan_yuan" in thresholds
    assert thresholds["low_liquidity_turnover_threshold_wan_yuan"] == 5000.0


def test_execution_cost_markdown_section_exists(tmp_path: Path, monkeypatch) -> None:
    """Test that markdown output includes execution cost summary section."""
    reports_root = tmp_path / "data" / "reports"
    _prepare_report_dir(reports_root)

    stock_basic = pd.DataFrame([{"ts_code": "000001.SZ", "symbol": "000001", "name": "Alpha", "industry": "AI", "market": "SZ", "list_date": "20200101"}])
    daily_basic = pd.DataFrame([{"ts_code": "000001.SZ", "turnover_rate": 10.0, "circ_mv": 100000.0}])
    price_outcomes = {"000001": _build_price_outcome(next_open_return=0.03, next_high_return=0.07, next_close_return=0.05, t_plus_2_close_return=0.08)}
    daily_price_batches = _build_daily_price_batches(stock_basic, price_outcomes)

    monkeypatch.setattr(tradeable_pool, "get_all_stock_basic", lambda: stock_basic.copy())
    monkeypatch.setattr(tradeable_pool, "get_daily_basic_batch", lambda trade_date: daily_basic.copy())
    monkeypatch.setattr(tradeable_pool, "get_open_trade_dates", lambda start_date, end_date: ["20260303", "20260304", "20260305"])
    monkeypatch.setattr(tradeable_pool, "get_daily_price_batch", lambda trade_date: daily_price_batches.get(trade_date, pd.DataFrame()))
    monkeypatch.setattr(tradeable_pool, "get_limit_list", lambda trade_date: pd.DataFrame())
    monkeypatch.setattr(tradeable_pool, "get_suspend_list", lambda trade_date: pd.DataFrame())
    monkeypatch.setattr(tradeable_pool, "get_cooled_tickers", lambda trade_date: set())

    analysis = tradeable_pool.analyze_btst_tradeable_opportunity_pool(
        reports_root,
        trade_dates={"2026-03-03"},
    )

    markdown = tradeable_pool.render_btst_tradeable_opportunity_pool_markdown(analysis)
    
    # Check that markdown includes execution cost section
    assert "## Execution Cost Impact" in markdown or "## 执行成本影响" in markdown
    # Check cost summary fields appear in markdown
    assert "base_liquidity" in markdown or "基础流动性" in markdown
    assert "low_liquidity" in markdown or "低流动性" in markdown


def test_execution_cost_summary_counts_flipped_rows_once_across_metrics() -> None:
    summary = tradeable_pool._build_execution_cost_summary(
        [
            {
                "ticker": "000001",
                "cost_regime": "base_liquidity",
                "estimated_slippage_rate": 0.0015,
                "round_trip_cost_rate": 0.0045,
                "next_high_return": 0.003,
                "next_high_return_after_cost": -0.0015,
                "next_close_return": 0.002,
                "next_close_return_after_cost": -0.0025,
                "t_plus_2_close_return": 0.001,
                "t_plus_2_close_return_after_cost": -0.0035,
            }
        ]
    )

    assert summary["positive_gross_any_metric_flipped_count"] == 1
    assert summary["positive_gross_any_metric_flipped_share"] == 1.0
    assert "100.0%" in summary["recommendation"]
