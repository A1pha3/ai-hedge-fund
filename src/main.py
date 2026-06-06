import argparse
import json
import os
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from src.agents.portfolio_manager import portfolio_management_agent
from src.agents.risk_manager import risk_management_agent
from src.cli.input import (
    parse_cli_inputs,
)
from src.llm.defaults import get_default_model_config
from src.execution.daily_pipeline import DailyPipeline
from src.graph.state import AgentState
from src.screening.candidate_pool import build_candidate_pool
from src.screening.market_state import detect_market_state
from src.screening.signal_fusion import fuse_batch
from src.screening.strategy_scorer import score_batch
from src.tools.tushare_api import get_ashare_daily_gainers_with_tushare
from src.utils.analysts import ANALYST_ORDER, get_analyst_nodes
from src.utils.display import (
    print_trading_output,
    save_daily_gainers_report,
    save_trading_report,
)
from src.utils.llm import build_parallel_provider_execution_plan
from src.utils.logging import get_logger, setup_logging
from src.utils.progress import progress

# Load environment variables from .env file and override stale inherited values.
load_dotenv(override=True)

# Setup logging
setup_logging()
logger = get_logger(__name__)


def parse_hedge_fund_response(response):
    """Parses a JSON string and returns a dictionary."""
    try:
        return json.loads(response)
    except json.JSONDecodeError as e:
        logger.error(f"JSON decoding error: {e}\nResponse: {repr(response)}")
        return None
    except TypeError as e:
        logger.error(f"Invalid response type (expected string, got {type(response).__name__}): {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error while parsing response: {e}\nResponse: {repr(response)}")
        return None


##### Run the Hedge Fund #####
def run_hedge_fund(
    tickers: list[str],
    start_date: str,
    end_date: str,
    portfolio: dict,
    show_reasoning: bool = False,
    selected_analysts: list[str] | None = None,
    model_name: str | None = None,
    model_provider: str | None = None,
    llm_observability: dict | None = None,
):
    resolved_model_name, resolved_model_provider = (model_name, model_provider) if model_name and model_provider else get_default_model_config()

    # Start progress tracking
    progress.start()

    try:
        analyst_nodes = get_analyst_nodes()
        selected_analyst_keys = _order_selected_analysts(selected_analysts or list(analyst_nodes.keys()))
        selected_analysts_key = tuple(selected_analyst_keys) if selected_analyst_keys else None
        base_concurrency_limit = _get_analyst_concurrency_limit()
        execution_plan = build_parallel_provider_execution_plan(
            agent_names=[analyst_nodes[analyst_key][0] for analyst_key in selected_analyst_keys],
            base_model_name=resolved_model_name,
            base_model_provider=resolved_model_provider,
            api_keys=None,
            per_provider_limit=base_concurrency_limit,
        )
        logger.info("LLM execution plan: %s", json.dumps(execution_plan["execution_provenance"], ensure_ascii=False, sort_keys=True))
        agent = _get_compiled_workflow(selected_analysts_key, int(execution_plan["effective_concurrency_limit"]))

        final_state = agent.invoke(
            {
                "messages": [
                    HumanMessage(
                        content="Make trading decisions based on the provided data.",
                    )
                ],
                "data": {
                    "tickers": tickers,
                    "portfolio": portfolio,
                    "start_date": start_date,
                    "end_date": end_date,
                    "analyst_signals": {},
                },
                "metadata": {
                    "show_reasoning": show_reasoning,
                    "model_name": resolved_model_name,
                    "model_provider": resolved_model_provider,
                    "agent_llm_overrides": execution_plan["agent_llm_overrides"],
                    "llm_observability": dict(llm_observability or {}),
                },
            },
        )

        return {
            "decisions": parse_hedge_fund_response(final_state["messages"][-1].content),
            "analyst_signals": final_state["data"]["analyst_signals"],
            "execution_plan_provenance": execution_plan["execution_provenance"],
        }
    finally:
        # Stop progress tracking
        progress.stop()


def start(state: AgentState):
    """Initialize the workflow with the input message."""
    return state


@lru_cache(maxsize=16)
def _get_compiled_workflow(selected_analysts_key: tuple[str, ...] | None, concurrency_limit: int):
    workflow = create_workflow(list(selected_analysts_key) if selected_analysts_key else None, concurrency_limit=concurrency_limit)
    return workflow.compile()


def create_workflow(selected_analysts=None, concurrency_limit: int | None = None):
    """Create the workflow with selected analysts."""
    workflow = StateGraph(AgentState)
    workflow.add_node("start_node", start)

    # Get analyst nodes from the configuration
    analyst_nodes = get_analyst_nodes()

    # Default to all analysts if none selected
    if selected_analysts is None:
        selected_analysts = list(analyst_nodes.keys())

    selected_analysts = _order_selected_analysts(selected_analysts)
    analyst_batches = _build_analyst_batches(selected_analysts, concurrency_limit or _get_analyst_concurrency_limit())

    # Add selected analyst nodes
    for analyst_key in selected_analysts:
        node_name, node_func = analyst_nodes[analyst_key]
        workflow.add_node(node_name, node_func)

    # Always add risk and portfolio management
    workflow.add_node("risk_management_agent", risk_management_agent)
    workflow.add_node("portfolio_manager", portfolio_management_agent)

    if analyst_batches:
        for analyst_key in analyst_batches[0]:
            workflow.add_edge("start_node", analyst_nodes[analyst_key][0])

        for previous_batch, current_batch in zip(analyst_batches, analyst_batches[1:], strict=False):
            for previous_key in previous_batch:
                previous_node_name = analyst_nodes[previous_key][0]
                for current_key in current_batch:
                    workflow.add_edge(previous_node_name, analyst_nodes[current_key][0])

        for analyst_key in analyst_batches[-1]:
            workflow.add_edge(analyst_nodes[analyst_key][0], "risk_management_agent")
    else:
        workflow.add_edge("start_node", "risk_management_agent")

    workflow.add_edge("risk_management_agent", "portfolio_manager")
    workflow.add_edge("portfolio_manager", END)

    workflow.set_entry_point("start_node")
    return workflow


def _get_analyst_concurrency_limit() -> int:
    raw_value = os.getenv("ANALYST_CONCURRENCY_LIMIT", "2")
    try:
        return max(1, int(raw_value))
    except ValueError:
        return 2


def _order_selected_analysts(selected_analysts: list[str]) -> list[str]:
    analyst_nodes = get_analyst_nodes()
    ordered_keys = [key for _, key in ANALYST_ORDER if key in analyst_nodes]
    ordered_selected = [key for key in ordered_keys if key in selected_analysts]
    remaining = [key for key in selected_analysts if key not in ordered_selected]
    return ordered_selected + remaining


def _build_analyst_batches(selected_analysts: list[str], concurrency_limit: int) -> list[list[str]]:
    return [selected_analysts[index : index + concurrency_limit] for index in range(0, len(selected_analysts), concurrency_limit)]


def run_daily_gainers_cli() -> int:
    """
    运行每日涨幅筛选 CLI
    """
    parser = argparse.ArgumentParser(description="获取指定日期涨幅超过阈值的 A 股列表")
    parser.add_argument("--daily-gainers", action="store_true", help="启用每日涨幅筛选模式")
    parser.add_argument(
        "--trade-date",
        type=str,
        default=datetime.now().strftime("%Y-%m-%d"),
        help="交易日期，格式 YYYY-MM-DD（默认当天）",
    )
    parser.add_argument(
        "--pct-threshold",
        type=float,
        default=3.0,
        help="涨幅阈值（默认 3.0）",
    )
    parser.add_argument(
        "--output-md",
        type=str,
        default=None,
        help="输出 Markdown 文件路径（可选）",
    )
    args = parser.parse_args()

    if not args.daily_gainers:
        return 1

    results = get_ashare_daily_gainers_with_tushare(args.trade_date, pct_threshold=args.pct_threshold, include_name=True)
    report_date = results[0].get("trade_date") if results else args.trade_date
    report_path = save_daily_gainers_report(results, report_date, args.pct_threshold, output_path=args.output_md)
    if report_path:
        print(f"已保存报告: {report_path}")
    else:
        print("报告保存失败")
    return 0


def _save_json_report(filename: str, payload: dict) -> Path:
    report_dir = Path(__file__).resolve().parents[1] / "data" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    output_path = report_dir / filename
    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2, default=str)
    return output_path


def run_pipeline_mode(trade_date: str) -> int:
    pipeline = DailyPipeline()
    plan = pipeline.run_post_market(trade_date)
    output_path = _save_json_report(f"execution_plan_{trade_date}.json", plan.model_dump())
    print(f"[Pipeline] 日期: {trade_date}")
    print(f"[Pipeline] Layer A: {plan.layer_a_count} | Layer B: {plan.layer_b_count} | Layer C: {plan.layer_c_count}")
    print(f"[Pipeline] 买入: {len(plan.buy_orders)} | 卖出: {len(plan.sell_orders)}")
    print(f"[Pipeline] 已输出: {output_path}")
    return 0


def run_screen_only_mode(trade_date: str) -> int:
    candidates = build_candidate_pool(trade_date)
    market_state = detect_market_state(trade_date)
    scored = score_batch(candidates, trade_date)
    fused = fuse_batch(scored, market_state, trade_date)
    high_pool = [item for item in fused if item.score_b >= 0.35]
    output = {
        "date": trade_date,
        "market_state": market_state.model_dump(),
        "layer_a_count": len(candidates),
        "layer_b_count": len(high_pool),
        "high_pool": [item.model_dump() for item in high_pool],
    }
    output_path = _save_json_report(f"screen_only_{trade_date}.json", output)
    print(f"[ScreenOnly] 日期: {trade_date}")
    print(f"[ScreenOnly] Layer A: {len(candidates)} | Layer B: {len(high_pool)}")
    print(f"[ScreenOnly] 已输出: {output_path}")
    return 0


def run_auto_screening(trade_date: str, top_n: int = 10) -> int:
    """一键跑全流程：全市场筛选 -> 因子评分 -> 信号融合 -> Top N 推荐。

    仅支持 A 股市场。流程：
      Step 1: build_candidate_pool()  全市场快筛 (Layer A)
      Step 2: score_batch()           四策略评分
      Step 3: fuse_batch()            信号融合与冲突仲裁 (Layer B)
      Step 4: 按 score_b 排序输出 Top N

    Args:
        trade_date: 交易日期，格式 YYYYMMDD
        top_n: 返回 Top N 推荐（默认 10）

    Returns:
        退出码（0 = 成功）
    """
    from colorama import Fore, Style
    from tabulate import tabulate

    progress.start()
    try:
        # Step 1: Layer A 候选池快筛
        progress.update_status("auto_screening", None, "Step 1/4: 全市场快筛 (Layer A)")
        logger.info("[Auto] Step 1/4: 全市场快筛 (Layer A) — trade_date=%s", trade_date)
        candidates = build_candidate_pool(trade_date)
        logger.info("[Auto] Layer A 候选池: %d 只", len(candidates))
        if not candidates:
            print(f"{Fore.YELLOW}[Auto] 候选池为空，终止流程。{Style.RESET_ALL}")
            return 1

        # Step 2: 四策略评分
        progress.update_status("auto_screening", None, f"Step 2/4: 四策略评分 ({len(candidates)} 只)")
        logger.info("[Auto] Step 2/4: 四策略评分 — %d 只候选", len(candidates))
        scored = score_batch(candidates, trade_date)

        # Step 3: 信号融合
        progress.update_status("auto_screening", None, "Step 3/4: 信号融合 + 冲突仲裁")
        logger.info("[Auto] Step 3/4: 市场状态检测 + 信号融合")
        market_state = detect_market_state(trade_date)
        fused = fuse_batch(scored, market_state, trade_date)

        # Step 4: 排序输出 Top N
        progress.update_status("auto_screening", None, f"Step 4/4: 输出 Top {top_n} 推荐")
        sorted_results = sorted(fused, key=lambda item: item.score_b, reverse=True)
        top_results = sorted_results[:top_n]

        # Save full report
        report_payload = {
            "mode": "auto_screening",
            "date": trade_date,
            "market_state": market_state.model_dump(),
            "layer_a_count": len(candidates),
            "total_scored": len(fused),
            "high_pool_count": sum(1 for item in fused if item.score_b >= 0.35),
            "top_n": top_n,
            "recommendations": [item.model_dump() for item in top_results],
        }
        report_path = _save_json_report(f"auto_screening_{trade_date}.json", report_payload)

        # Print formatted table
        _print_auto_screening_table(trade_date, top_results, market_state, len(candidates), top_n, report_path)
        return 0
    finally:
        progress.stop()


def _print_auto_screening_table(
    trade_date: str,
    top_results: list,
    market_state: object,
    pool_size: int,
    top_n: int,
    report_path: Path,
) -> None:
    """打印格式化的自动筛选推荐表格。"""
    from colorama import Fore, Style
    from tabulate import tabulate

    state_type = getattr(market_state, "state_type", "mixed")
    position_scale = getattr(market_state, "position_scale", 1.0)

    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[Auto Screening] 一键全流程{Style.RESET_ALL}")
    print(f"  日期: {trade_date}  |  市场状态: {state_type}  |  仓位系数: {position_scale:.2f}")
    print(f"  Layer A 候选池: {pool_size} 只  |  Top {top_n} 推荐")
    print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}\n")

    if not top_results:
        print(f"{Fore.YELLOW}  无符合条件的推荐标的{Style.RESET_ALL}\n")
        return

    table_data = []
    for idx, item in enumerate(top_results, 1):
        decision = item.decision
        score_b = item.score_b

        # Color-code the decision
        if score_b >= 0.35:
            decision_colored = f"{Fore.GREEN}{decision}{Style.RESET_ALL}"
            score_colored = f"{Fore.GREEN}{score_b:+.4f}{Style.RESET_ALL}"
        elif score_b >= 0.0:
            decision_colored = f"{Fore.YELLOW}{decision}{Style.RESET_ALL}"
            score_colored = f"{Fore.YELLOW}{score_b:+.4f}{Style.RESET_ALL}"
        else:
            decision_colored = f"{Fore.RED}{decision}{Style.RESET_ALL}"
            score_colored = f"{Fore.RED}{score_b:+.4f}{Style.RESET_ALL}"

        # Signal summary: direction + confidence per strategy
        signals = item.strategy_signals
        signal_parts = []
        for strategy_name in ("trend", "mean_reversion", "fundamental", "event_sentiment"):
            sig = signals.get(strategy_name)
            if sig is None:
                signal_parts.append("—")
                continue
            arrow = "↑" if sig.direction > 0 else "↓" if sig.direction < 0 else "—"
            signal_parts.append(f"{arrow}{sig.confidence:.0f}")
        signal_summary = " ".join(signal_parts)

        # Arbitration flags
        arbitration = ", ".join(item.arbitration_applied) if item.arbitration_applied else ""

        table_data.append([
            f"{idx}",
            item.ticker,
            score_colored,
            decision_colored,
            signal_summary,
            arbitration,
        ])

    headers = [
        f"{Fore.WHITE}#",
        "Ticker",
        "Score B",
        "Decision",
        "Signals (T MR F E)",
        "Arbitration",
    ]
    print(tabulate(table_data, headers=headers, tablefmt="grid", colalign=("right", "left", "right", "center", "center", "left")))

    print(f"\n  详细报告已保存: {Fore.CYAN}{report_path}{Style.RESET_ALL}")
    print()


if __name__ == "__main__":
    if "--daily-gainers" in sys.argv:
        raise SystemExit(run_daily_gainers_cli())

    if "--pipeline" in sys.argv or "--screen-only" in sys.argv:
        parser = argparse.ArgumentParser(description="Institutional multi-strategy pipeline runner")
        parser.add_argument("--pipeline", action="store_true", help="运行全流水线模式")
        parser.add_argument("--screen-only", action="store_true", help="仅运行 Layer A + Layer B")
        parser.add_argument("--trade-date", required=True, help="交易日期 YYYYMMDD")
        args = parser.parse_args()
        if args.pipeline:
            raise SystemExit(run_pipeline_mode(args.trade_date))
        if args.screen_only:
            raise SystemExit(run_screen_only_mode(args.trade_date))

    # Detect --auto early via sys.argv to bypass interactive prompts
    is_auto = "--auto" in sys.argv

    inputs = parse_cli_inputs(
        description="Run the hedge fund trading system",
        require_tickers=not is_auto,
        default_months_back=None,
        include_graph_flag=True,
        include_reasoning_flag=True,
    )

    # --auto mode: run the full screening pipeline
    if inputs.auto:
        trade_date = inputs.end_date.replace("-", "")
        raise SystemExit(run_auto_screening(trade_date, top_n=inputs.top_n))

    tickers = inputs.tickers
    selected_analysts = inputs.selected_analysts

    # Construct portfolio here
    portfolio = {
        "cash": inputs.initial_cash,
        "margin_requirement": inputs.margin_requirement,
        "margin_used": 0.0,
        "positions": {
            ticker: {
                "long": 0,
                "short": 0,
                "long_cost_basis": 0.0,
                "short_cost_basis": 0.0,
                "short_margin_used": 0.0,
            }
            for ticker in tickers
        },
        "realized_gains": {
            ticker: {
                "long": 0.0,
                "short": 0.0,
            }
            for ticker in tickers
        },
    }

    result = run_hedge_fund(
        tickers=tickers,
        start_date=inputs.start_date,
        end_date=inputs.end_date,
        portfolio=portfolio,
        show_reasoning=inputs.show_reasoning,
        selected_analysts=inputs.selected_analysts,
        model_name=inputs.model_name,
        model_provider=inputs.model_provider,
    )
    print_trading_output(result)
    save_trading_report(
        result=result,
        tickers=tickers,
        model_name=inputs.model_name,
        model_provider=inputs.model_provider,
        start_date=inputs.start_date,
        end_date=inputs.end_date,
    )
