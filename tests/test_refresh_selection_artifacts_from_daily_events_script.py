from __future__ import annotations

import json
from types import SimpleNamespace
from pathlib import Path

import pytest

import scripts.refresh_selection_artifacts_from_daily_events as refresh_module
from scripts.refresh_selection_artifacts_from_daily_events import refresh_selection_artifacts_for_report
from src.execution.models import ExecutionPlan
from src.screening.models import StrategySignal


def _make_signal(direction: int, confidence: float, completeness: float = 1.0, sub_factors: dict | None = None) -> StrategySignal:
    return StrategySignal(
        direction=direction,
        confidence=confidence,
        completeness=completeness,
        sub_factors=sub_factors or {},
    )


def _make_post_gate_released_shadow_entry() -> dict:
    return {
        "ticker": "300720",
        "score_b": 0.2,
        "score_c": -0.4,
        "score_final": 0.05,
        "quality_score": 0.58,
        "decision": "watch",
        "reason": "post_gate_liquidity_competition_shadow",
        "reasons": [
            "post_gate_liquidity_competition_shadow",
            "candidate_pool_truncated_after_filters",
            "post_gate_liquidity_competition",
            "catalyst_freshness_below_short_trade_boundary_floor",
            "upstream_shadow_release_score_floor_pass",
            "upstream_shadow_release_candidate",
        ],
        "candidate_source": "post_gate_liquidity_competition_shadow",
        "upstream_candidate_source": "candidate_pool_truncated_after_filters",
        "candidate_reason_codes": [
            "post_gate_liquidity_competition_shadow",
            "candidate_pool_truncated_after_filters",
            "post_gate_liquidity_competition",
            "catalyst_freshness_below_short_trade_boundary_floor",
            "upstream_shadow_release_score_floor_pass",
            "upstream_shadow_release_candidate",
        ],
        "candidate_pool_rank": 1131,
        "candidate_pool_lane": "post_gate_liquidity_competition",
        "candidate_pool_avg_amount_share_of_cutoff": 0.3221,
        "candidate_pool_avg_amount_share_of_min_gate": 9.6762,
        "short_trade_boundary_metrics": {
            "breakout_freshness": 0.4,
            "trend_acceleration": 0.8814,
            "volume_expansion_quality": 0.25,
            "catalyst_freshness": 0.0,
            "close_strength": 0.8902,
            "candidate_score": 0.4794,
        },
        "shadow_release_filter_reason": "catalyst_freshness_below_short_trade_boundary_floor",
        "shadow_release_reason": "upstream_shadow_release_score_floor_pass",
        "shadow_release_score_floor": 0.3,
        "shadow_release_candidate_score": 0.4794,
        "promotion_trigger": "受控 upstream shadow release 样本，仅进入 short-trade supplemental replay，默认不直接进入正式买入名单。",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                95.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 88.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 85.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 95.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 30.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 70.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "event_sentiment": _make_signal(
                1,
                40.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "mean_reversion": _make_signal(0, 0.0).model_dump(mode="json"),
            "fundamental": _make_signal(1, 45.0).model_dump(mode="json"),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.0, "investor": 0.0}},
    }


def _make_corridor_released_shadow_entry(*, shadow_visibility_gap_selected: bool) -> dict:
    return {
        "ticker": "300720",
        "score_b": 0.2,
        "score_c": -0.4,
        "score_final": 0.05,
        "quality_score": 0.58,
        "decision": "watch",
        "reason": "upstream_base_liquidity_uplift_shadow",
        "reasons": [
            "upstream_base_liquidity_uplift_shadow",
            "candidate_pool_truncated_after_filters",
            "layer_a_liquidity_corridor",
            "catalyst_freshness_below_short_trade_boundary_floor",
            "upstream_shadow_release_score_floor_pass",
            "upstream_shadow_release_candidate",
        ],
        "candidate_source": "upstream_liquidity_corridor_shadow",
        "upstream_candidate_source": "candidate_pool_truncated_after_filters",
        "candidate_reason_codes": [
            "upstream_base_liquidity_uplift_shadow",
            "candidate_pool_truncated_after_filters",
            "layer_a_liquidity_corridor",
            "catalyst_freshness_below_short_trade_boundary_floor",
            "upstream_shadow_release_score_floor_pass",
            "upstream_shadow_release_candidate",
        ],
        "candidate_pool_rank": 1131,
        "candidate_pool_lane": "layer_a_liquidity_corridor",
        "candidate_pool_shadow_reason": "upstream_base_liquidity_uplift_shadow_visibility_gap_relaxed_band" if shadow_visibility_gap_selected else "upstream_base_liquidity_uplift_shadow",
        "candidate_pool_avg_amount_share_of_cutoff": 0.3221,
        "candidate_pool_avg_amount_share_of_min_gate": 9.6762,
        "shadow_visibility_gap_selected": shadow_visibility_gap_selected,
        "short_trade_boundary_metrics": {
            "breakout_freshness": 0.4,
            "trend_acceleration": 0.8507,
            "volume_expansion_quality": 0.25,
            "catalyst_freshness": 0.0,
            "close_strength": 0.9092,
            "candidate_score": 0.4794,
        },
        "shadow_release_filter_reason": "catalyst_freshness_below_short_trade_boundary_floor",
        "shadow_release_reason": "upstream_shadow_release_score_floor_pass",
        "shadow_release_score_floor": 0.3,
        "shadow_release_candidate_score": 0.4794,
        "promotion_trigger": "受控 upstream shadow release 样本，仅进入 short-trade supplemental replay，默认不直接进入正式买入名单。",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                95.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 88.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 85.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 95.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 30.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 70.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "event_sentiment": _make_signal(
                1,
                40.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "mean_reversion": _make_signal(0, 0.0).model_dump(mode="json"),
            "fundamental": _make_signal(1, 45.0).model_dump(mode="json"),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.0, "investor": 0.0}},
    }


def _make_corridor_shadow_observation_entry() -> dict:
    return {
        "ticker": "301188",
        "decision": "observation",
        "reason": "upstream_base_liquidity_uplift_shadow",
        "candidate_source": "upstream_liquidity_corridor_shadow",
        "upstream_candidate_source": "candidate_pool_truncated_after_filters",
        "candidate_reason_codes": [
            "upstream_base_liquidity_uplift_shadow",
            "candidate_pool_truncated_after_filters",
            "layer_a_liquidity_corridor",
        ],
        "candidate_pool_lane": "layer_a_liquidity_corridor",
        "candidate_pool_shadow_reason": "upstream_base_liquidity_uplift_shadow_focus_relaxed_band",
        "candidate_pool_rank": 3179,
        "candidate_pool_avg_amount_share_of_cutoff": 0.0738,
        "candidate_pool_avg_amount_share_of_min_gate": 2.4069,
        "gate_status": {"score": "shadow_observation"},
        "top_reasons": [
            "candidate_score=0.01",
            "filter_reason=structural_prefilter_fail",
            "breakout_freshness=0.00",
        ],
        "short_trade_boundary_metrics": {
            "breakout_freshness": 0.0,
            "trend_acceleration": 0.0,
            "volume_expansion_quality": 0.0,
            "catalyst_freshness": 0.0,
            "close_strength": 0.068,
            "candidate_score": 0.0068,
        },
        "strategy_signals": {
            "trend": _make_signal(
                -1,
                45.0,
                sub_factors={
                    "momentum": {"direction": 0, "confidence": 50.0, "completeness": 1.0},
                    "adx_strength": {"direction": -1, "confidence": 21.7, "completeness": 1.0},
                    "ema_alignment": {"direction": -1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {"direction": -1, "confidence": 61.1, "completeness": 1.0},
                    "long_trend_alignment": {"direction": -1, "confidence": 32.5, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "mean_reversion": _make_signal(0, 49.0).model_dump(mode="json"),
            "fundamental": _make_signal(0, 0.0, completeness=0.0).model_dump(mode="json"),
            "event_sentiment": _make_signal(0, 0.0, completeness=0.0).model_dump(mode="json"),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.0, "investor": 0.0}},
    }


def _make_catalyst_theme_carryover_entry() -> dict:
    return {
        "ticker": "002001",
        "score_b": 0.2,
        "score_c": -0.4,
        "score_final": 0.05,
        "quality_score": 0.58,
        "decision": "catalyst_theme",
        "reason": "catalyst_theme_candidate_score_ranked",
        "reasons": [
            "catalyst_theme_candidate_score_ranked",
            "catalyst_theme_research_candidate",
            "catalyst_theme_short_trade_carryover_candidate",
        ],
        "candidate_source": "catalyst_theme",
        "candidate_reason_codes": [
            "catalyst_theme_candidate_score_ranked",
            "catalyst_theme_research_candidate",
            "catalyst_theme_short_trade_carryover_candidate",
        ],
        "short_trade_catalyst_relief": {
            "enabled": True,
            "reason": "catalyst_theme_short_trade_carryover",
            "catalyst_freshness_floor": 1.0,
            "near_miss_threshold": 0.44,
            "breakout_freshness_min": 0.35,
            "trend_acceleration_min": 0.72,
            "close_strength_min": 0.85,
            "require_no_profitability_hard_cliff": True,
        },
        "historical_prior": {
            "execution_quality_label": "close_continuation",
            "entry_timing_bias": "confirm_then_hold",
            "evaluable_count": 2,
            "next_high_hit_rate_at_threshold": 1.0,
            "next_close_positive_rate": 1.0,
            "next_open_to_close_return_mean": 0.0393,
            "execution_note": "历史上更偏向次日收盘延续，确认后可保留 follow-through 预期。",
        },
        "strategy_signals": {
            "trend": _make_signal(
                1,
                95.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 88.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 85.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 95.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 30.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 70.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "event_sentiment": _make_signal(
                1,
                40.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "mean_reversion": _make_signal(0, 0.0).model_dump(mode="json"),
            "fundamental": _make_signal(1, 45.0).model_dump(mode="json"),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.0, "investor": 0.0}},
    }


def _make_metric_override_catalyst_theme_carryover_entry() -> dict:
    entry = _make_catalyst_theme_carryover_entry()
    entry["ticker"] = "002002"
    entry["strategy_signals"] = {
        "trend": _make_signal(
            1,
            20.0,
            sub_factors={
                "momentum": {"direction": 1, "confidence": 10.0, "completeness": 1.0},
                "adx_strength": {"direction": 1, "confidence": 10.0, "completeness": 1.0},
                "ema_alignment": {"direction": 1, "confidence": 10.0, "completeness": 1.0},
                "volatility": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                "long_trend_alignment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
            },
        ).model_dump(mode="json"),
        "event_sentiment": _make_signal(
            0,
            0.0,
            sub_factors={
                "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
            },
        ).model_dump(mode="json"),
        "mean_reversion": _make_signal(0, 0.0).model_dump(mode="json"),
        "fundamental": _make_signal(1, 20.0).model_dump(mode="json"),
    }
    entry["metrics"] = {
        "breakout_freshness": 0.4,
        "trend_acceleration": 0.7594,
        "volume_expansion_quality": 0.25,
        "close_strength": 0.9317,
        "sector_resonance": 0.1,
        "catalyst_freshness": 0.0,
    }
    entry["catalyst_theme_metrics"] = {
        **entry["metrics"],
        "candidate_score": 0.4341,
        "effective_catalyst_freshness": 1.0,
    }
    return entry


def _make_low_sample_catalyst_theme_carryover_entry() -> dict:
    entry = _make_catalyst_theme_carryover_entry()
    entry["ticker"] = "688498"
    entry["historical_prior"] = {
        "execution_quality_label": "close_continuation",
        "entry_timing_bias": "confirm_then_hold",
        "evaluable_count": 1,
        "same_ticker_sample_count": 1,
        "same_family_sample_count": 74,
        "same_family_source_sample_count": 0,
        "same_family_source_score_catalyst_sample_count": 0,
        "same_source_score_sample_count": 0,
        "next_high_hit_rate_at_threshold": 1.0,
        "next_close_positive_rate": 1.0,
        "next_open_to_close_return_mean": 0.01,
        "execution_note": "历史样本很少，且只有 broad family 外围支持。",
    }
    return entry


def _make_short_trade_boundary_entry(*, ticker: str, strategy_signals: dict | None = None) -> dict:
    return {
        "ticker": ticker,
        "score_b": 0.2,
        "score_c": -0.4,
        "score_final": 0.05,
        "quality_score": 0.58,
        "decision": "watch",
        "reason": "short_trade_candidate_score_ranked",
        "reasons": ["short_trade_candidate_score_ranked", "short_trade_prequalified"],
        "candidate_source": "short_trade_boundary",
        "candidate_reason_codes": ["short_trade_candidate_score_ranked", "short_trade_prequalified"],
        "strategy_signals": dict(strategy_signals or {}),
        "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.0, "investor": 0.0}},
    }


def _make_watchlist_item(*, ticker: str, strategy_signals: dict | None = None) -> dict:
    return {
        "ticker": ticker,
        "score_c": 0.31,
        "score_final": 0.42,
        "score_b": 0.42,
        "quality_score": 0.62,
        "market_state": {},
        "candidate_source": "layer_c_watchlist",
        "candidate_reason_codes": ["watchlist_ranked"],
        "strategy_signals": dict(strategy_signals or {}),
        "agent_signals": {},
        "agent_contribution_summary": {},
        "decision": "watch",
    }


def test_refresh_selection_artifacts_from_daily_events_promotes_post_gate_shadow_entry(tmp_path, monkeypatch: pytest.MonkeyPatch):
    report_dir = tmp_path / "paper_trading_20260331_20260331_refresh_target"
    (report_dir / "selection_artifacts").mkdir(parents=True)
    trade_date = "20260331"

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {
                        "tickers": [],
                        "released_shadow_entries": [_make_post_gate_released_shadow_entry()],
                    },
                }
            }
        },
    )
    raw_current_plan = plan.model_dump(mode="json")
    raw_current_plan["candidate_pool_shadow"] = {
        "tickers": [
            {
                "ticker": "300720",
                "candidate_pool_rank": 1131,
                "candidate_pool_lane": "layer_a_liquidity_corridor",
                "candidate_pool_shadow_reason": "upstream_base_liquidity_uplift_shadow_visibility_gap_relaxed_band",
                "avg_amount_share_of_cutoff": 0.3221,
                "avg_amount_share_of_min_gate": 9.6762,
                "shadow_visibility_gap_selected": True,
                "shadow_visibility_gap_relaxed_band": True,
            }
        ]
    }
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": raw_current_plan,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        refresh_module,
        "_load_latest_historical_prior_by_ticker",
        lambda report_path: {
            "300720": {
                "execution_quality_label": "close_continuation",
                "evaluable_count": 4,
                "next_close_positive_rate": 0.75,
                "next_open_to_close_return_mean": 0.03,
            }
        },
    )

    result = refresh_selection_artifacts_for_report(report_dir, trade_date="2026-03-31")

    assert result["results"][0]["trade_date"] == "2026-03-31"
    replay_input = json.loads((report_dir / "selection_artifacts" / "2026-03-31" / "selection_target_replay_input.json").read_text(encoding="utf-8"))
    supplemental_entry = next(entry for entry in replay_input["supplemental_short_trade_entries"] if entry["ticker"] == "300720")
    assert supplemental_entry["short_trade_catalyst_relief"]["selected_threshold"] == 0.45
    assert supplemental_entry["short_trade_catalyst_relief"]["near_miss_threshold"] == 0.45

    selection_snapshot = json.loads((report_dir / "selection_artifacts" / "2026-03-31" / "selection_snapshot.json").read_text(encoding="utf-8"))
    assert selection_snapshot["short_trade_view"]["selected_symbols"] == ["300720"]
    assert selection_snapshot["selection_targets"]["300720"]["short_trade"]["decision"] == "selected"

    session_summary = json.loads((report_dir / "session_summary.json").read_text(encoding="utf-8"))
    assert session_summary["selection_artifact_refresh"]["refreshed_trade_dates"] == ["2026-03-31"]


def test_main_refreshes_unique_report_dirs_and_optional_followups(monkeypatch: pytest.MonkeyPatch, tmp_path, capsys: pytest.CaptureFixture[str]):
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "paper_trading_20260331_case"
    reports_root = report_dir.parent
    followup_calls: list[tuple] = []
    manifest_calls: list[Path] = []
    control_tower_calls: list[Path] = []

    monkeypatch.setattr(
        refresh_module,
        "parse_args",
        lambda: SimpleNamespace(
            input_paths=["first", "second"],
            trade_date="2026-03-31",
            report_name_contains="paper_trading",
            refresh_followup=True,
            refresh_manifest=True,
            refresh_control_tower=True,
        ),
    )
    monkeypatch.setattr(
        refresh_module,
        "discover_report_dirs",
        lambda raw_input, report_name_contains: [report_dir] if raw_input == "first" else [report_dir],
    )
    monkeypatch.setattr(
        refresh_module,
        "refresh_selection_artifacts_for_report",
        lambda report_dir, trade_date: {
            "report_dir": str(report_dir),
            "daily_events_path": str(report_dir / "daily_events.jsonl"),
            "results": [
                {
                    "trade_date": "2026-03-31",
                    "write_status": "written",
                    "snapshot_path": report_dir / "selection_artifacts/2026-03-31/selection_snapshot.json",
                    "replay_input_path": report_dir / "selection_artifacts/2026-03-31/selection_target_replay_input.json",
                    "short_trade_selected_symbols": ["300720", "002001"],
                }
            ],
        },
    )
    monkeypatch.setattr(
        refresh_module,
        "generate_and_register_btst_followup_artifacts",
        lambda report_dir, trade_date: followup_calls.append((report_dir, trade_date)) or {"brief_json": "brief.json", "execution_card_json": "card.json"},
    )
    monkeypatch.setattr(
        refresh_module,
        "generate_reports_manifest_artifacts",
        lambda reports_root: manifest_calls.append(reports_root) or {"json_path": "manifest.json"},
    )
    monkeypatch.setattr(
        refresh_module,
        "generate_btst_nightly_control_tower_artifacts",
        lambda reports_root: control_tower_calls.append(reports_root) or {"json_path": "control.json"},
    )

    refresh_module.main()

    assert followup_calls == [(report_dir, "2026-03-31")]
    assert manifest_calls == [reports_root]
    assert control_tower_calls == [reports_root]
    stdout = capsys.readouterr().out
    assert f"report_dir={report_dir}" in stdout
    assert "trade_date=2026-03-31" in stdout
    assert "short_trade_selected_symbols=300720,002001" in stdout
    assert "btst_brief_json=brief.json" in stdout
    assert "manifest_json=manifest.json" in stdout
    assert "nightly_control_tower_json=control.json" in stdout


def test_refresh_selection_artifacts_from_daily_events_promotes_visibility_gap_corridor_shadow_entry(tmp_path, monkeypatch: pytest.MonkeyPatch):
    report_dir = tmp_path / "paper_trading_20260406_20260406_refresh_target"
    (report_dir / "selection_artifacts").mkdir(parents=True)
    trade_date = "20260406"

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {
                        "tickers": [],
                        "released_shadow_entries": [_make_corridor_released_shadow_entry(shadow_visibility_gap_selected=True)],
                    },
                }
            }
        },
    )
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": plan.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        refresh_module,
        "_load_latest_historical_prior_by_ticker",
        lambda report_path: {
            "300720": {
                "execution_quality_label": "close_continuation",
                "evaluable_count": 4,
                "next_close_positive_rate": 0.75,
                "next_open_to_close_return_mean": 0.03,
            }
        },
    )

    refresh_selection_artifacts_for_report(report_dir, trade_date="2026-04-06")

    selection_snapshot = json.loads((report_dir / "selection_artifacts" / "2026-04-06" / "selection_snapshot.json").read_text(encoding="utf-8"))
    short_trade = selection_snapshot["selection_targets"]["300720"]["short_trade"]
    assert short_trade["metrics_payload"]["thresholds"]["effective_select_threshold"] == 0.40
    assert short_trade["metrics_payload"]["thresholds"]["near_miss_threshold"] == 0.34
    assert selection_snapshot["selection_targets"]["300720"]["short_trade"]["decision"] == "selected"


def test_refresh_selection_artifacts_from_daily_events_recomputes_shadow_observation_blockers(tmp_path):
    report_dir = tmp_path / "paper_trading_20260330_20260330_refresh_shadow_observation"
    (report_dir / "selection_artifacts").mkdir(parents=True)
    trade_date = "20260330"

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {
                        "tickers": [],
                        "released_shadow_entries": [],
                        "shadow_observation_entries": [_make_corridor_shadow_observation_entry()],
                    },
                }
            }
        },
    )
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": plan.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    refresh_selection_artifacts_for_report(report_dir, trade_date="2026-03-30")

    replay_input = json.loads((report_dir / "selection_artifacts" / "2026-03-30" / "selection_target_replay_input.json").read_text(encoding="utf-8"))
    observation_entry = replay_input["upstream_shadow_observation_entries"][0]
    assert observation_entry["ticker"] == "301188"
    assert observation_entry["filter_reason"] == "structural_prefilter_fail"
    assert observation_entry["blockers"] == ["trend_not_constructive"]
    assert observation_entry["short_trade_boundary_metrics"]["gate_status"] == {
        "data": "pass",
        "execution": "proxy_only",
        "structural": "fail",
        "score": "fail",
    }


def test_refresh_selection_artifacts_from_daily_events_keeps_plain_corridor_shadow_below_selected(tmp_path):
    report_dir = tmp_path / "paper_trading_20260406_20260406_refresh_target_plain"
    (report_dir / "selection_artifacts").mkdir(parents=True)
    trade_date = "20260406"

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {
                        "tickers": [],
                        "released_shadow_entries": [_make_corridor_released_shadow_entry(shadow_visibility_gap_selected=False)],
                    },
                }
            }
        },
    )
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": plan.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    refresh_selection_artifacts_for_report(report_dir, trade_date="2026-04-06")

    selection_snapshot = json.loads((report_dir / "selection_artifacts" / "2026-04-06" / "selection_snapshot.json").read_text(encoding="utf-8"))
    short_trade = selection_snapshot["selection_targets"]["300720"]["short_trade"]
    assert short_trade["metrics_payload"]["thresholds"]["effective_select_threshold"] == 0.40
    assert selection_snapshot["selection_targets"]["300720"]["short_trade"]["decision"] == "near_miss"


def test_refresh_selection_artifacts_from_daily_events_injects_historical_prior_into_boundary_candidate(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    report_dir = tmp_path / "paper_trading_20260406_20260406_refresh_boundary"
    (report_dir / "selection_artifacts").mkdir(parents=True)
    trade_date = "20260406"

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {
                        "tickers": [
                            {
                                "ticker": "300757",
                                "score_b": 0.2,
                                "score_c": -0.4,
                                "score_final": 0.05,
                                "quality_score": 0.58,
                                "decision": "watch",
                                "reason": "short_trade_candidate_score_ranked",
                                "reasons": ["short_trade_candidate_score_ranked", "short_trade_prequalified"],
                                "candidate_source": "short_trade_boundary",
                                "candidate_reason_codes": ["short_trade_candidate_score_ranked", "short_trade_prequalified"],
                                "strategy_signals": {
                                    "trend": _make_signal(
                                        1,
                                        95.0,
                                        sub_factors={
                                            "momentum": {"direction": 1, "confidence": 88.0, "completeness": 1.0},
                                            "adx_strength": {"direction": 1, "confidence": 85.0, "completeness": 1.0},
                                            "ema_alignment": {"direction": 1, "confidence": 95.0, "completeness": 1.0},
                                            "volatility": {"direction": 1, "confidence": 30.0, "completeness": 1.0},
                                            "long_trend_alignment": {"direction": 1, "confidence": 70.0, "completeness": 1.0},
                                        },
                                    ).model_dump(mode="json"),
                                    "event_sentiment": _make_signal(
                                        1,
                                        40.0,
                                        sub_factors={
                                            "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                                            "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                                        },
                                    ).model_dump(mode="json"),
                                    "mean_reversion": _make_signal(0, 0.0).model_dump(mode="json"),
                                    "fundamental": _make_signal(
                                        -1,
                                        68.0,
                                        sub_factors={
                                            "profitability": {
                                                "direction": -1,
                                                "confidence": 72.0,
                                                "completeness": 1.0,
                                                "metrics": {"positive_count": 0},
                                            }
                                        },
                                    ).model_dump(mode="json"),
                                },
                                "agent_contribution_summary": {"cohort_contributions": {"analyst": 0.0, "investor": 0.0}},
                            }
                        ],
                        "released_shadow_entries": [],
                    },
                }
            }
        },
    )
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": plan.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (report_dir / "btst_next_day_trade_brief_latest.json").write_text(
        json.dumps(
            {
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
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (report_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "end_date": "2026-04-06",
                "plan_generation": {"selection_target": "short_trade_only"},
                "btst_followup": {
                    "trade_date": "2026-04-06",
                    "brief_json": str((report_dir / "btst_next_day_trade_brief_latest.json").resolve()),
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    refresh_selection_artifacts_for_report(report_dir, trade_date="2026-04-06")

    replay_input = json.loads((report_dir / "selection_artifacts" / "2026-04-06" / "selection_target_replay_input.json").read_text(encoding="utf-8"))
    supplemental_entry = next(entry for entry in replay_input["supplemental_short_trade_entries"] if entry["ticker"] == "300757")
    assert supplemental_entry["historical_prior"]["execution_quality_label"] == "gap_chase_risk"
    assert supplemental_entry["historical_prior"]["entry_timing_bias"] == "avoid_open_chase"

    selection_snapshot = json.loads((report_dir / "selection_artifacts" / "2026-04-06" / "selection_snapshot.json").read_text(encoding="utf-8"))
    short_trade = selection_snapshot["selection_targets"]["300757"]["short_trade"]
    assert short_trade["decision"] in {"selected", "near_miss"}
    assert short_trade["preferred_entry_mode"] == "avoid_open_chase_confirmation"
    assert short_trade["metrics_payload"]["historical_execution_relief"]["applied"] is True
    assert short_trade["metrics_payload"]["historical_execution_relief"]["execution_quality_label"] == "gap_chase_risk"


def test_refresh_selection_artifacts_from_daily_events_preserves_catalyst_theme_candidates(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    report_dir = tmp_path / "paper_trading_20260409_20260409_refresh_catalyst_theme"
    (report_dir / "selection_artifacts").mkdir(parents=True)
    trade_date = "20260409"

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {"tickers": [], "released_shadow_entries": []},
                    "catalyst_theme_candidates": {
                        "tickers": [_make_catalyst_theme_carryover_entry()],
                        "selected_tickers": ["002001"],
                    },
                }
            }
        },
    )
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": plan.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (report_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "end_date": "2026-04-09",
                "plan_generation": {"selection_target": "short_trade_only"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        refresh_module,
        "_load_latest_historical_prior_by_ticker",
        lambda report_path: {
            "002001": {
                "execution_quality_label": "close_continuation",
                "entry_timing_bias": "confirm_then_hold",
                "evaluable_count": 2,
                "next_high_hit_rate_at_threshold": 1.0,
                "next_close_positive_rate": 1.0,
                "next_open_to_close_return_mean": 0.0393,
                "execution_note": "历史上更偏向次日收盘延续，确认后可保留 follow-through 预期。",
            }
        },
    )

    refresh_selection_artifacts_for_report(report_dir, trade_date="2026-04-09")

    selection_snapshot = json.loads((report_dir / "selection_artifacts" / "2026-04-09" / "selection_snapshot.json").read_text(encoding="utf-8"))
    short_trade = selection_snapshot["selection_targets"]["002001"]["short_trade"]
    assert short_trade["decision"] == "selected"
    assert short_trade["preferred_entry_mode"] == "confirm_then_hold_breakout"
    assert short_trade["metrics_payload"]["thresholds"]["effective_select_threshold"] == 0.40


def test_refresh_selection_artifacts_from_daily_events_prefers_rebuilt_catalyst_theme_rerun_artifact(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    report_dir = tmp_path / "paper_trading_20260410_20260410_refresh_catalyst_rerun_override"
    selection_dir = report_dir / "selection_artifacts" / "2026-04-10"
    selection_dir.mkdir(parents=True)
    trade_date = "20260410"

    legacy_entry = _make_catalyst_theme_carryover_entry()
    rebuilt_entry = _make_catalyst_theme_carryover_entry()
    rebuilt_entry["ticker"] = "002003"

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {"tickers": [], "released_shadow_entries": []},
                    "catalyst_theme_candidates": {
                        "tickers": [legacy_entry],
                        "shadow_candidates": [],
                        "selected_tickers": ["002001"],
                    },
                }
            }
        },
    )
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": plan.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (report_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "end_date": "2026-04-10",
                "plan_generation": {"selection_target": "short_trade_only"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (selection_dir / refresh_module.CATALYST_THEME_DIAGNOSTICS_RERUN_FILENAME).write_text(
        json.dumps(
            {
                "report_dir": str(report_dir),
                "trade_date": "2026-04-10",
                "baseline": {
                    "candidate_count": 1,
                    "shadow_candidate_count": 0,
                    "selected_tickers": ["002001"],
                    "shadow_tickers": [],
                    "tickers": [legacy_entry],
                    "shadow_candidates": [],
                },
                "rebuild": {
                    "candidate_count": 1,
                    "shadow_candidate_count": 0,
                    "selected_tickers": ["002003"],
                    "shadow_tickers": [],
                    "tickers": [rebuilt_entry],
                    "shadow_candidates": [],
                },
                "diff": {
                    "added_selected_tickers": ["002003"],
                    "removed_selected_tickers": ["002001"],
                    "added_shadow_tickers": [],
                    "removed_shadow_tickers": [],
                    "changed_selected_entries": [],
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        refresh_module,
        "_load_latest_historical_prior_by_ticker",
        lambda report_path: {
            "002001": legacy_entry["historical_prior"],
            "002003": rebuilt_entry["historical_prior"],
        },
    )

    refresh_selection_artifacts_for_report(report_dir, trade_date="2026-04-10")

    replay_input = json.loads((selection_dir / "selection_target_replay_input.json").read_text(encoding="utf-8"))
    supplemental_catalyst_tickers = {entry["ticker"] for entry in replay_input["supplemental_catalyst_theme_entries"]}
    assert supplemental_catalyst_tickers == {"002003"}

    selection_snapshot = json.loads((selection_dir / "selection_snapshot.json").read_text(encoding="utf-8"))
    assert "002003" in selection_snapshot["selection_targets"]
    assert "002001" not in selection_snapshot["selection_targets"]


def test_refresh_selection_artifacts_from_daily_events_honors_empty_rebuilt_catalyst_theme_rerun_artifact(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    report_dir = tmp_path / "paper_trading_20260410_20260410_refresh_empty_catalyst_rerun_override"
    selection_dir = report_dir / "selection_artifacts" / "2026-04-10"
    selection_dir.mkdir(parents=True)
    trade_date = "20260410"

    legacy_entry = _make_catalyst_theme_carryover_entry()
    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {"tickers": [], "released_shadow_entries": []},
                    "catalyst_theme_candidates": {
                        "tickers": [legacy_entry],
                        "shadow_candidates": [],
                        "selected_tickers": ["002001"],
                        "reason_counts": {"legacy_reason": 1},
                        "filtered_reason_counts": {"legacy_filtered_reason": 1},
                    },
                }
            }
        },
    )
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": plan.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (report_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "end_date": "2026-04-10",
                "plan_generation": {"selection_target": "short_trade_only"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (selection_dir / refresh_module.CATALYST_THEME_DIAGNOSTICS_RERUN_FILENAME).write_text(
        json.dumps(
            {
                "report_dir": str(report_dir),
                "trade_date": "2026-04-10",
                "baseline": {
                    "candidate_count": 1,
                    "shadow_candidate_count": 0,
                    "selected_tickers": ["002001"],
                    "shadow_tickers": [],
                    "tickers": [legacy_entry],
                    "shadow_candidates": [],
                    "reason_counts": {"legacy_reason": 1},
                    "filtered_reason_counts": {"legacy_filtered_reason": 1},
                },
                "rebuild": {
                    "candidate_count": 0,
                    "shadow_candidate_count": 0,
                    "selected_tickers": [],
                    "shadow_tickers": [],
                    "tickers": [],
                    "shadow_candidates": [],
                    "reason_counts": {},
                    "filtered_reason_counts": {},
                },
                "diff": {
                    "added_selected_tickers": [],
                    "removed_selected_tickers": ["002001"],
                    "added_shadow_tickers": [],
                    "removed_shadow_tickers": [],
                    "changed_selected_entries": [],
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(refresh_module, "_load_latest_historical_prior_by_ticker", lambda report_path: {})

    refresh_selection_artifacts_for_report(report_dir, trade_date="2026-04-10")

    replay_input = json.loads((selection_dir / "selection_target_replay_input.json").read_text(encoding="utf-8"))
    assert replay_input["supplemental_catalyst_theme_entries"] == []

    selection_snapshot = json.loads((selection_dir / "selection_snapshot.json").read_text(encoding="utf-8"))
    assert selection_snapshot["catalyst_theme_candidates"] == []
    assert "002001" not in selection_snapshot["selection_targets"]
    catalyst_theme_filter = selection_snapshot["funnel_diagnostics"]["filters"]["catalyst_theme_candidates"]
    assert catalyst_theme_filter["selected_tickers"] == []
    assert catalyst_theme_filter["reason_counts"] == {}
    assert catalyst_theme_filter["filtered_reason_counts"] == {}


def test_refresh_selection_artifacts_from_daily_events_uses_catalyst_theme_metric_overrides(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    report_dir = tmp_path / "paper_trading_20260409_20260409_refresh_catalyst_metric_override"
    (report_dir / "selection_artifacts").mkdir(parents=True)
    trade_date = "20260409"

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {"tickers": [], "released_shadow_entries": []},
                    "catalyst_theme_candidates": {
                        "tickers": [_make_metric_override_catalyst_theme_carryover_entry()],
                        "selected_tickers": ["002002"],
                    },
                }
            }
        },
    )
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": plan.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (report_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "end_date": "2026-04-09",
                "plan_generation": {"selection_target": "short_trade_only"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        refresh_module,
        "_load_latest_historical_prior_by_ticker",
        lambda report_path: {
            "002002": {
                "execution_quality_label": "close_continuation",
                "entry_timing_bias": "confirm_then_hold",
                "evaluable_count": 2,
                "next_high_hit_rate_at_threshold": 1.0,
                "next_close_positive_rate": 1.0,
                "next_open_to_close_return_mean": 0.0393,
                "execution_note": "历史上更偏向次日收盘延续，确认后可保留 follow-through 预期。",
            }
        },
    )

    refresh_selection_artifacts_for_report(report_dir, trade_date="2026-04-09")

    selection_snapshot = json.loads((report_dir / "selection_artifacts" / "2026-04-09" / "selection_snapshot.json").read_text(encoding="utf-8"))
    short_trade = selection_snapshot["selection_targets"]["002002"]["short_trade"]
    assert short_trade["decision"] == "selected"
    assert short_trade["score_target"] >= 0.45
    assert short_trade["metrics_payload"]["thresholds"]["effective_select_threshold"] == 0.40
    assert short_trade["explainability_payload"]["upstream_shadow_catalyst_relief"]["applied"] is True


def test_rebuild_catalyst_theme_diagnostics_for_report_replays_frozen_universe_beyond_baseline(tmp_path):
    report_dir = tmp_path / "paper_trading_20260410_20260410_catalyst_theme_rerun"
    selection_dir = report_dir / "selection_artifacts" / "2026-04-10"
    selection_dir.mkdir(parents=True)
    trade_date = "20260410"

    baseline_entry = _make_catalyst_theme_carryover_entry()
    baseline_entry["quality_score"] = 0.5
    baseline_entry.pop("market_state", None)
    contaminated_snapshot_entry = dict(baseline_entry)
    contaminated_snapshot_entry["quality_score"] = 0.1

    replay_entry = _make_catalyst_theme_carryover_entry()
    replay_entry["ticker"] = "002003"
    replay_entry["decision"] = "watch"
    replay_entry["reason"] = "watchlist_selected"
    replay_entry["reasons"] = ["watchlist_selected"]
    replay_entry["candidate_source"] = "layer_c_watchlist"
    replay_entry["candidate_reason_codes"] = ["watchlist_selected"]

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        market_state={
            "state_type": "trend",
            "adjusted_weights": {
                "trend": 0.3,
                "mean_reversion": 0.2,
                "fundamental": 0.3,
                "event_sentiment": 0.2,
            },
        },
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {"tickers": [], "released_shadow_entries": [], "selected_tickers": []},
                    "catalyst_theme_candidates": {
                        "tickers": [baseline_entry],
                        "shadow_candidates": [],
                        "selected_tickers": ["002001"],
                    },
                }
            }
        },
    )
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": plan.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (report_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "end_date": "2026-04-10",
                "plan_generation": {"selection_target": "short_trade_only"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (selection_dir / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "rejected_entries": [replay_entry],
                "supplemental_catalyst_theme_entries": [baseline_entry],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (selection_dir / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-04-10",
                "market_state": {
                    "state_type": "trend",
                    "adjusted_weights": {
                        "trend": 0.3,
                        "mean_reversion": 0.2,
                        "fundamental": 0.3,
                        "event_sentiment": 0.2,
                    },
                },
                "catalyst_theme_candidates": [contaminated_snapshot_entry],
                "catalyst_theme_shadow_candidates": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = refresh_module.rebuild_catalyst_theme_diagnostics_for_report(report_dir, trade_date="2026-04-10")

    assert Path(result["artifact_path"]).exists()
    payload = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))
    assert payload["source_summary"]["replay_universe_count"] == 2
    assert payload["baseline"]["_baseline_source"] == "plan_funnel_diagnostics"
    assert payload["baseline"]["selected_tickers"] == ["002001"]
    assert "002003" in payload["rebuild"]["selected_tickers"]
    assert "002003" in payload["diff"]["added_selected_tickers"]

    changed_entry = next(row for row in payload["diff"]["changed_selected_entries"] if row["ticker"] == "002001")
    assert changed_entry["baseline_quality_score"] == 0.5
    assert changed_entry["rebuilt_quality_score"] == pytest.approx(0.725, abs=1e-4)
    assert changed_entry["rebuilt_market_state_type"] == "trend"

    snapshot_result = refresh_module.rebuild_catalyst_theme_diagnostics_for_report(
        report_dir,
        trade_date="2026-04-10",
        use_selection_snapshot_baseline=True,
    )

    snapshot_payload = json.loads(Path(snapshot_result["artifact_path"]).read_text(encoding="utf-8"))
    assert snapshot_payload["baseline"]["_baseline_source"] == "selection_snapshot"
    snapshot_changed_entry = next(row for row in snapshot_payload["diff"]["changed_selected_entries"] if row["ticker"] == "002001")
    assert snapshot_changed_entry["baseline_quality_score"] == 0.1


def test_rebuild_catalyst_theme_diagnostics_for_report_creates_output_directory(tmp_path):
    report_dir = tmp_path / "paper_trading_20260411_20260411_catalyst_theme_missing_output_dir"
    trade_date = "20260411"

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {"tickers": [], "released_shadow_entries": [], "selected_tickers": []},
                    "catalyst_theme_candidates": {
                        "tickers": [_make_catalyst_theme_carryover_entry()],
                        "shadow_candidates": [],
                        "selected_tickers": ["002001"],
                    },
                }
            }
        },
    )
    (report_dir / "daily_events.jsonl").parent.mkdir(parents=True)
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": plan.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")

    result = refresh_module.rebuild_catalyst_theme_diagnostics_for_report(report_dir, trade_date="2026-04-11")

    artifact_path = Path(result["artifact_path"])
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact_path.exists()
    assert artifact_path.parent.name == "2026-04-11"
    assert payload["baseline"]["_baseline_source"] == "plan_funnel_diagnostics"
    assert sorted(payload["source_summary"]["missing_optional_inputs"]) == [
        "selection_artifacts/2026-04-11/selection_snapshot.json",
        "selection_artifacts/2026-04-11/selection_target_replay_input.json",
    ]


def test_rebuild_catalyst_theme_diagnostics_for_report_marks_requested_snapshot_baseline_fallback(tmp_path):
    report_dir = tmp_path / "paper_trading_20260411_20260411_catalyst_theme_missing_snapshot_baseline"
    trade_date = "20260411"

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {"tickers": [], "released_shadow_entries": [], "selected_tickers": []},
                    "catalyst_theme_candidates": {
                        "tickers": [_make_catalyst_theme_carryover_entry()],
                        "shadow_candidates": [],
                        "selected_tickers": ["002001"],
                    },
                }
            }
        },
    )
    (report_dir / "daily_events.jsonl").parent.mkdir(parents=True)
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": plan.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")

    result = refresh_module.rebuild_catalyst_theme_diagnostics_for_report(
        report_dir,
        trade_date="2026-04-11",
        use_selection_snapshot_baseline=True,
    )

    payload = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))
    assert payload["baseline"]["_baseline_source"] == "plan_funnel_diagnostics"
    assert payload["baseline"]["_baseline_fallback_reason"] == "selection_snapshot_requested_but_not_found"


def test_rebuild_catalyst_theme_diagnostics_for_report_accepts_hyphenated_frozen_trade_dates(tmp_path):
    report_dir = tmp_path / "paper_trading_20260414_20260414_hyphenated_frozen_date"
    frozen_trade_date = "2026-04-14"

    plan = ExecutionPlan(
        date=frozen_trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {"tickers": [], "released_shadow_entries": [], "selected_tickers": []},
                    "catalyst_theme_candidates": {
                        "tickers": [_make_catalyst_theme_carryover_entry()],
                        "shadow_candidates": [],
                        "selected_tickers": ["002001"],
                    },
                }
            }
        },
    )
    (report_dir / "daily_events.jsonl").parent.mkdir(parents=True)
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": frozen_trade_date,
                "current_plan": plan.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")

    hyphenated_result = refresh_module.rebuild_catalyst_theme_diagnostics_for_report(report_dir, trade_date=frozen_trade_date)
    compact_result = refresh_module.rebuild_catalyst_theme_diagnostics_for_report(report_dir, trade_date="20260414")

    hyphenated_payload = json.loads(Path(hyphenated_result["artifact_path"]).read_text(encoding="utf-8"))
    compact_payload = json.loads(Path(compact_result["artifact_path"]).read_text(encoding="utf-8"))
    assert hyphenated_payload["trade_date"] == "2026-04-14"
    assert compact_payload["trade_date"] == "2026-04-14"
    assert hyphenated_payload["baseline"]["selected_tickers"] == ["002001"]
    assert compact_payload["baseline"]["selected_tickers"] == ["002001"]


def test_rebuild_catalyst_theme_diagnostics_for_report_raises_clear_error_when_daily_events_missing(tmp_path):
    report_dir = tmp_path / "paper_trading_20260411_20260411_catalyst_theme_missing_daily_events"
    report_dir.mkdir()

    with pytest.raises(ValueError, match="Missing daily_events.jsonl"):
        refresh_module.rebuild_catalyst_theme_diagnostics_for_report(report_dir, trade_date="2026-04-11")


def test_rebuild_catalyst_theme_diagnostics_for_report_reports_entries_dropped_without_strategy_signals(tmp_path):
    report_dir = tmp_path / "paper_trading_20260411_20260411_catalyst_theme_dropped_no_signals"
    selection_dir = report_dir / "selection_artifacts" / "2026-04-11"
    selection_dir.mkdir(parents=True)
    trade_date = "20260411"

    empty_signal_entry = _make_short_trade_boundary_entry(ticker="300757", strategy_signals={})
    populated_entry = _make_catalyst_theme_carryover_entry()
    populated_entry["ticker"] = "002009"

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {"tickers": [], "released_shadow_entries": [], "selected_tickers": []},
                    "catalyst_theme_candidates": {
                        "tickers": [populated_entry],
                        "shadow_candidates": [],
                        "selected_tickers": ["002009"],
                    },
                }
            }
        },
    )
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": plan.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")
    (selection_dir / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "rejected_entries": [empty_signal_entry],
                "supplemental_catalyst_theme_entries": [populated_entry],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = refresh_module.rebuild_catalyst_theme_diagnostics_for_report(report_dir, trade_date="2026-04-11")

    payload = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))
    assert payload["source_summary"]["dropped_no_strategy_signals_counts"]["replay_input_rejected_entries"] == 1
    assert payload["source_summary"]["replay_requires_strategy_signals"] is True
    assert payload["source_summary"]["dropped_no_strategy_signal_tickers"] == ["300757"]
    assert payload["source_summary"]["replay_universe_count"] == 1


def test_rebuild_catalyst_theme_diagnostics_for_report_counts_only_winning_source_per_ticker(tmp_path):
    report_dir = tmp_path / "paper_trading_20260411_20260411_catalyst_theme_source_priority"
    selection_dir = report_dir / "selection_artifacts" / "2026-04-11"
    selection_dir.mkdir(parents=True)
    trade_date = "20260411"

    richer_entry = _make_catalyst_theme_carryover_entry()
    richer_entry["ticker"] = "002019"
    weaker_entry = _make_catalyst_theme_carryover_entry()
    weaker_entry["ticker"] = "002019"
    weaker_entry["strategy_signals"] = {
        "trend": _make_signal(1, 95.0).model_dump(mode="json"),
    }

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {"tickers": [], "released_shadow_entries": [], "selected_tickers": []},
                    "catalyst_theme_candidates": {
                        "tickers": [weaker_entry],
                        "shadow_candidates": [],
                        "selected_tickers": ["002019"],
                    },
                }
            }
        },
    )
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": plan.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (report_dir / "session_summary.json").write_text("{}\n", encoding="utf-8")
    (selection_dir / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "rejected_entries": [richer_entry],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = refresh_module.rebuild_catalyst_theme_diagnostics_for_report(report_dir, trade_date="2026-04-11")

    payload = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))
    assert payload["source_summary"]["source_ticker_counts"]["replay_input_rejected_entries"] == 1
    assert payload["source_summary"]["source_ticker_counts"].get("filter_catalyst_selected", 0) == 0


def test_rebuild_selection_targets_for_plan_uses_selection_target_historical_prior(monkeypatch: pytest.MonkeyPatch):
    captured_entries: list[dict] = []

    def _fake_build_selection_targets(**kwargs):
        captured_entries.extend(kwargs["supplemental_short_trade_entries"])
        return {}, SimpleNamespace(short_trade_selected_count=0)

    monkeypatch.setattr(refresh_module, "build_selection_targets", _fake_build_selection_targets)

    historical_prior = {
        "execution_quality_label": "close_continuation",
        "entry_timing_bias": "confirm_then_hold",
        "evaluable_count": 2,
        "next_high_hit_rate_at_threshold": 1.0,
        "next_close_positive_rate": 1.0,
        "next_open_to_close_return_mean": 0.0393,
    }
    plan = SimpleNamespace(
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {"tickers": [], "released_shadow_entries": []},
                    "catalyst_theme_candidates": {
                        "tickers": [_make_metric_override_catalyst_theme_carryover_entry()],
                    },
                }
            }
        },
        watchlist=[],
        buy_orders=[],
        target_mode="short_trade_only",
        selection_targets={
            "002002": SimpleNamespace(
                short_trade=SimpleNamespace(
                    explainability_payload={
                        "replay_context": {
                            "historical_prior": historical_prior,
                        }
                    }
                )
            )
        },
    )

    refresh_module.rebuild_selection_targets_for_plan(
        plan,
        "20260409",
        historical_prior_by_ticker={},
    )

    preserved_entry = next(entry for entry in captured_entries if entry["ticker"] == "002002")
    assert preserved_entry["historical_prior"]["execution_quality_label"] == "close_continuation"
    assert preserved_entry["historical_prior"]["next_close_positive_rate"] == 1.0


def test_refresh_selection_artifacts_from_daily_events_passthroughs_carryover_evidence_deficiency(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    report_dir = tmp_path / "paper_trading_20260409_20260409_refresh_carryover_evidence"
    (report_dir / "selection_artifacts").mkdir(parents=True)
    trade_date = "20260409"

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {"tickers": [], "released_shadow_entries": []},
                    "catalyst_theme_candidates": {
                        "tickers": [_make_low_sample_catalyst_theme_carryover_entry()],
                        "selected_tickers": [],
                    },
                }
            }
        },
    )
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": plan.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (report_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "end_date": "2026-04-09",
                "plan_generation": {"selection_target": "short_trade_only"},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        refresh_module,
        "_load_latest_historical_prior_by_ticker",
        lambda report_path: {
            "688498": {
                "execution_quality_label": "close_continuation",
                "entry_timing_bias": "confirm_then_hold",
                "evaluable_count": 1,
                "same_ticker_sample_count": 1,
                "same_family_sample_count": 74,
                "same_family_source_sample_count": 0,
                "same_family_source_score_catalyst_sample_count": 0,
                "same_source_score_sample_count": 0,
                "next_high_hit_rate_at_threshold": 1.0,
                "next_close_positive_rate": 1.0,
                "next_open_to_close_return_mean": 0.01,
                "execution_note": "历史样本很少，且只有 broad family 外围支持。",
            }
        },
    )

    refresh_selection_artifacts_for_report(report_dir, trade_date="2026-04-09")

    replay_input = json.loads((report_dir / "selection_artifacts" / "2026-04-09" / "selection_target_replay_input.json").read_text(encoding="utf-8"))
    replay_entry = next(entry for entry in replay_input["supplemental_catalyst_theme_entries"] if entry["ticker"] == "688498")
    assert replay_entry["negative_tags"][0] == "evidence_deficient_broad_family_only"
    assert replay_entry["rejection_reasons"][0] == "evidence_deficient_broad_family_only"
    assert replay_entry["carryover_evidence_deficiency"]["evidence_deficient"] is True
    assert replay_entry["short_trade_boundary_metrics"]["carryover_evidence_deficiency"]["same_family_sample_count"] == 74

    selection_snapshot = json.loads((report_dir / "selection_artifacts" / "2026-04-09" / "selection_snapshot.json").read_text(encoding="utf-8"))
    snapshot_entry = next(entry for entry in selection_snapshot["catalyst_theme_candidates"] if entry["ticker"] == "688498")
    assert snapshot_entry["negative_tags"][0] == "evidence_deficient_broad_family_only"
    assert snapshot_entry["carryover_evidence_deficiency"]["evidence_deficient"] is True
    assert (
        selection_snapshot["selection_targets"]["688498"]["short_trade"]["metrics_payload"]["carryover_evidence_deficiency"]["evidence_deficient"]
        is True
    )


def test_refresh_selection_artifacts_from_daily_events_rehydrates_strategy_signals_for_supplemental_entries_from_existing_replay_input(
    tmp_path,
):
    report_dir = tmp_path / "paper_trading_20260410_20260410_refresh_rehydrate_entry_signals"
    selection_dir = report_dir / "selection_artifacts" / "2026-04-10"
    selection_dir.mkdir(parents=True)
    trade_date = "20260410"

    empty_entry = _make_short_trade_boundary_entry(ticker="300757", strategy_signals={})
    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {
                        "tickers": [empty_entry],
                        "released_shadow_entries": [],
                    },
                }
            }
        },
    )
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": plan.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (selection_dir / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "supplemental_short_trade_entries": [
                    _make_short_trade_boundary_entry(
                        ticker="300757",
                        strategy_signals={
                            "trend": _make_signal(1, 95.0).model_dump(mode="json"),
                            "fundamental": _make_signal(1, 45.0).model_dump(mode="json"),
                        },
                    )
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    refresh_selection_artifacts_for_report(report_dir, trade_date="2026-04-10")

    replay_input = json.loads((selection_dir / "selection_target_replay_input.json").read_text(encoding="utf-8"))
    supplemental_entry = next(entry for entry in replay_input["supplemental_short_trade_entries"] if entry["ticker"] == "300757")
    assert supplemental_entry["strategy_signals"]["trend"]["confidence"] == 95.0
    assert set(supplemental_entry["strategy_signals"].keys()) == {"trend", "fundamental"}

    selection_snapshot = json.loads((selection_dir / "selection_snapshot.json").read_text(encoding="utf-8"))
    assert selection_snapshot["selection_targets"]["300757"]["short_trade"]["explainability_payload"]["available_strategy_signals"] == ["fundamental", "trend"]


def test_refresh_selection_artifacts_from_daily_events_rehydrates_strategy_signals_for_watchlist_from_existing_replay_input(
    tmp_path,
):
    report_dir = tmp_path / "paper_trading_20260410_20260410_refresh_rehydrate_watchlist_signals"
    selection_dir = report_dir / "selection_artifacts" / "2026-04-10"
    selection_dir.mkdir(parents=True)
    trade_date = "20260410"

    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        watchlist=[_make_watchlist_item(ticker="300999", strategy_signals={})],
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {"tickers": [], "released_shadow_entries": []},
                }
            }
        },
    )
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": plan.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (selection_dir / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "watchlist": [
                    _make_watchlist_item(
                        ticker="300999",
                        strategy_signals={
                            "trend": _make_signal(1, 91.0).model_dump(mode="json"),
                            "event_sentiment": _make_signal(1, 35.0).model_dump(mode="json"),
                        },
                    )
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    refresh_selection_artifacts_for_report(report_dir, trade_date="2026-04-10")

    replay_input = json.loads((selection_dir / "selection_target_replay_input.json").read_text(encoding="utf-8"))
    watchlist_entry = next(entry for entry in replay_input["watchlist"] if entry["ticker"] == "300999")
    assert watchlist_entry["strategy_signals"]["trend"]["confidence"] == 91.0
    assert set(watchlist_entry["strategy_signals"].keys()) == {"trend", "event_sentiment"}

    selection_snapshot = json.loads((selection_dir / "selection_snapshot.json").read_text(encoding="utf-8"))
    assert selection_snapshot["selection_targets"]["300999"]["short_trade"]["explainability_payload"]["available_strategy_signals"] == ["event_sentiment", "trend"]


def test_refresh_selection_artifacts_from_daily_events_rehydrates_strategy_signals_for_selected_catalyst_theme_entries_from_existing_replay_input(
    tmp_path,
):
    report_dir = tmp_path / "paper_trading_20260410_20260410_refresh_rehydrate_selected_catalyst_theme_signals"
    selection_dir = report_dir / "selection_artifacts" / "2026-04-10"
    selection_dir.mkdir(parents=True)
    trade_date = "20260410"

    empty_entry = _make_catalyst_theme_carryover_entry()
    empty_entry["strategy_signals"] = {}
    plan = ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        risk_metrics={
            "funnel_diagnostics": {
                "filters": {
                    "watchlist": {"tickers": [], "released_shadow_entries": []},
                    "short_trade_candidates": {"tickers": [], "released_shadow_entries": []},
                    "catalyst_theme_candidates": {
                        "tickers": [empty_entry],
                        "shadow_candidates": [],
                        "selected_tickers": ["002001"],
                    },
                }
            }
        },
    )
    (report_dir / "daily_events.jsonl").write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": plan.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    (selection_dir / "selection_target_replay_input.json").write_text(
        json.dumps(
            {
                "supplemental_catalyst_theme_entries": [
                    {
                        **_make_catalyst_theme_carryover_entry(),
                        "strategy_signals": {
                            "trend": _make_signal(1, 95.0).model_dump(mode="json"),
                            "fundamental": _make_signal(1, 45.0).model_dump(mode="json"),
                        },
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    refresh_selection_artifacts_for_report(report_dir, trade_date="2026-04-10")

    selection_snapshot = json.loads((selection_dir / "selection_snapshot.json").read_text(encoding="utf-8"))
    assert selection_snapshot["selection_targets"]["002001"]["short_trade"]["explainability_payload"]["available_strategy_signals"] == [
        "fundamental",
        "trend",
    ]
