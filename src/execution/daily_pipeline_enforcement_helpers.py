"""P3/P5/P6 execution enforcement helpers extracted from daily_pipeline.py.

P3 (prior quality): blocks selection_targets with poor historical priors.
P5 (execution contract): enforces gate, prior quality, and source eligibility on buy_orders.
P6 (risk budget): attaches risk budget metadata and overlays position budgets.

These functions are re-exported from daily_pipeline.py for backward compatibility.
"""
from __future__ import annotations

import os
from typing import Any

from src.execution.btst_shadow_promotion_helpers import resolve_btst_shadow_promotion_payload
from src.execution.daily_pipeline_buy_diagnostics_helpers import (
    _apply_btst_risk_budget_overlay_to_plan,
    _resolve_btst_position_budget,
)
from src.execution.models import ExecutionPlan
from src.targets.router import summarize_selection_targets

# Re-exported from daily_pipeline_regime_gate_helpers for use in P5
from src.execution.daily_pipeline_regime_gate_helpers import get_or_classify_gate as _get_or_classify_gate

BTST_0422_P3_PRIOR_QUALITY_MODE_ENV = "BTST_0422_P3_PRIOR_QUALITY_MODE"
BTST_0422_P3_PRIOR_QUALITY_MODES = frozenset({"off", "enforce"})
BTST_0422_P4_PRIOR_SHRINKAGE_MODE_ENV = "BTST_0422_P4_PRIOR_SHRINKAGE_MODE"
BTST_0422_P4_PRIOR_SHRINKAGE_MODES = frozenset({"off", "enforce"})
BTST_0422_P5_EXECUTION_CONTRACT_MODE_ENV = "BTST_0422_P5_EXECUTION_CONTRACT_MODE"
BTST_0422_P5_EXECUTION_CONTRACT_MODES = frozenset({"off", "enforce"})
BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE_ENV = "BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE"
BTST_0422_P6_RISK_BUDGET_MODE_ENV = "BTST_0422_P6_RISK_BUDGET_MODE"
BTST_0422_P6_RISK_BUDGET_MODES = frozenset({"off", "enforce"})


# ── P3: Prior Quality ──────────────────────────────────────────────────────────

def resolve_btst_prior_quality_p3_mode() -> str:
    normalized_mode = str(os.getenv(BTST_0422_P3_PRIOR_QUALITY_MODE_ENV, "off") or "off").strip().lower()
    return normalized_mode if normalized_mode in BTST_0422_P3_PRIOR_QUALITY_MODES else "off"


def extract_frozen_prior_by_ticker(plan: ExecutionPlan) -> dict[str, dict[str, Any]]:
    risk_metrics = dict(getattr(plan, "risk_metrics", {}) or {})
    explicit_mapping = dict(risk_metrics.get("historical_prior_by_ticker", {}) or {})
    if explicit_mapping:
        return {str(ticker): dict(payload or {}) for ticker, payload in explicit_mapping.items() if str(ticker or "").strip() and isinstance(payload, dict)}

    recovered: dict[str, dict[str, Any]] = {}
    for ticker, evaluation in dict(getattr(plan, "selection_targets", {}) or {}).items():
        short_trade = getattr(evaluation, "short_trade", None)
        metrics_payload = dict(getattr(short_trade, "metrics_payload", {}) or {}) if short_trade is not None else {}
        historical_prior = dict(metrics_payload.get("historical_prior", {}) or {})
        if historical_prior:
            recovered[str(ticker)] = historical_prior
    return recovered


def enforce_btst_prior_quality_p3(plan: ExecutionPlan, *, prior_by_ticker: dict[str, dict[str, Any]]) -> ExecutionPlan:
    """P3 prior quality hard gate: annotate and block selection_targets with poor historical priors.

    Only active when BTST_0422_P3_PRIOR_QUALITY_MODE=enforce.
    Preserves backward compatibility — off by default.
    Reuses prior_by_ticker already loaded during post-market watchlist context construction.

    In enforce mode:
      1. Classifies each selection target's historical prior and marks p3_execution_blocked.
      2. Removes buy orders for P3-blocked tickers from plan.buy_orders.
      3. Rebuilds plan.dual_target_summary to reflect post-enforcement P3 counts.
    """
    from src.targets.prior_quality import (
        apply_p3_prior_quality_gate_to_selection_targets,
    )
    from src.targets.router_build_helpers import build_dual_target_summary

    mode = resolve_btst_prior_quality_p3_mode()
    if mode != "enforce":
        return plan

    plan = plan.model_copy(deep=True)
    selection_targets = plan.selection_targets or {}
    if selection_targets:
        apply_p3_prior_quality_gate_to_selection_targets(
            selection_targets,
            mode=mode,
            prior_by_ticker=prior_by_ticker,
        )

    # Gap 1 fix: filter buy_orders to remove P3-blocked tickers.
    blocked_tickers = {ticker for ticker, ev in selection_targets.items() if ev.p3_execution_blocked}
    if blocked_tickers and plan.buy_orders:
        original_count = len(plan.buy_orders)
        plan.buy_orders = [o for o in plan.buy_orders if o.ticker not in blocked_tickers]
        buy_orders_removed = original_count - len(plan.buy_orders)
    else:
        buy_orders_removed = 0

    p3_blocked_count = len(blocked_tickers)
    enforcement_payload: dict[str, Any] = {
        "mode": "enforce",
        "p3_execution_blocked_count": p3_blocked_count,
        "buy_orders_removed": buy_orders_removed,
    }

    risk_metrics = dict(getattr(plan, "risk_metrics", {}) or {})
    funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics", {}) or {})
    risk_metrics["btst_prior_quality_p3_enforcement"] = enforcement_payload
    funnel_diagnostics["btst_prior_quality_p3_enforcement"] = enforcement_payload
    risk_metrics["funnel_diagnostics"] = funnel_diagnostics
    # Keep buy_order_count in sync with the actual post-enforcement list length.
    if buy_orders_removed:
        counts = dict(risk_metrics.get("counts", {}))
        counts["buy_order_count"] = len(plan.buy_orders)
        risk_metrics["counts"] = counts
    plan.risk_metrics = risk_metrics

    # Gap 2 fix: rebuild dual_target_summary so P3 counts are live (not pre-enforcement stale).
    if selection_targets:
        plan.dual_target_summary = build_dual_target_summary(
            selection_targets=selection_targets,
            target_mode=plan.target_mode,
        )

    return plan


# ── P5: Execution Contract ─────────────────────────────────────────────────────

def resolve_btst_execution_contract_p5_mode() -> str:
    normalized_mode = str(os.getenv(BTST_0422_P5_EXECUTION_CONTRACT_MODE_ENV, "off") or "off").strip().lower()
    return normalized_mode if normalized_mode in BTST_0422_P5_EXECUTION_CONTRACT_MODES else "off"


def resolve_btst_win_rate_first_precision_mode() -> bool:
    """Resolve win-rate-first precision mode from environment.

    When enabled, tightens P5 enforcement to downgrade any candidate without
    execution_ready prior quality. This mode requires P5 enforce mode to be active.
    Default: False (off) to preserve baseline behavior.
    """
    raw = str(os.getenv(BTST_0422_P5_WIN_RATE_FIRST_PRECISION_MODE_ENV, "false") or "false").strip().lower()
    return raw in {"true", "1", "yes", "on"}


def enforce_btst_execution_contract_p5(plan: ExecutionPlan) -> ExecutionPlan:
    from src.targets.router_build_helpers import build_dual_target_summary
    from src.targets.router_build_helpers import collect_formal_execution_block_flags

    if resolve_btst_execution_contract_p5_mode() != "enforce":
        return plan

    plan = plan.model_copy(deep=True)
    selection_targets = plan.selection_targets or {}
    if not selection_targets:
        return plan

    gate = _get_or_classify_gate(plan) or ""
    allowed_gate = gate in {"", "normal_trade", "aggressive_trade"}
    win_rate_first_precision_mode = resolve_btst_win_rate_first_precision_mode()
    downgrade_reason_counts: dict[str, int] = {}
    downgraded_tickers: set[str] = set()

    for ticker, evaluation in selection_targets.items():
        short_trade_result = evaluation.short_trade
        prior_quality_level = str(evaluation.p3_prior_quality_label or evaluation.historical_prior_quality_level or "").strip() or None
        shadow_promotion = resolve_btst_shadow_promotion_payload(
            evaluation=evaluation,
            short_trade_result=short_trade_result,
            gate=gate,
        )
        shadow_promotion_applied = bool(shadow_promotion.get("eligible"))
        if short_trade_result is not None and shadow_promotion.get("promoted_from_near_miss"):
            short_trade_result.decision = "selected"
            positive_tags = [str(tag) for tag in list(short_trade_result.positive_tags or []) if str(tag or "").strip()]
            if "shadow_promotion_lane" not in positive_tags:
                positive_tags.append("shadow_promotion_lane")
            short_trade_result.positive_tags = positive_tags
        downgrade_reasons: list[str] = []

        # Check if this is already formally blocked (P2/P3/P5/P6)
        # If so, we must NOT downgrade it - preserve the raw selected decision for correct blocked-selected provenance
        formal_execution_block_flags = collect_formal_execution_block_flags(evaluation, short_trade_result)
        is_formally_blocked = bool(formal_execution_block_flags)

        if short_trade_result is not None and short_trade_result.decision == "selected":
            # CRITICAL: Do NOT collect downgrade reasons if already formally blocked
            # Formal blocks are upstream hard stops - we don't need to re-reason about them
            if not is_formally_blocked:
                if not (allowed_gate or shadow_promotion_applied):
                    downgrade_reasons.append("btst_regime_gate_not_tradeable")

                if win_rate_first_precision_mode:
                    if prior_quality_level != "execution_ready" and not shadow_promotion_applied:
                        downgrade_reasons.append("win_rate_first_precision_prior_not_execution_ready")
                else:
                    if prior_quality_level not in {None, "", "execution_ready"} and not shadow_promotion_applied:
                        downgrade_reasons.append("historical_prior_not_execution_ready")
                if str(evaluation.candidate_source or "").strip() in {"upgrade_only", "research_only"}:
                    downgrade_reasons.append("research_only_source_not_formal_execution")

            # CRITICAL: Only apply downgrade if NOT already formally blocked
            # Formally-blocked names must preserve their raw "selected" decision for correct reporting
            # (blocked-selected provenance in build_reporting_target_summary)
            # But still mark execution_eligible=False and clear buy orders
            if downgrade_reasons and not is_formally_blocked:
                short_trade_result.decision = "near_miss"
                downgraded_tickers.add(str(ticker))

        # CRITICAL: A name is execution_eligible ONLY if:
        # 1. short_trade decision is "selected" (raw or preserved)
        # 2. AND NOT formally blocked (p2/p3/p5/p6_execution_blocked)
        # 3. AND has no downgrade reasons (gate, prior quality, source)
        execution_eligible = bool(short_trade_result is not None and short_trade_result.decision == "selected" and not is_formally_blocked and not downgrade_reasons)
        evaluation.execution_eligible = execution_eligible
        evaluation.downgrade_reasons = list(downgrade_reasons)
        evaluation.historical_prior_quality_level = prior_quality_level
        evaluation.btst_regime_gate = gate or None

        if short_trade_result is not None:
            short_trade_result.execution_eligible = execution_eligible
            short_trade_result.downgrade_reasons = list(downgrade_reasons)
            short_trade_result.historical_prior_quality_level = prior_quality_level
            short_trade_result.btst_regime_gate = gate or None
            metrics_payload = dict(short_trade_result.metrics_payload or {})
            explainability_payload = dict(short_trade_result.explainability_payload or {})
            metrics_payload.update(
                {
                    "execution_eligible": execution_eligible,
                    "downgrade_reasons": list(downgrade_reasons),
                    "historical_prior_quality_level": prior_quality_level,
                    "btst_regime_gate": gate or None,
                    "shadow_promotion": dict(shadow_promotion),
                }
            )
            explainability_payload.update(
                {
                    "execution_eligible": execution_eligible,
                    "downgrade_reasons": list(downgrade_reasons),
                    "historical_prior_quality_level": prior_quality_level,
                    "btst_regime_gate": gate or None,
                    "shadow_promotion": dict(shadow_promotion),
                }
            )
            short_trade_result.metrics_payload = metrics_payload
            short_trade_result.explainability_payload = explainability_payload

        for reason in downgrade_reasons:
            downgrade_reason_counts[reason] = int(downgrade_reason_counts.get(reason) or 0) + 1

    original_buy_order_count = len(plan.buy_orders)
    eligible_tickers = {ticker for ticker, evaluation in selection_targets.items() if evaluation.execution_eligible}
    plan.buy_orders = [order for order in plan.buy_orders if order.ticker in eligible_tickers]
    risk_metrics = dict(getattr(plan, "risk_metrics", {}) or {})
    p2_enforcement = dict(risk_metrics.get("btst_regime_gate_enforcement", {}) or {})
    upstream_cleared_count = int(p2_enforcement.get("buy_orders_cleared_count") or 0)
    funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics", {}) or {})
    enforcement_payload = {
        "mode": "enforce",
        "gate": gate or None,
        "execution_eligible_count": len(eligible_tickers),
        "downgraded_to_near_miss_count": len(downgraded_tickers),
        "buy_orders_removed": max(0, original_buy_order_count - len(plan.buy_orders)),
        "buy_orders_already_cleared_upstream_count": upstream_cleared_count,
        "downgrade_reason_counts": downgrade_reason_counts,
    }
    risk_metrics["btst_execution_contract_p5_enforcement"] = enforcement_payload
    funnel_diagnostics["btst_execution_contract_p5_enforcement"] = enforcement_payload
    counts = dict(risk_metrics.get("counts", {}) or {})
    counts["buy_order_count"] = len(plan.buy_orders)
    risk_metrics["counts"] = counts
    risk_metrics["funnel_diagnostics"] = funnel_diagnostics
    plan.risk_metrics = risk_metrics
    plan.dual_target_summary = build_dual_target_summary(selection_targets=selection_targets, target_mode=plan.target_mode)
    return plan


# ── P6: Risk Budget ────────────────────────────────────────────────────────────

def resolve_btst_risk_budget_p6_mode() -> str:
    normalized_mode = str(os.getenv(BTST_0422_P6_RISK_BUDGET_MODE_ENV, "off") or "off").strip().lower()
    return normalized_mode if normalized_mode in BTST_0422_P6_RISK_BUDGET_MODES else "off"


def attach_btst_risk_budget_p6(plan: ExecutionPlan) -> ExecutionPlan:
    mode = resolve_btst_risk_budget_p6_mode()
    if mode != "enforce":
        return plan
    plan = plan.model_copy(deep=True)
    selection_targets = dict(getattr(plan, "selection_targets", {}) or {})
    watchlist_by_ticker = {str(item.ticker): item for item in list(getattr(plan, "watchlist", []) or [])}
    buy_order_by_ticker = {str(order.ticker): order for order in list(getattr(plan, "buy_orders", []) or [])}
    nav = float((plan.portfolio_snapshot or {}).get("cash", 0.0) or 0.0)
    nav += sum(float(position.get("long", 0) or 0) * float(position.get("long_cost_basis", 0.0) or 0.0) for position in dict((plan.portfolio_snapshot or {}).get("positions", {}) or {}).values())
    summary = {
        "mode": mode,
        "gate_distribution": {},
        "formal_exposure_distribution": {},
        "suppressed_position_summary": {
            "zero_budget_count": 0,
            "reduced_budget_count": 0,
        },
    }
    for ticker, evaluation in selection_targets.items():
        item = watchlist_by_ticker.get(str(ticker))
        if item is None:
            continue
        budget = _resolve_btst_position_budget(
            item=item,
            selection_target=evaluation,
            candidate=None,
            nav=nav if nav > 0 else 1.0,
        )
        p6_payload = {
            "mode": str(budget.get("risk_budget_mode") or mode),
            "risk_budget_ratio": float(budget.get("formal_risk_budget_ratio", 1.0) or 0.0),
            "formal_exposure_bucket": str(budget.get("formal_exposure_bucket") or ""),
            "execution_contract_bucket": str(budget.get("execution_contract_bucket") or ""),
            "risk_budget_gate": str(budget.get("risk_budget_gate") or ""),
            "prior_quality_label": str(budget.get("prior_quality_label") or ""),
        }
        matching_order = buy_order_by_ticker.get(str(ticker))
        if matching_order is not None:
            p6_payload["planned_amount"] = round(float(getattr(matching_order, "amount", 0.0) or 0.0), 4)
            p6_payload["planned_shares"] = int(getattr(matching_order, "shares", 0) or 0)
            p6_payload["risk_budget_ratio_applied"] = round(float(getattr(matching_order, "risk_budget_ratio", 1.0) or 0.0), 4)
        short_trade_result = getattr(evaluation, "short_trade", None)
        if short_trade_result is not None:
            metrics_payload = dict(short_trade_result.metrics_payload or {})
            explainability_payload = dict(short_trade_result.explainability_payload or {})
            metrics_payload["p6_risk_budget"] = p6_payload
            explainability_payload["p6_risk_budget"] = p6_payload
            short_trade_result.metrics_payload = metrics_payload
            short_trade_result.explainability_payload = explainability_payload
        gate_name = p6_payload["risk_budget_gate"] or "unknown"
        bucket = p6_payload["formal_exposure_bucket"] or "unknown"
        summary["gate_distribution"][gate_name] = int(summary["gate_distribution"].get(gate_name) or 0) + 1
        summary["formal_exposure_distribution"][bucket] = int(summary["formal_exposure_distribution"].get(bucket) or 0) + 1
        if bucket == "zero_budget":
            summary["suppressed_position_summary"]["zero_budget_count"] += 1
        if bucket == "reduced":
            summary["suppressed_position_summary"]["reduced_budget_count"] += 1

    risk_metrics = dict(getattr(plan, "risk_metrics", {}) or {})
    funnel_diagnostics = dict(risk_metrics.get("funnel_diagnostics", {}) or {})
    risk_metrics["btst_risk_budget_p6_enforcement"] = summary
    funnel_diagnostics["btst_risk_budget_p6_enforcement"] = summary
    risk_metrics["funnel_diagnostics"] = funnel_diagnostics
    plan.risk_metrics = risk_metrics
    return plan
