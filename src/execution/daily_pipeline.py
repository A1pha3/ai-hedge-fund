"""日度执行流水线。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from time import perf_counter
from typing import Callable, Optional

from src.execution.crisis_handler import evaluate_crisis_response
from src.execution.layer_c_aggregator import aggregate_layer_c_results
from src.execution.models import ExecutionPlan, LayerCResult
from src.execution.plan_generator import generate_execution_plan
from src.execution.signal_decay import apply_signal_decay
from src.execution.t1_confirmation import confirm_buy_signal
from src.portfolio.position_calculator import calculate_position, enforce_daily_trade_limit
from src.screening.candidate_pool import build_candidate_pool
from src.screening.market_state import detect_market_state
from src.screening.signal_fusion import fuse_batch
from src.screening.strategy_scorer import score_batch


AgentRunner = Callable[[list[str], str, str], dict[str, dict[str, dict]]]
ExitChecker = Callable[[dict, str], list]


def _default_agent_runner(tickers: list[str], trade_date: str, model: str) -> dict[str, dict[str, dict]]:
    from src.main import run_hedge_fund

    start_date = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=365)).strftime("%Y-%m-%d")
    end_date = datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d")
    model_name = "gpt-4.1-mini" if model == "fast" else "gpt-4.1"
    result = run_hedge_fund(
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        portfolio={"cash": 1_000_000, "positions": {}, "margin_requirement": 0.0, "margin_used": 0.0, "realized_gains": {}},
        show_reasoning=False,
        model_name=model_name,
    )
    return result.get("analyst_signals", {})


def _default_exit_checker(portfolio_snapshot: dict, trade_date: str) -> list:
    return []


@dataclass
class DailyPipeline:
    agent_runner: AgentRunner = _default_agent_runner
    exit_checker: ExitChecker = _default_exit_checker

    def run_post_market(self, trade_date: str, portfolio_snapshot: Optional[dict] = None) -> ExecutionPlan:
        total_started_at = perf_counter()
        portfolio_snapshot = portfolio_snapshot or {"cash": 1_000_000, "positions": {}}

        stage_started_at = perf_counter()
        candidates = build_candidate_pool(trade_date)
        candidate_pool_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        market_state = detect_market_state(trade_date)
        market_state_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        scored = score_batch(candidates, trade_date)
        score_batch_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        fused = fuse_batch(scored, market_state, trade_date)
        fuse_batch_seconds = perf_counter() - stage_started_at
        high_pool = [item for item in fused if item.score_b >= 0.35]

        stage_started_at = perf_counter()
        agent_results = self.agent_runner([item.ticker for item in high_pool], trade_date, "fast") if high_pool else {}
        fast_agent_seconds = perf_counter() - stage_started_at

        top_20 = sorted(high_pool, key=lambda item: item.score_b, reverse=True)[:20]
        stage_started_at = perf_counter()
        if top_20:
            precise_results = self.agent_runner([item.ticker for item in top_20], trade_date, "precise")
            for agent_id, ticker_payload in precise_results.items():
                agent_results.setdefault(agent_id, {}).update(ticker_payload)
        precise_agent_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        layer_c_results = aggregate_layer_c_results(high_pool, agent_results)
        aggregate_layer_c_seconds = perf_counter() - stage_started_at
        watchlist = [item for item in layer_c_results if item.score_final >= 0.25 and item.decision != "avoid"]

        stage_started_at = perf_counter()
        buy_orders = self._build_buy_orders(watchlist, portfolio_snapshot)
        build_buy_orders_seconds = perf_counter() - stage_started_at

        stage_started_at = perf_counter()
        sell_orders = self.exit_checker(portfolio_snapshot, trade_date)
        sell_check_seconds = perf_counter() - stage_started_at

        timing_seconds = {
            "candidate_pool": round(candidate_pool_seconds, 3),
            "market_state": round(market_state_seconds, 3),
            "score_batch": round(score_batch_seconds, 3),
            "fuse_batch": round(fuse_batch_seconds, 3),
            "fast_agent": round(fast_agent_seconds, 3),
            "precise_agent": round(precise_agent_seconds, 3),
            "aggregate_layer_c": round(aggregate_layer_c_seconds, 3),
            "build_buy_orders": round(build_buy_orders_seconds, 3),
            "sell_check": round(sell_check_seconds, 3),
            "total_post_market": round(perf_counter() - total_started_at, 3),
        }
        return generate_execution_plan(
            trade_date=trade_date,
            market_state=market_state,
            watchlist=watchlist,
            buy_orders=buy_orders,
            sell_orders=sell_orders,
            portfolio_snapshot=portfolio_snapshot,
            risk_alerts=[],
            risk_metrics={
                "timing_seconds": timing_seconds,
                "counts": {
                    "layer_a_count": len(candidates),
                    "layer_b_count": len(high_pool),
                    "layer_c_count": len(layer_c_results),
                    "watchlist_count": len(watchlist),
                    "buy_order_count": len(buy_orders),
                    "sell_order_count": len(sell_orders),
                    "fast_agent_ticker_count": len(high_pool),
                    "precise_agent_ticker_count": len(top_20),
                },
            },
            layer_a_count=len(candidates),
            layer_b_count=len(high_pool),
        )

    def run_pre_market(
        self,
        plan: ExecutionPlan,
        trade_date_t1: str,
        refreshed_scores: dict[str, float] | None = None,
        atr_values: dict[str, float] | None = None,
        open_gap_pct: dict[str, float] | None = None,
        negative_news_tickers: set[str] | None = None,
    ) -> ExecutionPlan:
        return apply_signal_decay(
            plan,
            trade_date_t1,
            refreshed_scores=refreshed_scores,
            atr_values=atr_values,
            open_gap_pct=open_gap_pct,
            negative_news_tickers=negative_news_tickers,
        )

    def run_intraday(
        self,
        plan: ExecutionPlan,
        trade_date_t1: str,
        confirmation_inputs: dict[str, dict] | None = None,
        crisis_inputs: dict | None = None,
    ) -> tuple[list, list, dict]:
        confirmation_inputs = confirmation_inputs or {}
        confirmed_orders = []
        for order in plan.buy_orders:
            data = confirmation_inputs.get(order.ticker, {})
            result = confirm_buy_signal(
                day_low=float(data.get("day_low", 0.0)),
                ema30=float(data.get("ema30", 0.0)),
                current_price=float(data.get("current_price", 0.0)),
                vwap=float(data.get("vwap", 0.0)),
                intraday_volume=float(data.get("intraday_volume", 0.0)),
                avg_same_time_volume=float(data.get("avg_same_time_volume", 1.0)),
                industry_percentile=float(data.get("industry_percentile", 1.0)),
                stock_pct_change=float(data.get("stock_pct_change", 0.0)),
                industry_pct_change=float(data.get("industry_pct_change", 0.0)),
            )
            if result["confirmed"]:
                confirmed_orders.append(order)

        crisis_inputs = crisis_inputs or {}
        crisis_response = evaluate_crisis_response(
            hs300_daily_return=float(crisis_inputs.get("hs300_daily_return", 0.0)),
            limit_down_count=int(crisis_inputs.get("limit_down_count", 0)),
            recent_total_volumes=list(crisis_inputs.get("recent_total_volumes", [])),
            drawdown_pct=float(crisis_inputs.get("drawdown_pct", 0.0)),
        )
        exits = self.exit_checker(plan.portfolio_snapshot, trade_date_t1)
        return confirmed_orders, exits, crisis_response

    def _build_buy_orders(self, watchlist: list[LayerCResult], portfolio_snapshot: dict) -> list:
        cash = float(portfolio_snapshot.get("cash", 0.0))
        nav = cash + sum(
            float(position.get("long", 0)) * float(position.get("long_cost_basis", 0.0))
            for position in portfolio_snapshot.get("positions", {}).values()
        )
        nav = nav if nav > 0 else cash
        if not watchlist or cash <= 0:
            return []

        per_name_cash = cash / max(1, min(3, len(watchlist)))
        plans = []
        for item in watchlist:
            current_price = 10.0
            avg_volume_20d = 10_000_000.0
            industry_quota = nav * 0.25
            plan = calculate_position(
                ticker=item.ticker,
                current_price=current_price,
                score_final=item.score_final,
                portfolio_nav=nav,
                available_cash=min(cash, per_name_cash),
                avg_volume_20d=avg_volume_20d,
                industry_remaining_quota=industry_quota,
            )
            if plan.shares > 0:
                plans.append(plan)
        return enforce_daily_trade_limit(plans, nav)
