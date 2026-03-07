"""日度执行流水线。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Optional

from src.execution.layer_c_aggregator import aggregate_layer_c_results
from src.execution.models import ExecutionPlan, LayerCResult
from src.execution.plan_generator import generate_execution_plan
from src.portfolio.position_calculator import calculate_position, enforce_daily_trade_limit
from src.screening.candidate_pool import build_candidate_pool
from src.screening.market_state import detect_market_state
from src.screening.signal_fusion import fuse_batch
from src.screening.strategy_scorer import score_batch


AgentRunner = Callable[[list[str], str], dict[str, dict[str, dict]]]
ExitChecker = Callable[[dict, str], list]


def _default_agent_runner(tickers: list[str], trade_date: str) -> dict[str, dict[str, dict]]:
    from src.main import run_hedge_fund

    start_date = (datetime.strptime(trade_date, "%Y%m%d") - timedelta(days=365)).strftime("%Y-%m-%d")
    end_date = datetime.strptime(trade_date, "%Y%m%d").strftime("%Y-%m-%d")
    result = run_hedge_fund(
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        portfolio={"cash": 1_000_000, "positions": {}, "margin_requirement": 0.0, "margin_used": 0.0, "realized_gains": {}},
        show_reasoning=False,
    )
    return result.get("analyst_signals", {})


def _default_exit_checker(portfolio_snapshot: dict, trade_date: str) -> list:
    return []


@dataclass
class DailyPipeline:
    agent_runner: AgentRunner = _default_agent_runner
    exit_checker: ExitChecker = _default_exit_checker

    def run_post_market(self, trade_date: str, portfolio_snapshot: Optional[dict] = None) -> ExecutionPlan:
        portfolio_snapshot = portfolio_snapshot or {"cash": 1_000_000, "positions": {}}

        candidates = build_candidate_pool(trade_date)
        market_state = detect_market_state(trade_date)
        scored = score_batch(candidates, trade_date)
        fused = fuse_batch(scored, market_state, trade_date)
        high_pool = [item for item in fused if item.score_b >= 0.35]

        agent_results = self.agent_runner([item.ticker for item in high_pool], trade_date) if high_pool else {}
        top_20 = sorted(high_pool, key=lambda item: item.score_b, reverse=True)[:20]
        if top_20:
            precise_results = self.agent_runner([item.ticker for item in top_20], trade_date)
            for agent_id, ticker_payload in precise_results.items():
                agent_results.setdefault(agent_id, {}).update(ticker_payload)

        layer_c_results = aggregate_layer_c_results(high_pool, agent_results)
        watchlist = [item for item in layer_c_results if item.score_final >= 0.25 and item.decision != "avoid"]
        buy_orders = self._build_buy_orders(watchlist, portfolio_snapshot)
        sell_orders = self.exit_checker(portfolio_snapshot, trade_date)
        return generate_execution_plan(
            trade_date=trade_date,
            market_state=market_state,
            watchlist=watchlist,
            buy_orders=buy_orders,
            sell_orders=sell_orders,
            portfolio_snapshot=portfolio_snapshot,
            risk_alerts=[],
            risk_metrics={},
            layer_a_count=len(candidates),
            layer_b_count=len(high_pool),
        )

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
