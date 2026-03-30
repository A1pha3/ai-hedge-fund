from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_btst_candidate_entry_window_scan import analyze_btst_candidate_entry_window_scan
from src.screening.models import StrategySignal
from src.targets.router import build_selection_targets


def _make_signal(direction: int, confidence: float, completeness: float = 1.0, sub_factors: dict | None = None) -> StrategySignal:
    return StrategySignal(
        direction=direction,
        confidence=confidence,
        completeness=completeness,
        sub_factors=sub_factors or {},
    )


def _write_replay_input(report_dir: Path, *, trade_date: str, entries: list[dict]) -> None:
    selection_targets, summary = build_selection_targets(
        trade_date=trade_date.replace("-", ""),
        watchlist=[],
        rejected_entries=entries,
        supplemental_short_trade_entries=[],
        buy_order_tickers=set(),
        target_mode="dual_target",
    )
    payload = {
        "artifact_version": "v1",
        "run_id": f"test_{report_dir.name}_{trade_date}",
        "trade_date": trade_date,
        "market": "CN",
        "target_mode": "dual_target",
        "pipeline_config_snapshot": {},
        "source_summary": {
            "watchlist_count": 0,
            "rejected_entry_count": len(entries),
            "supplemental_short_trade_entry_count": 0,
            "buy_order_ticker_count": 0,
        },
        "watchlist": [],
        "rejected_entries": [
            {
                **entry,
                "strategy_signals": {name: signal.model_dump(mode="json") for name, signal in entry["strategy_signals"].items()},
            }
            for entry in entries
        ],
        "supplemental_short_trade_entries": [],
        "buy_order_tickers": [],
        "selection_targets": {ticker: evaluation.model_dump(mode="json") for ticker, evaluation in selection_targets.items()},
        "target_summary": summary.model_dump(mode="json"),
    }
    target_dir = report_dir / "selection_artifacts" / trade_date
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "selection_target_replay_input.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_entry(ticker: str, *, weak_structure: bool) -> dict:
    if weak_structure:
        return {
            "ticker": ticker,
            "score_b": 0.3829,
            "score_c": -0.1194,
            "score_final": 0.1568,
            "quality_score": 0.9375,
            "decision": "avoid",
            "bc_conflict": "b_positive_c_strong_bearish",
            "candidate_source": "watchlist_filter_diagnostics",
            "candidate_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
            "reason": "decision_avoid",
            "strategy_signals": {
                "trend": _make_signal(
                    1,
                    70.0,
                    sub_factors={
                        "momentum": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                        "adx_strength": {"direction": 1, "confidence": 50.0, "completeness": 1.0},
                        "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                        "volatility": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                        "long_trend_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    },
                ),
                "event_sentiment": _make_signal(
                    0,
                    0.0,
                    sub_factors={
                        "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                        "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    },
                ),
                "mean_reversion": _make_signal(0, 0.0),
            },
            "agent_contribution_summary": {"cohort_contributions": {"analyst": -0.0646, "investor": -0.0548}},
        }
    return {
        "ticker": ticker,
        "score_b": 0.4199,
        "score_c": -0.0961,
        "score_final": 0.1877,
        "quality_score": 0.975,
        "decision": "avoid",
        "bc_conflict": "b_positive_c_strong_bearish",
        "candidate_source": "watchlist_filter_diagnostics",
        "candidate_reason_codes": ["decision_avoid", "score_final_below_watchlist_threshold"],
        "reason": "decision_avoid",
        "strategy_signals": {
            "trend": _make_signal(
                1,
                100.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 49.24, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                    "volatility": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 1, "confidence": 100.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                0,
                0.0,
                sub_factors={
                    "event_freshness": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 0, "confidence": 0.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 0.0),
        },
        "agent_contribution_summary": {"cohort_contributions": {"analyst": -0.0305, "investor": -0.0656}},
    }


def test_analyze_btst_candidate_entry_window_scan_shadow_only_single_window(tmp_path: Path) -> None:
    report_a = tmp_path / "paper_trading_window_20260323_20260326_live_m2_7_dual_target_replay_input_validation_20260329"
    _write_replay_input(report_a, trade_date="2026-03-26", entries=[_build_entry("300394", weak_structure=False), _build_entry("300502", weak_structure=True)])

    report_b = tmp_path / "paper_trading_window_20260316_20260323_live_m2_7_20260323"
    _write_replay_input(report_b, trade_date="2026-03-20", entries=[_build_entry("300394", weak_structure=False)])

    analysis = analyze_btst_candidate_entry_window_scan(
        [report_a, report_b],
        structural_variant="exclude_watchlist_avoid_weak_structure_entries",
        focus_tickers=["300502"],
        preserve_tickers=["300394"],
    )

    assert analysis["report_count"] == 2
    assert analysis["filtered_report_count"] == 1
    assert analysis["focus_hit_report_count"] == 1
    assert analysis["preserve_misfire_report_count"] == 0
    assert analysis["distinct_window_count_with_filtered_entries"] == 1
    assert analysis["rollout_readiness"] == "shadow_only_until_second_window"
    assert analysis["filtered_ticker_counts"] == {"300502": 1}
    assert analysis["window_status_counts"]["filters_focus_tickers"] == 1
    assert analysis["window_status_counts"]["no_filtered_entries"] == 1
