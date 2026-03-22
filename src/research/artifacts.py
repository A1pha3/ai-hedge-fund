from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from src.execution.daily_pipeline import FAST_AGENT_MAX_TICKERS, FAST_AGENT_SCORE_THRESHOLD, PRECISE_AGENT_MAX_TICKERS, WATCHLIST_SCORE_THRESHOLD
from src.research.models import RejectedCandidate, SelectedCandidate, SelectionArtifactWriteResult, SelectionSnapshot
from src.research.review_renderer import render_selection_review

if TYPE_CHECKING:
    from src.execution.daily_pipeline import DailyPipeline
    from src.execution.models import ExecutionPlan, LayerCResult
    from src.portfolio.models import ExitSignal, PositionPlan


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


def _build_selected_reasoning(item: LayerCResult, included_in_buy_orders: bool) -> dict[str, list[str]]:
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
    if float(item.quality_score) < 0.5:
        what_to_check.append("基本面质量分偏低，需复核是否为估值陷阱或质量陷阱")
    if not what_to_check:
        what_to_check.append("确认上涨逻辑是否过度依赖短期事件噪声")
    return {
        "why_selected": why_selected[:3],
        "what_to_check": what_to_check[:2],
    }


def _build_selected_candidates(plan: ExecutionPlan) -> list[SelectedCandidate]:
    buy_order_by_ticker = {order.ticker: order for order in plan.buy_orders}
    nav = _portfolio_nav(plan.portfolio_snapshot)
    selected: list[SelectedCandidate] = []
    for rank, item in enumerate(sorted(plan.watchlist, key=lambda current: current.score_final, reverse=True), start=1):
        matching_order = buy_order_by_ticker.get(item.ticker)
        included_in_buy_orders = matching_order is not None
        amount = float(getattr(matching_order, "amount", 0.0) or 0.0) if matching_order is not None else 0.0
        selected.append(
            SelectedCandidate(
                symbol=item.ticker,
                decision="watchlist",
                score_b=round(float(item.score_b), 4),
                score_c=round(float(item.score_c), 4),
                score_final=round(float(item.score_final), 4),
                rank_in_watchlist=rank,
                layer_b_summary={
                    "top_factors": _extract_top_factors(item),
                },
                layer_c_summary={
                    **dict(item.agent_contribution_summary or {}),
                    "bc_conflict": item.bc_conflict,
                },
                execution_bridge={
                    "included_in_buy_orders": included_in_buy_orders,
                    "planned_shares": int(getattr(matching_order, "shares", 0) or 0) if matching_order is not None else 0,
                    "planned_amount": round(amount, 4),
                    "target_weight": round((amount / nav), 4) if nav > 0 and amount > 0 else 0.0,
                },
                research_prompts=_build_selected_reasoning(item, included_in_buy_orders),
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
            )
        )
    return rejected


def _build_pipeline_config_snapshot(pipeline: DailyPipeline | None, selected_analysts: list[str] | None) -> dict[str, Any]:
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
        "environment": {
            "market_region": "CN",
            "replay_mode": bool(getattr(pipeline, "frozen_post_market_plans", None)),
            "frozen_plan_source": getattr(pipeline, "frozen_plan_source", None),
        },
    }


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
        pipeline_config_snapshot=_build_pipeline_config_snapshot(pipeline, selected_analysts),
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
        day_dir = self._artifact_root / snapshot.trade_date
        day_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = day_dir / "selection_snapshot.json"
        review_path = day_dir / "selection_review.md"
        feedback_path = day_dir / "research_feedback.jsonl"
        try:
            review_path.write_text(render_selection_review(snapshot), encoding="utf-8")
            feedback_path.touch(exist_ok=True)
            finalized_snapshot = snapshot.model_copy(
                update={
                    "artifact_status": {
                        "snapshot_written": True,
                        "review_written": True,
                    }
                }
            )
            snapshot_path.write_text(json.dumps(finalized_snapshot.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
            return SelectionArtifactWriteResult(
                artifact_version=self._artifact_version,
                snapshot_path=str(snapshot_path),
                review_path=str(review_path),
                feedback_path=str(feedback_path),
                write_status="success",
            )
        except OSError as error:
            return SelectionArtifactWriteResult(
                artifact_version=self._artifact_version,
                snapshot_path=str(snapshot_path) if snapshot_path.exists() else None,
                review_path=str(review_path) if review_path.exists() else None,
                feedback_path=str(feedback_path) if feedback_path.exists() else None,
                write_status="partial_success" if any(path.exists() for path in (snapshot_path, review_path, feedback_path)) else "failed",
                error_message=str(error),
            )