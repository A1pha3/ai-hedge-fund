from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

import scripts.analyze_btst_early_runner_v1 as early_runner


def _write_snapshot(
    report_dir: Path,
    trade_date: str,
    selection_targets: dict[str, object],
    *,
    market_state: dict[str, object] | None = None,
    catalyst_theme_candidates: list[dict[str, Any]] | None = None,
    catalyst_theme_shadow_candidates: list[dict[str, Any]] | None = None,
) -> None:
    snapshot_dir = report_dir / "selection_artifacts" / trade_date
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_dir.joinpath("selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": trade_date.replace("-", ""),
                "market_state": market_state or {},
                "selection_targets": selection_targets,
                "catalyst_theme_candidates": catalyst_theme_candidates or [],
                "catalyst_theme_shadow_candidates": catalyst_theme_shadow_candidates or [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _selection_target(
    *,
    candidate_source: str,
    decision: str,
    score_target: float,
    preferred_entry_mode: str,
    metrics: dict[str, object],
) -> dict[str, object]:
    return {
        "candidate_source": candidate_source,
        "short_trade": {
            "decision": decision,
            "score_target": score_target,
            "preferred_entry_mode": preferred_entry_mode,
            "explainability_payload": dict(metrics),
        },
    }


def _stock_basic_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ts_code": "300001.SZ", "symbol": "300001", "name": "EarlyOne", "industry": "AI", "market": "SZ", "list_date": "20200101"},
            {"ts_code": "300002.SZ", "symbol": "300002", "name": "SecondOne", "industry": "Chip", "market": "SZ", "list_date": "20200101"},
            {"ts_code": "600003.SH", "symbol": "600003", "name": "ConfirmOne", "industry": "Chip", "market": "SH", "list_date": "20190101"},
            {"ts_code": "000004.SZ", "symbol": "000004", "name": "ST Demo", "industry": "Risk", "market": "SZ", "list_date": "20100101"},
            {"ts_code": "301005.SZ", "symbol": "301005", "name": "FreshIPO", "industry": "Bio", "market": "SZ", "list_date": "20260215"},
        ]
    )


def _daily_basic_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ts_code": "300001.SZ", "turnover_rate": 10.0, "circ_mv": 100000.0},
            {"ts_code": "300002.SZ", "turnover_rate": 8.0, "circ_mv": 100000.0},
            {"ts_code": "600003.SH", "turnover_rate": 9.0, "circ_mv": 100000.0},
            {"ts_code": "000004.SZ", "turnover_rate": 11.0, "circ_mv": 90000.0},
            {"ts_code": "301005.SZ", "turnover_rate": 12.0, "circ_mv": 80000.0},
        ]
    )


def test_analyze_btst_early_runner_v1_builds_ledgers_profiles_and_daily_boards(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260323_20260326_early_runner"
    report_dir.mkdir(parents=True, exist_ok=True)

    market_state = {
        "breadth_ratio": 0.58,
        "daily_return": 0.003,
        "style_dispersion": 0.18,
        "regime_flip_risk": 0.12,
        "regime_gate_level": "normal",
    }
    selection_targets = {
        "300001": _selection_target(
            candidate_source="catalyst_theme",
            decision="near_miss",
            score_target=0.66,
            preferred_entry_mode="confirm_then_hold_breakout",
            metrics={
                "trend_acceleration": 0.86,
                "breakout_freshness": 0.48,
                "volume_expansion_quality": 0.52,
                "close_strength": 0.78,
                "sector_resonance": 0.36,
                "catalyst_freshness": 0.62,
                "layer_c_alignment": 0.58,
                "ret_5d": 0.12,
                "ret_10d": 0.24,
                "gap_to_limit": 0.06,
                "failed_breakout_10": 0,
                "supply_pressure_60": 0.08,
                "projected_theme_exposure": 0.22,
                "amount": 80000000.0,
                "historical_prior": {
                    "sample_count": 8,
                    "next_high_hit_rate_at_threshold": 0.75,
                    "next_close_positive_rate": 0.62,
                },
            },
        ),
        "300002": _selection_target(
            candidate_source="catalyst_theme_shadow",
            decision="near_miss",
            score_target=0.63,
            preferred_entry_mode="avoid_open_chase_confirmation",
            metrics={
                "trend_acceleration": 0.91,
                "breakout_freshness": 0.74,
                "volume_expansion_quality": 0.66,
                "close_strength": 0.97,
                "sector_resonance": 0.43,
                "catalyst_freshness": 0.81,
                "layer_c_alignment": 0.72,
                "ret_5d": 0.31,
                "ret_10d": 0.55,
                "gap_to_limit": 0.01,
                "failed_breakout_10": 0,
                "supply_pressure_60": 0.09,
                "projected_theme_exposure": 0.19,
                "amount": 62000000.0,
            },
        ),
        "600003": _selection_target(
            candidate_source="short_trade_boundary",
            decision="selected",
            score_target=0.72,
            preferred_entry_mode="confirm_then_hold_breakout",
            metrics={
                "trend_acceleration": 0.71,
                "breakout_freshness": 0.63,
                "volume_expansion_quality": 0.49,
                "close_strength": 0.93,
                "sector_resonance": 0.31,
                "catalyst_freshness": 0.57,
                "layer_c_alignment": 0.61,
                "ret_5d": 0.18,
                "ret_10d": 0.28,
                "gap_to_limit": 0.04,
                "failed_breakout_10": 0,
                "supply_pressure_60": 0.10,
                "projected_theme_exposure": 0.24,
                "amount": 90000000.0,
            },
        ),
    }
    _write_snapshot(
        report_dir,
        "2026-03-24",
        selection_targets,
        market_state=market_state,
        catalyst_theme_candidates=[
            {"ticker": "300001", "theme_name": "AI Agent", "theme_category": "AI", "candidate_source": "catalyst_theme", "is_new_theme": True},
            {"ticker": "300002", "theme_name": "AI Agent", "theme_category": "AI", "candidate_source": "catalyst_theme", "is_new_theme": True},
        ],
        catalyst_theme_shadow_candidates=[
            {"ticker": "600003", "theme_name": "AI Agent", "theme_category": "AI", "candidate_source": "catalyst_theme_shadow", "is_new_theme": False},
        ],
    )

    monkeypatch.setattr(early_runner, "discover_report_dirs", lambda roots, report_name_contains="paper_trading_window": [report_dir])
    monkeypatch.setattr(early_runner, "get_all_stock_basic", _stock_basic_frame)
    monkeypatch.setattr(early_runner, "get_daily_basic_batch", lambda trade_date: _daily_basic_frame())
    monkeypatch.setattr(early_runner, "get_suspend_list", lambda trade_date: pd.DataFrame(columns=["ts_code"]))
    monkeypatch.setattr(early_runner, "get_limit_list", lambda trade_date: pd.DataFrame(columns=["ts_code", "limit"]))
    monkeypatch.setattr(early_runner, "get_open_trade_dates", lambda start_date, end_date: ["20260324", "20260325", "20260326", "20260327", "20260328", "20260331"])
    monkeypatch.setattr(
        early_runner,
        "_extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {
            "300001": {
                "cycle_status": "closed_cycle",
                "next_open_return": 0.02,
                "next_high_return": 0.16,
                "next_low_return": -0.01,
                "next_close_return": 0.05,
                "next_open_to_close_return": 0.03,
                "t_plus_2_close_return": 0.08,
                "max_future_high_return_2_5d": 0.18,
                "future_high_hit_15pct_2_5d": True,
            },
            "300002": {
                "cycle_status": "closed_cycle",
                "next_open_return": 0.04,
                "next_high_return": 0.09,
                "next_low_return": -0.06,
                "next_close_return": -0.03,
                "next_open_to_close_return": -0.07,
                "t_plus_2_close_return": -0.05,
                "max_future_high_return_2_5d": 0.10,
                "future_high_hit_15pct_2_5d": False,
            },
            "600003": {
                "cycle_status": "closed_cycle",
                "next_open_return": 0.01,
                "next_high_return": 0.07,
                "next_low_return": -0.02,
                "next_close_return": 0.04,
                "next_open_to_close_return": 0.03,
                "t_plus_2_close_return": 0.05,
                "max_future_high_return_2_5d": 0.08,
                "future_high_hit_15pct_2_5d": False,
            },
        }[ticker],
    )

    analysis = early_runner.analyze_btst_early_runner_v1(reports_root)

    assert set(analysis.keys()) == {
        "generated_at",
        "reports_root",
        "report_dir_count",
        "row_count",
        "feature_time_map",
        "feature_time_validation",
        "limit_rule_profile",
        "universe_filter",
        "universe_filter_summary",
        "cost_profile",
        "thresholds",
        "daily_boards",
        "theme_radar_by_trade_date",
        "industry_radar_by_trade_date",
        "failure_log",
        "walk_forward_threshold_report",
        "validation",
        "acceptance_checklist",
        "deployment_mode",
        "runtime_candidate_entries",
        "promotion_blockers",
        "early_runner_first_entry_ledger",
        "second_entry_reentry_ledger",
        "full_report_confirmation_ledger",
        "implementation_notes",
    }
    assert analysis["feature_time_validation"]["no_lookahead_fields_in_pre_score"] is True
    assert analysis["feature_time_map"]["trend_acceleration"]["allowed_in_pre_score"] is True
    assert analysis["feature_time_map"]["next_open_return"]["allowed_in_pre_score"] is False
    assert analysis["cost_profile"]["commission_rate"] == 0.00025
    assert analysis["cost_profile"]["stamp_duty_rate"] == 0.001
    assert analysis["validation"]["ledgers_separated"] is True
    assert analysis["validation"]["universe_filter_applied"] is True
    assert analysis["validation"]["max_single_theme_exposure"] == 0.24
    assert analysis["validation"]["failure_log_coverage"] == 1.0
    assert analysis["acceptance_checklist"]["deployment_mode"] == "shadow_only"
    assert "month_oos_pass_count" in analysis["acceptance_checklist"]["failed_items"]
    assert "deduped_closed" in analysis["acceptance_checklist"]["failed_items"]

    daily_board = analysis["daily_boards"][0]
    assert set(daily_board.keys()) == {
        "trade_date",
        "btst_regime_gate",
        "gate_action",
        "early_runner_watchlist",
        "early_runner_priority",
        "second_entry_reentry",
        "full_report_confirmation",
        "confirmed_entries",
        "theme_radar",
        "industry_radar",
        "theme_radar_ready",
        "runtime_candidate_entries",
        "deployment_mode",
    }
    assert daily_board["btst_regime_gate"] == "normal_trade"
    assert daily_board["deployment_mode"] == "shadow_only"
    assert [entry["ticker"] for entry in daily_board["early_runner_watchlist"]] == ["300001"]
    assert [entry["ticker"] for entry in daily_board["early_runner_priority"]] == ["300001"]
    assert [entry["ticker"] for entry in daily_board["second_entry_reentry"]] == ["300002"]
    assert [entry["ticker"] for entry in daily_board["confirmed_entries"]] == ["300001"]
    assert daily_board["theme_radar_ready"] is True
    assert daily_board["theme_radar"]["top_active_themes"] == ["AI Agent"]
    assert daily_board["runtime_candidate_entries"] == []

    assert set(analysis["acceptance_checklist"]["items"].keys()) == {
        "feature_time_map_coverage",
        "no_lookahead_fields_in_pre_score",
        "universe_filter_applied",
        "limit_rule_profile_version_logged",
        "cost_profile_version_logged",
        "tradable_after_cost_expectancy",
        "month_oos_pass_count",
        "deduped_closed",
        "unfilled_rate",
        "abandoned_gap_rate",
        "t_plus_1_drawdown_p10",
        "max_single_theme_exposure",
        "failure_log_coverage",
        "ledgers_separated",
        "halt_trade_count",
        "promotion_blockers",
    }
    assert analysis["early_runner_first_entry_ledger"]["sample_count"] == 1
    assert analysis["second_entry_reentry_ledger"]["sample_count"] == 1
    assert analysis["full_report_confirmation_ledger"]["sample_count"] == 1
    assert analysis["failure_log"][0]["ticker"] == "300002"
    assert analysis["failure_log"][0]["failure_reason"] == "gap_trap"
    assert analysis["walk_forward_threshold_report"]["candidate_grid_size"] > 0

    markdown = early_runner.render_btst_early_runner_v1_markdown(analysis)
    assert "# BTST Early Runner V1" in markdown
    assert "## Feature Time Map" in markdown
    assert "## Ledgers" in markdown


def test_analyze_btst_early_runner_v1_tolerates_missing_stock_basic(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260324_20260324_missing_stock_basic"
    report_dir.mkdir(parents=True, exist_ok=True)

    _write_snapshot(
        report_dir,
        "2026-03-24",
        {
            "300001": _selection_target(
                candidate_source="catalyst_theme",
                decision="near_miss",
                score_target=0.66,
                preferred_entry_mode="confirm_then_hold_breakout",
                metrics={
                    "trend_acceleration": 0.86,
                    "breakout_freshness": 0.48,
                    "volume_expansion_quality": 0.52,
                    "close_strength": 0.78,
                    "sector_resonance": 0.36,
                    "catalyst_freshness": 0.62,
                    "layer_c_alignment": 0.58,
                    "ret_5d": 0.12,
                    "ret_10d": 0.24,
                    "gap_to_limit": 0.06,
                    "failed_breakout_10": 0,
                    "supply_pressure_60": 0.08,
                    "projected_theme_exposure": 0.22,
                    "amount": 80000000.0,
                },
            )
        },
        market_state={
            "breadth_ratio": 0.58,
            "daily_return": 0.003,
            "style_dispersion": 0.18,
            "regime_flip_risk": 0.12,
            "regime_gate_level": "normal",
        },
    )

    monkeypatch.setattr(early_runner, "discover_report_dirs", lambda roots, report_name_contains="paper_trading_window": [report_dir])
    monkeypatch.setattr(early_runner, "get_all_stock_basic", lambda: None)
    monkeypatch.setattr(early_runner, "get_daily_basic_batch", lambda trade_date: _daily_basic_frame())
    monkeypatch.setattr(early_runner, "get_suspend_list", lambda trade_date: pd.DataFrame(columns=["ts_code"]))
    monkeypatch.setattr(early_runner, "get_limit_list", lambda trade_date: pd.DataFrame(columns=["ts_code", "limit"]))
    monkeypatch.setattr(early_runner, "get_open_trade_dates", lambda start_date, end_date: ["20260324", "20260325", "20260326"])
    monkeypatch.setattr(
        early_runner,
        "_extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {
            "cycle_status": "closed_cycle",
            "next_open_return": 0.02,
            "next_high_return": 0.16,
            "next_low_return": -0.01,
            "next_close_return": 0.05,
            "next_open_to_close_return": 0.03,
            "t_plus_2_close_return": 0.08,
            "max_future_high_return_2_5d": 0.18,
            "future_high_hit_15pct_2_5d": True,
        },
    )

    analysis = early_runner.analyze_btst_early_runner_v1(reports_root)

    assert analysis["report_dir_count"] == 1
    assert analysis["universe_filter_summary"]["total_row_count"] == 1
    assert analysis["row_count"] == 0
    assert analysis["daily_boards"] == []


def test_analyze_btst_early_runner_v1_respects_shadow_gate_and_universe_filter(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260327_20260331_shadow"
    report_dir.mkdir(parents=True, exist_ok=True)

    market_state = {
        "breadth_ratio": 0.44,
        "daily_return": -0.001,
        "style_dispersion": 0.58,
        "regime_flip_risk": 0.40,
        "regime_gate_level": "normal",
    }
    selection_targets = {
        "300001": _selection_target(
            candidate_source="catalyst_theme",
            decision="near_miss",
            score_target=0.64,
            preferred_entry_mode="confirm_then_hold_breakout",
            metrics={
                "trend_acceleration": 0.82,
                "breakout_freshness": 0.46,
                "volume_expansion_quality": 0.50,
                "close_strength": 0.77,
                "sector_resonance": 0.35,
                "catalyst_freshness": 0.60,
                "ret_5d": 0.10,
                "ret_10d": 0.22,
                "gap_to_limit": 0.08,
                "failed_breakout_10": 0,
                "supply_pressure_60": 0.09,
                "amount": 76000000.0,
            },
        ),
        "000004": _selection_target(
            candidate_source="catalyst_theme",
            decision="near_miss",
            score_target=0.67,
            preferred_entry_mode="confirm_then_hold_breakout",
            metrics={
                "trend_acceleration": 0.88,
                "breakout_freshness": 0.49,
                "volume_expansion_quality": 0.53,
                "close_strength": 0.80,
                "sector_resonance": 0.36,
                "catalyst_freshness": 0.63,
                "ret_5d": 0.11,
                "ret_10d": 0.20,
                "gap_to_limit": 0.07,
                "failed_breakout_10": 0,
                "supply_pressure_60": 0.08,
                "amount": 70000000.0,
            },
        ),
        "301005": _selection_target(
            candidate_source="catalyst_theme_shadow",
            decision="near_miss",
            score_target=0.61,
            preferred_entry_mode="confirm_then_hold_breakout",
            metrics={
                "trend_acceleration": 0.80,
                "breakout_freshness": 0.45,
                "volume_expansion_quality": 0.48,
                "close_strength": 0.75,
                "sector_resonance": 0.32,
                "catalyst_freshness": 0.58,
                "ret_5d": 0.09,
                "ret_10d": 0.19,
                "gap_to_limit": 0.08,
                "failed_breakout_10": 0,
                "supply_pressure_60": 0.07,
                "amount": 65000000.0,
            },
        ),
    }
    _write_snapshot(report_dir, "2026-03-27", selection_targets, market_state=market_state)

    monkeypatch.setattr(early_runner, "discover_report_dirs", lambda roots, report_name_contains="paper_trading_window": [report_dir])
    monkeypatch.setattr(early_runner, "get_all_stock_basic", _stock_basic_frame)
    monkeypatch.setattr(early_runner, "get_daily_basic_batch", lambda trade_date: _daily_basic_frame())
    monkeypatch.setattr(early_runner, "get_suspend_list", lambda trade_date: pd.DataFrame(columns=["ts_code"]))
    monkeypatch.setattr(early_runner, "get_limit_list", lambda trade_date: pd.DataFrame(columns=["ts_code", "limit"]))
    monkeypatch.setattr(early_runner, "get_open_trade_dates", lambda start_date, end_date: ["20260327", "20260328", "20260331", "20260401", "20260402", "20260403"])
    monkeypatch.setattr(
        early_runner,
        "_extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {
            "cycle_status": "closed_cycle",
            "next_open_return": 0.01,
            "next_high_return": 0.08,
            "next_low_return": -0.02,
            "next_close_return": 0.03,
            "next_open_to_close_return": 0.02,
            "t_plus_2_close_return": 0.04,
            "max_future_high_return_2_5d": 0.09,
            "future_high_hit_15pct_2_5d": False,
        },
    )

    analysis = early_runner.analyze_btst_early_runner_v1(reports_root)

    daily_board = analysis["daily_boards"][0]
    assert daily_board["btst_regime_gate"] == "shadow_only"
    assert daily_board["gate_action"] == "research_only"
    assert daily_board["deployment_mode"] == "research_only"
    assert [entry["ticker"] for entry in daily_board["early_runner_watchlist"]] == ["300001"]
    assert daily_board["confirmed_entries"] == []

    universe_summary = analysis["universe_filter_summary"]
    assert universe_summary["excluded_st_or_risk_warning_count"] == 1
    assert universe_summary["excluded_new_listing_count"] == 1
    assert analysis["validation"]["halt_trade_count"] == 0


def test_analyze_btst_early_runner_v1_uses_watchlist_cohort_for_first_entry_validation(tmp_path: Path, monkeypatch) -> None:
    """First-entry validation should count watchlist samples even when no row reaches priority threshold."""
    reports_root = tmp_path / "data" / "reports"
    report_dir = reports_root / "paper_trading_window_20260407_20260408_early_runner"
    report_dir.mkdir(parents=True, exist_ok=True)

    selection_targets = {
        "300001": _selection_target(
            candidate_source="catalyst_theme",
            decision="near_miss",
            score_target=0.46,
            preferred_entry_mode="confirm_then_hold_breakout",
            metrics={
                "trend_acceleration": 0.79,
                "breakout_freshness": 0.58,
                "volume_expansion_quality": 0.34,
                "close_strength": 0.88,
                "sector_resonance": 0.18,
                "catalyst_freshness": 0.0,
                "layer_c_alignment": 0.49,
                "ret_5d": 0.0,
                "ret_10d": 0.0,
                "gap_to_limit": 0.10,
                "failed_breakout_10": 0,
                "supply_pressure_60": 0.10,
                "projected_theme_exposure": 0.12,
            },
        ),
        "300002": _selection_target(
            candidate_source="catalyst_theme",
            decision="near_miss",
            score_target=0.45,
            preferred_entry_mode="confirm_then_hold_breakout",
            metrics={
                "trend_acceleration": 0.81,
                "breakout_freshness": 0.56,
                "volume_expansion_quality": 0.32,
                "close_strength": 0.87,
                "sector_resonance": 0.17,
                "catalyst_freshness": 0.0,
                "layer_c_alignment": 0.48,
                "ret_5d": 0.0,
                "ret_10d": 0.0,
                "gap_to_limit": 0.10,
                "failed_breakout_10": 0,
                "supply_pressure_60": 0.10,
                "projected_theme_exposure": 0.10,
            },
        ),
    }
    _write_snapshot(
        report_dir,
        "2026-04-07",
        selection_targets,
        catalyst_theme_candidates=[
            {"ticker": "300001", "theme_name": "", "theme_category": "", "candidate_source": "catalyst_theme"},
            {"ticker": "300002", "theme_name": "", "theme_category": "", "candidate_source": "catalyst_theme"},
        ],
    )

    monkeypatch.setattr(early_runner, "discover_report_dirs", lambda roots, report_name_contains="paper_trading_window": [report_dir])
    monkeypatch.setattr(
        early_runner,
        "get_all_stock_basic",
        lambda: pd.DataFrame(
            [
                {"ts_code": "300001.SZ", "symbol": "300001", "name": "EarlyOne", "industry": "AI", "market": "SZ", "list_date": "20200101"},
                {"ts_code": "300002.SZ", "symbol": "300002", "name": "ThemeMate", "industry": "AI", "market": "SZ", "list_date": "20200101"},
            ]
        ),
    )
    monkeypatch.setattr(early_runner, "get_daily_basic_batch", lambda trade_date: _daily_basic_frame())
    monkeypatch.setattr(early_runner, "get_suspend_list", lambda trade_date: pd.DataFrame(columns=["ts_code"]))
    monkeypatch.setattr(early_runner, "get_limit_list", lambda trade_date: pd.DataFrame(columns=["ts_code", "limit"]))
    monkeypatch.setattr(early_runner, "get_open_trade_dates", lambda start_date, end_date: ["20260407", "20260408", "20260409"])
    monkeypatch.setattr(
        early_runner,
        "compute_confirm_assessment",
        lambda *args, **kwargs: {
            "score": 0.55,
            "provenance": "proxy_fallback",
            "checks": {},
            "hard_failures": {},
            "inputs": {},
            "intraday_metrics": {},
        },
    )
    monkeypatch.setattr(
        early_runner,
        "_extract_btst_price_outcome",
        lambda ticker, trade_date, price_cache: {
            "cycle_status": "closed_cycle",
            "next_open_return": 0.01,
            "next_high_return": 0.06,
            "next_low_return": -0.02,
            "next_close_return": 0.03,
            "next_open_to_close_return": 0.02,
            "t_plus_2_close_return": 0.05,
            "max_future_high_return_2_5d": 0.07,
            "future_high_hit_15pct_2_5d": False,
        },
    )

    analysis = early_runner.analyze_btst_early_runner_v1(reports_root)

    daily_board = analysis["daily_boards"][0]
    assert [entry["ticker"] for entry in daily_board["early_runner_watchlist"]] == ["300001", "300002"]
    assert analysis["theme_radar_by_trade_date"]["2026-04-07"]["top_active_themes"] == ["AI"]
    assert analysis["early_runner_first_entry_ledger"]["sample_count"] == len(daily_board["early_runner_watchlist"])
    assert analysis["early_runner_first_entry_ledger"]["deduped_sample_count"] == len(daily_board["early_runner_watchlist"])
