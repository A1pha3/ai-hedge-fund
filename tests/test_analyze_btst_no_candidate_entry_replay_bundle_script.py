from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.analyze_btst_no_candidate_entry_replay_bundle import analyze_btst_no_candidate_entry_replay_bundle
from src.screening.models import StrategySignal
from src.targets.router import build_selection_targets


def _write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _make_signal(direction: int, confidence: float, completeness: float = 1.0, sub_factors: dict | None = None) -> StrategySignal:
    return StrategySignal(
        direction=direction,
        confidence=confidence,
        completeness=completeness,
        sub_factors=sub_factors or {},
    )


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


def _write_replay_input(report_dir: Path, *, trade_date: str, weak_tickers: list[str]) -> None:
    entries = [_build_entry("300394", weak_structure=False)] + [_build_entry(ticker, weak_structure=True) for ticker in weak_tickers]
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
    selection_dir = report_dir / "selection_artifacts" / trade_date
    selection_dir.mkdir(parents=True, exist_ok=True)
    (selection_dir / "selection_target_replay_input.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_json(report_dir / "session_summary.json", {"plan_generation": {"selection_target": "dual_target"}})


def test_analyze_btst_no_candidate_entry_replay_bundle_builds_priority_and_window_scan(tmp_path: Path, monkeypatch) -> None:
    reports_root = tmp_path / "data" / "reports"
    research_report = reports_root / "paper_trading_20260302_20260313_btst_research_replay"
    window_report = reports_root / "paper_trading_window_20260323_20260326_btst_catalyst_floor_zero_refresh"
    _write_replay_input(research_report, trade_date="2026-03-23", weak_tickers=["300720"])
    _write_replay_input(window_report, trade_date="2026-03-25", weak_tickers=["003036"])

    action_board_path = _write_json(
        reports_root / "btst_no_candidate_entry_action_board_latest.json",
        {
            "reports_root": str(reports_root.resolve()),
            "preserve_tickers": ["300394"],
            "top_priority_tickers": ["300720", "003036"],
            "priority_queue": [
                {"priority_rank": 1, "ticker": "300720", "primary_report_dir": research_report.name},
                {"priority_rank": 2, "ticker": "003036", "primary_report_dir": window_report.name},
            ],
            "window_hotspot_rows": [
                {"priority_rank": 1, "report_dir": window_report.name, "top_focus_tickers": ["003036"]},
            ],
        },
    )

    def fake_get_price_data(ticker: str, start_date: str, end_date: str):
        price_rows = {
            "300394": [
                {"date": "2026-03-23", "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0},
                {"date": "2026-03-24", "open": 10.1, "high": 10.6, "low": 10.0, "close": 10.4},
                {"date": "2026-03-25", "open": 10.4, "high": 10.7, "low": 10.3, "close": 10.5},
                {"date": "2026-03-26", "open": 10.5, "high": 10.8, "low": 10.4, "close": 10.6},
                {"date": "2026-03-27", "open": 10.6, "high": 10.9, "low": 10.5, "close": 10.7},
            ],
            "300720": [
                {"date": "2026-03-23", "open": 8.0, "high": 8.1, "low": 7.9, "close": 8.0},
                {"date": "2026-03-24", "open": 7.9, "high": 8.0, "low": 7.7, "close": 7.8},
                {"date": "2026-03-25", "open": 7.8, "high": 7.9, "low": 7.5, "close": 7.6},
                {"date": "2026-03-26", "open": 7.6, "high": 7.7, "low": 7.4, "close": 7.5},
                {"date": "2026-03-27", "open": 7.5, "high": 7.6, "low": 7.3, "close": 7.4},
            ],
            "003036": [
                {"date": "2026-03-25", "open": 9.0, "high": 9.1, "low": 8.9, "close": 9.0},
                {"date": "2026-03-26", "open": 8.9, "high": 9.0, "low": 8.7, "close": 8.8},
                {"date": "2026-03-27", "open": 8.8, "high": 8.9, "low": 8.6, "close": 8.7},
                {"date": "2026-03-30", "open": 8.7, "high": 8.8, "low": 8.5, "close": 8.6},
                {"date": "2026-03-31", "open": 8.6, "high": 8.7, "low": 8.4, "close": 8.5},
            ],
        }
        return pd.DataFrame(price_rows[ticker]).assign(date=lambda data: pd.to_datetime(data["date"]).dt.normalize()).set_index("date")

    monkeypatch.setattr("scripts.btst_analysis_utils.get_price_data", fake_get_price_data)

    analysis = analyze_btst_no_candidate_entry_replay_bundle(
        action_board_path,
        priority_replay_limit=2,
        hotspot_replay_limit=1,
        global_scan_focus_limit=2,
    )

    assert analysis["promising_priority_tickers"] == ["300720", "003036"]
    assert analysis["best_variant_counts"]["weak_structure_triplet"] == 3
    assert analysis["candidate_entry_status_counts"]["filters_focus_and_weaker_than_false_negative_pool"] == 3
    assert analysis["global_window_scan"]["focus_hit_report_count"] == 1
    assert analysis["global_window_scan"]["rollout_readiness"] == "shadow_only_until_second_window"
    assert analysis["priority_replay_rows"][0]["viable_recall_probe"] is True
    assert analysis["priority_replay_rows"][0]["best_variant_name"] == "weak_structure_triplet"
    assert any("300720" in item for item in analysis["next_actions"])
    assert "preserve-safe candidate-entry recall probe" in analysis["recommendation"]