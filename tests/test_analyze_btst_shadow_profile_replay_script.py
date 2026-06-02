from __future__ import annotations

import json
from pathlib import Path

from src.execution.daily_pipeline import _serialize_short_trade_target_profile
from src.execution.models import ExecutionPlan, LayerCResult
from src.screening.models import MarketState, StrategySignal
from src.targets import build_short_trade_target_profile
from src.targets.models import DualTargetEvaluation

import scripts.analyze_btst_shadow_profile_replay as shadow_profile_replay


def _make_signal(direction: int, confidence: float, completeness: float = 1.0, sub_factors: dict | None = None) -> StrategySignal:
    return StrategySignal(
        direction=direction,
        confidence=confidence,
        completeness=completeness,
        sub_factors=sub_factors or {},
    )


def _build_frozen_plan(*, trade_date: str = "20260421", include_existing_buy_order: bool = False) -> ExecutionPlan:
    watchlist_entry = LayerCResult(
        ticker="300620",
        score_b=0.60,
        score_c=0.60,
        score_final=0.40,
        quality_score=0.63,
        decision="watch",
        candidate_source="layer_c_watchlist",
        strategy_signals={
            "trend": _make_signal(
                1,
                60.0,
                sub_factors={
                    "momentum": {"direction": 1, "confidence": 28.0, "completeness": 1.0},
                    "adx_strength": {"direction": 1, "confidence": 34.0, "completeness": 1.0},
                    "ema_alignment": {"direction": 1, "confidence": 44.0, "completeness": 1.0},
                    "volatility": {"direction": 1, "confidence": 42.0, "completeness": 1.0},
                    "long_trend_alignment": {"direction": 0, "confidence": 10.0, "completeness": 1.0},
                },
            ),
            "event_sentiment": _make_signal(
                1,
                60.0,
                sub_factors={
                    "event_freshness": {"direction": 1, "confidence": 30.0, "completeness": 1.0},
                    "news_sentiment": {"direction": 1, "confidence": 80.0, "completeness": 1.0},
                },
            ),
            "mean_reversion": _make_signal(0, 0.0),
        },
        agent_contribution_summary={"cohort_contributions": {"analyst": 0.40, "investor": 0.20}},
    )
    preserved_selected_target = DualTargetEvaluation.model_validate(
        {
            "ticker": "300620",
            "trade_date": trade_date,
            "candidate_source": "layer_c_watchlist",
            "execution_eligible": True,
            "short_trade": {
                "target_type": "short_trade",
                "decision": "selected",
                "score_target": 0.52,
                "confidence": 0.63,
                "preferred_entry_mode": "next_day_breakout_confirmation",
                "execution_eligible": True,
                "downgrade_reasons": [],
                "historical_prior_quality_level": "execution_ready",
                "btst_regime_gate": "normal_trade",
                "candidate_source": "layer_c_watchlist",
                "gate_status": {
                    "data": "pass",
                    "execution": "pass",
                    "structural": "pass",
                    "score": "pass",
                },
                "metrics_payload": {"execution_eligible": True},
                "explainability_payload": {"candidate_source": "layer_c_watchlist"},
            },
        }
    )
    baseline_profile = build_short_trade_target_profile("btst_precision_v2")
    return ExecutionPlan(
        date=trade_date,
        target_mode="short_trade_only",
        market_state=MarketState(
            breadth_ratio=0.66,
            daily_return=-0.004,
            style_dispersion=0.18,
            regime_flip_risk=0.08,
            regime_gate_level="normal",
        ),
        watchlist=[watchlist_entry],
        selection_targets={"300620": preserved_selected_target},
        short_trade_target_profile_name="btst_precision_v2",
        short_trade_target_profile_config=_serialize_short_trade_target_profile(baseline_profile),
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        buy_orders=[
            {
                "ticker": "300620",
                "shares": 100,
                "amount": 12000.0,
                "score_final": 0.52,
                "execution_ratio": 0.3,
            }
        ]
        if include_existing_buy_order
        else [],
    )


def _write_frozen_plan_source(tmp_path: Path, *, trade_date: str = "20260421", include_existing_buy_order: bool = False) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source_path = tmp_path / "daily_events.jsonl"
    frozen_plan = _build_frozen_plan(trade_date=trade_date, include_existing_buy_order=include_existing_buy_order)
    source_path.write_text(
        json.dumps(
            {
                "event": "paper_trading_day",
                "trade_date": trade_date,
                "current_plan": frozen_plan.model_dump(mode="json"),
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return source_path


def _write_selection_target_replay_input(tmp_path: Path, *, trade_date: str = "20260421") -> Path:
    from src.research.artifacts import build_selection_target_replay_input

    tmp_path.mkdir(parents=True, exist_ok=True)
    date_folder = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}"
    artifact_dir = tmp_path / "selection_artifacts" / date_folder
    artifact_dir.mkdir(parents=True, exist_ok=True)
    replay_input_path = artifact_dir / "selection_target_replay_input.json"

    frozen_plan = _build_frozen_plan(trade_date=trade_date)
    replay_input = build_selection_target_replay_input(
        plan=frozen_plan,
        trade_date=trade_date,
        run_id="test",
        pipeline=None,
        selected_analysts=None,
        experiment_id=None,
        market="CN",
        artifact_version="v1",
    )

    payload = replay_input.model_dump(mode="json")
    # Make sure the rebuilt selection_targets sees this as a strong candidate under the baseline profile.
    for row in list(payload.get("watchlist") or []):
        if str(row.get("ticker") or "").strip() == "300620":
            row["score_b"] = 0.95
            row["score_c"] = 0.95
            row["score_final"] = 0.95
            row["quality_score"] = 0.95

    replay_input_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return replay_input_path


def test_analyze_btst_shadow_profile_replay_compares_baseline_and_shadow_replay(tmp_path: Path) -> None:
    source_path = _write_frozen_plan_source(tmp_path)
    output_json = tmp_path / "shadow_profile_replay.json"
    output_markdown = tmp_path / "shadow_profile_replay.md"

    analysis = shadow_profile_replay.analyze_btst_shadow_profile_replay(
        frozen_plan_source=source_path,
        baseline_profile="btst_precision_v2",
        shadow_profile="btst_precision_v2_layer_c_watchlist_shadow",
        output_json_path=output_json,
        output_markdown_path=output_markdown,
    )

    assert analysis["trade_dates"] == ["20260421"]
    assert analysis["baseline"]["buy_order_tickers_by_date"] == {"20260421": ["300620"]}
    assert analysis["shadow"]["buy_order_tickers_by_date"] == {"20260421": []}
    assert analysis["delta"]["buy_orders_removed_by_date"] == {"20260421": ["300620"]}
    assert analysis["delta"]["execution_eligibility_lost_by_date"] == {"20260421": ["300620"]}

    eval_by_date = analysis["delta"].get("removed_ticker_eval_snapshot_by_date") or {}
    assert eval_by_date["20260421"]["300620"]["baseline"]["short_trade"]["decision"] == "selected"
    assert eval_by_date["20260421"]["300620"]["baseline"]["execution_eligible"] is True
    assert eval_by_date["20260421"]["300620"]["shadow"]["execution_eligible"] is False

    persisted_json = json.loads(output_json.read_text(encoding="utf-8"))
    assert persisted_json["shadow"]["profile_name"] == "btst_precision_v2_layer_c_watchlist_shadow"
    markdown = output_markdown.read_text(encoding="utf-8")
    assert "btst_precision_v2_layer_c_watchlist_shadow" in markdown
    assert "300620" in markdown


def test_analyze_btst_shadow_profile_replay_rebuilds_from_empty_buy_orders_when_frozen_plan_keeps_stale_buy_order(tmp_path: Path) -> None:
    source_path = _write_frozen_plan_source(tmp_path, include_existing_buy_order=True)

    analysis = shadow_profile_replay.analyze_btst_shadow_profile_replay(
        frozen_plan_source=source_path,
        baseline_profile="btst_precision_v2",
        shadow_profile="btst_precision_v2_layer_c_watchlist_shadow",
    )

    assert analysis["baseline"]["buy_order_tickers_by_date"] == {"20260421": ["300620"]}
    assert analysis["shadow"]["buy_order_tickers_by_date"] == {"20260421": []}
    assert analysis["delta"]["buy_orders_removed_by_date"] == {"20260421": ["300620"]}


def test_analyze_btst_shadow_profile_replay_accepts_profile_overrides(tmp_path: Path) -> None:
    source_path = _write_frozen_plan_source(tmp_path)

    analysis = shadow_profile_replay.analyze_btst_shadow_profile_replay(
        frozen_plan_source=source_path,
        baseline_profile="momentum_optimized",
        baseline_profile_overrides={"select_threshold": 0.38, "layer_c_watchlist_selected_rank_cap": 1},
        shadow_profile="momentum_optimized",
        shadow_profile_overrides={"select_threshold": 0.38, "layer_c_watchlist_selected_rank_cap": 0},
    )

    assert analysis["baseline"]["profile_name"] == "momentum_optimized"
    assert analysis["shadow"]["profile_name"] == "momentum_optimized"
    assert analysis["baseline"]["profile_overrides"] == {"select_threshold": 0.38, "layer_c_watchlist_selected_rank_cap": 1}
    assert analysis["shadow"]["profile_overrides"] == {"select_threshold": 0.38, "layer_c_watchlist_selected_rank_cap": 0}
    assert analysis["baseline"]["selected_tickers_by_date"] == {"20260421": ["300620"]}
    assert analysis["shadow"]["selected_tickers_by_date"] == {"20260421": []}
    assert analysis["delta"]["selected_removed_by_date"] == {"20260421": ["300620"]}


def test_analyze_btst_shadow_profile_replay_accepts_multiple_frozen_sources(tmp_path: Path) -> None:
    source_path_day1 = _write_frozen_plan_source(tmp_path / "day1", trade_date="20260421")
    source_path_day2 = _write_frozen_plan_source(tmp_path / "day2", trade_date="20260422")

    analysis = shadow_profile_replay.analyze_btst_shadow_profile_replay(
        frozen_plan_source=[source_path_day1, source_path_day2],
        baseline_profile="btst_precision_v2",
        shadow_profile="btst_precision_v2_layer_c_watchlist_shadow",
    )

    assert analysis["trade_dates"] == ["20260421", "20260422"]
    assert analysis["baseline"]["buy_order_tickers_by_date"] == {
        "20260421": ["300620"],
        "20260422": ["300620"],
    }
    assert analysis["shadow"]["buy_order_tickers_by_date"] == {
        "20260421": [],
        "20260422": [],
    }


def test_analyze_btst_shadow_profile_replay_accepts_weekly_validation_json(tmp_path: Path) -> None:
    report_root = tmp_path / "reports"
    report_a = report_root / "paper_trading_20260421_plan"
    report_b = report_root / "paper_trading_20260422_plan"
    source_a = _write_frozen_plan_source(report_a, trade_date="20260421")
    source_b = _write_frozen_plan_source(report_b, trade_date="20260422")
    weekly_validation_json = tmp_path / "weekly_validation.json"
    weekly_validation_json.write_text(
        json.dumps(
            {
                "selected_reports": [
                    {"trade_date": "2026-04-21", "report_dir": str(report_a.resolve())},
                    {"trade_date": "2026-04-22", "report_dir": str(report_b.resolve())},
                ]
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    analysis = shadow_profile_replay.analyze_btst_shadow_profile_replay(
        weekly_validation_json=weekly_validation_json,
        baseline_profile="btst_precision_v2",
        shadow_profile="btst_precision_v2_layer_c_watchlist_shadow",
    )

    assert analysis["frozen_plan_source"] == [str(source_a.resolve()), str(source_b.resolve())]
    assert analysis["trade_dates"] == ["20260421", "20260422"]


def test_analyze_btst_shadow_profile_replay_adds_removed_ticker_source_attribution_when_selection_artifacts_present(tmp_path: Path) -> None:
    source_path = _write_frozen_plan_source(tmp_path, trade_date="20260421")

    analysis = shadow_profile_replay.analyze_btst_shadow_profile_replay(
        frozen_plan_source=source_path,
        baseline_profile="btst_precision_v2",
        shadow_profile="btst_precision_v2_layer_c_watchlist_shadow",
    )

    hits_by_date = analysis["delta"].get("removed_ticker_source_hits_by_date") or {}
    hits = hits_by_date.get("20260421") or {}
    assert hits["300620"]["candidate_source_counts"]["layer_c_watchlist"] >= 1
    assert hits["300620"]["total_hits"] >= 1

    eval_by_date = analysis["delta"].get("removed_ticker_eval_snapshot_by_date") or {}
    assert eval_by_date["20260421"]["300620"]["baseline"]["short_trade"]["decision"] == "selected"
