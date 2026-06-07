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
from src.screening.consecutive_recommendation import (
    DEFAULT_LOOKBACK_DAYS,
    enrich_recommendations_with_history,
    resolve_report_dir as _resolve_consecutive_report_dir,
)
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
    fused = fuse_batch(scored, market_state, trade_date, candidates=candidates)
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
        # P0-1: 创建批量数据获取器 (默认开启，可通过 USE_BATCH_FETCHER=false 关闭)
        from src.screening.batch_data_fetcher import (
            get_global_batch_data_fetcher,
        )
        from src.screening.signal_decay_detector import (
            DecayLevel,
            build_decay_summary,
            detect_signal_decay,
        )

        batch_fetcher = get_global_batch_data_fetcher()
        batch_fetcher.reset_stats()
        logger.info(
            "[Auto] P0-1 BatchDataFetcher: use_batch=%s, max_concurrency=%d",
            batch_fetcher.use_batch,
            batch_fetcher._max_concurrency,
        )

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
        fused = fuse_batch(scored, market_state, trade_date, candidates=candidates)

        # Step 4: 排序输出 Top N
        progress.update_status("auto_screening", None, f"Step 4/4: 输出 Top {top_n} 推荐")
        sorted_results = sorted(fused, key=lambda item: item.score_b, reverse=True)
        top_results = sorted_results[:top_n]

        # Sector concentration guard
        sector_warnings = _check_sector_concentration(top_results)

        # P0-6 多日推荐聚合 — 附加连续推荐标记
        consecutive_report_dir = _resolve_consecutive_report_dir()
        top_results_serializable = [item.model_dump() for item in top_results]
        top_results_serializable = enrich_recommendations_with_history(
            recommendations=top_results_serializable,
            lookback_days=DEFAULT_LOOKBACK_DAYS,
            report_dir=consecutive_report_dir,
            end_date=trade_date,
        )
        consecutive_highlight = sum(
            1 for rec in top_results_serializable if rec.get("consecutive_days", 0) >= 3
        )

        # P0-3 信号衰减检测 — 对比当前与历史 score_b
        decay_map = detect_signal_decay(
            current_recommendations=top_results_serializable,
            report_dir=consecutive_report_dir,
            lookback_days=DEFAULT_LOOKBACK_DAYS,
            end_date=trade_date,
        )
        decay_summary = build_decay_summary(decay_map)
        # Attach decay info to each recommendation in the serializable list
        for rec in top_results_serializable:
            ticker = rec.get("ticker", "")
            decay_info = decay_map.get(ticker)
            if decay_info is not None:
                rec["decay"] = decay_info.to_dict()
            else:
                rec["decay"] = {"level": "none", "current_score": rec.get("score_b", 0), "previous_score": None, "change_pct": None, "days_since_peak": 0}

        # Save full report
        report_payload = {
            "mode": "auto_screening",
            "date": trade_date,
            "market_state": market_state.model_dump(),
            "layer_a_count": len(candidates),
            "total_scored": len(fused),
            "high_pool_count": sum(1 for item in fused if item.score_b >= 0.35),
            "top_n": top_n,
            "recommendations": top_results_serializable,
            "sector_concentration_warnings": sector_warnings,
            "consecutive_recommendation": {
                "lookback_days": DEFAULT_LOOKBACK_DAYS,
                "high_streak_count": consecutive_highlight,
            },
            # P0-3: 信号衰减汇总
            "signal_decay_summary": decay_summary,
            # P0-1: 批量获取层统计
            "batch_data_fetcher": {
                "use_batch": batch_fetcher.use_batch,
                **batch_fetcher.stats(),
            },
        }
        report_path = _save_json_report(f"auto_screening_{trade_date}.json", report_payload)

        # P0-1: 输出 batch fetcher 统计
        fetcher_stats = batch_fetcher.stats()
        logger.info(
            "[Auto] P0-1 BatchDataFetcher stats: batch_calls=%d, batch_failures=%d, "
            "single_ticker_calls=%d, cache_hits=%d",
            fetcher_stats["batch_calls"],
            fetcher_stats["batch_failures"],
            fetcher_stats["single_ticker_calls"],
            fetcher_stats["cache_hits"],
        )

        # Print formatted table
        _print_auto_screening_table(
            trade_date,
            top_results,
            market_state,
            len(candidates),
            top_n,
            report_path,
            sector_warnings,
            consecutive_recommendations=top_results_serializable,
            decay_map=decay_map,
        )
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
    sector_warnings: list[str] | None = None,
    consecutive_recommendations: list[dict] | None = None,
    decay_map: dict | None = None,
) -> None:
    """打印格式化的自动筛选推荐表格。

    Args:
        consecutive_recommendations: 与 ``top_results`` 顺序对应的连续推荐元数据列表
            (每个 dict 包含 ``consecutive_days`` / ``stability_bonus`` 等字段)。
        decay_map: P0-3 信号衰减映射 ``{ticker: DecayInfo}``，用于显示 Decay 列。
    """
    from colorama import Fore, Style
    from tabulate import tabulate

    from src.screening.signal_decay_detector import DecayInfo, DecayLevel

    state_type = getattr(market_state, "state_type", "mixed")
    position_scale = getattr(market_state, "position_scale", 1.0)

    consecutive_lookup: dict[str, dict] = {}
    if consecutive_recommendations:
        for rec in consecutive_recommendations:
            ticker = rec.get("ticker", "")
            if ticker:
                consecutive_lookup[ticker] = rec

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

        # P0-6 连续推荐标记
        consecutive_info = consecutive_lookup.get(item.ticker, {})
        consecutive_days = int(consecutive_info.get("consecutive_days", 0) or 0)
        if consecutive_days >= 3:
            consecutive_str = f"{Fore.GREEN}{Style.BRIGHT}{consecutive_days}d{Style.RESET_ALL}"
        elif consecutive_days == 2:
            consecutive_str = f"{Fore.YELLOW}{consecutive_days}d{Style.RESET_ALL}"
        elif consecutive_days == 1:
            consecutive_str = f"{Fore.WHITE}{consecutive_days}d{Style.RESET_ALL}"
        else:
            consecutive_str = f"{Fore.RED}—{Style.RESET_ALL}"

        # 高亮连续 3+ 天的 ticker
        ticker_label = f"{item.ticker} {item.name}" if item.name else item.ticker
        if consecutive_days >= 3:
            ticker_label = f"{Fore.GREEN}{Style.BRIGHT}{ticker_label}{Style.RESET_ALL}"

        # P0-3 信号衰减标记
        decay_info = decay_map.get(item.ticker) if decay_map else None
        if decay_info is None or decay_info.level == DecayLevel.NONE:
            decay_str = f"{Fore.WHITE}—{Style.RESET_ALL}"
        elif decay_info.level == DecayLevel.MILD:
            decay_str = f"{Fore.YELLOW}↓{abs(decay_info.change_pct or 0):.0f}%{Style.RESET_ALL}"
        elif decay_info.level == DecayLevel.MODERATE:
            decay_str = f"{Fore.YELLOW}{Style.BRIGHT}↓{abs(decay_info.change_pct or 0):.0f}%{Style.RESET_ALL}"
        else:  # SEVERE
            decay_str = f"{Fore.RED}{Style.BRIGHT}↓{abs(decay_info.change_pct or 0):.0f}%{Style.RESET_ALL}"

        table_data.append([
            f"{idx}",
            ticker_label,
            item.industry_sw or "—",
            score_colored,
            decision_colored,
            signal_summary,
            consecutive_str,
            decay_str,
            arbitration,
        ])

    headers = [
        f"{Fore.WHITE}#",
        "Ticker",
        "Industry",
        "Score B",
        "Decision",
        "Signals (T MR F E)",
        "Consecutive",
        "Decay",
        "Arbitration",
    ]
    print(tabulate(table_data, headers=headers, tablefmt="grid", colalign=("right", "left", "left", "right", "center", "center", "center", "center", "left")))

    print(f"\n  详细报告已保存: {Fore.CYAN}{report_path}{Style.RESET_ALL}")

    # Sector concentration warnings
    if sector_warnings:
        for w in sector_warnings:
            print(f"  {Fore.YELLOW}⚠️  {w}{Style.RESET_ALL}")
    print()


def _check_sector_concentration(top_results: list, threshold: float = 0.4) -> list[str]:
    """Check sector concentration in top recommendations and return warnings."""
    from collections import Counter

    if not top_results:
        return []

    warnings: list[str] = []
    sectors = [item.industry_sw for item in top_results if item.industry_sw]
    if not sectors:
        return warnings

    total = len(top_results)
    sector_counts = Counter(sectors)
    for sector, count in sector_counts.most_common(3):
        ratio = count / total
        if ratio > threshold and sector:
            warnings.append(f"行业集中度: {sector} {count}/{total} ({ratio:.0%}). 建议分散配置。")
    return warnings


def run_explain(ticker: str) -> int:
    """Explain why a ticker was recommended by reading the latest auto-screening report.

    Loads the most recent auto_screening_*.json from data/reports/, finds the ticker,
    and prints a 10-line readable breakdown of each strategy's contribution.
    """
    import json as _json

    from colorama import Fore, Style

    # Find the most recent auto_screening report
    reports_dir = _REPORT_DIR if hasattr(__import__(__name__), "_REPORT_DIR") else Path("data/reports")
    if not reports_dir.exists():
        print(f"{Fore.RED}未找到 reports 目录: {reports_dir}{Style.RESET_ALL}")
        return 1

    report_files = sorted(reports_dir.glob("auto_screening_*.json"), reverse=True)
    if not report_files:
        print(f"{Fore.RED}没有 auto_screening_*.json 报告, 请先运行 --auto{Style.RESET_ALL}")
        return 1

    latest = report_files[0]
    try:
        with open(latest) as f:
            data = _json.load(f)
    except Exception as exc:  # pragma: no cover
        print(f"{Fore.RED}读取报告失败: {exc}{Style.RESET_ALL}")
        return 1

    recs = data.get("recommendations", [])
    match = next((r for r in recs if r.get("ticker") == ticker), None)
    if not match:
        print(f"{Fore.YELLOW}在 {latest.name} 中未找到 {ticker}, 该票未在 Top 推荐中{Style.RESET_ALL}")
        available = ", ".join(r.get("ticker", "") for r in recs[:10])
        print(f"  Top 10 票: {available}")
        return 1

    name = match.get("name", "")
    industry = match.get("industry_sw", "")
    score_b = match.get("score_b", 0.0)
    decision = match.get("decision", "neutral")
    signals = match.get("strategy_signals", {})
    arbitration = match.get("arbitration_applied", [])

    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[Explain] {ticker} {name} ({industry}){Style.RESET_ALL}")
    print(f"  报告: {latest.name}")
    print(f"  决策: {decision}  |  Score B: {score_b:+.4f}")
    print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}\n")

    # Market state at scoring time
    ms = data.get("market_state", {})
    if ms:
        print(f"{Fore.CYAN}市场状态:{Style.RESET_ALL} {ms.get('state_type', '?')}  |  "
              f"仓位系数: {ms.get('position_scale', 1.0):.2f}  |  "
              f"regime: {ms.get('regime_gate_level', 'normal')}")

    # Per-strategy breakdown
    _STRATEGY_CN_LABELS = {
        "trend": "趋势策略",
        "mean_reversion": "均值回归",
        "fundamental": "基本面",
        "event_sentiment": "事件情绪",
    }
    print(f"\n{Fore.CYAN}策略贡献:{Style.RESET_ALL}")
    for strat_name in ("trend", "mean_reversion", "fundamental", "event_sentiment"):
        sig = signals.get(strat_name)
        if not sig:
            print(f"  {strat_name:18s}  —  数据缺失")
            continue
        direction = sig.get("direction", 0)
        conf = sig.get("confidence", 0.0)
        arrow = "↑" if direction > 0 else "↓" if direction < 0 else "—"
        color = Fore.GREEN if direction > 0 else Fore.RED if direction < 0 else Fore.YELLOW
        print(f"  {strat_name:18s}  {color}{arrow} {conf:5.1f}{Style.RESET_ALL}")

    # ── Block A: 因子贡献度明细 ──
    _print_factor_detail_block(signals, _STRATEGY_CN_LABELS)

    # ── Block B: 近 5 日关键事件 ──
    _print_recent_events_block(data, match)

    # ── Block C: 同行业排名 ──
    _print_industry_ranking_block(recs, match)

    # Arbitration
    if arbitration:
        print(f"\n{Fore.CYAN}仲裁规则:{Style.RESET_ALL}")
        for rule in arbitration:
            print(f"  • {rule}")
    else:
        print(f"\n{Fore.CYAN}仲裁规则:{Style.RESET_ALL} 无")

    print()
    return 0


def _build_factor_bar(confidence: float, max_bar_width: int = 10) -> str:
    """Build a 10-cell ASCII bar chart proportional to confidence (0-100)."""
    import math as _math

    # Guard against NaN — cannot convert NaN to int
    if _math.isnan(confidence) if isinstance(confidence, float) else False:
        confidence = 0.0
    filled = min(max(int(round(confidence / 10.0)), 0), max_bar_width)
    return "█" * filled + "░" * (max_bar_width - filled)


def _print_factor_detail_block(signals: dict, strategy_labels: dict) -> None:
    """Block A: Print top-3 sub-factor detail per strategy, grouped and bar-charted."""
    from colorama import Fore, Style

    print(f"\n{Fore.CYAN}因子明细:{Style.RESET_ALL}")
    has_any_factor = False
    for strat_name in ("trend", "mean_reversion", "fundamental", "event_sentiment"):
        sig = signals.get(strat_name)
        if not sig or not isinstance(sig, dict):
            continue
        sub_factors = sig.get("sub_factors")
        if not sub_factors or not isinstance(sub_factors, dict):
            continue
        # Collect (name, direction, confidence) for each sub-factor
        factor_items: list[tuple[str, int, float]] = []
        for _fname, fpayload in sub_factors.items():
            if not isinstance(fpayload, dict):
                continue
            fname = fpayload.get("name", _fname)
            fdir = fpayload.get("direction", 0)
            fconf = fpayload.get("confidence", 0.0)
            factor_items.append((str(fname), int(fdir), float(fconf)))
        if not factor_items:
            continue
        # Sort by |confidence| descending, take top 3
        factor_items.sort(key=lambda x: abs(x[2]), reverse=True)
        label = strategy_labels.get(strat_name, strat_name)
        print(f"  {label}:")
        for fname, fdir, fconf in factor_items[:3]:
            arrow = "↑" if fdir > 0 else "↓" if fdir < 0 else "—"
            color = Fore.GREEN if fdir > 0 else Fore.RED if fdir < 0 else Fore.YELLOW
            bar = _build_factor_bar(fconf)
            print(f"    {fname:20s} {color}{arrow} {fconf:5.2f}{Style.RESET_ALL}  {bar}")
            has_any_factor = True
    if not has_any_factor:
        print("  暂无因子明细数据")


def _print_recent_events_block(report_data: dict, match: dict) -> None:
    """Block B: Print recent 5-day key events from report or event_sentiment sub-factors."""
    from colorama import Fore, Style

    print(f"\n{Fore.CYAN}近期事件 (5 日):{Style.RESET_ALL}")

    # Priority 1: report-level recent_events field
    events = report_data.get("recent_events")
    if events and isinstance(events, list) and len(events) > 0:
        for evt in events[:5]:
            if isinstance(evt, dict):
                date_str = str(evt.get("date", evt.get("time", "")))
                desc = str(evt.get("description", evt.get("text", str(evt))))
                print(f"  {date_str}  {desc}")
            else:
                print(f"  {evt}")
        return

    # Priority 2: extract from event_sentiment strategy's sub-factors metrics
    signals = match.get("strategy_signals", {})
    event_sig = signals.get("event_sentiment")
    if event_sig and isinstance(event_sig, dict):
        sub_factors = event_sig.get("sub_factors")
        if isinstance(sub_factors, dict):
            articles = _extract_articles_from_event_subfactors(sub_factors)
            if articles:
                printed_any = False
                for art in articles[:5]:
                    date_str = str(art.get("days_old", "?"))
                    title = str(art.get("title", ""))
                    if title:
                        day_label = f"{int(date_str)}天前" if date_str.isdigit() else date_str
                        print(f"  {day_label}  新闻: \"{title}\"")
                        printed_any = True
                if printed_any:
                    return

    print("  暂无近期事件数据")


def _extract_articles_from_event_subfactors(sub_factors: dict) -> list[dict]:
    """Extract article metrics from news_sentiment sub-factor within event_sentiment."""
    news_sf = sub_factors.get("news_sentiment")
    if not isinstance(news_sf, dict):
        return []
    metrics = news_sf.get("metrics")
    if not isinstance(metrics, dict):
        return []
    articles = metrics.get("articles")
    if not isinstance(articles, list):
        return []
    return [a for a in articles if isinstance(a, dict)]


def _print_industry_ranking_block(recs: list[dict], match: dict) -> None:
    """Block C: Print industry ranking and percentile among same-industry recommendations."""
    from colorama import Fore, Style

    industry = match.get("industry_sw", "")
    ticker = match.get("ticker", "")

    if not industry:
        print(f"\n{Fore.CYAN}同行业排名:{Style.RESET_ALL} 无行业信息")
        return

    # Filter recommendations in the same industry, sort by score_b descending
    # GAMMA-008: coerce None / NaN score_b to 0.0 — .get() only substitutes
    # when the key is missing, not when the value is explicitly None or NaN.
    import math as _math

    def _safe_score(v: object) -> float:
        if v is None:
            return 0.0
        try:
            fv = float(v)
            return 0.0 if _math.isnan(fv) else fv
        except (TypeError, ValueError):
            return 0.0

    peers = [
        (r.get("ticker", ""), _safe_score(r.get("score_b")))
        for r in recs
        if r.get("industry_sw") == industry
    ]
    if not peers:
        print(f"\n{Fore.CYAN}同行业排名:{Style.RESET_ALL} 无同行业数据")
        return

    peers_sorted = sorted(peers, key=lambda x: x[1], reverse=True)
    total = len(peers_sorted)

    # Find current ticker's rank
    rank = 1
    for idx, (t, _s) in enumerate(peers_sorted, 1):
        if t == ticker:
            rank = idx
            break

    percentile = rank / total if total > 0 else 1.0
    pct_label = f"前 {percentile:.0%}" if percentile <= 1.0 else "—"
    print(f"\n{Fore.CYAN}同行业排名:{Style.RESET_ALL} {industry} — 第 {rank}/{total} 名 ({pct_label})")


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

    # --explain mode: read the latest auto-screening report and explain a ticker
    if inputs.explain:
        raise SystemExit(run_explain(inputs.explain))

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
