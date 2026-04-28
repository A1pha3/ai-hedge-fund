from __future__ import annotations

import json
import os

from scripts.btst_latest_followup_utils import (
    load_btst_followup_by_ticker_for_report,
    load_latest_btst_followup_by_ticker,
    load_latest_btst_historical_prior_by_ticker,
    load_latest_upstream_shadow_followup_by_ticker,
    load_latest_upstream_shadow_followup_summary,
    select_latest_btst_followup_candidate,
)


def _write_followup_report(
    report_dir,
    *,
    trade_date: str,
    selection_target: str,
    brief_payload: dict,
    mtime: int,
) -> None:
    report_dir.mkdir(parents=True)
    brief_path = report_dir / "btst_next_day_trade_brief_latest.json"
    brief_path.write_text(json.dumps(brief_payload, ensure_ascii=False) + "\n", encoding="utf-8")
    (report_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "end_date": trade_date,
                "plan_generation": {"selection_target": selection_target},
                "btst_followup": {
                    "trade_date": trade_date,
                    "brief_json": str(brief_path.resolve()),
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    os.utime(report_dir, (mtime, mtime))


def test_select_latest_btst_followup_candidate_prefers_fresher_selected_over_larger_near_miss_report(tmp_path):
    reports_root = tmp_path / "reports"
    old_report = reports_root / "paper_trading_20260331_old_near_miss"
    new_report = reports_root / "paper_trading_20260331_new_selected"

    _write_followup_report(
        old_report,
        trade_date="2026-03-31",
        selection_target="short_trade_only",
        brief_payload={
            "upstream_shadow_summary": {"top_focus_tickers": ["300720", "003036"]},
            "near_miss_entries": [
                {"ticker": "300720", "decision": "near_miss", "candidate_source": "post_gate_liquidity_competition_shadow"},
                {"ticker": "003036", "decision": "near_miss", "candidate_source": "post_gate_liquidity_competition_shadow"},
            ],
        },
        mtime=100,
    )
    _write_followup_report(
        new_report,
        trade_date="2026-03-31",
        selection_target="short_trade_only",
        brief_payload={
            "upstream_shadow_summary": {"top_focus_tickers": ["300720"]},
            "selected_entries": [
                {
                    "ticker": "300720",
                    "decision": "selected",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "historical_prior": {
                        "execution_quality_label": "balanced_confirmation",
                        "entry_timing_bias": "confirm_then_review",
                        "execution_note": "历史表现相对均衡，仍应坚持盘中确认后再决定是否持有。",
                    },
                },
            ],
        },
        mtime=200,
    )

    latest_candidate = select_latest_btst_followup_candidate(reports_root)
    latest_summary = load_latest_upstream_shadow_followup_summary(reports_root)
    latest_by_ticker = load_latest_upstream_shadow_followup_by_ticker(reports_root)

    assert latest_candidate["report_dir_name"] == "paper_trading_20260331_new_selected"
    assert latest_summary["report_dir"].endswith("paper_trading_20260331_new_selected")
    assert latest_summary["selected_tickers"] == ["300720"]
    assert latest_by_ticker["300720"]["decision"] == "selected"
    assert latest_by_ticker["300720"]["report_dir"].endswith("paper_trading_20260331_new_selected")
    assert latest_by_ticker["300720"]["historical_execution_quality_label"] == "balanced_confirmation"
    assert latest_by_ticker["300720"]["historical_entry_timing_bias"] == "confirm_then_review"


def test_select_latest_btst_followup_candidate_prefers_newer_selected_followup_over_older_blocked_truth(tmp_path):
    reports_root = tmp_path / "reports"
    old_report = reports_root / "paper_trading_20260421_old_blocked"
    new_report = reports_root / "paper_trading_20260422_new_selected"

    _write_followup_report(
        old_report,
        trade_date="2026-04-21",
        selection_target="short_trade_only",
        brief_payload={
            "upstream_shadow_summary": {"top_focus_tickers": ["300720"]},
            "selected_entries": [
                {
                    "ticker": "300720",
                    "decision": "selected",
                    "reporting_decision": "blocked",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "p2_execution_blocked": True,
                }
            ],
        },
        mtime=200,
    )
    _write_followup_report(
        new_report,
        trade_date="2026-04-22",
        selection_target="short_trade_only",
        brief_payload={
            "upstream_shadow_summary": {"top_focus_tickers": ["300720"]},
            "near_miss_entries": [
                {
                    "ticker": "300720",
                    "decision": "selected",
                    "reporting_decision": "near_miss",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                }
            ],
        },
        mtime=100,
    )

    latest_candidate = select_latest_btst_followup_candidate(reports_root)
    latest_summary = load_latest_upstream_shadow_followup_summary(reports_root)
    latest_by_ticker = load_latest_upstream_shadow_followup_by_ticker(reports_root)

    assert latest_candidate["report_dir_name"] == "paper_trading_20260422_new_selected"
    assert latest_summary["report_dir"].endswith("paper_trading_20260422_new_selected")
    assert latest_summary["near_miss_tickers"] == ["300720"]
    assert latest_summary["decision_counts"] == {"near_miss": 1}
    assert latest_by_ticker["300720"]["decision"] == "near_miss"
    assert latest_by_ticker["300720"]["report_dir"].endswith("paper_trading_20260422_new_selected")


def test_load_latest_upstream_shadow_followup_by_ticker_prefers_blocked_truth_within_same_freshness_bucket(tmp_path):
    reports_root = tmp_path / "reports"
    stale_selected_report = reports_root / "paper_trading_20260428_same_bucket_selected"
    formal_blocked_report = reports_root / "paper_trading_20260428_same_bucket_blocked"

    _write_followup_report(
        stale_selected_report,
        trade_date="2026-04-28",
        selection_target="short_trade_only",
        brief_payload={
            "upstream_shadow_summary": {"top_focus_tickers": ["300720"]},
            "selected_entries": [
                {
                    "ticker": "300720",
                    "decision": "selected",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                }
            ],
        },
        mtime=200,
    )
    _write_followup_report(
        formal_blocked_report,
        trade_date="2026-04-28",
        selection_target="short_trade_only",
        brief_payload={
            "upstream_shadow_summary": {"top_focus_tickers": ["300720"]},
            "selected_entries": [
                {
                    "ticker": "300720",
                    "decision": "selected",
                    "reporting_decision": "blocked",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "p2_execution_blocked": True,
                }
            ],
        },
        mtime=200,
    )

    latest_by_ticker = load_latest_upstream_shadow_followup_by_ticker(reports_root)

    assert latest_by_ticker["300720"]["decision"] == "blocked"
    assert latest_by_ticker["300720"]["report_dir"].endswith("paper_trading_20260428_same_bucket_blocked")


def test_load_latest_upstream_shadow_followup_summary_ignores_newer_plain_rerun_without_upstream_truth(tmp_path):
    reports_root = tmp_path / "reports"
    old_shadow_report = reports_root / "paper_trading_20260501_shadow_blocked"
    new_plain_report = reports_root / "paper_trading_20260502_plain_rerun"

    _write_followup_report(
        old_shadow_report,
        trade_date="2026-05-01",
        selection_target="short_trade_only",
        brief_payload={
            "upstream_shadow_summary": {"top_focus_tickers": ["300720"]},
            "selected_entries": [
                {
                    "ticker": "300720",
                    "decision": "selected",
                    "reporting_decision": "blocked",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "p2_execution_blocked": True,
                }
            ],
        },
        mtime=100,
    )
    _write_followup_report(
        new_plain_report,
        trade_date="2026-05-02",
        selection_target="short_trade_only",
        brief_payload={
            "selected_entries": [
                {
                    "ticker": "600522",
                    "decision": "selected",
                    "candidate_source": "short_trade_boundary",
                }
            ],
        },
        mtime=200,
    )

    latest_candidate = select_latest_btst_followup_candidate(reports_root)
    latest_summary = load_latest_upstream_shadow_followup_summary(reports_root)
    latest_by_ticker = load_latest_upstream_shadow_followup_by_ticker(reports_root)

    assert latest_candidate["report_dir_name"] == "paper_trading_20260502_plain_rerun"
    assert latest_summary["status"] == "validated_upstream_shadow_followup_available"
    assert latest_summary["report_dir"].endswith("paper_trading_20260501_shadow_blocked")
    assert latest_summary["validated_tickers"] == ["300720"]
    assert latest_summary["decision_counts"] == {"blocked": 1}
    assert latest_by_ticker["300720"]["decision"] == "blocked"
    assert latest_by_ticker["300720"]["report_dir"] == latest_summary["report_dir"]


def test_select_latest_btst_followup_candidate_prefers_newer_blocked_followup_over_older_selected_report(tmp_path):
    reports_root = tmp_path / "reports"
    old_report = reports_root / "paper_trading_20260428_old_selected"
    new_report = reports_root / "paper_trading_20260428_new_blocked"

    _write_followup_report(
        old_report,
        trade_date="2026-04-28",
        selection_target="short_trade_only",
        brief_payload={
            "upstream_shadow_summary": {"top_focus_tickers": ["300720"]},
            "selected_entries": [
                {
                    "ticker": "300720",
                    "decision": "selected",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                }
            ],
        },
        mtime=100,
    )
    _write_followup_report(
        new_report,
        trade_date="2026-04-28",
        selection_target="short_trade_only",
        brief_payload={
            "upstream_shadow_summary": {"top_focus_tickers": ["300720"]},
            "selected_entries": [
                {
                    "ticker": "300720",
                    "decision": "selected",
                    "reporting_decision": "blocked",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "p2_execution_blocked": True,
                }
            ],
        },
        mtime=200,
    )

    latest_candidate = select_latest_btst_followup_candidate(reports_root)
    latest_summary = load_latest_upstream_shadow_followup_summary(reports_root)
    latest_by_ticker = load_latest_upstream_shadow_followup_by_ticker(reports_root)

    assert latest_candidate["report_dir_name"] == "paper_trading_20260428_new_blocked"
    assert latest_summary["report_dir"].endswith("paper_trading_20260428_new_blocked")
    assert latest_summary["validated_tickers"] == ["300720"]
    assert latest_summary["decision_counts"] == {"blocked": 1}
    assert latest_by_ticker["300720"]["decision"] == "blocked"
    assert latest_by_ticker["300720"]["report_dir"].endswith("paper_trading_20260428_new_blocked")


def test_load_latest_upstream_shadow_followup_by_ticker_reads_top_level_shadow_entries_alongside_standard_sections(tmp_path):
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_20260506_mixed_shadow_truth"

    _write_followup_report(
        report_dir,
        trade_date="2026-05-06",
        selection_target="short_trade_only",
        brief_payload={
            "upstream_shadow_summary": {"top_focus_tickers": ["300720"]},
            "selected_entries": [
                {
                    "ticker": "600522",
                    "decision": "selected",
                    "candidate_source": "short_trade_boundary",
                }
            ],
            "upstream_shadow_entries": [
                {
                    "ticker": "300720",
                    "decision": "blocked",
                    "reporting_decision": "blocked",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "top_reasons": ["halt_gate_active"],
                    "positive_tags": ["upstream_shadow_release_candidate"],
                }
            ],
        },
        mtime=200,
    )

    latest_summary = load_latest_upstream_shadow_followup_summary(reports_root)
    latest_by_ticker = load_latest_upstream_shadow_followup_by_ticker(reports_root)

    assert latest_summary["validated_tickers"] == ["300720"]
    assert latest_summary["decision_counts"] == {"blocked": 1}
    assert latest_by_ticker["300720"]["decision"] == "blocked"
    assert latest_by_ticker["300720"]["report_dir"].endswith("paper_trading_20260506_mixed_shadow_truth")


def test_load_latest_btst_followup_by_ticker_keeps_generic_historical_prior_rows(tmp_path):
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_20260406_short_trade"

    _write_followup_report(
        report_dir,
        trade_date="2026-04-06",
        selection_target="short_trade_only",
        brief_payload={
            "opportunity_pool_entries": [
                {
                    "ticker": "300757",
                    "decision": "rejected",
                    "candidate_source": "short_trade_boundary",
                    "historical_prior": {
                        "execution_quality_label": "gap_chase_risk",
                        "entry_timing_bias": "avoid_open_chase",
                        "evaluable_count": 6,
                        "next_high_hit_rate_at_threshold": 0.6667,
                        "next_close_positive_rate": 0.6667,
                        "execution_note": "历史上更像高开后回落，避免开盘直接追价。",
                    },
                }
            ]
        },
        mtime=200,
    )

    latest_by_ticker = load_latest_btst_followup_by_ticker(reports_root)

    assert latest_by_ticker["300757"]["candidate_source"] == "short_trade_boundary"
    assert latest_by_ticker["300757"]["historical_prior"]["execution_quality_label"] == "gap_chase_risk"
    assert latest_by_ticker["300757"]["historical_prior"]["next_close_positive_rate"] == 0.6667


def test_load_btst_followup_by_ticker_for_report_reads_current_report_rows(tmp_path):
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_20260406_short_trade"

    _write_followup_report(
        report_dir,
        trade_date="2026-04-06",
        selection_target="short_trade_only",
        brief_payload={
            "opportunity_pool_entries": [
                {
                    "ticker": "600522",
                    "decision": "rejected",
                    "candidate_source": "short_trade_boundary",
                    "historical_prior": {
                        "execution_quality_label": "intraday_only",
                        "entry_timing_bias": "confirm_then_reduce",
                        "evaluable_count": 18,
                        "next_high_hit_rate_at_threshold": 1.0,
                        "next_close_positive_rate": 0.3889,
                        "execution_note": "历史上更多是盘中给空间、收盘回落。",
                    },
                }
            ]
        },
        mtime=200,
    )

    rows_by_ticker = load_btst_followup_by_ticker_for_report(report_dir)

    assert rows_by_ticker["600522"]["historical_prior"]["execution_quality_label"] == "intraday_only"
    assert rows_by_ticker["600522"]["historical_prior"]["next_close_positive_rate"] == 0.3889


def test_load_btst_followup_by_ticker_for_report_uses_reporting_decision_and_skips_pruned_sections(tmp_path):
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_20260424_short_trade"

    _write_followup_report(
        report_dir,
        trade_date="2026-04-24",
        selection_target="short_trade_only",
        brief_payload={
            "near_miss_entries": [
                {
                    "ticker": "002028",
                    "decision": "selected",
                    "reporting_decision": "near_miss",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "historical_prior": {
                        "execution_quality_label": "intraday_only",
                        "evaluable_count": 6,
                    },
                }
            ],
            "weak_history_pruned_entries": [
                {
                    "ticker": "600522",
                    "decision": "selected",
                    "reporting_decision": "opportunity_pool",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "historical_prior": {
                        "execution_quality_label": "zero_follow_through",
                        "evaluable_count": 6,
                    },
                }
            ],
        },
        mtime=200,
    )

    rows_by_ticker = load_btst_followup_by_ticker_for_report(report_dir)

    assert rows_by_ticker["002028"]["decision"] == "near_miss"
    assert rows_by_ticker["002028"]["reporting_decision"] == "near_miss"
    assert "600522" not in rows_by_ticker


def test_load_latest_btst_followup_by_ticker_prefers_broader_more_conservative_prior_for_same_ticker(tmp_path):
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_20260406_short_trade"

    _write_followup_report(
        report_dir,
        trade_date="2026-04-06",
        selection_target="short_trade_only",
        brief_payload={
            "near_miss_entries": [
                {
                    "ticker": "300720",
                    "decision": "near_miss",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "historical_prior": {
                        "applied_scope": "same_ticker",
                        "sample_count": 4,
                        "evaluable_count": 4,
                        "execution_quality_label": "intraday_only",
                        "entry_timing_bias": "confirm_then_reduce",
                        "next_high_hit_rate_at_threshold": 1.0,
                        "next_close_positive_rate": 0.0,
                        "execution_note": "历史上更多是盘中给空间、收盘回落。",
                    },
                }
            ],
            "upstream_shadow_summary": {
                "released_shadow_entries": [
                    {
                        "ticker": "300720",
                        "decision": "rejected",
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                        "historical_prior": {
                            "applied_scope": "same_family_source",
                            "sample_count": 2,
                            "evaluable_count": 2,
                            "execution_quality_label": "balanced_confirmation",
                            "entry_timing_bias": "confirm_then_review",
                            "next_high_hit_rate_at_threshold": 0.5,
                            "next_close_positive_rate": 0.5,
                            "execution_note": "样本较少，隔夜表现相对均衡。",
                        },
                    }
                ]
            },
        },
        mtime=200,
    )

    latest_by_ticker = load_latest_btst_followup_by_ticker(reports_root)

    assert latest_by_ticker["300720"]["historical_prior"]["execution_quality_label"] == "intraday_only"
    assert latest_by_ticker["300720"]["historical_prior"]["evaluable_count"] == 4
    assert latest_by_ticker["300720"]["historical_prior"]["applied_scope"] == "same_ticker"


def test_load_latest_btst_followup_by_ticker_prefers_newer_report_for_same_ticker_over_older_selected_report(tmp_path):
    reports_root = tmp_path / "reports"
    old_report = reports_root / "paper_trading_20260331_old_selected"
    new_report = reports_root / "paper_trading_20260406_newer_near_miss"

    _write_followup_report(
        old_report,
        trade_date="2026-03-31",
        selection_target="short_trade_only",
        brief_payload={
            "selected_entries": [
                {
                    "ticker": "300720",
                    "decision": "selected",
                    "candidate_source": "post_gate_liquidity_competition_shadow",
                    "historical_prior": {
                        "applied_scope": "candidate_source",
                        "sample_count": 2,
                        "evaluable_count": 2,
                        "execution_quality_label": "balanced_confirmation",
                        "entry_timing_bias": "confirm_then_review",
                    },
                }
            ]
        },
        mtime=100,
    )
    _write_followup_report(
        new_report,
        trade_date="2026-04-06",
        selection_target="short_trade_only",
        brief_payload={
            "near_miss_entries": [
                {
                    "ticker": "300720",
                    "decision": "near_miss",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "historical_prior": {
                        "applied_scope": "same_ticker",
                        "sample_count": 4,
                        "evaluable_count": 4,
                        "execution_quality_label": "intraday_only",
                        "entry_timing_bias": "confirm_then_reduce",
                    },
                }
            ]
        },
        mtime=200,
    )

    latest_by_ticker = load_latest_btst_followup_by_ticker(reports_root)

    assert latest_by_ticker["300720"]["trade_date"] == "20260406"
    assert latest_by_ticker["300720"]["report_dir_name"] == "paper_trading_20260406_newer_near_miss"
    assert latest_by_ticker["300720"]["historical_prior"]["execution_quality_label"] == "intraday_only"


def test_load_latest_btst_historical_prior_by_ticker_skips_newer_rows_without_prior(tmp_path):
    reports_root = tmp_path / "reports"
    prior_report = reports_root / "paper_trading_20260406_with_prior"
    newer_observation_report = reports_root / "paper_trading_20260407_without_prior"

    _write_followup_report(
        prior_report,
        trade_date="2026-04-06",
        selection_target="short_trade_only",
        brief_payload={
            "near_miss_entries": [
                {
                    "ticker": "300720",
                    "decision": "near_miss",
                    "candidate_source": "upstream_liquidity_corridor_shadow",
                    "historical_prior": {
                        "applied_scope": "same_ticker",
                        "sample_count": 4,
                        "evaluable_count": 4,
                        "execution_quality_label": "intraday_only",
                        "entry_timing_bias": "confirm_then_reduce",
                    },
                }
            ]
        },
        mtime=100,
    )
    _write_followup_report(
        newer_observation_report,
        trade_date="2026-04-07",
        selection_target="short_trade_only",
        brief_payload={
            "upstream_shadow_summary": {
                "top_focus_tickers": ["300720"],
                "observation_entries": [
                    {
                        "ticker": "300720",
                        "decision": "observation",
                        "candidate_source": "upstream_liquidity_corridor_shadow",
                    }
                ],
            }
        },
        mtime=200,
    )

    priors_by_ticker = load_latest_btst_historical_prior_by_ticker(reports_root)

    assert priors_by_ticker["300720"]["execution_quality_label"] == "intraday_only"
    assert priors_by_ticker["300720"]["evaluable_count"] == 4


def test_load_latest_btst_historical_prior_by_ticker_recognizes_real_scope_aliases(tmp_path):
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_20260406_short_trade"

    _write_followup_report(
        report_dir,
        trade_date="2026-04-06",
        selection_target="short_trade_only",
        brief_payload={
            "selected_entries": [
                {
                    "ticker": "688498",
                    "decision": "selected",
                    "candidate_source": "catalyst_theme",
                    "historical_prior": {
                        "applied_scope": "candidate_source",
                        "sample_count": 3,
                        "evaluable_count": 3,
                        "execution_quality_label": "balanced_confirmation",
                        "entry_timing_bias": "confirm_then_review",
                    },
                }
            ],
            "opportunity_pool_entries": [
                {
                    "ticker": "688498",
                    "decision": "rejected",
                    "candidate_source": "catalyst_theme",
                    "historical_prior": {
                        "applied_scope": "family_source_score_catalyst",
                        "sample_count": 3,
                        "evaluable_count": 3,
                        "execution_quality_label": "close_continuation",
                        "entry_timing_bias": "confirm_then_hold",
                    },
                }
            ],
        },
        mtime=200,
    )

    priors_by_ticker = load_latest_btst_historical_prior_by_ticker(reports_root)

    assert priors_by_ticker["688498"]["applied_scope"] == "family_source_score_catalyst"
    assert priors_by_ticker["688498"]["execution_quality_label"] == "close_continuation"
