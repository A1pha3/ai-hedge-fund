from __future__ import annotations

from src.targets.models import TargetEvaluationResult


def evaluate_short_trade_skeleton(*, trade_date: str, ticker: str) -> TargetEvaluationResult:
    return TargetEvaluationResult(
        target_type="short_trade",
        decision="rejected",
        score_target=0.0,
        confidence=0.0,
        positive_tags=[],
        negative_tags=["skeleton_only"],
        blockers=["short_trade_target_rules_not_implemented"],
        top_reasons=["short_trade target skeleton active without rule pack"],
        rejection_reasons=["short_trade_target_rules_not_implemented"],
        gate_status={"skeleton": "placeholder", "rules": "pending"},
        expected_holding_window="t1_short_trade",
        preferred_entry_mode="breakout_entry_pending",
        metrics_payload={"ticker": ticker},
        explainability_payload={"source": "short_trade_skeleton", "trade_date": trade_date},
    )