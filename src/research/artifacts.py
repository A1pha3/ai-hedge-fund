from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from src.execution.daily_pipeline import FAST_AGENT_MAX_TICKERS, FAST_AGENT_SCORE_THRESHOLD, PRECISE_AGENT_MAX_TICKERS, WATCHLIST_SCORE_THRESHOLD
from src.research.models import DualTargetDeltaView, RejectedCandidate, ResearchTargetView, SelectedCandidate, SelectionArtifactWriteResult, SelectionSnapshot, SelectionTargetReplayInput, ShortTradeTargetView
from src.research.review_renderer import render_selection_review

if TYPE_CHECKING:
    from src.execution.daily_pipeline import DailyPipeline
    from src.execution.models import ExecutionPlan, LayerCResult
    from src.portfolio.models import PositionPlan


class SelectionArtifactWriter(Protocol):
    def write_for_plan(
        self,
        *,
        plan: ExecutionPlan,
        trade_date: str,
        pipeline: DailyPipeline | None,
        selected_analysts: list[str] | None,
    ) -> SelectionArtifactWriteResult:
        ...


def _format_trade_date(trade_date: str) -> str:
    trade_date = str(trade_date)
    if len(trade_date) == 8 and trade_date.isdigit():
        return f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}"
    return trade_date


def _portfolio_nav(portfolio_snapshot: dict[str, Any]) -> float:
    cash = float((portfolio_snapshot or {}).get("cash", 0.0) or 0.0)
    positions = dict((portfolio_snapshot or {}).get("positions", {}) or {})
    total = cash
    for position in positions.values():
        total += float(position.get("long", 0) or 0) * float(position.get("long_cost_basis", 0.0) or 0.0)
    return total if total > 0 else cash


def _extract_top_factors(item: LayerCResult) -> list[dict[str, Any]]:
    factors: list[dict[str, Any]] = []
    for strategy_name, signal in sorted((item.strategy_signals or {}).items()):
        factors.append(
            {
                "name": strategy_name,
                "direction": getattr(signal, "direction", 0),
                "confidence": round(float(getattr(signal, "confidence", 0.0) or 0.0), 2),
                "completeness": round(float(getattr(signal, "completeness", 0.0) or 0.0), 2),
            }
        )
    factors.sort(key=lambda current: (abs(float(current.get("direction", 0))) * float(current.get("confidence", 0.0))), reverse=True)
    return factors[:3]


def _extract_fallback_top_factors(plan: ExecutionPlan, item: LayerCResult) -> list[dict[str, Any]]:
    factors: list[dict[str, Any]] = []
    logic_score = float(plan.logic_scores.get(item.ticker, item.score_b) or 0.0)
    factors.append(
        {
            "name": "logic_score",
            "value": round(logic_score, 4),
            "source": "plan.logic_scores",
        }
    )

    adjusted_weights = dict(getattr(plan.market_state, "adjusted_weights", {}) or {})
    source_name = "market_state.adjusted_weights" if adjusted_weights else "plan.strategy_weights"
    ranked_weights = sorted((adjusted_weights or plan.strategy_weights or {}).items(), key=lambda current: float(current[1] or 0.0), reverse=True)
    for strategy_name, weight in ranked_weights[:2]:
        factors.append(
            {
                "name": str(strategy_name),
                "weight": round(float(weight or 0.0), 4),
                "source": source_name,
            }
        )
    return factors[:3]


def _build_layer_b_summary(plan: ExecutionPlan, item: LayerCResult) -> dict[str, Any]:
    top_factors = _extract_top_factors(item)
    if top_factors:
        return {
            "top_factors": top_factors,
            "explanation_source": "strategy_signals",
            "fallback_used": False,
        }
    return {
        "top_factors": _extract_fallback_top_factors(plan, item),
        "explanation_source": "legacy_plan_fields",
        "fallback_used": True,
    }


def _build_selected_reasoning(item: LayerCResult, included_in_buy_orders: bool, layer_b_fallback_used: bool) -> dict[str, list[str]]:
    why_selected = [
        f"Layer B 综合分数为 {item.score_b:.4f}",
        f"Layer C 综合分数为 {item.score_c:.4f}",
        f"最终得分为 {item.score_final:.4f}",
    ]
    if item.bc_conflict:
        why_selected.append(f"存在 B/C 冲突标记: {item.bc_conflict}")
    if included_in_buy_orders:
        why_selected.append("通过了执行层约束并进入 buy_orders")

    what_to_check = []
    if item.bc_conflict:
        what_to_check.append("B/C 分歧是否意味着选股逻辑仍然不够稳定")
    if layer_b_fallback_used:
        what_to_check.append("当前 Layer B 因子摘要来自历史回放兼容字段，需结合原始 plan 字段复核")
    if float(item.quality_score) < 0.5:
        what_to_check.append("基本面质量分偏低，需复核是否为估值陷阱或质量陷阱")
    if not what_to_check:
        what_to_check.append("确认上涨逻辑是否过度依赖短期事件噪声")
    return {
        "why_selected": why_selected[:3],
        "what_to_check": what_to_check[:2],
    }


def _build_execution_bridge(plan: ExecutionPlan, item: LayerCResult, nav: float, matching_order: PositionPlan | None) -> dict[str, Any]:
    funnel_diagnostics = dict((plan.risk_metrics or {}).get("funnel_diagnostics", {}) or {})
    buy_order_filters = dict((funnel_diagnostics.get("filters", {}) or {}).get("buy_orders", {}) or {})
    filtered_by_ticker = {
        str(entry.get("ticker") or ""): dict(entry)
        for entry in list((buy_order_filters or {}).get("tickers", []) or [])
        if entry.get("ticker")
    }
    blocked_buy_tickers = {
        str(ticker): dict(details or {})
        for ticker, details in dict(funnel_diagnostics.get("blocked_buy_tickers", {}) or {}).items()
    }

    included_in_buy_orders = matching_order is not None
    amount = float(getattr(matching_order, "amount", 0.0) or 0.0) if matching_order is not None else 0.0
    filter_details = filtered_by_ticker.get(item.ticker, {})
    blocked_details = blocked_buy_tickers.get(item.ticker, {})
    block_reason = str(filter_details.get("reason") or blocked_details.get("trigger_reason") or "").strip() or None

    execution_bridge = {
        "included_in_buy_orders": included_in_buy_orders,
        "planned_shares": int(getattr(matching_order, "shares", 0) or 0) if matching_order is not None else 0,
        "planned_amount": round(amount, 4),
        "target_weight": round((amount / nav), 4) if nav > 0 and amount > 0 else 0.0,
    }
    if block_reason:
        execution_bridge["block_reason"] = block_reason
    if filter_details.get("constraint_binding"):
        execution_bridge["constraint_binding"] = str(filter_details.get("constraint_binding"))
    if filter_details.get("execution_ratio") is not None:
        execution_bridge["execution_ratio"] = round(float(filter_details.get("execution_ratio") or 0.0), 4)
    if blocked_details.get("blocked_until"):
        execution_bridge["blocked_until"] = str(blocked_details.get("blocked_until"))
    if blocked_details.get("reentry_review_until"):
        execution_bridge["reentry_review_until"] = str(blocked_details.get("reentry_review_until"))
    if blocked_details.get("exit_trade_date"):
        execution_bridge["exit_trade_date"] = str(blocked_details.get("exit_trade_date"))
    if blocked_details.get("trigger_reason"):
        execution_bridge["trigger_reason"] = str(blocked_details.get("trigger_reason"))
    return execution_bridge


def _build_target_context(plan: ExecutionPlan, ticker: str) -> dict[str, Any]:
    target_context = {
        "target_mode": str(getattr(plan, "target_mode", "research_only") or "research_only"),
        "selection_target_attached": False,
    }
    evaluation = dict(getattr(plan, "selection_targets", {}) or {}).get(ticker)
    if evaluation is None:
        return target_context

    target_context["selection_target_attached"] = True
    candidate_source = getattr(evaluation, "candidate_source", None)
    if candidate_source:
        target_context["candidate_source"] = str(candidate_source)
    candidate_reason_codes = [str(reason) for reason in list(getattr(evaluation, "candidate_reason_codes", []) or []) if str(reason or "").strip()]
    if candidate_reason_codes:
        target_context["candidate_reason_codes"] = candidate_reason_codes
    research_result = getattr(evaluation, "research", None)
    short_trade_result = getattr(evaluation, "short_trade", None)
    if research_result is not None:
        target_context["research_decision"] = str(research_result.decision or "")
    if short_trade_result is not None:
        target_context["short_trade_decision"] = str(short_trade_result.decision or "")
    delta_classification = getattr(evaluation, "delta_classification", None)
    if delta_classification:
        target_context["delta_classification"] = str(delta_classification)
    return target_context


def _build_target_decisions(plan: ExecutionPlan, ticker: str) -> dict[str, Any]:
    evaluation = dict(getattr(plan, "selection_targets", {}) or {}).get(ticker)
    if evaluation is None:
        return {}
    decisions: dict[str, Any] = {}
    if getattr(evaluation, "research", None) is not None:
        decisions["research"] = evaluation.research
    if getattr(evaluation, "short_trade", None) is not None:
        decisions["short_trade"] = evaluation.short_trade
    return decisions


def _increment_counter(counter: dict[str, int], key: str) -> None:
    normalized_key = str(key or "unknown")
    counter[normalized_key] = int(counter.get(normalized_key) or 0) + 1


def _build_research_target_view(plan: ExecutionPlan) -> ResearchTargetView:
    view = ResearchTargetView()
    for ticker, evaluation in dict(plan.selection_targets or {}).items():
        research_result = getattr(evaluation, "research", None)
        if research_result is None:
            continue
        decision = str(research_result.decision or "")
        if decision == "selected":
            view.selected_symbols.append(str(ticker))
        elif decision == "near_miss":
            view.near_miss_symbols.append(str(ticker))
        else:
            view.rejected_symbols.append(str(ticker))
        for blocker in list(getattr(research_result, "blockers", []) or []):
            _increment_counter(view.blocker_counts, blocker)

    view.selected_symbols.sort()
    view.near_miss_symbols.sort()
    view.rejected_symbols.sort()
    return view


def _build_short_trade_target_view(plan: ExecutionPlan) -> ShortTradeTargetView:
    view = ShortTradeTargetView()
    for ticker, evaluation in dict(plan.selection_targets or {}).items():
        short_trade_result = getattr(evaluation, "short_trade", None)
        if short_trade_result is None:
            continue
        decision = str(short_trade_result.decision or "")
        blockers = list(getattr(short_trade_result, "blockers", []) or [])
        if decision == "selected":
            view.selected_symbols.append(str(ticker))
        elif decision == "near_miss":
            view.near_miss_symbols.append(str(ticker))
        elif decision == "blocked":
            view.blocked_symbols.append(str(ticker))
        else:
            view.rejected_symbols.append(str(ticker))
        for blocker in blockers:
            _increment_counter(view.blocker_counts, blocker)

    view.selected_symbols.sort()
    view.near_miss_symbols.sort()
    view.rejected_symbols.sort()
    view.blocked_symbols.sort()
    return view


def _build_dual_target_delta(plan: ExecutionPlan) -> DualTargetDeltaView:
    delta_counts: dict[str, int] = {}
    dominant_delta_reasons: dict[str, int] = {}
    representative_cases: list[dict[str, Any]] = []

    for ticker, evaluation in dict(plan.selection_targets or {}).items():
        delta_classification = str(getattr(evaluation, "delta_classification", "") or "")
        if delta_classification:
            _increment_counter(delta_counts, delta_classification)
        for reason in list(getattr(evaluation, "delta_summary", []) or []):
            _increment_counter(dominant_delta_reasons, reason)
        if len(representative_cases) >= 5:
            continue
        if not delta_classification and not getattr(evaluation, "delta_summary", []):
            continue
        representative_cases.append(
            {
                "ticker": str(ticker),
                "delta_classification": delta_classification or None,
                "research_decision": getattr(getattr(evaluation, "research", None), "decision", None),
                "short_trade_decision": getattr(getattr(evaluation, "short_trade", None), "decision", None),
                "delta_summary": list(getattr(evaluation, "delta_summary", []) or []),
            }
        )

    dominant_delta_reason_list = [
        reason
        for reason, _ in sorted(dominant_delta_reasons.items(), key=lambda item: (-item[1], item[0]))[:3]
    ]
    return DualTargetDeltaView(
        delta_counts=delta_counts,
        representative_cases=representative_cases,
        dominant_delta_reasons=dominant_delta_reason_list,
    )


def _build_selected_candidates(plan: ExecutionPlan) -> list[SelectedCandidate]:
    buy_order_by_ticker = {order.ticker: order for order in plan.buy_orders}
    nav = _portfolio_nav(plan.portfolio_snapshot)
    selected: list[SelectedCandidate] = []
    for rank, item in enumerate(sorted(plan.watchlist, key=lambda current: current.score_final, reverse=True), start=1):
        matching_order = buy_order_by_ticker.get(item.ticker)
        included_in_buy_orders = matching_order is not None
        layer_b_summary = _build_layer_b_summary(plan, item)
        execution_bridge = _build_execution_bridge(plan, item, nav, matching_order)
        research_prompts = _build_selected_reasoning(item, included_in_buy_orders, bool(layer_b_summary.get("fallback_used")))
        if not included_in_buy_orders and execution_bridge.get("block_reason"):
            blocker = f"执行层未生成 buy_order，原因: {execution_bridge['block_reason']}"
            constraint_binding = execution_bridge.get("constraint_binding")
            if constraint_binding:
                blocker = f"{blocker} (binding={constraint_binding})"
            research_prompts["what_to_check"] = [blocker, *list(research_prompts.get("what_to_check", []))][:2]
        selected.append(
            SelectedCandidate(
                symbol=item.ticker,
                decision="watchlist",
                score_b=round(float(item.score_b), 4),
                score_c=round(float(item.score_c), 4),
                score_final=round(float(item.score_final), 4),
                rank_in_watchlist=rank,
                layer_b_summary=layer_b_summary,
                layer_c_summary={
                    **dict(item.agent_contribution_summary or {}),
                    "bc_conflict": item.bc_conflict,
                },
                execution_bridge=execution_bridge,
                research_prompts=research_prompts,
                target_context=_build_target_context(plan, item.ticker),
                target_decisions=_build_target_decisions(plan, item.ticker),
            )
        )
    return selected


def _build_rejected_candidates(plan: ExecutionPlan, max_candidates: int = 5) -> list[RejectedCandidate]:
    watchlist_filters = dict(((plan.risk_metrics or {}).get("funnel_diagnostics", {}) or {}).get("filters", {})).get("watchlist", {})
    entries = list((watchlist_filters or {}).get("tickers", []) or [])
    ranked = sorted(entries, key=lambda current: float(current.get("score_final", current.get("score_b", 0.0)) or 0.0), reverse=True)
    rejected: list[RejectedCandidate] = []
    for entry in ranked[:max_candidates]:
        reasons = list(entry.get("reasons", []) or [])
        rejected.append(
            RejectedCandidate(
                symbol=str(entry.get("ticker") or ""),
                rejection_stage="watchlist",
                score_b=round(float(entry.get("score_b", 0.0) or 0.0), 4),
                score_c=round(float(entry.get("score_c", 0.0) or 0.0), 4),
                score_final=round(float(entry.get("score_final", 0.0) or 0.0), 4),
                rejection_reason_codes=[str(reason) for reason in reasons],
                rejection_reason_text=str(entry.get("reason") or ", ".join(reasons)),
                target_context={
                    "target_mode": str(getattr(plan, "target_mode", "research_only") or "research_only"),
                    **_build_target_context(plan, str(entry.get("ticker") or "")),
                },
                target_decisions=_build_target_decisions(plan, str(entry.get("ticker") or "")),
            )
        )
    return rejected


def _build_pipeline_config_snapshot(plan: ExecutionPlan, pipeline: DailyPipeline | None, selected_analysts: list[str] | None) -> dict[str, Any]:
    return {
        "code_version": os.getenv("GIT_SHA", ""),
        "execution_version": "daily_pipeline",
        "analyst_roster_version": "custom" if selected_analysts else "default",
        "selected_analysts": list(selected_analysts or []),
        "model_provider": getattr(pipeline, "base_model_provider", ""),
        "model_name": getattr(pipeline, "base_model_name", ""),
        "key_thresholds": {
            "score_b_min": FAST_AGENT_SCORE_THRESHOLD,
            "score_final_min": WATCHLIST_SCORE_THRESHOLD,
            "max_fast_pool_size": FAST_AGENT_MAX_TICKERS,
            "max_precise_pool_size": PRECISE_AGENT_MAX_TICKERS,
        },
        "short_trade_target_profile": {
            "name": str(getattr(plan, "short_trade_target_profile_name", "default") or "default"),
            "config": dict(getattr(plan, "short_trade_target_profile_config", {}) or {}),
        },
        "environment": {
            "market_region": "CN",
            "replay_mode": bool(getattr(pipeline, "frozen_post_market_plans", None)),
            "frozen_plan_source": getattr(pipeline, "frozen_plan_source", None),
        },
    }


def _serialize_strategy_signals(strategy_signals: dict[str, Any] | None) -> dict[str, Any]:
    return {
        str(name): signal.model_dump(mode="json") if hasattr(signal, "model_dump") else dict(signal or {})
        for name, signal in dict(strategy_signals or {}).items()
    }


def _serialize_layer_c_result_for_replay(item: LayerCResult, *, candidate_source: str) -> dict[str, Any]:
    return {
        "ticker": item.ticker,
        "score_b": round(float(item.score_b), 4),
        "score_c": round(float(item.score_c), 4),
        "score_final": round(float(item.score_final), 4),
        "quality_score": round(float(item.quality_score), 4),
        "decision": str(item.decision or "neutral"),
        "bc_conflict": item.bc_conflict,
        "candidate_source": candidate_source,
        "strategy_signals": _serialize_strategy_signals(item.strategy_signals),
        "agent_contribution_summary": dict(item.agent_contribution_summary or {}),
    }


def build_selection_target_replay_input(
    *,
    plan: ExecutionPlan,
    trade_date: str,
    run_id: str,
    pipeline: DailyPipeline | None,
    selected_analysts: list[str] | None,
    experiment_id: str | None = None,
    market: str = "CN",
    artifact_version: str = "v1",
) -> SelectionTargetReplayInput:
    formatted_trade_date = _format_trade_date(trade_date)
    funnel_diagnostics = dict((plan.risk_metrics or {}).get("funnel_diagnostics", {}) or {})
    filters = dict(funnel_diagnostics.get("filters", {}) or {})
    rejected_entries = list(dict(filters.get("watchlist", {}) or {}).get("tickers", []) or [])
    supplemental_short_trade_entries = list(dict(filters.get("short_trade_candidates", {}) or {}).get("tickers", []) or [])
    watchlist_entries = [
        _serialize_layer_c_result_for_replay(item, candidate_source="layer_c_watchlist")
        for item in sorted(plan.watchlist, key=lambda current: current.score_final, reverse=True)
    ]
    return SelectionTargetReplayInput(
        artifact_version=artifact_version,
        run_id=run_id,
        experiment_id=experiment_id,
        trade_date=formatted_trade_date,
        market=market,
        target_mode=str(getattr(plan, "target_mode", "research_only") or "research_only"),
        pipeline_config_snapshot=_build_pipeline_config_snapshot(plan, pipeline, selected_analysts),
        source_summary={
            "watchlist_count": len(watchlist_entries),
            "rejected_entry_count": len(rejected_entries),
            "supplemental_short_trade_entry_count": len(supplemental_short_trade_entries),
            "buy_order_ticker_count": len(plan.buy_orders),
        },
        watchlist=watchlist_entries,
        rejected_entries=rejected_entries,
        supplemental_short_trade_entries=supplemental_short_trade_entries,
        buy_order_tickers=sorted({str(order.ticker) for order in plan.buy_orders}),
        selection_targets=dict(plan.selection_targets or {}),
        target_summary=plan.dual_target_summary,
    )


def build_selection_snapshot(
    *,
    plan: ExecutionPlan,
    trade_date: str,
    run_id: str,
    pipeline: DailyPipeline | None,
    selected_analysts: list[str] | None,
    experiment_id: str | None = None,
    market: str = "CN",
    artifact_version: str = "v1",
) -> SelectionSnapshot:
    formatted_trade_date = _format_trade_date(trade_date)
    counts = dict((plan.risk_metrics or {}).get("counts", {}) or {})
    funnel_diagnostics = dict((plan.risk_metrics or {}).get("funnel_diagnostics", {}) or {})
    return SelectionSnapshot(
        artifact_version=artifact_version,
        run_id=run_id,
        experiment_id=experiment_id,
        trade_date=formatted_trade_date,
        market=market,
        decision_timestamp=f"{formatted_trade_date}T15:05:00+08:00",
        data_available_until=f"{formatted_trade_date}T15:00:00+08:00",
        target_mode=str(getattr(plan, "target_mode", "research_only") or "research_only"),
        pipeline_config_snapshot=_build_pipeline_config_snapshot(plan, pipeline, selected_analysts),
        universe_summary={
            "input_symbol_count": int(counts.get("layer_a_count", plan.layer_a_count) or 0),
            "candidate_count": int(counts.get("layer_a_count", plan.layer_a_count) or 0),
            "high_pool_count": int(counts.get("layer_b_count", plan.layer_b_count) or 0),
            "watchlist_count": int(counts.get("watchlist_count", len(plan.watchlist)) or 0),
            "buy_order_count": int(counts.get("buy_order_count", len(plan.buy_orders)) or 0),
            "sell_order_count": int(counts.get("sell_order_count", len(plan.sell_orders)) or 0),
        },
        selected=_build_selected_candidates(plan),
        rejected=_build_rejected_candidates(plan),
        selection_targets=dict(plan.selection_targets or {}),
        target_summary=plan.dual_target_summary,
        research_view=_build_research_target_view(plan),
        short_trade_view=_build_short_trade_target_view(plan),
        dual_target_delta=_build_dual_target_delta(plan),
        buy_orders=[order.model_dump(mode="json") for order in plan.buy_orders],
        sell_orders=[order.model_dump(mode="json") for order in plan.sell_orders],
        funnel_diagnostics=funnel_diagnostics,
        artifact_status={
            "snapshot_written": False,
            "review_written": False,
        },
    )


class FileSelectionArtifactWriter:
    def __init__(
        self,
        *,
        artifact_root: str | Path,
        run_id: str,
        experiment_id: str | None = None,
        market: str = "CN",
        artifact_version: str = "v1",
    ) -> None:
        self._artifact_root = Path(artifact_root)
        self._run_id = run_id
        self._experiment_id = experiment_id
        self._market = market
        self._artifact_version = artifact_version

    def write_for_plan(
        self,
        *,
        plan: ExecutionPlan,
        trade_date: str,
        pipeline: DailyPipeline | None,
        selected_analysts: list[str] | None,
    ) -> SelectionArtifactWriteResult:
        snapshot = build_selection_snapshot(
            plan=plan,
            trade_date=trade_date,
            run_id=self._run_id,
            pipeline=pipeline,
            selected_analysts=selected_analysts,
            experiment_id=self._experiment_id,
            market=self._market,
            artifact_version=self._artifact_version,
        )
        replay_input = build_selection_target_replay_input(
            plan=plan,
            trade_date=trade_date,
            run_id=self._run_id,
            pipeline=pipeline,
            selected_analysts=selected_analysts,
            experiment_id=self._experiment_id,
            market=self._market,
            artifact_version=self._artifact_version,
        )
        day_dir = self._artifact_root / snapshot.trade_date
        snapshot_path = day_dir / "selection_snapshot.json"
        review_path = day_dir / "selection_review.md"
        feedback_path = day_dir / "research_feedback.jsonl"
        replay_input_path = day_dir / "selection_target_replay_input.json"
        try:
            day_dir.mkdir(parents=True, exist_ok=True)
            review_path.write_text(render_selection_review(snapshot), encoding="utf-8")
            feedback_path.touch(exist_ok=True)
            replay_input_path.write_text(json.dumps(replay_input.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
            finalized_snapshot = snapshot.model_copy(
                update={
                    "artifact_status": {
                        "snapshot_written": True,
                        "review_written": True,
                        "replay_input_written": True,
                    }
                }
            )
            snapshot_path.write_text(json.dumps(finalized_snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
            return SelectionArtifactWriteResult(
                artifact_version=self._artifact_version,
                snapshot_path=str(snapshot_path),
                review_path=str(review_path),
                feedback_path=str(feedback_path),
                replay_input_path=str(replay_input_path),
                write_status="success",
            )
        except OSError as error:
            return SelectionArtifactWriteResult(
                artifact_version=self._artifact_version,
                snapshot_path=str(snapshot_path) if snapshot_path.exists() else None,
                review_path=str(review_path) if review_path.exists() else None,
                feedback_path=str(feedback_path) if feedback_path.exists() else None,
                replay_input_path=str(replay_input_path) if replay_input_path.exists() else None,
                write_status="partial_success" if any(path.exists() for path in (snapshot_path, review_path, feedback_path, replay_input_path)) else "failed",
                error_message=str(error),
            )