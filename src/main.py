import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from src.agents.portfolio_manager import portfolio_management_agent
from src.agents.risk_manager import risk_management_agent
from src.cli.input import (
    parse_cli_inputs,
)
from src.execution.daily_pipeline import DailyPipeline
from src.graph.state import AgentState
from src.screening.candidate_pool import build_candidate_pool
from src.screening.market_state import detect_market_state
from src.screening.signal_fusion import fuse_batch
from src.screening.strategy_scorer import score_batch
from src.tools.tushare_api import get_ashare_daily_gainers_with_tushare
from src.utils.analysts import get_analyst_nodes
from src.utils.display import (
    print_trading_output,
    save_daily_gainers_report,
    save_trading_report,
)
from src.utils.logging import get_logger, setup_logging
from src.utils.progress import progress

# Load environment variables from .env file
load_dotenv()

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
    selected_analysts: list[str] = [],
    model_name: str = "gpt-4.1",
    model_provider: str = "OpenAI",
):
    # Start progress tracking
    progress.start()

    try:
        # Build workflow (default to all analysts when none provided)
        workflow = create_workflow(selected_analysts if selected_analysts else None)
        agent = workflow.compile()

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
                    "model_name": model_name,
                    "model_provider": model_provider,
                },
            },
        )

        return {
            "decisions": parse_hedge_fund_response(final_state["messages"][-1].content),
            "analyst_signals": final_state["data"]["analyst_signals"],
        }
    finally:
        # Stop progress tracking
        progress.stop()


def start(state: AgentState):
    """Initialize the workflow with the input message."""
    return state


def create_workflow(selected_analysts=None):
    """Create the workflow with selected analysts."""
    workflow = StateGraph(AgentState)
    workflow.add_node("start_node", start)

    # Get analyst nodes from the configuration
    analyst_nodes = get_analyst_nodes()

    # Default to all analysts if none selected
    if selected_analysts is None:
        selected_analysts = list(analyst_nodes.keys())
    # Add selected analyst nodes
    for analyst_key in selected_analysts:
        node_name, node_func = analyst_nodes[analyst_key]
        workflow.add_node(node_name, node_func)
        workflow.add_edge("start_node", node_name)

    # Always add risk and portfolio management
    workflow.add_node("risk_management_agent", risk_management_agent)
    workflow.add_node("portfolio_manager", portfolio_management_agent)

    # Connect selected analysts to risk management
    for analyst_key in selected_analysts:
        node_name = analyst_nodes[analyst_key][0]
        workflow.add_edge(node_name, "risk_management_agent")

    workflow.add_edge("risk_management_agent", "portfolio_manager")
    workflow.add_edge("portfolio_manager", END)

    workflow.set_entry_point("start_node")
    return workflow


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

    inputs = parse_cli_inputs(
        description="Run the hedge fund trading system",
        require_tickers=True,
        default_months_back=None,
        include_graph_flag=True,
        include_reasoning_flag=True,
    )

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
