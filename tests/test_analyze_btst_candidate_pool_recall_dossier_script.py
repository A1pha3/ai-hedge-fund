from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import scripts.analyze_btst_candidate_pool_recall_dossier as recall_script
from scripts.analyze_btst_candidate_pool_recall_dossier import analyze_btst_candidate_pool_recall_dossier


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def test_build_focus_tickers_backfills_high_value_strict_no_candidate_misses() -> None:
    focus_tickers = recall_script._build_focus_tickers(
        {
            "rows": [
                {
                    "trade_date": "2026-03-31",
                    "ticker": "301188",
                    "first_kill_switch": "no_candidate_entry",
                    "strict_btst_goal_case": True,
                    "next_high_return": 0.2001,
                    "t_plus_2_close_return": 0.3844,
                },
                {
                    "trade_date": "2026-04-01",
                    "ticker": "688677",
                    "first_kill_switch": "no_candidate_entry",
                    "strict_btst_goal_case": True,
                    "next_high_return": 0.1999,
                    "t_plus_2_close_return": 0.3721,
                },
                {
                    "trade_date": "2026-03-20",
                    "ticker": "301292",
                    "first_kill_switch": "no_candidate_entry",
                    "strict_btst_goal_case": False,
                    "next_high_return": 0.2000,
                    "t_plus_2_close_return": 0.3953,
                },
            ],
            "no_candidate_entry_summary": {
                "top_ticker_rows": [{"ticker": "300720"}, {"ticker": "003036"}, {"ticker": "603778"}]
            },
        },
        {
            "top_absent_from_candidate_pool_tickers": ["300720", "003036", "603778"],
        },
        {},
        priority_limit=5,
    )

    assert focus_tickers == ["300720", "003036", "603778", "301188", "688677"]


def test_analyze_btst_candidate_pool_recall_dossier_splits_layer_a_root_causes(tmp_path: Path) -> None:
    avg_amount_share_of_min_gate = round(9100.0 / float(recall_script.MIN_AVG_AMOUNT_20D), 4)
    cutoff_avg_amount_share_of_min_gate = round(9250.0 / float(recall_script.MIN_AVG_AMOUNT_20D), 4)
    reports_root = tmp_path / "data" / "reports"
    tradeable_pool_path = _write_json(
        reports_root / "btst_tradeable_opportunity_pool_march.json",
        {
            "reports_root": str(reports_root.resolve()),
            "rows": [
                {
                    "trade_date": "2026-03-23",
                    "ticker": "300720",
                    "first_kill_switch": "no_candidate_entry",
                    "report_dir": "paper_trading_window_a",
                    "report_mode": "live_pipeline",
                    "strict_btst_goal_case": True,
                    "next_high_return": 0.08,
                    "t_plus_2_close_return": 0.05,
                },
                {
                    "trade_date": "2026-03-24",
                    "ticker": "003036",
                    "first_kill_switch": "no_candidate_entry",
                    "report_dir": "paper_trading_window_b",
                    "report_mode": "live_pipeline",
                    "strict_btst_goal_case": True,
                    "next_high_return": 0.07,
                    "t_plus_2_close_return": 0.06,
                },
                {
                    "trade_date": "2026-03-25",
                    "ticker": "301292",
                    "first_kill_switch": "no_candidate_entry",
                    "report_dir": "paper_trading_window_c",
                    "report_mode": "live_pipeline",
                    "strict_btst_goal_case": False,
                    "next_high_return": 0.06,
                    "t_plus_2_close_return": 0.01,
                },
            ],
            "no_candidate_entry_summary": {
                "top_ticker_rows": [
                    {"ticker": "300720"},
                    {"ticker": "003036"},
                    {"ticker": "301292"},
                ]
            },
        },
    )
    watchlist_recall_dossier_path = _write_json(
        reports_root / "btst_watchlist_recall_dossier_latest.json",
        {
            "top_absent_from_candidate_pool_tickers": ["300720", "003036", "301292"],
            "priority_ticker_dossiers": [
                {
                    "ticker": "300720",
                    "occurrence_evidence": [{"trade_date": "2026-03-23", "recall_stage": "absent_from_candidate_pool"}],
                },
                {
                    "ticker": "003036",
                    "occurrence_evidence": [{"trade_date": "2026-03-24", "recall_stage": "absent_from_candidate_pool"}],
                },
                {
                    "ticker": "301292",
                    "occurrence_evidence": [{"trade_date": "2026-03-25", "recall_stage": "absent_from_candidate_pool"}],
                },
            ],
        },
    )

    analysis = analyze_btst_candidate_pool_recall_dossier(
        tradeable_pool_path,
        watchlist_recall_dossier_path=watchlist_recall_dossier_path,
        diagnostics_override={
            ("300720", "20260323"): {
                "blocking_stage": "low_avg_amount_20d",
                "candidate_pool_visible": False,
                "candidate_pool_rank": None,
                "avg_amount_20d": 4120.0,
            },
            ("003036", "20260324"): {
                "blocking_stage": "candidate_pool_truncated_after_filters",
                "candidate_pool_visible": False,
                "candidate_pool_rank": None,
                "estimated_amount_1d": 8350.0,
                "avg_amount_20d": 9100.0,
                "pre_truncation_total_candidates": 318,
                "pre_truncation_cutoff_rank": 300,
                "pre_truncation_rank": 304,
                "pre_truncation_rank_gap_to_cutoff": 4,
                "pre_truncation_cutoff_ticker": "600123",
                "pre_truncation_cutoff_avg_amount_20d": 9250.0,
                "pre_truncation_cutoff_market_cap": 18.4,
                "pre_truncation_frontier_window": [
                    {"rank": 299, "ticker": "600120", "avg_amount_20d": 9280.0, "market_cap": 19.1},
                    {"rank": 300, "ticker": "600123", "avg_amount_20d": 9250.0, "market_cap": 18.4},
                    {"rank": 301, "ticker": "600125", "avg_amount_20d": 9210.0, "market_cap": 17.9},
                    {"rank": 304, "ticker": "003036", "avg_amount_20d": 9100.0, "market_cap": 16.2},
                ],
            },
            ("301292", "20260325"): {
                "blocking_stage": "cooldown_excluded",
                "candidate_pool_visible": False,
                "candidate_pool_rank": None,
            },
        },
    )

    assert analysis["priority_stage_counts"] == {
        "cooldown_excluded": 1,
        "low_avg_amount_20d": 1,
        "candidate_pool_truncated_after_filters": 1,
    }
    assert analysis["dominant_stage"] == "cooldown_excluded"
    assert analysis["top_stage_tickers"] == {
        "cooldown_excluded": ["301292"],
        "low_avg_amount_20d": ["300720"],
        "candidate_pool_truncated_after_filters": ["003036"],
    }
    assert analysis["truncation_frontier_summary"]["observed_case_count"] == 1
    assert analysis["truncation_frontier_summary"]["rank_observed_case_count"] == 1
    assert analysis["truncation_frontier_summary"]["frontier_verdict"] == "near_cutoff_boundary"
    assert analysis["truncation_frontier_summary"]["dominant_ranking_driver"] == "mixed_post_filter_gap"
    assert analysis["truncation_frontier_summary"]["dominant_liquidity_gap_mode"] == "near_cutoff_liquidity_gap"
    assert analysis["truncation_frontier_summary"]["avg_amount_share_of_cutoff_mean"] == 0.9838
    assert analysis["truncation_frontier_summary"]["closest_cases"][0]["ticker"] == "003036"
    assert analysis["truncation_frontier_summary"]["closest_distinct_ticker_cases"][0]["ticker"] == "003036"
    assert analysis["action_queue"][0]["task_id"] == "300720_low_avg_amount_20d"
    dossiers_by_ticker = {row["ticker"]: row for row in analysis["priority_ticker_dossiers"]}
    assert dossiers_by_ticker["300720"]["dominant_blocking_stage"] == "low_avg_amount_20d"
    assert dossiers_by_ticker["003036"]["dominant_blocking_stage"] == "candidate_pool_truncated_after_filters"
    assert dossiers_by_ticker["301292"]["dominant_blocking_stage"] == "cooldown_excluded"
    assert dossiers_by_ticker["003036"]["truncation_ranking_summary"] == {
        "truncation_case_count": 1,
        "dominant_ranking_driver": "mixed_post_filter_gap",
        "ranking_driver_counts": {"mixed_post_filter_gap": 1},
        "dominant_liquidity_gap_mode": "near_cutoff_liquidity_gap",
        "liquidity_gap_mode_counts": {"near_cutoff_liquidity_gap": 1},
        "avg_rank_gap_to_cutoff": 4.0,
        "min_rank_gap_to_cutoff": 4,
        "avg_amount_share_of_cutoff_mean": 0.9838,
        "avg_amount_share_of_cutoff_min": 0.9838,
        "avg_amount_share_of_cutoff_max": 0.9838,
        "avg_amount_share_of_min_gate_mean": avg_amount_share_of_min_gate,
        "avg_amount_share_of_min_gate_min": avg_amount_share_of_min_gate,
        "avg_amount_share_of_min_gate_max": avg_amount_share_of_min_gate,
        "cutoff_avg_amount_share_of_min_gate_mean": cutoff_avg_amount_share_of_min_gate,
        "cutoff_avg_amount_share_of_min_gate_min": cutoff_avg_amount_share_of_min_gate,
        "cutoff_avg_amount_share_of_min_gate_max": cutoff_avg_amount_share_of_min_gate,
        "closest_case": {
            "trade_date": "20260324",
            "pre_truncation_rank": 304,
            "pre_truncation_rank_gap_to_cutoff": 4,
            "pre_truncation_avg_amount_share_of_cutoff": 0.9838,
            "pre_truncation_ranking_driver": "mixed_post_filter_gap",
            "avg_amount_share_of_min_gate": avg_amount_share_of_min_gate,
            "pre_truncation_liquidity_gap_mode": "near_cutoff_liquidity_gap",
        },
    }
    assert dossiers_by_ticker["003036"]["truncation_liquidity_profile"] == {
        "ticker": "003036",
        "truncation_case_count": 1,
        "dominant_liquidity_gap_mode": "near_cutoff_liquidity_gap",
        "dominant_ranking_driver": "mixed_post_filter_gap",
        "avg_amount_share_of_cutoff_mean": 0.9838,
        "avg_amount_share_of_min_gate_mean": avg_amount_share_of_min_gate,
        "cutoff_avg_amount_share_of_min_gate_mean": cutoff_avg_amount_share_of_min_gate,
        "min_rank_gap_to_cutoff": 4,
        "avg_rank_gap_to_cutoff": 4.0,
        "priority_handoff": "top300_boundary_micro_tuning",
        "profile_summary": "这只票更接近 cutoff 微边界，可保留为 top300 boundary 微调对照样本。",
        "closest_case": {
            "trade_date": "20260324",
            "pre_truncation_rank": 304,
            "pre_truncation_rank_gap_to_cutoff": 4,
            "pre_truncation_avg_amount_share_of_cutoff": 0.9838,
            "pre_truncation_ranking_driver": "mixed_post_filter_gap",
            "avg_amount_share_of_min_gate": avg_amount_share_of_min_gate,
            "pre_truncation_liquidity_gap_mode": "near_cutoff_liquidity_gap",
        },
    }
    assert analysis["focus_liquidity_profile_summary"] == {
        "profile_count": 1,
        "dominant_liquidity_gap_mode": "near_cutoff_liquidity_gap",
        "liquidity_gap_mode_counts": {"near_cutoff_liquidity_gap": 1},
        "priority_handoff_counts": {"top300_boundary_micro_tuning": 1},
        "primary_focus_tickers": [dossiers_by_ticker["003036"]["truncation_liquidity_profile"]],
    }
    assert analysis["priority_handoff_branch_diagnoses"] == [
        {
            "priority_handoff": "top300_boundary_micro_tuning",
            "ticker_count": 1,
            "tickers": ["003036"],
            "dominant_liquidity_gap_mode": "near_cutoff_liquidity_gap",
            "dominant_ranking_driver": "mixed_post_filter_gap",
            "avg_amount_share_of_cutoff_mean": 0.9838,
            "avg_amount_share_of_min_gate_mean": avg_amount_share_of_min_gate,
            "min_rank_gap_to_cutoff": 4,
            "liquidity_gap_mode_counts": {"near_cutoff_liquidity_gap": 1},
            "ranking_driver_counts": {"mixed_post_filter_gap": 1},
            "closest_focus_profile": dossiers_by_ticker["003036"]["truncation_liquidity_profile"],
            "diagnosis_summary": "003036 更接近 cutoff 微边界，当前可以保留为 top300 boundary micro-tuning 对照样本。",
            "next_step": "优先保留 pre-truncation rank 观测，评估是否存在可控的 top300 微边界调参空间。",
        }
    ]
    assert analysis["priority_handoff_branch_mechanisms"] == [
        {
            "priority_handoff": "top300_boundary_micro_tuning",
            "ticker_count": 1,
            "tickers": ["003036"],
            "occurrence_count": 1,
            "avg_amount_share_of_cutoff_mean": 0.9838,
            "avg_amount_gap_to_cutoff_mean": 150.0,
            "avg_amount_share_of_min_gate_mean": avg_amount_share_of_min_gate,
            "cutoff_avg_amount_share_of_min_gate_mean": cutoff_avg_amount_share_of_min_gate,
            "cutoff_to_candidate_liquidity_multiple_mean": 1.0165,
            "min_rank_gap_to_cutoff": 4,
            "peer_avg_amount_multiple_mean": 1.0161,
            "peer_market_cap_multiple_mean": None,
            "nearest_frontier_peer_amount_multiple_mean": 1.0121,
            "nearest_frontier_peer_amount_multiple_min": 1.0121,
            "nearest_frontier_peer_amount_multiple_median": 1.0121,
            "lower_market_cap_higher_liquidity_peer_share": 0.0,
            "cutoff_lower_market_cap_share": None,
            "recurring_top5_peer_share": 1.0,
            "pressure_peer_cluster_type": "insufficient_branch_evidence",
            "top_cutoff_tickers": [{"ticker": "600123", "count": 1}],
            "top_frontier_peers": [
                {"ticker": "600120", "count": 1},
                {"ticker": "600123", "count": 1},
                {"ticker": "600125", "count": 1},
            ],
            "top_lower_market_cap_hot_peers": [],
            "top_larger_market_cap_wall_peers": [],
            "representative_cases": [
                {
                    "ticker": "003036",
                    "trade_date": "20260324",
                    "pre_truncation_rank": 304,
                    "pre_truncation_rank_gap_to_cutoff": 4,
                    "pre_truncation_avg_amount_share_of_cutoff": 0.9838,
                    "avg_amount_share_of_min_gate": avg_amount_share_of_min_gate,
                    "pre_truncation_cutoff_ticker": "600123",
                    "pre_truncation_ranking_driver": "mixed_post_filter_gap",
                }
            ],
            "mechanism_summary": "当前分支还缺足够样本解释其截断机制。",
            "pressure_cluster_summary": "当前分支还缺足够样本解释其压力同伴结构。",
            "repair_hypothesis_type": "generic_branch_repair_hypothesis",
            "repair_hypothesis_summary": "当前分支距离最近 frontier peer 的成交额差距均值约为 1.0121 倍，可继续围绕 recurring peer 结构做定向修复实验。",
        }
    ]
    assert analysis["priority_handoff_branch_experiment_queue"] == [
        {
            "task_id": "top300_boundary_micro_tuning_top300_boundary_shadow_tuning_probe",
            "priority_rank": 4,
            "priority_handoff": "top300_boundary_micro_tuning",
            "tickers": ["003036"],
            "repair_hypothesis_type": "generic_branch_repair_hypothesis",
            "prototype_type": "top300_boundary_shadow_tuning_probe",
            "prototype_readiness": "research_only",
            "uplift_to_cutoff_multiple_mean": 1.0165,
            "uplift_to_cutoff_multiple_min": 1.0165,
            "uplift_to_cutoff_multiple_max": 1.0165,
            "target_cutoff_avg_amount_20d_mean": 9250.0,
            "top300_lower_market_cap_hot_peer_count_mean": None,
            "lower_cap_hot_peer_case_share": None,
            "estimated_rank_gap_after_rebucket_mean": None,
            "selective_exemption_readiness": None,
            "selective_exemption_summary": None,
            "prototype_summary": "把 003036 保留为 top300 boundary shadow tuning 对照样本，只验证 cutoff 附近的微边界弹性，不与 far-below-cutoff 车道混用。",
            "success_signal": "若 min_rank_gap_to_cutoff 持续维持在当前近边界水平，且 nearest frontier multiple 保持在 1.0121 倍附近，再评估是否值得做微调。",
            "guardrail_summary": "仅限 top300 boundary micro-tuning 分支；不得把该样本外推成 corridor 或 competition lane 的修复规则。",
            "evaluation_summary": "当前 prototype 还缺足够 occurrence 证据，暂不进入 execution-ready 讨论。",
            "why_now": "当前分支距离最近 frontier peer 的成交额差距均值约为 1.0121 倍，可继续围绕 recurring peer 结构做定向修复实验。",
        }
    ]
    assert "硬过滤阶段" in analysis["recommendation"]


def test_analyze_btst_candidate_pool_recall_dossier_marks_legacy_unknown_shadow_snapshot(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    snapshots_root = tmp_path / "data" / "snapshots"
    snapshots_root.mkdir(parents=True, exist_ok=True)
    tradeable_pool_path = _write_json(
        reports_root / "btst_tradeable_opportunity_pool_march.json",
        {
            "reports_root": str(reports_root.resolve()),
            "rows": [
                {
                    "trade_date": "2026-03-27",
                    "ticker": "688677",
                    "first_kill_switch": "no_candidate_entry",
                    "report_dir": "paper_trading_window_a",
                    "report_mode": "live_pipeline",
                    "strict_btst_goal_case": True,
                    "next_high_return": 0.10,
                    "t_plus_2_close_return": 0.37,
                },
            ],
            "no_candidate_entry_summary": {"top_ticker_rows": [{"ticker": "688677"}]},
        },
    )
    watchlist_recall_dossier_path = _write_json(
        reports_root / "btst_watchlist_recall_dossier_latest.json",
        {
            "top_absent_from_candidate_pool_tickers": ["688677"],
            "priority_ticker_dossiers": [
                {
                    "ticker": "688677",
                    "occurrence_evidence": [{"trade_date": "2026-03-27", "recall_stage": "absent_from_candidate_pool"}],
                }
            ],
        },
    )
    _write_json(
        snapshots_root / "candidate_pool_20260327_top300.json",
        [
                {
                    "ticker": "600001",
                    "name": "A",
                    "industry_sw": "银行",
                    "market_cap": 10.0,
                    "avg_volume_20d": 165000.0,
                    "listing_date": "20200101",
                }
            ],
        )
    _write_json(
        snapshots_root / "candidate_pool_20260327_top300_shadow.json",
        {
            "selected_candidates": [],
            "shadow_candidates": [],
            "shadow_summary": {
                "pool_size": 300,
                "selected_count": 300,
                "overflow_count": 0,
                "selected_tickers": [],
                "tickers": [],
            },
        },
    )

    stock_basic = pd.DataFrame(
        [
            {"symbol": "688677", "ts_code": "688677.SH", "name": "海泰新光", "list_date": "20200101", "market": "科创板"},
        ]
    )
    daily_basic = pd.DataFrame(
        [
            {"ts_code": "688677.SH", "turnover_rate": 10.0, "circ_mv": 100000.0, "total_mv": 100000.0},
        ]
    )

    monkeypatch.setattr(recall_script, "get_all_stock_basic", lambda: stock_basic.copy())
    monkeypatch.setattr(recall_script, "get_daily_basic_batch", lambda trade_date: daily_basic.copy())
    monkeypatch.setattr(recall_script, "get_suspend_list", lambda trade_date: pd.DataFrame(columns=["ts_code"]))
    monkeypatch.setattr(recall_script, "get_limit_list", lambda trade_date: pd.DataFrame(columns=["ts_code", "limit"]))
    monkeypatch.setattr(recall_script, "get_cooled_tickers", lambda trade_date: set())
    monkeypatch.setattr(recall_script, "_get_pro", lambda: None)

    analysis = analyze_btst_candidate_pool_recall_dossier(
        tradeable_pool_path,
        watchlist_recall_dossier_path=watchlist_recall_dossier_path,
    )

    dossier = analysis["priority_ticker_dossiers"][0]
    occurrence = dossier["occurrence_evidence"][0]
    assert occurrence["blocking_stage"] == "shadow_snapshot_legacy_unknown"
    assert occurrence["candidate_pool_shadow_recall_complete"] is False
    assert occurrence["candidate_pool_shadow_recall_status"] == "legacy_unknown"
    assert occurrence["candidate_pool_shadow_snapshot_path"].endswith("candidate_pool_20260327_top300_shadow.json")
    assert dossier["dominant_blocking_stage"] == "shadow_snapshot_legacy_unknown"


def test_analyze_btst_candidate_pool_recall_dossier_uses_local_prices_fallback_for_true_absence(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    snapshots_root = tmp_path / "data" / "snapshots"
    ticker_snapshot_root = snapshots_root / "301188" / "2026-04-04"
    ticker_snapshot_root.mkdir(parents=True, exist_ok=True)
    tradeable_pool_path = _write_json(
        reports_root / "btst_tradeable_opportunity_pool_march.json",
        {
            "reports_root": str(reports_root.resolve()),
            "rows": [
                {
                    "trade_date": "2026-03-31",
                    "ticker": "301188",
                    "first_kill_switch": "no_candidate_entry",
                    "report_dir": "paper_trading_window_b",
                    "report_mode": "live_pipeline",
                    "strict_btst_goal_case": True,
                    "next_high_return": 0.20,
                    "t_plus_2_close_return": 0.38,
                },
            ],
            "no_candidate_entry_summary": {"top_ticker_rows": [{"ticker": "301188"}]},
        },
    )
    watchlist_recall_dossier_path = _write_json(
        reports_root / "btst_watchlist_recall_dossier_latest.json",
        {
            "top_absent_from_candidate_pool_tickers": ["301188"],
            "priority_ticker_dossiers": [
                {
                    "ticker": "301188",
                    "occurrence_evidence": [{"trade_date": "2026-03-31", "recall_stage": "absent_from_candidate_pool"}],
                }
            ],
        },
    )
    _write_json(
        snapshots_root / "candidate_pool_20260331_top300.json",
        [
            {
                "ticker": "600001",
                "name": "A",
                "industry_sw": "银行",
                "market_cap": 10.0,
                    "avg_volume_20d": 165000.0,
                "listing_date": "20200101",
            }
        ],
    )
    _write_json(
        snapshots_root / "candidate_pool_20260331_top300_shadow.json",
        {
            "selected_candidates": [],
            "shadow_candidates": [
                {
                    "ticker": "300762",
                    "name": "shadow",
                    "industry_sw": "军工",
                    "market_cap": 20.0,
                    "avg_volume_20d": 60000.0,
                    "listing_date": "20200101",
                    "candidate_pool_lane": "post_gate_liquidity_competition",
                    "candidate_pool_shadow_reason": "post_gate_liquidity_competition_shadow",
                }
            ],
            "shadow_summary": {
                "pool_size": 300,
                "selected_count": 300,
                "overflow_count": 10,
                "selected_cutoff_avg_volume_20d": 165000.0,
                "selected_tickers": ["300762"],
                "tickers": [{"ticker": "300762"}],
            },
        },
    )
    _write_json(
        ticker_snapshot_root / "prices.json",
        [
            {"time": "2026-03-27", "close": 17.02, "volume": 52782},
            {"time": "2026-03-30", "close": 16.60, "volume": 52105},
            {"time": "2026-03-31", "close": 17.04, "volume": 52803},
        ],
    )

    stock_basic = pd.DataFrame(
        [
            {"symbol": "301188", "ts_code": "301188.SZ", "name": "力诺药包", "list_date": "20200101", "market": "创业板"},
        ]
    )
    daily_basic = pd.DataFrame(
        [
            {"ts_code": "301188.SZ", "turnover_rate": 10.0, "circ_mv": 100000.0, "total_mv": 100000.0},
        ]
    )

    monkeypatch.setattr(recall_script, "get_all_stock_basic", lambda: stock_basic.copy())
    monkeypatch.setattr(recall_script, "get_daily_basic_batch", lambda trade_date: daily_basic.copy())
    monkeypatch.setattr(recall_script, "get_suspend_list", lambda trade_date: pd.DataFrame(columns=["ts_code"]))
    monkeypatch.setattr(recall_script, "get_limit_list", lambda trade_date: pd.DataFrame(columns=["ts_code", "limit"]))
    monkeypatch.setattr(recall_script, "get_cooled_tickers", lambda trade_date: set())
    monkeypatch.setattr(recall_script, "_get_pro", lambda: None)

    analysis = analyze_btst_candidate_pool_recall_dossier(
        tradeable_pool_path,
        watchlist_recall_dossier_path=watchlist_recall_dossier_path,
    )

    occurrence = analysis["priority_ticker_dossiers"][0]["occurrence_evidence"][0]
    assert occurrence["blocking_stage"] == "candidate_pool_truncated_after_filters"
    assert occurrence["avg_amount_20d_source"] == "local_snapshot_prices"
    assert occurrence["local_prices_snapshot_path"].endswith("data/snapshots/301188/2026-04-04/prices.json")
    assert occurrence["candidate_pool_shadow_recall_status"] == "computed_legacy"
    assert occurrence["candidate_pool_selected_cutoff_avg_volume_20d"] == 165000.0
    assert occurrence["candidate_pool_shadow_selected_cutoff_avg_volume_20d"] == 165000.0
    assert occurrence["avg_amount_20d"] == 8876.8525
    assert occurrence["local_avg_amount_share_of_cutoff"] == 0.0538
    assert analysis["truncation_frontier_summary"]["frontier_verdict"] == "far_below_cutoff_not_boundary"
    assert analysis["truncation_frontier_summary"]["avg_amount_share_of_cutoff_mean"] == 0.0538
    assert analysis["priority_ticker_dossiers"][0]["truncation_liquidity_profile"]["priority_handoff"] == "layer_a_liquidity_corridor"


def test_analyze_btst_candidate_pool_recall_dossier_uses_tradeable_pool_stock_basic_fallback(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "data" / "reports"
    snapshots_root = tmp_path / "data" / "snapshots"
    ticker_snapshot_root = snapshots_root / "301188" / "2026-04-04"
    ticker_snapshot_root.mkdir(parents=True, exist_ok=True)
    tradeable_pool_path = _write_json(
        reports_root / "btst_tradeable_opportunity_pool_march.json",
        {
            "reports_root": str(reports_root.resolve()),
            "rows": [
                {
                    "trade_date": "2026-03-31",
                    "ticker": "301188",
                    "ts_code": "301188.SZ",
                    "name": "力诺药包",
                    "list_date": "2021-11-11",
                    "market": "创业板",
                    "first_kill_switch": "no_candidate_entry",
                    "report_dir": "paper_trading_window_b",
                    "report_mode": "live_pipeline",
                    "strict_btst_goal_case": True,
                    "next_high_return": 0.20,
                    "t_plus_2_close_return": 0.38,
                },
            ],
            "no_candidate_entry_summary": {"top_ticker_rows": [{"ticker": "301188"}]},
        },
    )
    watchlist_recall_dossier_path = _write_json(
        reports_root / "btst_watchlist_recall_dossier_latest.json",
        {
            "top_absent_from_candidate_pool_tickers": ["301188"],
            "priority_ticker_dossiers": [
                {
                    "ticker": "301188",
                    "occurrence_evidence": [{"trade_date": "2026-03-31", "recall_stage": "absent_from_candidate_pool"}],
                }
            ],
        },
    )
    _write_json(
        snapshots_root / "candidate_pool_20260331_top300.json",
        [
                {
                    "ticker": "600001",
                    "name": "A",
                    "industry_sw": "银行",
                    "market_cap": 10.0,
                    "avg_volume_20d": 165000.0,
                    "listing_date": "20200101",
                }
            ],
        )
    _write_json(
        snapshots_root / "candidate_pool_20260331_top300_shadow.json",
        {
            "selected_candidates": [],
            "shadow_candidates": [],
            "shadow_summary": {
                "pool_size": 300,
                "selected_count": 300,
                "overflow_count": 10,
                    "selected_cutoff_avg_volume_20d": 165000.0,
                    "shadow_recall_complete": True,
                    "shadow_recall_status": "computed",
                    "selected_tickers": [],
                "tickers": [],
            },
        },
    )
    _write_json(
        ticker_snapshot_root / "prices.json",
        [
            {"time": "2026-03-27", "close": 17.02, "volume": 52782},
            {"time": "2026-03-30", "close": 16.60, "volume": 52105},
            {"time": "2026-03-31", "close": 17.04, "volume": 52803},
        ],
    )

    monkeypatch.setattr(recall_script, "get_all_stock_basic", lambda: pd.DataFrame())
    monkeypatch.setattr(recall_script, "get_daily_basic_batch", lambda trade_date: None)
    monkeypatch.setattr(recall_script, "get_suspend_list", lambda trade_date: pd.DataFrame(columns=["ts_code"]))
    monkeypatch.setattr(recall_script, "get_limit_list", lambda trade_date: pd.DataFrame(columns=["ts_code", "limit"]))
    monkeypatch.setattr(recall_script, "get_cooled_tickers", lambda trade_date: set())
    monkeypatch.setattr(recall_script, "_get_pro", lambda: None)

    analysis = analyze_btst_candidate_pool_recall_dossier(
        tradeable_pool_path,
        watchlist_recall_dossier_path=watchlist_recall_dossier_path,
    )

    occurrence = analysis["priority_ticker_dossiers"][0]["occurrence_evidence"][0]
    assert occurrence["blocking_stage"] == "candidate_pool_truncated_after_filters"
    assert occurrence["avg_amount_20d_source"] == "local_snapshot_prices"
    assert occurrence["avg_amount_20d"] == 8876.8525
    assert occurrence["candidate_pool_selected_cutoff_avg_volume_20d"] == 165000.0
    assert occurrence["candidate_pool_shadow_recall_status"] == "computed"
    assert analysis["truncation_frontier_summary"]["frontier_verdict"] == "far_below_cutoff_not_boundary"
    assert analysis["priority_ticker_dossiers"][0]["truncation_liquidity_profile"]["priority_handoff"] == "layer_a_liquidity_corridor"


def test_build_priority_handoff_branch_mechanisms_adds_pressure_peer_structure_summary() -> None:
    priority_ticker_dossiers = [
        {
            "ticker": "AAA001",
            "truncation_liquidity_profile": {"priority_handoff": "layer_a_liquidity_corridor"},
            "occurrence_evidence": [
                {
                    "blocking_stage": "candidate_pool_truncated_after_filters",
                    "trade_date": "20260323",
                    "ticker": "AAA001",
                    "avg_amount_20d": 100.0,
                    "market_cap": 10.0,
                    "pre_truncation_cutoff_avg_amount_20d": 500.0,
                    "pre_truncation_cutoff_market_cap": 40.0,
                    "pre_truncation_avg_amount_share_of_cutoff": 0.2,
                    "pre_truncation_avg_amount_gap_to_cutoff": 400.0,
                    "avg_amount_share_of_min_gate": 4.0,
                    "pre_truncation_cutoff_avg_amount_share_of_min_gate": 20.0,
                    "pre_truncation_rank_gap_to_cutoff": 500,
                    "top300_lower_market_cap_hot_peer_count": 0,
                    "estimated_rank_gap_after_rebucket": 500,
                    "pre_truncation_frontier_window": [
                        {"ticker": "P1", "avg_amount_20d": 500.0, "market_cap": 80.0},
                        {"ticker": "P2", "avg_amount_20d": 480.0, "market_cap": 70.0},
                    ],
                },
                {
                    "blocking_stage": "candidate_pool_truncated_after_filters",
                    "trade_date": "20260324",
                    "ticker": "AAA001",
                    "avg_amount_20d": 100.0,
                    "market_cap": 10.0,
                    "pre_truncation_cutoff_avg_amount_20d": 520.0,
                    "pre_truncation_cutoff_market_cap": 42.0,
                    "pre_truncation_avg_amount_share_of_cutoff": 0.2,
                    "pre_truncation_avg_amount_gap_to_cutoff": 420.0,
                    "avg_amount_share_of_min_gate": 4.2,
                    "pre_truncation_cutoff_avg_amount_share_of_min_gate": 21.0,
                    "pre_truncation_rank_gap_to_cutoff": 520,
                    "top300_lower_market_cap_hot_peer_count": 0,
                    "estimated_rank_gap_after_rebucket": 520,
                    "pre_truncation_frontier_window": [
                        {"ticker": "P1", "avg_amount_20d": 520.0, "market_cap": 85.0},
                        {"ticker": "P3", "avg_amount_20d": 510.0, "market_cap": 90.0},
                    ],
                },
                {
                    "blocking_stage": "candidate_pool_truncated_after_filters",
                    "trade_date": "20260325",
                    "ticker": "AAA001",
                    "avg_amount_20d": 100.0,
                    "market_cap": 10.0,
                    "pre_truncation_cutoff_avg_amount_20d": 510.0,
                    "pre_truncation_cutoff_market_cap": 38.0,
                    "pre_truncation_avg_amount_share_of_cutoff": 0.2,
                    "pre_truncation_avg_amount_gap_to_cutoff": 410.0,
                    "avg_amount_share_of_min_gate": 4.1,
                    "pre_truncation_cutoff_avg_amount_share_of_min_gate": 20.5,
                    "pre_truncation_rank_gap_to_cutoff": 510,
                    "top300_lower_market_cap_hot_peer_count": 0,
                    "estimated_rank_gap_after_rebucket": 510,
                    "pre_truncation_frontier_window": [
                        {"ticker": "P2", "avg_amount_20d": 495.0, "market_cap": 82.0},
                        {"ticker": "P3", "avg_amount_20d": 505.0, "market_cap": 87.0},
                    ],
                },
            ],
        },
        {
            "ticker": "BBB001",
            "truncation_liquidity_profile": {"priority_handoff": "post_gate_liquidity_competition"},
            "occurrence_evidence": [
                {
                    "blocking_stage": "candidate_pool_truncated_after_filters",
                    "trade_date": "20260323",
                    "ticker": "BBB001",
                    "avg_amount_20d": 100.0,
                    "market_cap": 50.0,
                    "pre_truncation_cutoff_avg_amount_20d": 200.0,
                    "pre_truncation_cutoff_market_cap": 120.0,
                    "pre_truncation_avg_amount_share_of_cutoff": 0.5,
                    "pre_truncation_avg_amount_gap_to_cutoff": 100.0,
                    "avg_amount_share_of_min_gate": 15.0,
                    "pre_truncation_cutoff_avg_amount_share_of_min_gate": 30.0,
                    "pre_truncation_rank_gap_to_cutoff": 320,
                    "top300_lower_market_cap_hot_peer_count": 1,
                    "estimated_rank_gap_after_rebucket": 319,
                    "pre_truncation_frontier_window": [
                        {"ticker": "Q1", "avg_amount_20d": 220.0, "market_cap": 45.0},
                        {"ticker": "Q2", "avg_amount_20d": 210.0, "market_cap": 80.0},
                    ],
                },
                {
                    "blocking_stage": "candidate_pool_truncated_after_filters",
                    "trade_date": "20260324",
                    "ticker": "BBB001",
                    "avg_amount_20d": 100.0,
                    "market_cap": 50.0,
                    "pre_truncation_cutoff_avg_amount_20d": 222.2222,
                    "pre_truncation_cutoff_market_cap": 130.0,
                    "pre_truncation_avg_amount_share_of_cutoff": 0.45,
                    "pre_truncation_avg_amount_gap_to_cutoff": 120.0,
                    "avg_amount_share_of_min_gate": 14.5,
                    "pre_truncation_cutoff_avg_amount_share_of_min_gate": 31.0,
                    "pre_truncation_rank_gap_to_cutoff": 340,
                    "top300_lower_market_cap_hot_peer_count": 2,
                    "estimated_rank_gap_after_rebucket": 338,
                    "pre_truncation_frontier_window": [
                        {"ticker": "Q1", "avg_amount_20d": 230.0, "market_cap": 48.0},
                        {"ticker": "Q3", "avg_amount_20d": 205.0, "market_cap": 42.0},
                    ],
                },
                {
                    "blocking_stage": "candidate_pool_truncated_after_filters",
                    "trade_date": "20260325",
                    "ticker": "BBB001",
                    "avg_amount_20d": 100.0,
                    "market_cap": 50.0,
                    "pre_truncation_cutoff_avg_amount_20d": 208.3333,
                    "pre_truncation_cutoff_market_cap": 125.0,
                    "pre_truncation_avg_amount_share_of_cutoff": 0.48,
                    "pre_truncation_avg_amount_gap_to_cutoff": 110.0,
                    "avg_amount_share_of_min_gate": 14.7,
                    "pre_truncation_cutoff_avg_amount_share_of_min_gate": 30.5,
                    "pre_truncation_rank_gap_to_cutoff": 330,
                    "top300_lower_market_cap_hot_peer_count": 1,
                    "estimated_rank_gap_after_rebucket": 329,
                    "pre_truncation_frontier_window": [
                        {"ticker": "Q2", "avg_amount_20d": 215.0, "market_cap": 78.0},
                        {"ticker": "Q3", "avg_amount_20d": 208.0, "market_cap": 44.0},
                    ],
                },
            ],
        },
    ]

    mechanisms = recall_script._build_priority_handoff_branch_mechanisms(priority_ticker_dossiers)
    by_handoff = {row["priority_handoff"]: row for row in mechanisms}
    experiment_queue = recall_script._build_priority_handoff_branch_experiment_queue(mechanisms, priority_ticker_dossiers)
    queue_by_handoff = {row["priority_handoff"]: row for row in experiment_queue}

    corridor = by_handoff["layer_a_liquidity_corridor"]
    assert corridor["pressure_peer_cluster_type"] == "broad_large_cap_liquidity_wall"
    assert corridor["peer_avg_amount_multiple_mean"] == 5.0167
    assert corridor["peer_market_cap_multiple_mean"] == 8.2333
    assert corridor["nearest_frontier_peer_amount_multiple_mean"] == 4.95
    assert corridor["nearest_frontier_peer_amount_multiple_min"] == 4.8
    assert corridor["nearest_frontier_peer_amount_multiple_median"] == 4.95
    assert corridor["lower_market_cap_higher_liquidity_peer_share"] == 0.0
    assert corridor["cutoff_lower_market_cap_share"] == 0.0
    assert corridor["recurring_top5_peer_share"] == 1.0
    assert corridor["top_lower_market_cap_hot_peers"] == []
    assert corridor["top_larger_market_cap_wall_peers"] == [
        {"ticker": "P1", "count": 2},
        {"ticker": "P2", "count": 2},
        {"ticker": "P3", "count": 2},
    ]
    assert "一整层更大更活跃的 liquidity wall" in corridor["pressure_cluster_summary"]
    assert corridor["repair_hypothesis_type"] == "raise_base_liquidity_before_cutoff_tuning"
    assert "把 20 日成交额抬到当前的 4.95 倍" in corridor["repair_hypothesis_summary"]
    assert queue_by_handoff["layer_a_liquidity_corridor"]["prototype_type"] == "upstream_base_liquidity_uplift_probe"
    assert queue_by_handoff["layer_a_liquidity_corridor"]["prototype_readiness"] == "shadow_ready_large_gap"
    assert queue_by_handoff["layer_a_liquidity_corridor"]["uplift_to_cutoff_multiple_mean"] == 5.0
    assert queue_by_handoff["layer_a_liquidity_corridor"]["uplift_to_cutoff_multiple_min"] == 5.0
    assert queue_by_handoff["layer_a_liquidity_corridor"]["uplift_to_cutoff_multiple_max"] == 5.0
    assert queue_by_handoff["layer_a_liquidity_corridor"]["target_cutoff_avg_amount_20d_mean"] == 510.0
    assert queue_by_handoff["layer_a_liquidity_corridor"]["top300_lower_market_cap_hot_peer_count_mean"] == 0.0
    assert queue_by_handoff["layer_a_liquidity_corridor"]["lower_cap_hot_peer_case_share"] == 0.0
    assert queue_by_handoff["layer_a_liquidity_corridor"]["estimated_rank_gap_after_rebucket_mean"] == 510.0
    assert "AAA001 收敛到 upstream base-liquidity uplift shadow probe" in queue_by_handoff["layer_a_liquidity_corridor"]["prototype_summary"]
    assert "larger-cap liquidity wall" in queue_by_handoff["layer_a_liquidity_corridor"]["guardrail_summary"]
    assert "平均需要把 20 日成交额抬到当前的 5.0 倍" in queue_by_handoff["layer_a_liquidity_corridor"]["evaluation_summary"]

    competition = by_handoff["post_gate_liquidity_competition"]
    assert competition["pressure_peer_cluster_type"] == "mixed_size_hot_peer_competition"
    assert competition["peer_avg_amount_multiple_mean"] == 2.1467
    assert competition["peer_market_cap_multiple_mean"] == 1.1233
    assert competition["nearest_frontier_peer_amount_multiple_mean"] == 2.0767
    assert competition["nearest_frontier_peer_amount_multiple_min"] == 2.05
    assert competition["nearest_frontier_peer_amount_multiple_median"] == 2.08
    assert competition["lower_market_cap_higher_liquidity_peer_share"] == 0.6667
    assert competition["cutoff_lower_market_cap_share"] == 0.0
    assert competition["recurring_top5_peer_share"] == 1.0
    assert competition["top_lower_market_cap_hot_peers"] == [
        {"ticker": "Q1", "count": 2},
        {"ticker": "Q3", "count": 2},
    ]
    assert competition["top_larger_market_cap_wall_peers"] == [{"ticker": "Q2", "count": 2}]
    assert "更小市值下仍具备更高流动性" in competition["pressure_cluster_summary"]
    assert competition["repair_hypothesis_type"] == "rebucket_mixed_size_hot_competitors"
    assert "Q1', 'Q3" in competition["repair_hypothesis_summary"]
    assert queue_by_handoff["post_gate_liquidity_competition"]["prototype_type"] == "post_gate_competition_rebucket_probe"
    assert queue_by_handoff["post_gate_liquidity_competition"]["prototype_readiness"] == "shadow_ready_rebucket_signal"
    assert queue_by_handoff["post_gate_liquidity_competition"]["uplift_to_cutoff_multiple_mean"] == 2.1018
    assert queue_by_handoff["post_gate_liquidity_competition"]["uplift_to_cutoff_multiple_min"] == 2.0
    assert queue_by_handoff["post_gate_liquidity_competition"]["uplift_to_cutoff_multiple_max"] == 2.2222
    assert queue_by_handoff["post_gate_liquidity_competition"]["target_cutoff_avg_amount_20d_mean"] == 210.1852
    assert queue_by_handoff["post_gate_liquidity_competition"]["top300_lower_market_cap_hot_peer_count_mean"] == 1.3333
    assert queue_by_handoff["post_gate_liquidity_competition"]["lower_cap_hot_peer_case_share"] == 1.0
    assert queue_by_handoff["post_gate_liquidity_competition"]["estimated_rank_gap_after_rebucket_mean"] == 328.6667
    assert queue_by_handoff["post_gate_liquidity_competition"]["selective_exemption_readiness"] == "shadow_only_large_remaining_rank_gap"
    assert "只保留 shadow probe，不进入 selective exemption review" in queue_by_handoff["post_gate_liquidity_competition"]["selective_exemption_summary"]
    assert "BBB001 放入 post-gate competition rebucket shadow probe" in queue_by_handoff["post_gate_liquidity_competition"]["prototype_summary"]
    assert "不得直接下调 MIN_AVG_AMOUNT_20D" in queue_by_handoff["post_gate_liquidity_competition"]["guardrail_summary"]
    assert "平均约有 1.3333 个更小市值高流动性 peer 挡在前面" in queue_by_handoff["post_gate_liquidity_competition"]["evaluation_summary"]
    assert "rebucket 后剩余 rank gap 仍高于 300" in queue_by_handoff["post_gate_liquidity_competition"]["evaluation_summary"]


def test_describe_branch_experiment_prototype_marks_low_gate_corridor_focus_split():
    prototype_type, prototype_summary, success_signal, guardrail_summary = recall_script._describe_branch_experiment_prototype(
        {
            "priority_handoff": "layer_a_liquidity_corridor",
            "tickers": ["301188"],
            "avg_amount_share_of_cutoff_mean": 0.0709,
            "avg_amount_share_of_min_gate_mean": 2.3434,
            "nearest_frontier_peer_amount_multiple_mean": 10.5,
            "nearest_frontier_peer_amount_multiple_min": 3.8,
            "pressure_peer_cluster_type": "broad_large_cap_liquidity_wall",
            "top_lower_market_cap_hot_peers": [],
        }
    )

    assert prototype_type == "upstream_base_liquidity_uplift_probe"
    assert "tighter cutoff split" in prototype_summary
    assert "0.075" in prototype_summary
    assert "avg_amount/cutoff 仍不高于 0.075" in guardrail_summary
    assert "avg_amount_share_of_cutoff 明显高于当前 0.0709" in success_signal


def test_recall_recommendation_prioritizes_branch_split_before_generic_far_below_summary() -> None:
    recommendation = recall_script._build_recommendation(
        "candidate_pool_truncated_after_filters",
        top_stage_tickers={"candidate_pool_truncated_after_filters": ["688796", "688383", "301292"]},
        truncation_frontier_summary={
            "frontier_verdict": "far_below_cutoff_not_boundary",
            "closest_distinct_ticker_cases": [
                {
                    "ticker": "301292",
                    "trade_date": "20260331",
                    "pre_truncation_rank": 609,
                    "pre_truncation_rank_gap_to_cutoff": 309,
                    "pre_truncation_avg_amount_share_of_cutoff": 0.5611,
                }
            ],
        },
        focus_liquidity_profile_summary={
            "primary_focus_tickers": [
                {"ticker": "688796", "dominant_liquidity_gap_mode": "barely_above_gate_and_far_below_cutoff", "priority_handoff": "layer_a_liquidity_corridor"},
                {"ticker": "301292", "dominant_liquidity_gap_mode": "well_above_gate_but_far_below_cutoff", "priority_handoff": "post_gate_liquidity_competition"},
            ]
        },
        priority_handoff_branch_diagnoses=[
            {"priority_handoff": "layer_a_liquidity_corridor", "tickers": ["688796", "688383"], "diagnosis_summary": "688796/688383 更像 Layer A 流动性走廊样本。"},
            {"priority_handoff": "post_gate_liquidity_competition", "tickers": ["301292"], "diagnosis_summary": "301292 已经转成 post-gate competition。"},
        ],
        priority_handoff_branch_mechanisms=[
            {
                "mechanism_summary": "corridor 样本主要被更大更活跃的 liquidity wall 压制。",
                "pressure_cluster_summary": "压力主要来自 larger-cap wall。",
                "repair_hypothesis_summary": "优先修复 upstream base liquidity。",
            }
        ],
        priority_handoff_branch_experiment_queue=[
            {
                "prototype_summary": "先做 corridor uplift shadow probe。",
                "evaluation_summary": "当前先不讨论 pool-size 放宽。",
                "guardrail_summary": "不得把 competition lane 混入 corridor。",
            }
        ],
    )

    assert "已拆成分支车道" in recommendation
    assert "('layer_a_liquidity_corridor', ['688796', '688383'])" in recommendation
    assert "('post_gate_liquidity_competition', ['301292'])" in recommendation
    assert "最近的 distinct ticker 也只有 301292" not in recommendation


def test_recall_next_actions_prioritize_branch_split_before_generic_far_below_summary() -> None:
    actions = recall_script._build_next_actions(
        "candidate_pool_truncated_after_filters",
        top_stage_tickers={"candidate_pool_truncated_after_filters": ["688796", "688383", "301292"]},
        truncation_frontier_summary={
            "frontier_verdict": "far_below_cutoff_not_boundary",
            "dominant_ranking_driver": "avg_amount_20d_gap_dominant",
            "dominant_liquidity_gap_mode": "barely_above_gate_and_far_below_cutoff",
            "closest_distinct_ticker_cases": [
                {
                    "ticker": "301292",
                    "pre_truncation_rank_gap_to_cutoff": 309,
                    "pre_truncation_avg_amount_share_of_cutoff": 0.5611,
                }
            ],
        },
        focus_liquidity_profile_summary={
            "primary_focus_tickers": [
                {"ticker": "688796", "priority_handoff": "layer_a_liquidity_corridor"},
                {"ticker": "301292", "priority_handoff": "post_gate_liquidity_competition"},
            ]
        },
        priority_handoff_branch_diagnoses=[
            {
                "priority_handoff": "layer_a_liquidity_corridor",
                "tickers": ["688796", "688383"],
                "next_step": "优先把 corridor backlog 下钻到 gate 与 cutoff 之间的 liquidity corridor。",
            },
            {
                "priority_handoff": "post_gate_liquidity_competition",
                "tickers": ["301292"],
                "next_step": "优先回查 post-gate competition composition。",
            },
        ],
        priority_handoff_branch_mechanisms=[
            {
                "mechanism_summary": "corridor 样本主要被更大更活跃的 liquidity wall 压制。",
                "pressure_cluster_summary": "压力主要来自 larger-cap wall。",
                "repair_hypothesis_summary": "优先修复 upstream base liquidity。",
            }
        ],
        priority_handoff_branch_experiment_queue=[
            {
                "prototype_summary": "先做 corridor uplift shadow probe。",
                "evaluation_summary": "当前先不讨论 pool-size 放宽。",
                "success_signal": "先看 nearest frontier multiple 是否收敛。",
            }
        ],
    )

    assert actions[0].startswith("按焦点 ticker 画像拆分后续 handoff")
    assert actions[1] == "优先把 corridor backlog 下钻到 gate 与 cutoff 之间的 liquidity corridor。"
    assert actions[2] == "优先回查 post-gate competition composition。"
    assert not any("不要把 ['688796', '688383', '301292'] 直接当作 top300 边界微调问题" in action for action in actions)


def test_analyze_btst_candidate_pool_recall_dossier_reconstructs_pre_truncation_rank(monkeypatch, tmp_path: Path) -> None:
    avg_amount_share_of_min_gate = round(7000.0 / float(recall_script.MIN_AVG_AMOUNT_20D), 4)
    cutoff_avg_amount_share_of_min_gate = round(8000.0 / float(recall_script.MIN_AVG_AMOUNT_20D), 4)
    reports_root = tmp_path / "data" / "reports"
    tradeable_pool_path = _write_json(
        reports_root / "btst_tradeable_opportunity_pool_march.json",
        {
            "reports_root": str(reports_root.resolve()),
            "rows": [
                {
                    "trade_date": "2026-03-24",
                    "ticker": "003036",
                    "first_kill_switch": "no_candidate_entry",
                    "report_dir": "paper_trading_window_b",
                    "report_mode": "live_pipeline",
                    "strict_btst_goal_case": True,
                    "next_high_return": 0.07,
                    "t_plus_2_close_return": 0.06,
                },
            ],
            "no_candidate_entry_summary": {"top_ticker_rows": [{"ticker": "003036"}]},
        },
    )
    watchlist_recall_dossier_path = _write_json(
        reports_root / "btst_watchlist_recall_dossier_latest.json",
        {
            "top_absent_from_candidate_pool_tickers": ["003036"],
            "priority_ticker_dossiers": [
                {
                    "ticker": "003036",
                    "occurrence_evidence": [{"trade_date": "2026-03-24", "recall_stage": "absent_from_candidate_pool"}],
                }
            ],
        },
    )

    stock_basic = pd.DataFrame(
        [
            {"symbol": "600001", "ts_code": "600001.SH", "name": "A", "list_date": "20200101", "market": "主板"},
            {"symbol": "600002", "ts_code": "600002.SH", "name": "B", "list_date": "20200101", "market": "主板"},
            {"symbol": "600003", "ts_code": "600003.SH", "name": "C", "list_date": "20200101", "market": "主板"},
            {"symbol": "003036", "ts_code": "003036.SZ", "name": "D", "list_date": "20200101", "market": "主板"},
        ]
    )
    daily_basic = pd.DataFrame(
        [
            {"ts_code": "600001.SH", "turnover_rate": 10.0, "circ_mv": 100000.0, "total_mv": 100000.0},
            {"ts_code": "600002.SH", "turnover_rate": 10.0, "circ_mv": 90000.0, "total_mv": 90000.0},
            {"ts_code": "600003.SH", "turnover_rate": 10.0, "circ_mv": 80000.0, "total_mv": 80000.0},
            {"ts_code": "003036.SZ", "turnover_rate": 10.0, "circ_mv": 70000.0, "total_mv": 70000.0},
        ]
    )

    monkeypatch.setattr(recall_script, "MAX_CANDIDATE_POOL_SIZE", 3)
    monkeypatch.setattr(recall_script, "get_all_stock_basic", lambda: stock_basic.copy())
    monkeypatch.setattr(recall_script, "get_daily_basic_batch", lambda trade_date: daily_basic.copy())
    monkeypatch.setattr(recall_script, "get_suspend_list", lambda trade_date: pd.DataFrame(columns=["ts_code"]))
    monkeypatch.setattr(recall_script, "get_limit_list", lambda trade_date: pd.DataFrame(columns=["ts_code", "limit"]))
    monkeypatch.setattr(recall_script, "get_cooled_tickers", lambda trade_date: set())
    monkeypatch.setattr(recall_script, "_get_pro", lambda: object())
    monkeypatch.setattr(
        recall_script,
        "_get_avg_amount_20d_map",
        lambda pro, ts_codes, trade_date: {
            "600001.SH": 10000.0,
            "600002.SH": 9000.0,
            "600003.SH": 8000.0,
            "003036.SZ": 7000.0,
        },
    )
    monkeypatch.setattr(recall_script, "_get_avg_amount_20d", lambda pro, ts_code, trade_date: {"003036.SZ": 7000.0}.get(ts_code, 0.0))

    analysis = analyze_btst_candidate_pool_recall_dossier(
        tradeable_pool_path,
        watchlist_recall_dossier_path=watchlist_recall_dossier_path,
    )

    dossier = analysis["priority_ticker_dossiers"][0]
    occurrence = dossier["occurrence_evidence"][0]
    assert occurrence["blocking_stage"] == "candidate_pool_truncated_after_filters"
    assert occurrence["pre_truncation_rank"] == 4
    assert occurrence["pre_truncation_cutoff_rank"] == 3
    assert occurrence["pre_truncation_rank_gap_to_cutoff"] == 1
    assert occurrence["pre_truncation_cutoff_ticker"] == "600003"
    assert occurrence["pre_truncation_avg_amount_gap_to_cutoff"] == 1000.0
    assert occurrence["pre_truncation_avg_amount_share_of_cutoff"] == 0.875
    assert occurrence["pre_truncation_market_cap_gap_to_cutoff"] == 1.0
    assert occurrence["pre_truncation_market_cap_share_of_cutoff"] == 0.875
    assert occurrence["pre_truncation_ranking_driver"] == "avg_amount_20d_gap"
    assert occurrence["avg_amount_share_of_min_gate"] == avg_amount_share_of_min_gate
    assert occurrence["pre_truncation_cutoff_avg_amount_share_of_min_gate"] == cutoff_avg_amount_share_of_min_gate
    assert occurrence["pre_truncation_liquidity_gap_mode"] == "near_cutoff_liquidity_gap"
    assert occurrence["market_cap"] == 7.0
    assert [row["ticker"] for row in occurrence["pre_truncation_frontier_window"]] == ["600001", "600002", "600003", "003036"]
    assert dossier["closest_pre_truncation_gap"] == 1
    assert dossier["truncation_ranking_summary"] == {
        "truncation_case_count": 1,
        "dominant_ranking_driver": "avg_amount_20d_gap",
        "ranking_driver_counts": {"avg_amount_20d_gap": 1},
        "dominant_liquidity_gap_mode": "near_cutoff_liquidity_gap",
        "liquidity_gap_mode_counts": {"near_cutoff_liquidity_gap": 1},
        "avg_rank_gap_to_cutoff": 1.0,
        "min_rank_gap_to_cutoff": 1,
        "avg_amount_share_of_cutoff_mean": 0.875,
        "avg_amount_share_of_cutoff_min": 0.875,
        "avg_amount_share_of_cutoff_max": 0.875,
        "avg_amount_share_of_min_gate_mean": avg_amount_share_of_min_gate,
        "avg_amount_share_of_min_gate_min": avg_amount_share_of_min_gate,
        "avg_amount_share_of_min_gate_max": avg_amount_share_of_min_gate,
        "cutoff_avg_amount_share_of_min_gate_mean": cutoff_avg_amount_share_of_min_gate,
        "cutoff_avg_amount_share_of_min_gate_min": cutoff_avg_amount_share_of_min_gate,
        "cutoff_avg_amount_share_of_min_gate_max": cutoff_avg_amount_share_of_min_gate,
        "closest_case": {
            "trade_date": "20260324",
            "pre_truncation_rank": 4,
            "pre_truncation_rank_gap_to_cutoff": 1,
            "pre_truncation_avg_amount_share_of_cutoff": 0.875,
            "pre_truncation_ranking_driver": "avg_amount_20d_gap",
            "avg_amount_share_of_min_gate": avg_amount_share_of_min_gate,
            "pre_truncation_liquidity_gap_mode": "near_cutoff_liquidity_gap",
        },
    }
    assert dossier["truncation_liquidity_profile"] == {
        "ticker": "003036",
        "truncation_case_count": 1,
        "dominant_liquidity_gap_mode": "near_cutoff_liquidity_gap",
        "dominant_ranking_driver": "avg_amount_20d_gap",
        "avg_amount_share_of_cutoff_mean": 0.875,
        "avg_amount_share_of_min_gate_mean": avg_amount_share_of_min_gate,
        "cutoff_avg_amount_share_of_min_gate_mean": cutoff_avg_amount_share_of_min_gate,
        "min_rank_gap_to_cutoff": 1,
        "avg_rank_gap_to_cutoff": 1.0,
        "priority_handoff": "top300_boundary_micro_tuning",
        "profile_summary": "这只票更接近 cutoff 微边界，可保留为 top300 boundary 微调对照样本。",
        "closest_case": {
            "trade_date": "20260324",
            "pre_truncation_rank": 4,
            "pre_truncation_rank_gap_to_cutoff": 1,
            "pre_truncation_avg_amount_share_of_cutoff": 0.875,
            "pre_truncation_ranking_driver": "avg_amount_20d_gap",
            "avg_amount_share_of_min_gate": avg_amount_share_of_min_gate,
            "pre_truncation_liquidity_gap_mode": "near_cutoff_liquidity_gap",
        },
    }
    assert analysis["truncation_frontier_summary"] == {
        "observed_case_count": 1,
        "rank_observed_case_count": 1,
        "frontier_verdict": "near_cutoff_boundary",
        "closest_cases": [
            {
                "ticker": "003036",
                "trade_date": "20260324",
                "pre_truncation_rank": 4,
                "pre_truncation_cutoff_rank": 3,
                "pre_truncation_rank_gap_to_cutoff": 1,
                "pre_truncation_total_candidates": 4,
                "pre_truncation_cutoff_ticker": "600003",
                "pre_truncation_cutoff_avg_amount_20d": 8000.0,
                "pre_truncation_cutoff_avg_amount_share_of_min_gate": cutoff_avg_amount_share_of_min_gate,
                "pre_truncation_cutoff_market_cap": 8.0,
                "pre_truncation_avg_amount_gap_to_cutoff": 1000.0,
                "pre_truncation_avg_amount_share_of_cutoff": 0.875,
                "avg_amount_share_of_min_gate": avg_amount_share_of_min_gate,
                "pre_truncation_market_cap_gap_to_cutoff": 1.0,
                "pre_truncation_market_cap_share_of_cutoff": 0.875,
                "pre_truncation_ranking_driver": "avg_amount_20d_gap",
                "pre_truncation_liquidity_gap_mode": "near_cutoff_liquidity_gap",
                "avg_amount_20d": 7000.0,
                "market_cap": 7.0,
                "pre_truncation_frontier_window": [
                    {"rank": 1, "ticker": "600001", "ts_code": "600001.SH", "name": "A", "avg_amount_20d": 10000.0, "market_cap": 10.0},
                    {"rank": 2, "ticker": "600002", "ts_code": "600002.SH", "name": "B", "avg_amount_20d": 9000.0, "market_cap": 9.0},
                    {"rank": 3, "ticker": "600003", "ts_code": "600003.SH", "name": "C", "avg_amount_20d": 8000.0, "market_cap": 8.0},
                    {"rank": 4, "ticker": "003036", "ts_code": "003036.SZ", "name": "D", "avg_amount_20d": 7000.0, "market_cap": 7.0},
                ],
            }
        ],
        "closest_distinct_ticker_cases": [
            {
                "ticker": "003036",
                "trade_date": "20260324",
                "pre_truncation_rank": 4,
                "pre_truncation_cutoff_rank": 3,
                "pre_truncation_rank_gap_to_cutoff": 1,
                "pre_truncation_total_candidates": 4,
                "pre_truncation_cutoff_ticker": "600003",
                "pre_truncation_cutoff_avg_amount_20d": 8000.0,
                "pre_truncation_cutoff_avg_amount_share_of_min_gate": cutoff_avg_amount_share_of_min_gate,
                "pre_truncation_cutoff_market_cap": 8.0,
                "pre_truncation_avg_amount_gap_to_cutoff": 1000.0,
                "pre_truncation_avg_amount_share_of_cutoff": 0.875,
                "avg_amount_share_of_min_gate": avg_amount_share_of_min_gate,
                "pre_truncation_market_cap_gap_to_cutoff": 1.0,
                "pre_truncation_market_cap_share_of_cutoff": 0.875,
                "pre_truncation_ranking_driver": "avg_amount_20d_gap",
                "pre_truncation_liquidity_gap_mode": "near_cutoff_liquidity_gap",
                "avg_amount_20d": 7000.0,
                "market_cap": 7.0,
                "pre_truncation_frontier_window": [
                    {"rank": 1, "ticker": "600001", "ts_code": "600001.SH", "name": "A", "avg_amount_20d": 10000.0, "market_cap": 10.0},
                    {"rank": 2, "ticker": "600002", "ts_code": "600002.SH", "name": "B", "avg_amount_20d": 9000.0, "market_cap": 9.0},
                    {"rank": 3, "ticker": "600003", "ts_code": "600003.SH", "name": "C", "avg_amount_20d": 8000.0, "market_cap": 8.0},
                    {"rank": 4, "ticker": "003036", "ts_code": "003036.SZ", "name": "D", "avg_amount_20d": 7000.0, "market_cap": 7.0},
                ],
            }
        ],
        "ranking_driver_counts": {"avg_amount_20d_gap": 1},
        "dominant_ranking_driver": "avg_amount_20d_gap",
        "liquidity_gap_mode_counts": {"near_cutoff_liquidity_gap": 1},
        "dominant_liquidity_gap_mode": "near_cutoff_liquidity_gap",
        "avg_amount_share_of_cutoff_mean": 0.875,
        "avg_amount_share_of_cutoff_min": 0.875,
        "avg_amount_share_of_cutoff_max": 0.875,
        "avg_amount_share_of_min_gate_mean": avg_amount_share_of_min_gate,
        "avg_amount_share_of_min_gate_min": avg_amount_share_of_min_gate,
        "avg_amount_share_of_min_gate_max": avg_amount_share_of_min_gate,
        "cutoff_avg_amount_share_of_min_gate_mean": cutoff_avg_amount_share_of_min_gate,
        "cutoff_avg_amount_share_of_min_gate_min": cutoff_avg_amount_share_of_min_gate,
        "cutoff_avg_amount_share_of_min_gate_max": cutoff_avg_amount_share_of_min_gate,
        "avg_amount_gap_to_cutoff_mean": 1000.0,
        "avg_amount_gap_to_cutoff_min": 1000.0,
        "avg_amount_gap_to_cutoff_max": 1000.0,
        "min_rank_gap_to_cutoff": 1,
        "max_rank_gap_to_cutoff": 1,
        "avg_rank_gap_to_cutoff": 1.0,
    }
    assert analysis["focus_liquidity_profile_summary"] == {
        "profile_count": 1,
        "dominant_liquidity_gap_mode": "near_cutoff_liquidity_gap",
        "liquidity_gap_mode_counts": {"near_cutoff_liquidity_gap": 1},
        "priority_handoff_counts": {"top300_boundary_micro_tuning": 1},
        "primary_focus_tickers": [dossier["truncation_liquidity_profile"]],
    }
