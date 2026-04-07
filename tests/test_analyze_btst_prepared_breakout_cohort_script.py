from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_prepared_breakout_cohort import (
    analyze_btst_prepared_breakout_cohort,
    render_btst_prepared_breakout_cohort_markdown,
)
from src.execution.models import LayerCResult
from src.screening.models import StrategySignal
from src.targets.router import build_selection_targets


def _make_signal(direction: int, confidence: float, completeness: float = 1.0, sub_factors: dict | None = None) -> StrategySignal:
    return StrategySignal(
        direction=direction,
        confidence=confidence,
        completeness=completeness,
        sub_factors=sub_factors or {},
    )


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _build_300505_prepared_breakout_report(report_dir: Path, trade_date: str) -> None:
    watch_item = LayerCResult(
        ticker="300505",
        score_b=0.3899,
        score_c=0.375,
        score_final=0.3832,
        quality_score=0.75,
        decision="watch",
        candidate_source="layer_c_watchlist",
        strategy_signals={
            "trend": _make_signal(
                1,
                39.9,
                sub_factors={
                    "momentum": {
                        "direction": 0,
                        "confidence": 50.0,
                        "completeness": 1.0,
                        "metrics": {
                            "momentum_1m": -0.1924,
                            "momentum_3m": 0.3893,
                            "momentum_6m": 0.4729,
                            "volume_momentum": 0.5695,
                        },
                    },
                    "adx_strength": {"direction": 1, "confidence": 31.1, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {
                        "direction": 0,
                        "confidence": 50.0,
                        "completeness": 1.0,
                        "metrics": {"volatility_regime": 1.26, "atr_ratio": 0.0988},
                    },
                    "long_trend_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                },
            ).model_dump(mode="json"),
            "event_sentiment": _make_signal(
                0,
                0.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 0.0},
                },
            ).model_dump(mode="json"),
            "fundamental": _make_signal(1, 52.7).model_dump(mode="json"),
            "mean_reversion": _make_signal(1, 11.1).model_dump(mode="json"),
        },
        agent_contribution_summary={"cohort_contributions": {"analyst": 0.375, "investor": 0.0}},
    )
    selection_targets, summary = build_selection_targets(
        trade_date=trade_date.replace("-", ""),
        watchlist=[watch_item],
        rejected_entries=[],
        supplemental_short_trade_entries=[],
        buy_order_tickers=set(),
        target_mode="dual_target",
    )
    replay_input = {
        "artifact_version": "v1",
        "run_id": f"prepared_breakout_{trade_date}",
        "trade_date": trade_date,
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 1,
            "rejected_entry_count": 0,
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 0,
        },
        "watchlist": [watch_item.model_dump(mode="json")],
        "rejected_entries": [],
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": [],
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
    }
    _write_json(report_dir / "selection_artifacts" / trade_date / "selection_target_replay_input.json", replay_input)
    _write_json(report_dir / "session_summary.json", {"plan_generation": {"selection_target": "dual_target"}})


def test_analyze_btst_prepared_breakout_cohort_keeps_300505_as_anchor(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    report_a = reports_root / "paper_trading_window_20260323_20260326_live_a"
    report_b = reports_root / "paper_trading_window_20260327_20260331_live_b"
    report_a.mkdir(parents=True)
    report_b.mkdir(parents=True)
    _write_json(
        reports_root / "btst_tplus2_candidate_dossier_300505_latest.json",
        {
            "candidate_row_count": 4,
            "recent_window_count": 4,
            "recent_validation_verdict": "recent_tier_confirmed",
            "promotion_readiness_verdict": "validation_queue_ready",
            "tier_focus_surface_summary": {
                "next_high_hit_rate_at_threshold": 1.0,
                "next_close_positive_rate": 1.0,
                "t_plus_2_close_positive_rate": 1.0,
                "next_close_return_distribution": {"mean": 0.0542},
                "t_plus_2_close_return_distribution": {"mean": 0.0361},
            },
        },
    )

    monkeypatch.setattr(
        "scripts.analyze_btst_prepared_breakout_cohort.discover_nested_report_dirs",
        lambda report_root_dirs, report_name_contains="": [report_a, report_b],
    )
    monkeypatch.setattr(
        "scripts.analyze_btst_prepared_breakout_cohort.load_selection_target_replay_sources",
        lambda report_dir: [(report_dir / "selection_artifacts" / ("2026-03-24" if report_dir == report_a else "2026-03-28") / "selection_target_replay_input.json", {"selection_targets": {"300505": {}}})],
    )
    monkeypatch.setattr(
        "scripts.analyze_btst_prepared_breakout_cohort.analyze_selection_target_replay_sources",
        lambda replay_sources, profile_name="default", focus_tickers=None: {
            "focused_score_diagnostics": [
                {
                    "ticker": "300505",
                    "trade_date": "2026-03-24" if "2026-03-24" in str(replay_sources[0][0]) else "2026-03-28",
                    "candidate_source": "layer_c_watchlist",
                    "replayed_decision": "selected",
                    "stored_decision": "selected",
                    "replayed_score_target": 0.6056,
                    "replayed_gap_to_near_miss": -0.1556,
                    "replayed_gap_to_selected": 0.0,
                    "delta_classification": "stable",
                    "replay_input_path": str(replay_sources[0][0]),
                    "replayed_top_reasons": [],
                    "replayed_blockers": [],
                    "replayed_gate_status": {},
                    "replayed_metrics_payload": {
                        "breakout_stage": "prepared_breakout",
                        "prepared_breakout_penalty_relief": {"applied": True},
                        "prepared_breakout_catalyst_relief": {"applied": True},
                        "prepared_breakout_volume_relief": {"applied": True},
                        "prepared_breakout_continuation_relief": {"applied": True},
                        "prepared_breakout_selected_catalyst_relief": {"applied": True},
                    },
                }
            ]
        },
    )

    analysis = analyze_btst_prepared_breakout_cohort(reports_root)

    assert analysis["candidate_count"] == 1
    assert analysis["reference_anchor"]["ticker"] == "300505"
    assert analysis["reference_anchor"]["verdict"] == "reference_selected_relief_anchor"
    assert analysis["reference_anchor"]["selected_relief_window_count"] == 2
    assert analysis["reference_anchor"]["decision_counts"]["selected"] == 2
    assert analysis["next_candidate"] is None
    assert analysis["verdict"] == "anchor_only_no_second_peer"

    markdown = render_btst_prepared_breakout_cohort_markdown(analysis)
    assert "# BTST Prepared-Breakout Cohort Scan" in markdown
    assert "300505" in markdown
    assert "anchor_only_no_second_peer" in markdown


def test_analyze_btst_prepared_breakout_cohort_ranks_frontier_candidate(monkeypatch, tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    reports_root.mkdir(parents=True)
    report_dir = reports_root / "paper_trading_window_20260323_20260326_live"
    report_dir.mkdir(parents=True)
    _write_json(
        reports_root / "btst_tplus2_candidate_dossier_300505_latest.json",
        {
            "tier_focus_surface_summary": {
                "next_high_hit_rate_at_threshold": 1.0,
                "next_close_positive_rate": 1.0,
                "t_plus_2_close_positive_rate": 1.0,
            }
        },
    )
    _write_json(
        reports_root / "btst_tplus2_candidate_dossier_000792_latest.json",
        {
            "tier_focus_surface_summary": {
                "next_high_hit_rate_at_threshold": 0.7,
                "next_close_positive_rate": 0.65,
                "t_plus_2_close_positive_rate": 0.7,
            }
        },
    )

    monkeypatch.setattr(
        "scripts.analyze_btst_prepared_breakout_cohort.discover_nested_report_dirs",
        lambda report_root_dirs, report_name_contains="": [report_dir],
    )
    monkeypatch.setattr(
        "scripts.analyze_btst_prepared_breakout_cohort.load_selection_target_replay_sources",
        lambda report_dir: [(report_dir / "selection_artifacts" / "2026-03-24" / "selection_target_replay_input.json", {"selection_targets": {"300505": {}, "000792": {}}})],
    )
    monkeypatch.setattr(
        "scripts.analyze_btst_prepared_breakout_cohort.analyze_selection_target_replay_sources",
        lambda replay_sources, profile_name="default", focus_tickers=None: {
            "focused_score_diagnostics": [
                {
                    "ticker": "300505",
                    "trade_date": "2026-03-24",
                    "candidate_source": "layer_c_watchlist",
                    "replayed_decision": "selected",
                    "stored_decision": "selected",
                    "replayed_score_target": 0.6056,
                    "replayed_gap_to_near_miss": -0.1556,
                    "replayed_gap_to_selected": 0.0,
                    "delta_classification": "stable",
                    "replay_input_path": str(report_dir / "selection_artifacts" / "2026-03-24" / "selection_target_replay_input.json"),
                    "replayed_top_reasons": [],
                    "replayed_blockers": [],
                    "replayed_gate_status": {},
                    "replayed_metrics_payload": {
                        "breakout_stage": "prepared_breakout",
                        "prepared_breakout_penalty_relief": {"applied": True},
                        "prepared_breakout_catalyst_relief": {"applied": True},
                        "prepared_breakout_volume_relief": {"applied": True},
                        "prepared_breakout_continuation_relief": {"applied": True},
                        "prepared_breakout_selected_catalyst_relief": {"applied": True},
                    },
                },
                {
                    "ticker": "000792",
                    "trade_date": "2026-03-24",
                    "candidate_source": "layer_c_watchlist",
                    "replayed_decision": "near_miss",
                    "stored_decision": "rejected",
                    "replayed_score_target": 0.512,
                    "replayed_gap_to_near_miss": -0.062,
                    "replayed_gap_to_selected": 0.068,
                    "delta_classification": "promoted",
                    "replay_input_path": str(report_dir / "selection_artifacts" / "2026-03-24" / "selection_target_replay_input.json"),
                    "replayed_top_reasons": ["confirmed_breakout"],
                    "replayed_blockers": [],
                    "replayed_gate_status": {"structural": "pass"},
                    "replayed_metrics_payload": {
                        "breakout_stage": "prepared_breakout",
                        "prepared_breakout_penalty_relief": {"applied": True},
                        "prepared_breakout_catalyst_relief": {"applied": True},
                        "prepared_breakout_volume_relief": {"applied": True},
                        "prepared_breakout_continuation_relief": {"applied": True},
                        "prepared_breakout_selected_catalyst_relief": {"applied": False},
                    },
                },
            ]
        },
    )

    analysis = analyze_btst_prepared_breakout_cohort(reports_root)

    assert analysis["candidate_count"] == 2
    assert analysis["next_candidate"]["ticker"] == "000792"
    assert analysis["next_candidate"]["verdict"] == "prepared_breakout_selected_frontier"
    assert analysis["selected_frontier_candidate_count"] == 1
    assert analysis["verdict"] == "selected_frontier_peer_found"
