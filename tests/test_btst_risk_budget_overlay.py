from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.execution.daily_pipeline_buy_diagnostics_helpers import (
    _resolve_btst_position_budget,
    build_buy_orders_with_diagnostics,
)
from src.execution.daily_pipeline import _attach_btst_risk_budget_p6
from src.execution.models import ExecutionPlan
from src.execution.models import LayerCResult
from src.portfolio.models import PositionPlan
from src.screening.models import CandidateStock
from src.targets.models import DualTargetEvaluation, TargetEvaluationResult



def _selection_target(*, gate: str, prior_quality_label: str, execution_eligible: bool = True, candidate_source: str = "layer_c_watchlist") -> DualTargetEvaluation:
    return DualTargetEvaluation(
        ticker="300724",
        trade_date="20260422",
        execution_eligible=execution_eligible,
        candidate_source=candidate_source,
        p3_prior_quality_label=prior_quality_label,
        historical_prior_quality_level=prior_quality_label,
        btst_regime_gate=gate,
        short_trade=TargetEvaluationResult(
            target_type="short_trade",
            decision="selected" if execution_eligible else "near_miss",
            execution_eligible=execution_eligible,
            score_target=0.81,
            metrics_payload={
                "thresholds": {
                    "market_state_threshold_adjustment": {
                        "enabled": True,
                        "regime_gate_level": gate,
                        "risk_level": gate,
                    }
                }
            },
        ),
    )



def _watchlist_item(*, score_final: float = 0.55, quality_score: float = 0.5) -> LayerCResult:
    return LayerCResult(ticker="300724", score_b=0.72, score_c=0.64, score_final=score_final, quality_score=quality_score, decision="watch")



def test_p6_risk_budget_matrix_zeroes_non_tradeable_cases(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")
    item = _watchlist_item()
    candidate = CandidateStock(ticker="300724", name="Test", industry_sw="电子")

    cases = [
        ("halt", "execution_ready"),
        ("shadow_only", "execution_ready"),
        ("normal_trade", "watch_only"),
    ]

    for gate, prior_quality_label in cases:
        budget = _resolve_btst_position_budget(
            item=item,
            selection_target=_selection_target(gate=gate, prior_quality_label=prior_quality_label, execution_eligible=prior_quality_label == "execution_ready" and gate == "normal_trade"),
            candidate=candidate,
            nav=100000.0,
        )
        assert budget["formal_risk_budget_ratio"] == 0.0
        assert budget["formal_exposure_bucket"] == "zero_budget"



def test_p6_risk_budget_matrix_respects_btst_gate_when_market_state_uses_risk_off(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")
    target = _selection_target(gate="halt", prior_quality_label="execution_ready", execution_eligible=True)
    target.short_trade.metrics_payload["thresholds"]["market_state_threshold_adjustment"]["regime_gate_level"] = "risk_off"
    target.short_trade.metrics_payload["thresholds"]["market_state_threshold_adjustment"]["risk_level"] = "risk_off"

    budget = _resolve_btst_position_budget(
        item=_watchlist_item(score_final=0.88, quality_score=0.82),
        selection_target=target,
        candidate=CandidateStock(ticker="300724", name="Test", industry_sw="电子"),
        nav=100000.0,
    )

    assert budget["risk_budget_gate"] == "halt"
    assert budget["formal_risk_budget_ratio"] == 0.0
    assert budget["formal_exposure_bucket"] == "zero_budget"


def test_p6_risk_budget_matrix_caps_lower_quality_execution_eligible_case(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")

    budget = _resolve_btst_position_budget(
        item=_watchlist_item(score_final=0.32, quality_score=0.52),
        selection_target=_selection_target(gate="normal_trade", prior_quality_label="execution_ready", execution_eligible=True),
        candidate=CandidateStock(ticker="300724", name="Test", industry_sw="电子"),
        nav=100000.0,
    )

    assert budget["formal_risk_budget_ratio"] == pytest.approx(0.6)
    assert budget["formal_exposure_bucket"] == "reduced"
    assert budget["execution_contract_bucket"] == "formal_capped"



def test_build_buy_orders_with_diagnostics_applies_p6_overlay_to_position_sizing(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")
    watchlist = [_watchlist_item(score_final=0.55, quality_score=0.5)]
    selection_targets = {"300724": _selection_target(gate="normal_trade", prior_quality_label="execution_ready", execution_eligible=True)}

    buy_orders, diagnostics = build_buy_orders_with_diagnostics(
        watchlist=watchlist,
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        trade_date="20260422",
        candidate_by_ticker={"300724": CandidateStock(ticker="300724", name="Test", industry_sw="电子", avg_volume_20d=1000000.0)},
        price_map={"300724": 10.0},
        blocked_buy_tickers={},
        selection_targets=selection_targets,
        normalize_blocked_buy_tickers_fn=lambda payload: payload or {},
        build_filter_summary_fn=lambda entries: {"filtered_count": len(entries), "reason_counts": {}, "tickers": entries},
        build_reentry_filter_entry_fn=lambda *args, **kwargs: None,
        resolve_continuation_execution_overrides_fn=lambda **kwargs: {},
        calculate_position_fn=__import__("src.portfolio.position_calculator", fromlist=["calculate_position"]).calculate_position,
        enforce_daily_trade_limit_fn=lambda plans, nav: plans,
    )

    assert len(buy_orders) == 1
    assert buy_orders[0].shares == 600
    assert buy_orders[0].amount == pytest.approx(6000.0)
    assert buy_orders[0].risk_budget_ratio == pytest.approx(0.6)
    assert diagnostics["btst_risk_budget_overlay"]["formal_exposure_distribution"] == {"reduced": 1}



def test_build_buy_orders_with_diagnostics_zeroes_watch_only_formal_exposure(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "enforce")
    watchlist = [_watchlist_item(score_final=0.55, quality_score=0.7)]
    selection_targets = {"300724": _selection_target(gate="normal_trade", prior_quality_label="watch_only", execution_eligible=False)}

    buy_orders, diagnostics = build_buy_orders_with_diagnostics(
        watchlist=watchlist,
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        trade_date="20260422",
        candidate_by_ticker={"300724": CandidateStock(ticker="300724", name="Test", industry_sw="电子", avg_volume_20d=1000000.0)},
        price_map={"300724": 10.0},
        blocked_buy_tickers={},
        selection_targets=selection_targets,
        normalize_blocked_buy_tickers_fn=lambda payload: payload or {},
        build_filter_summary_fn=lambda entries: {"filtered_count": len(entries), "reason_counts": {}, "tickers": entries},
        build_reentry_filter_entry_fn=lambda *args, **kwargs: None,
        resolve_continuation_execution_overrides_fn=lambda **kwargs: {},
        calculate_position_fn=__import__("src.portfolio.position_calculator", fromlist=["calculate_position"]).calculate_position,
        enforce_daily_trade_limit_fn=lambda plans, nav: plans,
    )

    assert buy_orders == []
    assert diagnostics["btst_risk_budget_overlay"]["suppressed_position_summary"]["zero_budget_count"] == 1
    assert diagnostics["tickers"][0]["reason"] == "position_blocked_risk_budget_overlay"



def test_p6_off_preserves_existing_position_sizing(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "off")
    watchlist = [_watchlist_item(score_final=0.55, quality_score=0.5)]
    selection_targets = {"300724": _selection_target(gate="normal_trade", prior_quality_label="execution_ready", execution_eligible=True)}

    buy_orders, diagnostics = build_buy_orders_with_diagnostics(
        watchlist=watchlist,
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        trade_date="20260422",
        candidate_by_ticker={"300724": CandidateStock(ticker="300724", name="Test", industry_sw="电子", avg_volume_20d=1000000.0)},
        price_map={"300724": 10.0},
        blocked_buy_tickers={},
        selection_targets=selection_targets,
        normalize_blocked_buy_tickers_fn=lambda payload: payload or {},
        build_filter_summary_fn=lambda entries: {"filtered_count": len(entries), "reason_counts": {}, "tickers": entries},
        build_reentry_filter_entry_fn=lambda *args, **kwargs: None,
        resolve_continuation_execution_overrides_fn=lambda **kwargs: {},
        calculate_position_fn=__import__("src.portfolio.position_calculator", fromlist=["calculate_position"]).calculate_position,
        enforce_daily_trade_limit_fn=lambda plans, nav: plans,
    )

    assert len(buy_orders) == 1
    assert buy_orders[0].shares == 1000
    assert buy_orders[0].amount == pytest.approx(10000.0)
    assert diagnostics["btst_risk_budget_overlay"]["mode"] == "off"



def test_attach_btst_risk_budget_p6_off_does_not_annotate_plan(monkeypatch):
    monkeypatch.setenv("BTST_0422_P6_RISK_BUDGET_MODE", "off")
    target = _selection_target(gate="normal_trade", prior_quality_label="execution_ready", execution_eligible=True)
    plan = ExecutionPlan(
        date="2026-04-22",
        portfolio_snapshot={"cash": 100000.0, "positions": {}},
        watchlist=[_watchlist_item(score_final=0.55, quality_score=0.5)],
        selection_targets={"300724": target},
        buy_orders=[PositionPlan(ticker="300724", shares=1000, amount=10000.0, score_final=0.55, execution_ratio=1.0, quality_score=0.5)],
        risk_metrics={},
    )

    updated = _attach_btst_risk_budget_p6(plan)

    assert "p6_risk_budget" not in updated.selection_targets["300724"].short_trade.metrics_payload
    assert "p6_risk_budget" not in updated.selection_targets["300724"].short_trade.explainability_payload
    assert "btst_risk_budget_p6_enforcement" not in updated.risk_metrics


def test_analyze_btst_risk_budget_overlay_eval_returns_required_shape(tmp_path: Path) -> None:
    from scripts.analyze_btst_risk_budget_overlay_eval import analyze_btst_risk_budget_overlay_eval, _render_markdown

    report_dir = tmp_path / "paper_trading_window_sample"
    (report_dir / "selection_artifacts" / "2026-04-22").mkdir(parents=True)
    (report_dir / "selection_artifacts" / "2026-04-22" / "selection_snapshot.json").write_text(
        json.dumps(
            {
                "trade_date": "2026-04-22",
                "selection_targets": {
                    "300724": {
                        "ticker": "300724",
                        "candidate_source": "layer_c_watchlist",
                        "execution_eligible": True,
                        "historical_prior_quality_level": "execution_ready",
                        "btst_regime_gate": "normal_trade",
                        "short_trade": {
                            "decision": "selected",
                            "metrics_payload": {
                                "p6_risk_budget": {
                                    "mode": "enforce",
                                    "risk_budget_ratio": 0.6,
                                    "formal_exposure_bucket": "reduced",
                                    "execution_contract_bucket": "formal_capped",
                                }
                            },
                        },
                    },
                    "688313": {
                        "ticker": "688313",
                        "candidate_source": "layer_c_watchlist",
                        "execution_eligible": False,
                        "historical_prior_quality_level": "watch_only",
                        "btst_regime_gate": "shadow_only",
                        "short_trade": {
                            "decision": "near_miss",
                            "metrics_payload": {
                                "p6_risk_budget": {
                                    "mode": "enforce",
                                    "risk_budget_ratio": 0.0,
                                    "formal_exposure_bucket": "zero_budget",
                                    "execution_contract_bucket": "watch_only",
                                }
                            },
                        },
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    (report_dir / "session_summary.json").write_text(
        json.dumps(
            {
                "btst_risk_budget_p6_summary": {
                    "gate_distribution": {"normal_trade": 1, "shadow_only": 1},
                    "formal_exposure_distribution": {"reduced": 1, "zero_budget": 1},
                    "suppressed_position_summary": {"zero_budget_count": 1, "reduced_budget_count": 1},
                }
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    analysis = analyze_btst_risk_budget_overlay_eval(report_dir)

    assert analysis["report_type"] == "p6_btst_risk_budget_overlay_eval"
    assert analysis["snapshot_count"] == 1
    assert "risk_budget_matrix" in analysis
    assert analysis["gate_distribution"] == {"normal_trade": 1, "shadow_only": 1}
    assert analysis["formal_exposure_distribution"] == {"reduced": 1, "zero_budget": 1}
    assert analysis["suppressed_position_summary"] == {"zero_budget_count": 1, "reduced_budget_count": 1}
    assert analysis["strong_day_retention_summary"] == {
        "strong_day_candidate_count": 1,
        "retained_formal_exposure_count": 1,
        "retained_formal_exposure_rate": 1.0,
    }
    markdown = _render_markdown(analysis)
    assert "风险预算矩阵说明" in markdown
    assert "强势日正式暴露保留" in markdown
    assert "normal_trade × execution_ready × formal_capped" in markdown
