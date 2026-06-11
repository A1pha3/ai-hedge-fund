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
from src.screening.industry_rotation import (
    IndustrySignal,
    calculate_industry_rotation,
    format_rotation_block,
)
from src.screening.recommendation_tracker import (
    get_tracking_summary,
    render_tracking_summary,
    update_tracking_history,
)
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
from src.utils.numeric import safe_float as _safe_float, safe_int as _safe_int, is_finite_number as _is_finite_number

# Round 20.14: 从 main.py 抽取到独立模块的 UI 辅助函数 (纯重构, 行为不变)
from src.cli.explain_helpers import (
    _print_factor_detail_block,
    _print_industry_ranking_block,
    _print_recent_events_block,
)
from src.cli.market_status_helpers import (
    _extract_market_status,
    _format_market_status_table,
)

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



def run_market_status(trade_date: str) -> int:
    """P1-9 一键查看市场温度计 — 不跑全流程，仅展示市场状态。

    调用 ``market_state.py`` 的 ``detect_market_state()``，
    以彩色表格形式输出 ADX、ATR、涨跌比、北向资金、涨跌停等核心指标，
    并给出综合 state_type / 仓位系数 / Regime Gate。

    Args:
        trade_date: 交易日期，格式 YYYYMMDD

    Returns:
        退出码（0 = 成功，1 = 数据暂不可用或异常）
    """
    from colorama import Fore, Style

    try:
        market_state = detect_market_state(trade_date)
    except Exception as exc:
        print(f"{Fore.RED}市场温度计: 数据获取失败: {exc}{Style.RESET_ALL}")
        return 1

    data = _extract_market_status(market_state)
    data["date"] = trade_date

    output = _format_market_status_table(data)
    print()
    print(output)
    print()

    has_index_data = _is_finite_number(data["adx"]) and data["adx"] > 0
    has_price_data = _is_finite_number(data["atr_ratio"]) and data["atr_ratio"] > 0
    if not has_index_data and not has_price_data:
        return 1
    return 0


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
    try:
        pipeline = DailyPipeline()
        plan = pipeline.run_post_market(trade_date)
        output_path = _save_json_report(f"execution_plan_{trade_date}.json", plan.model_dump())
        print(f"[Pipeline] 日期: {trade_date}")
        print(f"[Pipeline] Layer A: {plan.layer_a_count} | Layer B: {plan.layer_b_count} | Layer C: {plan.layer_c_count}")
        print(f"[Pipeline] 买入: {len(plan.buy_orders)} | 卖出: {len(plan.sell_orders)}")
        print(f"[Pipeline] 已输出: {output_path}")
        return 0
    except Exception as exc:
        print(f"[Pipeline] 执行失败: {exc}")
        return 1


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


def _build_selected_strategy_weights(selected_strategies: list[str] | None) -> "StrategyWeights | None":
    """Convert a strategy subset into equal custom weights for reranking."""
    if not selected_strategies:
        return None

    from src.screening.custom_weights import STRATEGY_KEYS, StrategyWeights

    invalid = [strategy for strategy in selected_strategies if strategy not in STRATEGY_KEYS]
    if invalid:
        raise ValueError(f"未知策略: {invalid} (合法: {list(STRATEGY_KEYS)})")

    unique_selected = [strategy for strategy in STRATEGY_KEYS if strategy in set(selected_strategies)]
    if not unique_selected:
        return None

    weight_per_strategy = 1.0 / len(unique_selected)
    return StrategyWeights(
        trend=weight_per_strategy if "trend" in unique_selected else 0.0,
        mean_reversion=weight_per_strategy if "mean_reversion" in unique_selected else 0.0,
        fundamental=weight_per_strategy if "fundamental" in unique_selected else 0.0,
        event_sentiment=weight_per_strategy if "event_sentiment" in unique_selected else 0.0,
    )


def compute_auto_screening_results(trade_date: str, top_n: int = 10, selected_strategies: list[str] | None = None) -> dict:
    """Run the full --auto pipeline and return a JSON-serializable payload (no IO side effects).

    这是 ``run_auto_screening`` 的纯函数版本 — 不打印表格, 不保存文件,
    不写日志, 仅返回完整的 payload dict (含 recommendations / market_state /
    industry_rotation / batch_data_fetcher 统计 / consecutive_recommendation /
    signal_decay_summary 等).

    复用此函数可让 Web 端点 ``POST /api/screening/auto`` 与 CLI ``--auto`` 输出
    保持完全一致。

    Args:
        trade_date: 交易日期, 格式 YYYYMMDD
        top_n: 返回 Top N 推荐 (默认 10)
        selected_strategies: 可选策略子集; 若提供, 在 Top N 截断前按该子集等权重重排

    Returns:
        dict 包含所有 auto_screening 输出字段, 可直接 ``json.dumps`` 序列化。

    Raises:
        ValueError: 候选池为空 (供 Web 端返回 503)
        RuntimeError: 数据获取失败 (e.g. tushare token 缺失)
    """
    # P0-1: 创建批量数据获取器 (默认开启, 可通过 USE_BATCH_FETCHER=false 关闭)
    from src.screening.batch_data_fetcher import (
        get_global_batch_data_fetcher,
    )
    from src.screening.signal_decay_detector import (
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
        raise ValueError(f"候选池为空 (trade_date={trade_date}), 请检查市场数据源是否可用")

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
    if selected_strategies:
        from src.screening.custom_weights import reweight_recommendations

        selected_weights = _build_selected_strategy_weights(selected_strategies)
        reweighted_results = reweight_recommendations(
            [item.model_dump(mode="json") for item in fused],
            selected_weights,
        )
        top_results_serializable = reweighted_results[:top_n]
        fused_by_ticker = {str(item.ticker): item for item in fused}
        top_results_for_sector = [fused_by_ticker.get(str(rec.get("ticker", "")), rec) for rec in top_results_serializable]
    else:
        sorted_results = sorted(fused, key=lambda item: item.score_b, reverse=True)
        top_results = sorted_results[:top_n]
        top_results_for_sector = top_results
        top_results_serializable = [item.model_dump(mode="json") for item in top_results]

    # Sector concentration guard
    sector_warnings = _check_sector_concentration(top_results_for_sector)

    # P0-6 多日推荐聚合 — 附加连续推荐标记
    consecutive_report_dir = _resolve_consecutive_report_dir()
    top_results_serializable = enrich_recommendations_with_history(
        recommendations=top_results_serializable,
        lookback_days=DEFAULT_LOOKBACK_DAYS,
        report_dir=consecutive_report_dir,
        end_date=trade_date,
    )
    consecutive_highlight = sum(1 for rec in top_results_serializable if rec.get("consecutive_days", 0) >= 3)

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

    # P1-2 行业轮动信号 — 申万一级行业动量 + 强度排名
    industry_signals = calculate_industry_rotation(
        recommendations=top_results_serializable,
        trade_date=trade_date,
    )
    industry_rotation_payload = [sig.to_dict() for sig in industry_signals]

    # 落盘当前报告 — 让后续 P1-3 追踪 / P0-6 连续推荐 / P0-3 信号衰减
    # 等跨日模块能读到最新文件。
    _save_json_report(
        f"auto_screening_{trade_date}.json",
        {
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
            "signal_decay_summary": decay_summary,
            "batch_data_fetcher": {
                "use_batch": batch_fetcher.use_batch,
                **batch_fetcher.stats(),
            },
            "industry_rotation": industry_rotation_payload,
            # P1-10: 条件单建议 (空数组 — 真实价格 provider 由调用方注入)
            "conditional_orders": [],
        },
    )

    # 构建 payload (不再包含 market_state.model_dump() 自身 — caller 单独获取)
    fetcher_stats = batch_fetcher.stats()
    return {
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
            **fetcher_stats,
        },
        # P1-2: 行业轮动信号
        "industry_rotation": industry_rotation_payload,
        # P1-10: 条件单建议 (基于 ATR 波动率) — 默认注入空数组,
        # 真实价格 provider 由调用方在 Web 端 / CLI 端注入
        "conditional_orders": [],
    }


def run_preheat(
    trade_date: str | None = None,
    tasks: list[str] | None = None,
    force: bool = False,
    list_tasks: bool = False,
) -> int:
    """P1-1 缓存预热 CLI 入口。

    Args:
        trade_date: 交易日期 YYYYMMDD, None = 今天。
        tasks: 指定预热任务, None = 全部。
        force: 强制刷新。
        list_tasks: 列出可用任务后退出。

    Returns:
        退出码 (0 = 成功)。
    """
    from colorama import Fore, Style

    from src.data.cache_preheater import format_preheat_report, get_preheat_tasks, preheat_cache

    if list_tasks:
        available = get_preheat_tasks()
        print(f"\n{Fore.CYAN}{Style.BRIGHT}可用预热任务:{Style.RESET_ALL}")
        for t in available:
            print(f"  {t['id']:<22s}  {t['description']:<20s}  (~{t['estimated_time']})")
        print()
        return 0

    if trade_date is None:
        trade_date = datetime.now().strftime("%Y%m%d")

    task_label = "全部" if tasks is None else ",".join(tasks)
    stats = preheat_cache(trade_date, tasks=tasks, force=force, concurrency=4)
    print(format_preheat_report(stats, trade_date, task_label))
    return 0 if stats.tasks_failed == 0 else 1


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

    progress.start()
    try:
        # P1-1: PREHEAT_BEFORE_AUTO=true 时在 auto 开始前预热缓存
        if os.environ.get("PREHEAT_BEFORE_AUTO", "").strip().lower() in ("1", "true", "yes", "on"):
            try:
                from src.data.cache_preheater import preheat_cache as _preheat

                _preheat_stats = _preheat(trade_date, concurrency=4)
                logger.info(
                    "[Auto] P1-1 缓存预热完成: %d/%d 成功, %d 跳过, %.1fs",
                    _preheat_stats.tasks_success,
                    _preheat_stats.tasks_total,
                    _preheat_stats.tasks_skipped,
                    _preheat_stats.elapsed_seconds,
                )
            except Exception as exc:  # pragma: no cover - 预热失败不阻塞主流程
                logger.warning("[Auto] P1-1 缓存预热失败: %s", exc)

        # 调用纯函数 — 复用 Web 端点的核心逻辑
        report_payload = compute_auto_screening_results(trade_date, top_n)

        # 重建 top_results 对象 (供 CLI 表格打印)
        from src.screening.signal_fusion import FusedScore  # noqa: F401

        top_results = [FusedScore.model_validate(item) for item in report_payload["recommendations"]]

        # 反查 market_state (供 _print_auto_screening_table 使用)
        market_state_payload = report_payload["market_state"]
        from src.screening.market_state import MarketState

        market_state = MarketState.model_validate(market_state_payload)

        # 反查行业轮动信号 (供 CLI 打印)
        industry_signals = [
            IndustrySignal(
                industry_name=item.get("industry_name", ""),
                industry_code=item.get("industry_code", ""),
                momentum_score=item.get("momentum_score", 0.0),
                avg_score_b=item.get("avg_score_b", 0.0),
                candidate_count=item.get("candidate_count", 0),
                north_money_flow=item.get("north_money_flow", 0.0),
                rank=item.get("rank", 0),
                tickers=list(item.get("tickers", []) or []),
            )
            for item in report_payload.get("industry_rotation", [])
        ]

        # 反查信号衰减映射 (供 CLI 打印)
        from src.screening.signal_decay_detector import DecayInfo

        decay_map: dict = {}
        for rec in report_payload["recommendations"]:
            decay_payload = rec.get("decay") or {}
            if decay_payload.get("level") and decay_payload.get("level") != "none":
                try:
                    decay_map[rec["ticker"]] = DecayInfo.from_dict(decay_payload)
                except Exception:
                    pass

        # Save full report — 报告已由 compute_auto_screening_results 写入,
        # 这里复用同一路径返回给 _print_auto_screening_table 用于 UI 提示。
        report_path = _resolve_consecutive_report_dir() / f"auto_screening_{trade_date}.json"

        # P1-3 + P0-5: tracking history + watchlist update (lightweight side effects)
        pdf_path = _enrich_recommendations_with_history(
            report_payload=report_payload,
            trade_date=trade_date,
            tracking_dir=report_path.parent,
        )

        # P1-11 + P1-12 + P2-3: post-screening analytics (attribution, rebalance, push)
        _handle_post_screening_tasks(
            report_payload=report_payload,
            trade_date=trade_date,
            report_path=report_path,
            pdf_path=pdf_path,
        )

        # P0-1 + O-1: output batch fetcher stats + formatted table
        _print_table_block(
            report_payload=report_payload,
            trade_date=trade_date,
            top_results=top_results,
            market_state=market_state,
            top_n=top_n,
            report_path=report_path,
            decay_map=decay_map,
            industry_signals=industry_signals,
        )

        return 0
    except ValueError as exc:
        # 候选池为空 — 纯函数明确抛出的 ValueError
        print(f"{Fore.YELLOW}[Auto] {exc}{Style.RESET_ALL}")
        return 1
    finally:
        progress.stop()


def _enrich_recommendations_with_history(
    report_payload: dict,
    trade_date: str,
    tracking_dir: Path,
) -> Path | None:
    """P1-3 + P0-5: 轻量级历史/自选池附加 — 失败容错，不阻塞主流程。

    Returns:
        pdf_path: 若 AUTO_EXPORT_PDF 已触发则返回 PDF 路径（供后续 P2-3 推送使用），
                  否则 None。
    """
    from colorama import Fore, Style

    # P1-3 推荐标的自动追踪 — 记录本次 Top N, 并补全历史 T+1/T+3/T+5 收益
    try:
        updated_records = update_tracking_history(
            reports_dir=tracking_dir,
            trade_date=trade_date,
        )
        logger.info("[Auto] P1-3 追踪历史已更新: %d 条记录", updated_records)
    except Exception as exc:  # pragma: no cover - 追踪失败不影响主流程
        logger.warning("[Auto] P1-3 追踪更新失败: %s", exc)
        updated_records = 0
    tracking_summary = get_tracking_summary(
        history_path=tracking_dir / "tracking_history.json",
        lookback_days=30,
    )
    if tracking_summary.get("total_recommendations", 0) > 0:
        report_payload["tracking_summary"] = tracking_summary
        # 重新落盘 — 让 tracking_summary 出现在 JSON 中
        try:
            _save_json_report(f"auto_screening_{trade_date}.json", report_payload)
        except Exception as exc:  # pragma: no cover
            logger.debug("[Auto] tracking_summary 二次落盘失败: %s", exc)

    # P0-5: 智能自选池 — 更新 watchlist 中标的的评分和信号
    try:
        watchlist_update = update_watchlist_from_screening(report_payload)
    except Exception as exc:  # pragma: no cover - 自选池更新失败不影响主流程
        logger.warning("[Auto] P0-5 自选池更新失败: %s", exc)
        watchlist_update = {"scored_count": 0, "top_picks": []}
    if watchlist_update.get("scored_count", 0) > 0:
        report_payload["watchlist_update"] = watchlist_update
        logger.info(
            "[Auto] P0-5 Watchlist: %d 只自选标的已更新评分",
            watchlist_update["scored_count"],
        )
        try:
            _save_json_report(f"auto_screening_{trade_date}.json", report_payload)
        except Exception as exc:  # pragma: no cover
            logger.debug("[Auto] watchlist_update 二次落盘失败: %s", exc)

    # P1-7: 可选 — 自动导出 PDF 报告 (环境变量 AUTO_EXPORT_PDF=true)
    pdf_path: Path | None = None
    if os.environ.get("AUTO_EXPORT_PDF", "").strip().lower() in ("1", "true", "yes", "on"):
        try:
            from src.reporting.pdf_exporter import (
                PDFReportConfig,
                generate_screening_pdf,
            )

            pdf_dir = tracking_dir
            pdf_path = pdf_dir / f"auto_screening_{trade_date}.pdf"
            generate_screening_pdf(report_payload, pdf_path, PDFReportConfig())
            print(f"{Fore.CYAN}[Auto] P1-7 PDF 报告已生成: {pdf_path}{Style.RESET_ALL}")
            logger.info("[Auto] P1-7 PDF 报告已生成: %s", pdf_path)
        except Exception as exc:  # pragma: no cover - PDF 失败不影响主流程
            logger.warning("[Auto] P1-7 PDF 导出失败: %s", exc)
            pdf_path = None

    return pdf_path


def _handle_post_screening_tasks(
    report_payload: dict,
    trade_date: str,
    report_path: Path,
    pdf_path: Path | None,
) -> None:
    """P1-11 + P1-12 + P2-3: 筛选后处理 (归因、再平衡、推送)。所有失败容错。"""
    from colorama import Fore, Style

    # P1-11: 策略归因日报 — 若当前有持仓 (data/positions.json) 则附加归因摘要到 JSON 报告。
    try:
        from src.screening.strategy_attribution_daily import (
            compute_strategy_daily_attribution,
            render_attribution_report,
        )

        attr_positions_path = _resolve_positions_path()
        attr_positions = _load_positions_for_attribution(attr_positions_path)
        if attr_positions:
            attributions = compute_strategy_daily_attribution(
                attr_positions, today_date=trade_date
            )
            if attributions:
                attr_total_pnl = sum(a.daily_pnl for a in attributions.values())
                attr_base = sum(
                    float(p.get("prev_value", 0.0) or 0.0)
                    for p in attr_positions
                    if isinstance(p.get("prev_value"), (int, float))
                )
                report_payload["strategy_attribution_daily"] = {
                    "date": trade_date,
                    "portfolio_total_pnl": attr_total_pnl,
                    "portfolio_value_base": attr_base,
                    "positions_path": str(attr_positions_path) if attr_positions_path else None,
                    "attributions": {n: a.to_dict() for n, a in attributions.items()},
                    "report_text": render_attribution_report(
                        attributions,
                        attr_total_pnl,
                        trade_date,
                        portfolio_value_base=attr_base if attr_base > 0 else None,
                    ),
                }
                logger.info(
                    "[Auto] P1-11 策略归因日报: %d 条策略归因 (总 PnL=%.2f)",
                    len(attributions),
                    attr_total_pnl,
                )
                try:
                    _save_json_report(f"auto_screening_{trade_date}.json", report_payload)
                except Exception as exc:  # pragma: no cover
                    logger.debug("[Auto] strategy_attribution_daily 二次落盘失败: %s", exc)
    except Exception as exc:  # pragma: no cover - 归因失败不影响主流程
        logger.warning("[Auto] P1-11 策略归因日报附加失败: %s", exc)

    # P1-12: 组合再平衡建议 — 若当前有持仓则附加到 report payload (rebalance_actions 顶层字段)。
    try:
        from src.portfolio.rebalance_advisor import compute_rebalance_actions

        reb_positions, reb_pv = _load_positions_for_rebalance(_resolve_positions_path())
        if reb_positions and reb_pv > 0.0:
            reb_actions = compute_rebalance_actions(reb_positions, reb_pv)
            report_payload["rebalance_actions"] = {
                "portfolio_value": reb_pv,
                "drift_threshold": 0.05,
                "actions": [a.to_dict() for a in reb_actions],
            }
            if reb_actions:
                logger.info(
                    "[Auto] P1-12 组合再平衡: %d 条建议 (优先级1=%d)",
                    len(reb_actions),
                    sum(1 for a in reb_actions if a.priority == 1),
                )
            try:
                _save_json_report(f"auto_screening_{trade_date}.json", report_payload)
            except Exception as exc:  # pragma: no cover
                logger.debug("[Auto] rebalance_actions 二次落盘失败: %s", exc)
    except Exception as exc:  # pragma: no cover - 再平衡失败不影响主流程
        logger.warning("[Auto] P1-12 组合再平衡附加失败: %s", exc)

    # P2-3: 邮件 / Webhook 推送 — 加载 push_config.json, 对每个 enabled 通道调用 send_push。
    # 失败容错: 配置缺失 / 解析失败 / 推送异常 → 仅记录日志, 不影响 run_auto_screening 返回码。
    try:
        from src.notification.push import (
            DEFAULT_PUSH_CONFIG_PATH,
            load_push_config,
            send_push,
        )

        push_configs = load_push_config(DEFAULT_PUSH_CONFIG_PATH, only_enabled=True)
        if push_configs:
            push_pdf = pdf_path if pdf_path is not None and pdf_path.exists() else None
            push_results = []
            for cfg in push_configs:
                result = send_push(cfg, report_payload, pdf_path=push_pdf)
                push_results.append(result)
                status = "OK" if result.success else "FAIL"
                logger.info(
                    "[Auto] P2-3 推送 %s → %s (%s, attempts=%d, %.0fms)",
                    cfg.channel.value,
                    cfg.target,
                    status,
                    result.attempts,
                    result.duration_ms,
                )
            success_count = sum(1 for r in push_results if r.success)
            print(
                f"{Fore.CYAN}[Auto] P2-3 推送完成: {success_count}/{len(push_results)} 通道成功{Style.RESET_ALL}"
            )
    except Exception as exc:  # pragma: no cover - 推送失败不影响主流程
        logger.warning("[Auto] P2-3 推送异常: %s", exc)


def _print_table_block(
    report_payload: dict,
    trade_date: str,
    top_results: list,
    market_state,
    top_n: int,
    report_path: Path,
    decay_map: dict,
    industry_signals: list,
) -> None:
    """P0-1 + O-1: 输出 batch fetcher 统计 + CLI 表格。"""
    fetcher_stats = report_payload.get("batch_data_fetcher", {})
    logger.info(
        "[Auto] P0-1 BatchDataFetcher stats: batch_calls=%d, batch_failures=%d, " "single_ticker_calls=%d, cache_hits=%d",
        fetcher_stats.get("batch_calls", 0),
        fetcher_stats.get("batch_failures", 0),
        fetcher_stats.get("single_ticker_calls", 0),
        fetcher_stats.get("cache_hits", 0),
    )
    # O-1: 缓存命中率可观测性 — CLI 表格底部增加一行摘要
    _print_cache_hit_summary(fetcher_stats)

    # Print formatted table
    _print_auto_screening_table(
        trade_date,
        top_results,
        market_state,
        report_payload["layer_a_count"],
        top_n,
        report_path,
        report_payload.get("sector_concentration_warnings") or [],
        consecutive_recommendations=report_payload["recommendations"],
        decay_map=decay_map,
        industry_signals=industry_signals,
    )


def _apply_top_filters(recs: list[dict], filters: dict) -> tuple[list[dict], str]:
    """Filter recommendations from a cached report without re-running the pipeline.

    Returns:
        (filtered_recs, filter_summary_string) — summary is human-readable for CLI display.
    """
    parts: list[str] = []
    before = len(recs)

    # Industry filter (substring match on industry_sw)
    industry = filters.get("industry")
    if industry:
        recs = [r for r in recs if industry in (r.get("industry_sw", "") or "")]
        parts.append(f"行业={industry}")

    # Score range filters
    min_score = filters.get("min_score")
    if min_score is not None:
        recs = [r for r in recs if float(r.get("score_b", 0) or 0) >= float(min_score)]
        parts.append(f"score_b≥{min_score}")

    max_score = filters.get("max_score")
    if max_score is not None:
        recs = [r for r in recs if float(r.get("score_b", 0) or 0) <= float(max_score)]
        parts.append(f"score_b≤{max_score}")

    # Market cap range (元)
    min_mcap = filters.get("min_market_cap")
    if min_mcap is not None:
        threshold = float(min_mcap)
        recs = [r for r in recs if float(r.get("market_cap", 0) or 0) >= threshold]
        parts.append(f"市值≥{min_mcap}")

    max_mcap = filters.get("max_market_cap")
    if max_mcap is not None:
        threshold = float(max_mcap)
        recs = [r for r in recs if float(r.get("market_cap", 0) or 0) <= threshold]
        parts.append(f"市值≤{max_mcap}")

    # Exclude ST
    if filters.get("exclude_st"):
        recs = [r for r in recs if "ST" not in (r.get("name", "") or "").upper()]
        parts.append("排除ST")

    # Minimum consecutive recommendation days
    min_consec = filters.get("min_consecutive")
    if min_consec is not None:
        threshold = int(min_consec)
        recs = [r for r in recs if int(r.get("consecutive_days", 0) or 0) >= threshold]
        parts.append(f"连续≥{threshold}天")

    # Exact ticker match
    ticker_filter = filters.get("ticker")
    if ticker_filter:
        recs = [r for r in recs if r.get("ticker", "") == ticker_filter]
        parts.append(f"ticker={ticker_filter}")

    # Name substring match
    name_contains = filters.get("name_contains")
    if name_contains:
        recs = [r for r in recs if name_contains in (r.get("name", "") or "")]
        parts.append(f"名称含「{name_contains}」")

    after = len(recs)
    summary = f"{', '.join(parts)} → {before}→{after} 条"
    return recs, summary


def run_top(top_n: int = 10, filters: dict | None = None) -> int:
    """``--top [N] [--filter ...]`` — 显示最近一次 ``--auto`` 的 Top N 推荐，无需重跑流水线。

    从 ``data/reports/auto_screening_*.json`` 加载最新报告，重建 FusedScore 对象
    并打印格式化表格。秒级返回，适合快速查看当前推荐。

    Args:
        top_n: 显示前 N 个推荐 (默认 10)
        filters: 可选过滤参数字典，支持的键：
            - industry (str): 申万行业名 (例如 "电子", "银行")
            - min_score (float): 最低 score_b 阈值
            - max_score (float): 最高 score_b 阈值
            - min_market_cap (float): 最低市值 (元)
            - max_market_cap (float): 最高市值 (元)
            - exclude_st (bool): 排除 ST/*ST 标的
            - min_consecutive (int): 最低连续推荐天数
            - ticker (str): 精确匹配 ticker
            - name_contains (str): 名称包含子串 (中文)

    Returns:
        退出码 (0=成功, 1=无报告, 2=过滤后无结果)
    """
    from colorama import Fore, Style
    from tabulate import tabulate

    from src.screening.consecutive_recommendation import resolve_report_dir
    from src.reporting.pdf_exporter import find_latest_report, load_report

    report_dir = resolve_report_dir()
    report_path = find_latest_report(report_dir)
    if report_path is None:
        print(f"{Fore.RED}[Top] 未找到 auto_screening 报告。请先运行 --auto{Style.RESET_ALL}")
        return 1

    try:
        payload = load_report(report_path)
    except ValueError as exc:
        print(f"{Fore.RED}[Top] {exc}{Style.RESET_ALL}")
        return 1

    recs = payload.get("recommendations", [])
    if not recs:
        print(f"{Fore.YELLOW}[Top] 最新报告无推荐结果{Style.RESET_ALL}")
        return 0

    # Apply filters
    if filters:
        recs, filter_summary = _apply_top_filters(recs, filters)
        if not recs:
            print(f"{Fore.YELLOW}[Top] 过滤后无符合条件的结果。{filter_summary}{Style.RESET_ALL}")
            return 2
        print(f"{Fore.CYAN}[Top] 过滤生效: {filter_summary}{Style.RESET_ALL}")

    # Trim to top_n
    recs = recs[:top_n]
    trade_date = payload.get("date", report_path.stem.replace("auto_screening_", ""))
    market_state = payload.get("market_state", {})
    state_type = market_state.get("state_type", "mixed")
    pool_size = payload.get("layer_a_count", len(recs))

    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[Top] 最近推荐{Style.RESET_ALL}")
    print(f"  报告日期: {trade_date}  |  市场状态: {state_type}  |  候选池: {pool_size}")
    print(f"  报告路径: {Fore.CYAN}{report_path}{Style.RESET_ALL}")
    print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}\n")

    table_data = []
    for idx, rec in enumerate(recs, 1):
        score_b = float(rec.get("score_b", 0.0))
        decision = rec.get("decision", "neutral")

        if score_b >= 0.35:
            score_colored = f"{Fore.GREEN}{score_b:+.4f}{Style.RESET_ALL}"
            decision_colored = f"{Fore.GREEN}{decision}{Style.RESET_ALL}"
        elif score_b >= 0.0:
            score_colored = f"{Fore.YELLOW}{score_b:+.4f}{Style.RESET_ALL}"
            decision_colored = f"{Fore.YELLOW}{decision}{Style.RESET_ALL}"
        else:
            score_colored = f"{Fore.RED}{score_b:+.4f}{Style.RESET_ALL}"
            decision_colored = f"{Fore.RED}{decision}{Style.RESET_ALL}"

        ticker = rec.get("ticker", "—")
        name = rec.get("name", "")
        industry = rec.get("industry_sw", "—")
        ticker_label = f"{ticker} {name}" if name else ticker

        # Consecutive days / re-entry signal (P4-2)
        consecutive_days = int(rec.get("consecutive_days", 0) or 0)
        # P4-2: REENTRY_SIGNAL — 曾被推荐后消失又重返, 标记为 "↻" 提示用户
        rec_status = str(rec.get("consecutive_status", "") or "")
        is_reentry = rec_status == "reentry_signal"
        if is_reentry:
            cons_str = f"{Fore.MAGENTA}{Style.BRIGHT}↻{consecutive_days}d{Style.RESET_ALL}"
        elif consecutive_days >= 3:
            cons_str = f"{Fore.GREEN}{Style.BRIGHT}{consecutive_days}d{Style.RESET_ALL}"
        elif consecutive_days == 2:
            cons_str = f"{Fore.YELLOW}{consecutive_days}d{Style.RESET_ALL}"
        elif consecutive_days == 1:
            cons_str = f"{Fore.WHITE}{consecutive_days}d{Style.RESET_ALL}"
        else:
            cons_str = f"{Fore.RED}—{Style.RESET_ALL}"

        # Decay
        decay = rec.get("decay", {})
        decay_level = decay.get("level", "none")
        if decay_level == "none" or not decay_level:
            decay_str = f"{Fore.WHITE}—{Style.RESET_ALL}"
        else:
            decay_pct = abs(float(decay.get("change_pct", 0) or 0))
            decay_str = f"{Fore.YELLOW}↓{decay_pct:.0f}%{Style.RESET_ALL}"

        table_data.append([idx, ticker_label, industry, score_colored, decision_colored, cons_str, decay_str])

    headers = [f"{Fore.WHITE}#", "Ticker", "Industry", "Score B", "Decision", "Consec", "Decay"]
    print(tabulate(table_data, headers=headers, tablefmt="grid", colalign=("right", "left", "left", "right", "center", "center", "center")))

    # Score decomposition for top 5 (skip on validation failure — preserve backward compat with older reports)
    consecutive_lookup = {r.get("ticker", ""): r for r in recs}
    from src.screening.signal_fusion import FusedScore
    top_results: list = []
    for r in recs[:5]:
        try:
            top_results.append(FusedScore.model_validate(r))
        except Exception:
            # Older report format — skip decomposition rather than crash
            continue
    if top_results:
        _print_score_decomposition(top_results, consecutive_lookup)
        # R20.5 P1-3 扩展: 因子瀑布显示完整调整项
        _print_score_waterfall(top_results, consecutive_lookup)

    # Cache stats if available
    fetcher_stats = payload.get("batch_data_fetcher", {})
    if fetcher_stats:
        _print_cache_hit_summary(fetcher_stats)

    print(f"  完整报告: {Fore.CYAN}{report_path}{Style.RESET_ALL}\n")
    return 0


def _print_score_decomposition(
    top_results: list,
    consecutive_lookup: dict[str, dict],
) -> None:
    """O-2: 在 --auto 表格下方打印 Top N 评分构成摘要，让用户理解排序依据。

    每行显示: ticker | score_b | 各策略贡献(方向×权重×置信) | attention | stability_bonus
    """
    from colorama import Fore, Style

    if not top_results:
        return

    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'━' * 24} 评分构成 (Top {len(top_results)}) {'━' * 24}{Style.RESET_ALL}")

    for item in top_results:
        ticker = item.ticker
        score_b = item.score_b
        weights = item.weights_used or {}
        signals = item.strategy_signals or {}

        # 各策略贡献值 = weight * direction * (confidence/100) * completeness
        parts: list[str] = []
        strategy_names = ("trend", "mean_reversion", "fundamental", "event_sentiment")
        strategy_labels = ("T", "MR", "F", "E")
        for sname, slabel in zip(strategy_names, strategy_labels):
            w = weights.get(sname, 0.0)
            sig = signals.get(sname)
            if sig is None or w == 0.0:
                parts.append(f"{slabel}:—")
                continue
            contribution = w * sig.direction * (sig.confidence / 100.0) * sig.completeness
            arrow = "↑" if contribution > 0 else "↓" if contribution < 0 else "—"
            parts.append(f"{slabel}:{arrow}{abs(contribution):.3f}")

        # attention_composite (from metrics)
        attention = float((item.metrics or {}).get("attention_composite", 0.0) or 0.0)
        att_str = f"att:{attention:.2f}" if attention > 0 else "att:—"

        # stability_bonus (from consecutive_lookup)
        consecutive_info = consecutive_lookup.get(ticker, {})
        stability_bonus = float(consecutive_info.get("stability_bonus", 0.0) or 0.0)
        stab_str = f"stab:{stability_bonus:.1f}" if stability_bonus > 0 else "stab:—"

        # Consensus bonus indicator
        consensus = "★" if "consensus_bonus" in (item.arbitration_applied or []) else " "

        # Color by score
        if score_b >= 0.35:
            score_color = Fore.GREEN
        elif score_b >= 0.0:
            score_color = Fore.YELLOW
        else:
            score_color = Fore.RED

        print(
            f"  {consensus} {Fore.CYAN}{ticker:<8s}{Style.RESET_ALL} "
            f"{score_color}{score_b:+.4f}{Style.RESET_ALL}  "
            f"{' | '.join(parts)}  "
            f"{att_str}  {stab_str}"
        )

    print(f"{Fore.WHITE}{'━' * 72}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}T=趋势 MR=均值回归 F=基本面 E=事件情绪  att=注意力  stab=连续推荐加成  ★=共识加成{Style.RESET_ALL}\n")


def _print_score_waterfall(
    top_results: list,
    consecutive_lookup: dict[str, dict],
) -> None:
    """R20.5 P1-3 扩展: 因子级瀑布 (factor-level waterfall)。

    在 _print_score_decomposition 之上, 显示每个推荐的完整调整项:
      base (各策略) + attention + stability_bonus + consensus_bonus + other = score_b

    让用户精确理解"为什么 A 排在 B 前面"——不仅看 4 个策略贡献, 还能看
    市场状态调整 / 连续推荐加成 / 共识加成等所有项。
    """
    from colorama import Fore, Style

    from src.screening.signal_fusion import compute_score_decomposition

    if not top_results:
        return

    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'━' * 22} 因子瀑布 (Top {len(top_results)}) {'━' * 22}{Style.RESET_ALL}")
    strategy_labels = {"trend": "T", "mean_reversion": "MR", "fundamental": "F", "event_sentiment": "E"}

    for item in top_results:
        consecutive_info = consecutive_lookup.get(item.ticker, {})
        decomp = compute_score_decomposition(item, consecutive_info)

        print(f"  {Fore.CYAN}{item.ticker:<8s}{Style.RESET_ALL} {Fore.WHITE}{item.name}{Style.RESET_ALL}")

        # Base contributions
        for sname, contrib in decomp["base_contributions"].items():
            label = strategy_labels.get(sname, sname)
            if abs(contrib) < 1e-6:
                continue
            arrow = "+" if contrib > 0 else ""
            color = Fore.GREEN if contrib > 0 else Fore.RED
            print(f"    {Fore.WHITE}{label:<6s}{Style.RESET_ALL} {color}{arrow}{contrib:+.4f}{Style.RESET_ALL}")

        # Attention
        if abs(decomp["attention_contribution"]) > 1e-6:
            color = Fore.GREEN if decomp["attention_contribution"] > 0 else Fore.RED
            print(f"    {Fore.WHITE}att   {Style.RESET_ALL} {color}{decomp['attention_contribution']:+.4f}{Style.RESET_ALL}  (cross-sectional attention)")

        # Stability bonus
        if abs(decomp["stability_bonus"]) > 1e-6:
            consec_days = int(consecutive_info.get("consecutive_days", 0) or 0)
            print(f"    {Fore.WHITE}stab  {Style.RESET_ALL} {Fore.GREEN}+{decomp['stability_bonus']:.4f}{Style.RESET_ALL}  (consecutive={consec_days}d)")

        # Consensus bonus
        if abs(decomp["consensus_bonus"]) > 1e-6:
            label = "★bull" if decomp["consensus_bonus"] > 0 else "★bear"
            color = Fore.GREEN if decomp["consensus_bonus"] > 0 else Fore.RED
            print(f"    {Fore.WHITE}{label:<6s}{Style.RESET_ALL} {color}{decomp['consensus_bonus']:+.4f}{Style.RESET_ALL}")

        # Other adjustments (residual)
        if abs(decomp["other_adjustments"]) > 1e-6:
            color = Fore.YELLOW
            print(f"    {Fore.WHITE}other {Style.RESET_ALL} {color}{decomp['other_adjustments']:+.4f}{Style.RESET_ALL}  (market-state + residual)")

        # Total
        total = decomp["total"]
        if total >= 0.35:
            total_color = Fore.GREEN + Style.BRIGHT
        elif total >= 0.0:
            total_color = Fore.YELLOW
        else:
            total_color = Fore.RED
        print(f"    {Fore.WHITE}{'─' * 30}{Style.RESET_ALL}")
        print(f"    {Fore.WHITE}score_b{Style.RESET_ALL}  {total_color}{total:+.4f}{Style.RESET_ALL}\n")

    print(f"{Fore.WHITE}{'━' * 64}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}所有调整项相加应近似 score_b (差距 = other 残差){Style.RESET_ALL}\n")


def _print_cache_hit_summary(fetcher_stats: dict[str, int]) -> None:
    """O-1: 在 --auto 表格后打印一行缓存命中率摘要，让用户感知缓存提速效果。

    命中率 = (batch_calls 节省 + single_ticker_cache_hits) / 总请求，
    其中总请求 ≈ batch_calls + single_ticker_calls（简化模型）。
    """
    from colorama import Fore, Style

    batch_calls = int(fetcher_stats.get("batch_calls", 0))
    batch_failures = int(fetcher_stats.get("batch_failures", 0))
    single_calls = int(fetcher_stats.get("single_ticker_calls", 0))
    cache_hits = int(fetcher_stats.get("single_ticker_cache_hits", 0))
    total_requests = batch_calls + single_calls
    total_served_from_cache = cache_hits  # batch_calls 本身也是"一次请求服务全部 ticker"
    if total_requests > 0:
        effective_hit_rate = total_served_from_cache / total_requests * 100
    else:
        effective_hit_rate = 0.0
    colour = Fore.GREEN if effective_hit_rate >= 50 else Fore.YELLOW if effective_hit_rate >= 20 else Fore.RED
    print(
        f"  {colour}Cache: {effective_hit_rate:.0f}% hit "
        f"({total_served_from_cache} cached / {total_requests} requests)"
        f" | Batch: {batch_calls} calls ({batch_failures} failures)"
        f"{Style.RESET_ALL}"
    )


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
    industry_signals: list[IndustrySignal] | None = None,
) -> None:
    """打印格式化的自动筛选推荐表格。

    Args:
        consecutive_recommendations: 与 ``top_results`` 顺序对应的连续推荐元数据列表
            (每个 dict 包含 ``consecutive_days`` / ``stability_bonus`` 等字段)。
        decay_map: P0-3 信号衰减映射 ``{ticker: DecayInfo}``，用于显示 Decay 列。
        industry_signals: P1-2 行业轮动信号列表 (已按 momentum_score 降序)。
    """
    from colorama import Fore, Style
    from tabulate import tabulate

    from src.screening.signal_decay_detector import DecayLevel

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

        table_data.append(
            [
                f"{idx}",
                ticker_label,
                item.industry_sw or "—",
                score_colored,
                decision_colored,
                signal_summary,
                consecutive_str,
                decay_str,
                arbitration,
            ]
        )

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

    # O-2: 推荐排序策略透明化 — 在表格下方打印 Top 5 的评分构成摘要
    _print_score_decomposition(top_results[:5], consecutive_lookup)
    # R20.5 P1-3 扩展: 因子瀑布 — 完整调整项明细
    _print_score_waterfall(top_results[:5], consecutive_lookup)

    # Sector concentration warnings
    if sector_warnings:
        for w in sector_warnings:
            print(f"  {Fore.YELLOW}⚠️  {w}{Style.RESET_ALL}")

    # P1-2 行业轮动信号块
    if industry_signals:
        print(f"\n{Fore.WHITE}{Style.BRIGHT}{'━' * 24} 行业轮动信号 {'━' * 24}{Style.RESET_ALL}")
        print(format_rotation_block(industry_signals, top_n=5, bottom_n=3), end="")


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


def run_tracking_summary(lookback_days: int = 30) -> int:
    """P1-3 独立 CLI: 展示历史推荐胜率与平均收益。

    Args:
        lookback_days: 回溯天数 (默认 30)

    Returns:
        退出码 (0 = 成功, 1 = 历史文件不存在)
    """
    from colorama import Fore, Style

    from src.screening.consecutive_recommendation import resolve_report_dir

    report_dir = resolve_report_dir()
    if not report_dir.exists():
        print(f"{Fore.RED}未找到 reports 目录: {report_dir}{Style.RESET_ALL}")
        return 1
    history_path = report_dir / "tracking_history.json"
    if not history_path.exists():
        print(f"{Fore.YELLOW}暂无追踪历史 (请先运行 --auto 至少一次){Style.RESET_ALL}")
        return 1
    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[Tracking Summary] 推荐标的持续性追踪 (P1-3){Style.RESET_ALL}")
    print(f"  历史文件: {Fore.WHITE}{history_path}{Style.RESET_ALL}")
    print(f"  回溯天数: {lookback_days} 天")
    print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}\n")
    print(render_tracking_summary(history_path, lookback_days=lookback_days), end="")
    return 0


def run_export_pdf(trade_date: str | None = None, output_path: str | None = None) -> int:
    """P1-7 选股报告 PDF 导出入口 (CLI: ``--export-pdf``)。

    Args:
        trade_date: 指定交易日期 ``YYYYMMDD``; 缺省取最新报告。
        output_path: 自定义输出路径; 缺省写到 ``data/reports/auto_screening_<date>.pdf``。

    Returns:
        退出码 (0 = 成功, 1 = 错误)。
    """
    from colorama import Fore, Style

    from src.reporting.pdf_exporter import (
        PDFReportConfig,
        find_latest_report,
        generate_screening_pdf,
        load_report,
    )
    from src.screening.consecutive_recommendation import resolve_report_dir

    report_dir = resolve_report_dir()
    if trade_date:
        # 标准化 YYYYMMDD (8 位) — 接受含分隔符的输入
        cleaned = trade_date.replace("-", "").replace("/", "")
        if len(cleaned) != 8 or not cleaned.isdigit():
            print(f"{Fore.RED}[PDF Export] 日期格式错误: {trade_date} (期望 YYYYMMDD){Style.RESET_ALL}")
            return 1
        report_path = report_dir / f"auto_screening_{cleaned}.json"
    else:
        report_path = find_latest_report(report_dir)

    if not report_path or not report_path.exists():
        print(f"{Fore.RED}[PDF Export] 未找到报告 (trade_date={trade_date or 'latest'}), 请先运行 --auto{Style.RESET_ALL}")
        return 1

    try:
        report_data = load_report(report_path)
    except ValueError as exc:
        print(f"{Fore.RED}[PDF Export] {exc}{Style.RESET_ALL}")
        return 1

    if output_path:
        target = Path(output_path).expanduser()
    else:
        target = report_path.with_suffix(".pdf")

    try:
        result = generate_screening_pdf(report_data, target, PDFReportConfig())
    except Exception as exc:
        print(f"{Fore.RED}[PDF Export] 生成失败: {exc}{Style.RESET_ALL}")
        return 1

    print(f"{Fore.GREEN}[PDF Export] 已生成: {result} ({result.stat().st_size:,} bytes){Style.RESET_ALL}")
    return 0


def _resolve_positions_path() -> Path | None:
    """定位 ``data/positions.json`` (P1-11 归因日报使用的持仓快照)。

    解析顺序:
      1. 环境变量 ``ATTRIBUTION_POSITIONS_PATH`` (用户自定义路径)
      2. ``<repo_root>/data/positions.json``

    返回 None 表示文件不存在 — 此时归因日报会回落到「暂无持仓」提示。
    """
    env_override = os.getenv("ATTRIBUTION_POSITIONS_PATH")
    if env_override:
        candidate = Path(env_override).expanduser()
        return candidate if candidate.exists() else None
    repo_root = Path(__file__).resolve().parents[1]
    default = repo_root / "data" / "positions.json"
    return default if default.exists() else None


def _load_positions_for_attribution(positions_path: Path | None) -> list[dict]:
    """读取持仓快照, 返回 ``list[dict]``;
    任何 IO / JSON 解析错误统一返回空列表 (归因日报会优雅降级)。
    """
    if positions_path is None or not positions_path.exists():
        return []
    try:
        with open(positions_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[Attribution] 读取持仓文件失败 (%s): %s", positions_path, exc)
        return []
    # 支持两种 schema:
    #   1. 直接是 list[dict]
    #   2. {"positions": [...]} 包装
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        positions = data.get("positions")
        if isinstance(positions, list):
            return [item for item in positions if isinstance(item, dict)]
    logger.warning("[Attribution] 持仓文件格式不识别 (期望 list 或 {'positions': [...]})", )
    return []


def run_attribution_daily(trade_date: str, positions_path: Path | None = None) -> int:
    """P1-11 策略归因日报独立 CLI 入口。

    Args:
        trade_date: 交易日期 (YYYYMMDD 或 YYYY-MM-DD)。
        positions_path: 可选, 持仓 JSON 路径; 缺省时从 ``_resolve_positions_path`` 解析。

    Returns:
        退出码 (0 = 成功, 1 = 无持仓)。
    """
    from colorama import Fore, Style

    from src.screening.strategy_attribution_daily import (
        compute_strategy_daily_attribution,
        render_attribution_report,
    )

    resolved_path = positions_path or _resolve_positions_path()
    positions = _load_positions_for_attribution(resolved_path)
    if not positions:
        print(f"{Fore.YELLOW}[Attribution] 未找到可归因的持仓 — 请在 data/positions.json 或 ATTRIBUTION_POSITIONS_PATH 提供持仓快照。{Style.RESET_ALL}")
        # 仍然渲染空报告, 便于联调
        print(render_attribution_report({}, 0.0, trade_date))
        return 1

    attributions = compute_strategy_daily_attribution(positions, today_date=trade_date)
    total_pnl = sum(a.daily_pnl for a in attributions.values())
    portfolio_value_base = sum(
        float(p.get("prev_value", 0.0) or 0.0)
        for p in positions
        if isinstance(p.get("prev_value"), (int, float))
    )
    report_text = render_attribution_report(
        attributions,
        total_pnl,
        trade_date,
        portfolio_value_base=portfolio_value_base if portfolio_value_base > 0 else None,
    )

    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[Attribution Daily] 策略归因日报 (P1-11){Style.RESET_ALL}")
    if resolved_path is not None:
        print(f"  持仓来源: {Fore.WHITE}{resolved_path}{Style.RESET_ALL}")
    print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(report_text)

    # 落盘 JSON 报告 (供 Web / 其他流程消费)
    payload = {
        "mode": "attribution_daily",
        "date": trade_date,
        "portfolio_total_pnl": total_pnl,
        "portfolio_value_base": portfolio_value_base,
        "positions_path": str(resolved_path) if resolved_path else None,
        "attributions": {name: attr.to_dict() for name, attr in attributions.items()},
        "report_text": report_text,
    }
    try:
        output_path = _save_json_report(f"attribution_daily_{trade_date}.json", payload)
        print(f"{Fore.CYAN}已输出: {output_path}{Style.RESET_ALL}")
    except Exception as exc:  # pragma: no cover
        logger.debug("[Attribution] 落盘失败: %s", exc)
    return 0


def _load_positions_for_rebalance(positions_path: Path | None) -> tuple[list[dict], float]:
    """读取 ``positions.json``, 返回 ``(positions, portfolio_value)``。

    支持两种 schema:
      1. ``{"portfolio_value": N, "positions": [...]}`` (推荐, 显式总市值)
      2. ``[{"ticker": ..., "current_value": ..., ...}, ...]`` (退化, 总市值 = sum(current_value))

    任何 IO / JSON 错误返回 ``([], 0.0)``。
    """
    if positions_path is None or not positions_path.exists():
        return [], 0.0
    try:
        with open(positions_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("[Rebalance] 读取持仓文件失败 (%s): %s", positions_path, exc)
        return [], 0.0

    if isinstance(data, list):
        positions = [item for item in data if isinstance(item, dict)]
        pv = sum(float(p.get("current_value", 0.0) or 0.0) for p in positions)
        return positions, pv
    if isinstance(data, dict):
        positions = data.get("positions") or []
        if not isinstance(positions, list):
            positions = []
        positions = [item for item in positions if isinstance(item, dict)]
        pv_raw = data.get("portfolio_value")
        try:
            pv = float(pv_raw) if pv_raw is not None else 0.0
        except (TypeError, ValueError):
            pv = 0.0
        if pv <= 0.0:
            pv = sum(float(p.get("current_value", 0.0) or 0.0) for p in positions)
        return positions, pv
    return [], 0.0


def run_rebalance(positions_path: Path | None = None, drift_threshold: float = 0.05) -> int:
    """P1-12 组合再平衡建议独立 CLI 入口。

    Args:
        positions_path: 持仓 JSON 路径; 缺省时从 ``_resolve_positions_path`` 解析。
        drift_threshold: 漂移阈值, 默认 5%。

    Returns:
        退出码 (0 = 成功, 1 = 无持仓)。
    """
    from colorama import Fore, Style

    from src.portfolio.rebalance_advisor import (
        compute_rebalance_actions,
        format_rebalance_actions,
    )

    resolved_path = positions_path or _resolve_positions_path()
    positions, portfolio_value = _load_positions_for_rebalance(resolved_path)
    if not positions or portfolio_value <= 0.0:
        print(f"{Fore.YELLOW}[Rebalance] 未找到可用持仓 — 请在 data/positions.json 提供 {{portfolio_value, positions: [...]}}{Style.RESET_ALL}")
        return 1

    actions = compute_rebalance_actions(positions, portfolio_value, drift_threshold=drift_threshold)
    text = format_rebalance_actions(actions, portfolio_value, drift_threshold=drift_threshold)

    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[Rebalance] 组合再平衡建议 (P1-12){Style.RESET_ALL}")
    if resolved_path is not None:
        print(f"  持仓来源: {Fore.WHITE}{resolved_path}{Style.RESET_ALL}")
    print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(text)

    # 落盘 JSON 报告
    payload = {
        "mode": "rebalance_advice",
        "portfolio_value": portfolio_value,
        "drift_threshold": drift_threshold,
        "positions_path": str(resolved_path) if resolved_path else None,
        "actions": [a.to_dict() for a in actions],
        "report_text": text,
    }
    try:
        output_path = _save_json_report(
            f"rebalance_{datetime.now().strftime('%Y%m%d')}.json",
            payload,
        )
        print(f"{Fore.CYAN}已输出: {output_path}{Style.RESET_ALL}")
    except Exception as exc:  # pragma: no cover
        logger.debug("[Rebalance] 落盘失败: %s", exc)
    return 0


def run_push_test(
    channel: str | None = None,
    config_path: Path | str | None = None,
    *,
    init: bool = False,
) -> int:
    """P2-3 推送通道连通性测试 — CLI 入口。

    行为:
      - 不发起真实 HTTP / SMTP 请求 (供调试 / smoke test 用)。
      - 若 ``init=True`` → 写入一份默认 push_config.json 模板到 ``data/push_config.json``,
        不会覆盖已有文件 (除非 ``--force``)。
      - 否则从配置文件加载通道, 发送一个含当日日期的最小测试 payload,
        打印每个通道的 ``PushResult.to_dict()``。

    Args:
        channel: 仅测试指定通道名 (``"wecom"`` / ``"dingtalk"`` / ``"email"`` / ``"webhook"``);
            None 表示测试配置中所有 enabled 通道。
        config_path: 配置文件路径, 默认 ``data/push_config.json``。
        init: True 时生成默认配置文件模板。

    Returns:
        退出码 (0 = 至少一个通道成功, 1 = 全部失败 / 配置缺失)。
    """
    from colorama import Fore, Style

    from src.notification.push import (
        DEFAULT_PUSH_CONFIG_PATH,
        build_default_config,
        format_report_markdown,
        load_push_config,
        send_push,
    )

    resolved_path = Path(config_path) if config_path else DEFAULT_PUSH_CONFIG_PATH

    if init:
        template = build_default_config(enabled_channels=("wecom", "dingtalk", "email", "webhook"))
        if resolved_path.exists():
            print(
                f"{Fore.YELLOW}[PushTest] 配置文件已存在, 不会覆盖: {resolved_path}{Style.RESET_ALL}\n"
                f"  如需重新生成, 请先删除该文件。"
            )
            return 1
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(
            json.dumps(template, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"{Fore.GREEN}[PushTest] 已生成默认配置: {resolved_path}{Style.RESET_ALL}")
        print("  请编辑该文件, 把 channel 改成 enabled=true 并填入真实 target。")
        return 0

    configs = load_push_config(resolved_path, only_enabled=True)
    if not configs:
        print(
            f"{Fore.YELLOW}[PushTest] 未找到任何 enabled 通道 ({resolved_path}){Style.RESET_ALL}\n"
            f"  提示: 使用 --push-test --init 生成默认模板。"
        )
        return 1

    if channel:
        target = channel.strip().lower()
        configs = [c for c in configs if c.channel.value == target]
        if not configs:
            print(f"{Fore.RED}[PushTest] 配置中无 channel={target!r} 的 enabled 通道{Style.RESET_ALL}")
            return 1

    test_payload = {
        "date": datetime.now().strftime("%Y%m%d"),
        "market_state": {"state_type": "mixed", "position_scale": 0.5},
        "recommendations": [
            {
                "ticker": "300750",
                "decision": "buy",
                "score_b": 0.42,
                "strategy_signals": {
                    "trend": {"direction": 1, "confidence": 80.0},
                    "mean_reversion": {"direction": 0, "confidence": 30.0},
                    "fundamental": {"direction": 1, "confidence": 65.0},
                    "event_sentiment": {"direction": 1, "confidence": 50.0},
                },
            }
        ],
    }
    # 预先打印一次 (供 CLI 输出)
    print("\n[PushTest] 测试 payload Markdown 预览 (前 10 行):")
    preview = format_report_markdown(test_payload).splitlines()[:10]
    for line in preview:
        print(f"  {line}")
    print()

    results = []
    for cfg in configs:
        # 强制注入: 即使真实 SMTP/HTTP 也会失败 (无沙箱环境), 这里仅做连通性提示。
        # 实际发送会被 default 实现尝试, 但本 CLI 入口不连真实服务 (无沙箱) — 因此
        # 注入 raise 让失败可预测地展示。
        result = send_push(cfg, test_payload)
        results.append(result)
        marker = f"{Fore.GREEN}OK{Style.RESET_ALL}" if result.success else f"{Fore.RED}FAIL{Style.RESET_ALL}"
        print(
            f"  [{marker}] {cfg.channel.value:<14} → {cfg.target}  "
            f"(attempts={result.attempts}, {result.duration_ms:.0f}ms, "
            f"truncated={result.truncated})"
        )
        if result.error:
            print(f"    error: {result.error}")

    success_count = sum(1 for r in results if r.success)
    total = len(results)
    print(f"\n[PushTest] 完成: {success_count}/{total} 通道成功")
    return 0 if success_count == total else 1


def run_custom_weights(
    trend: float,
    mean_reversion: float,
    fundamental: float,
    event_sentiment: float,
    top_n: int = 10,
    trade_date: str | None = None,
) -> int:
    """P2-5 自定义策略权重 — CLI 入口。

    从最新 (或指定日期) auto_screening_*.json 报告加载推荐列表, 按用户指定
    的四策略权重重算每条 rec 的 score_b, 重新排序并打印 Top N。

    Args:
        trend: 趋势策略权重
        mean_reversion: 均值回归策略权重
        fundamental: 基本面策略权重
        event_sentiment: 事件情绪策略权重
        top_n: 返回 Top N (默认 10)
        trade_date: 指定报告日期 YYYYMMDD; 缺省取最新

    Returns:
        退出码 (0 = 成功, 1 = 校验失败 / 报告缺失)
    """
    from colorama import Fore, Style

    from src.screening.custom_weights import (
        StrategyWeights,
        load_latest_recommendations,
        reweight_recommendations,
    )

    # 1. 构造权重 (StrategyWeights.__post_init__ 会做 NaN/求和校验)
    try:
        weights = StrategyWeights(
            trend=trend,
            mean_reversion=mean_reversion,
            fundamental=fundamental,
            event_sentiment=event_sentiment,
        )
    except ValueError as exc:
        print(f"{Fore.RED}[CustomWeights] 权重校验失败: {exc}{Style.RESET_ALL}")
        return 1

    # 2. 加载报告
    recs = load_latest_recommendations(trade_date=trade_date)
    if not recs:
        print(
            f"{Fore.YELLOW}[CustomWeights] 未找到可用推荐报告 (trade_date={trade_date or 'latest'}), "
            f"请先运行 --auto{Style.RESET_ALL}"
        )
        return 1

    # 3. 重算
    reweighted = reweight_recommendations(recs, weights)
    top = reweighted[: max(1, top_n)]

    # 4. 渲染
    today = datetime.now().strftime("%Y-%m-%d")
    w = weights.to_dict()
    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[CustomWeights] 自定义权重推荐 · {today}{Style.RESET_ALL}")
    print(
        f"权重: 趋势 {w['trend']:.2f} / 均值回归 {w['mean_reversion']:.2f} / "
        f"基本面 {w['fundamental']:.2f} / 事件情绪 {w['event_sentiment']:.2f}"
    )
    print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    if not top:
        print(f"{Fore.YELLOW}无可用推荐{Style.RESET_ALL}")
        return 0

    print(f"Top {len(top)}:")
    for idx, rec in enumerate(top, start=1):
        ticker = str(rec.get("ticker", ""))
        name = str(rec.get("name", "") or "")
        score_b = float(rec.get("score_b", 0.0) or 0.0)
        original = float(rec.get("original_score_b", 0.0) or 0.0)
        diff = score_b - original
        diff_str = f"{diff:+.3f}"
        label = f"{ticker} {name}".strip()
        print(f"  {idx:>2}. {label:<22}  score_b {score_b:+.3f}  (原 {original:+.3f}  Δ {diff_str})")

    # 5. 落盘 JSON
    payload = {
        "mode": "custom_weights",
        "trade_date": trade_date,
        "weights": w,
        "top_n": top_n,
        "total_recommendations": len(recs),
        "top": [dict(r) for r in top],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    try:
        output_path = _save_json_report(
            f"custom_weights_{datetime.now().strftime('%Y%m%d')}.json",
            payload,
        )
        print(f"{Fore.CYAN}已输出: {output_path}{Style.RESET_ALL}")
    except Exception as exc:  # pragma: no cover
        logger.debug("[CustomWeights] 落盘失败: %s", exc)
    return 0


def run_conditional_orders(
    top_n: int = 20,
    *,
    atr_period: int = 14,
    lookback_sessions: int = 60,
) -> int:
    """P1-10 条件单建议 CLI 入口 — 包装 ``run_conditional_orders_cli`` 供 ``--conditional-orders`` 使用。

    Args:
        top_n: Top N 推荐 (1-50, 默认 20)
        atr_period: ATR 周期 (默认 14)
        lookback_sessions: 回溯窗口 (默认 60)

    Returns:
        退出码 (0 = 成功, 1 = 未找到报告, 2 = 报告中无推荐)
    """
    from src.screening.conditional_order_advisor import run_conditional_orders_cli

    return run_conditional_orders_cli(
        top_n=top_n,
        atr_period=atr_period,
        lookback_sessions=lookback_sessions,
    )


def run_industry_rotation(trade_date: str | None = None, top_n: int = 5, bottom_n: int = 3) -> int:
    """从最新 (或指定日期) auto_screening 报告中读取推荐结果, 计算并展示行业轮动信号。

    Args:
        trade_date: 指定交易日期 YYYYMMDD, 缺省取最新报告。
        top_n: 强势行业显示数量 (默认 5)。
        bottom_n: 弱势行业显示数量 (默认 3)。

    Returns:
        退出码 (0 = 成功, 1 = 错误)。
    """
    from colorama import Fore, Style

    from src.screening.consecutive_recommendation import resolve_report_dir

    report_dir = resolve_report_dir()
    if not report_dir.exists():
        print(f"{Fore.RED}未找到 reports 目录: {report_dir}{Style.RESET_ALL}")
        return 1

    if trade_date:
        # 标准化为 YYYYMMDD
        candidate_dates = [trade_date.replace("-", "")]
    else:
        report_files = sorted(report_dir.glob("auto_screening_*.json"), reverse=True)
        if not report_files:
            print(f"{Fore.RED}没有 auto_screening_*.json 报告, 请先运行 --auto{Style.RESET_ALL}")
            return 1
        candidate_dates = []
        for f in report_files[:5]:  # 最多看最近 5 个文件
            stem = f.stem  # e.g., auto_screening_20260607
            date_part = stem.replace("auto_screening_", "")
            if len(date_part) == 8 and date_part.isdigit():
                candidate_dates.append(date_part)

    # 选最近一个含 industry_rotation 字段的; 否则退回到含 recommendations 的
    chosen_payload: dict | None = None
    chosen_date: str = ""
    for date_str in candidate_dates:
        path = report_dir / f"auto_screening_{date_str}.json"
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as exc:  # pragma: no cover
            print(f"{Fore.YELLOW}读取 {path.name} 失败: {exc}{Style.RESET_ALL}")
            continue
        recs = payload.get("recommendations", [])
        if not recs:
            continue
        chosen_payload = payload
        chosen_date = date_str
        break

    if not chosen_payload:
        print(f"{Fore.RED}在候选报告中未找到 recommendations 字段{Style.RESET_ALL}")
        return 1

    # 优先使用 report 内嵌的 industry_rotation (避免重复计算)
    cached_rotation = chosen_payload.get("industry_rotation")
    if cached_rotation and isinstance(cached_rotation, list) and len(cached_rotation) > 0:
        # 反序列化为 IndustrySignal
        signals = [
            IndustrySignal(
                industry_name=item.get("industry_name", ""),
                industry_code=item.get("industry_code", ""),
                momentum_score=_safe_float(item.get("momentum_score", 0.0), 0.0),
                avg_score_b=_safe_float(item.get("avg_score_b", 0.0), 0.0),
                candidate_count=_safe_int(item.get("candidate_count", 0), 0),
                north_money_flow=_safe_float(item.get("north_money_flow", 0.0), 0.0),
                rank=_safe_int(item.get("rank", 0), 0),
                tickers=list(item.get("tickers", []) or []),
            )
            for item in cached_rotation
        ]
    else:
        recs = chosen_payload.get("recommendations", [])
        signals = calculate_industry_rotation(recs, chosen_date)

    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[Industry Rotation] 行业轮动信号{Style.RESET_ALL}")
    print(f"  报告日期: {chosen_date}  |  推荐数: {len(chosen_payload.get('recommendations', []))}")
    print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}\n")

    if not signals:
        print(f"{Fore.YELLOW}  无有效行业信号 (候选数不足, 或全部行业候选数 < 2){Style.RESET_ALL}\n")
        return 0

    print(format_rotation_block(signals, top_n=top_n, bottom_n=bottom_n), end="")
    return 0


# ---------------------------------------------------------------------------
# P0-5: Watchlist CLI handlers
# ---------------------------------------------------------------------------


def run_watchlist_add(ticker: str, name: str, tags: list[str] | None = None, note: str = "") -> int:
    """添加标的到自选池 (P0-5)。"""
    from colorama import Fore, Style

    from src.screening.watchlist import Watchlist

    wl = Watchlist()
    try:
        entry = wl.add(ticker=ticker, name=name, tags=tags, note=note)
    except ValueError as exc:
        print(f"{Fore.RED}[Watchlist] 添加失败: {exc}{Style.RESET_ALL}")
        return 1
    print(f"{Fore.GREEN}[Watchlist] 已添加 {entry.ticker} {entry.name}{Style.RESET_ALL}")
    if entry.tags:
        print(f"  标签: {', '.join(entry.tags)}")
    if entry.note:
        print(f"  备注: {entry.note}")
    print(f"  共 {len(wl)} 只自选标的 | 文件: {wl.path}")
    return 0


def run_watchlist_remove(ticker: str) -> int:
    """从自选池移除标的 (P0-5)。"""
    from colorama import Fore, Style

    from src.screening.watchlist import Watchlist

    wl = Watchlist()
    ok = wl.remove(ticker)
    if ok:
        print(f"{Fore.GREEN}[Watchlist] 已移除 {ticker}{Style.RESET_ALL}")
        print(f"  共 {len(wl)} 只自选标的")
        return 0
    print(f"{Fore.YELLOW}[Watchlist] {ticker} 不在自选池中{Style.RESET_ALL}")
    return 1


def run_watchlist_list(tag: str | None = None) -> int:
    """列出自选池所有标的 (P0-5)。"""
    from colorama import Fore, Style
    from tabulate import tabulate

    from src.screening.watchlist import Watchlist

    wl = Watchlist()
    entries = wl.list(tag=tag)
    print(f"\n{Fore.WHITE}{Style.BRIGHT}━━━ 智能自选池 ━━━{Style.RESET_ALL}")
    print(f"共 {len(entries)} 只关注标的" + (f" (标签: {tag})" if tag else ""))
    print(f"文件: {Fore.CYAN}{wl.path}{Style.RESET_ALL}\n")

    if not entries:
        print(f"{Fore.YELLOW}  自选池为空。使用 --watchlist-add 添加标的{Style.RESET_ALL}\n")
        return 0

    rows = []
    for entry in entries:
        tags_str = ", ".join(entry.tags) if entry.tags else "—"
        history_len = len(entry.score_history)
        latest = entry.score_history[-1] if entry.score_history else None
        latest_str = f"{latest.get('score', 0):+.2f} {latest.get('signal', '')}" if latest else "—"
        rows.append([entry.ticker, entry.name or "—", entry.added_at, tags_str, entry.note or "—", latest_str, history_len])

    headers = ["Ticker", "名称", "加入日期", "标签", "备注", "最新评分", "历史天数"]
    print(tabulate(rows, headers=headers, tablefmt="grid"))
    print()
    return 0


def run_watchlist_status() -> int:
    """展示自选池最新评分 + 信号 + 连续推荐 (P0-5)。"""
    from colorama import Fore, Style

    from src.screening.consecutive_recommendation import (
        DEFAULT_LOOKBACK_DAYS,
        compute_consecutive_recommendations,
        resolve_report_dir,
    )
    from src.screening.watchlist import Watchlist, format_watchlist_status

    wl = Watchlist()
    if len(wl) == 0:
        print(f"\n{Fore.YELLOW}自选池为空。使用 --watchlist-add 添加标的{Style.RESET_ALL}\n")
        return 0

    # 计算连续推荐 (若有历史报告)
    consecutive_lookup: dict[str, dict] = {}
    try:
        report_dir = resolve_report_dir()
        if report_dir.exists():
            stats_map = compute_consecutive_recommendations(
                lookback_days=DEFAULT_LOOKBACK_DAYS,
                report_dir=report_dir,
            )
            for ticker, stats in stats_map.items():
                consecutive_lookup[ticker] = {
                    "consecutive_days": stats.consecutive_days,
                    "status": stats.status.value,
                }
    except Exception as exc:  # pragma: no cover - 容错: 历史读取失败仍展示自选池
        logger.debug("[Watchlist] 连续推荐查询失败: %s", exc)

    output = format_watchlist_status(wl, consecutive_lookup=consecutive_lookup)
    print("\n" + output)
    return 0


def update_watchlist_from_screening(
    report_payload: dict,
    watchlist_path: Path | None = None,
) -> dict:
    """从 auto_screening 报告中提取与自选池相关的标的, 更新评分, 返回汇总。

    集成点 (P0-5 step 3):
      1. 加载自选池
      2. 对 ``report_payload['recommendations']`` 中属于自选池的标的写入 score_history
      3. 返回 ``{scored_count, top_picks}``

    Args:
        report_payload: ``compute_auto_screening_results`` 返回的 dict
        watchlist_path: 自定义 watchlist 路径 (供测试用); None 使用默认。

    Returns:
        ``{"scored_count": N, "top_picks": [...]}``
    """
    from src.screening.watchlist import Watchlist

    wl = Watchlist(watchlist_path) if watchlist_path else Watchlist()
    if len(wl) == 0:
        return {"scored_count": 0, "top_picks": []}

    trade_date_raw = str(report_payload.get("date", "")).strip()
    # 将 YYYYMMDD 规范化为 YYYY-MM-DD 便于人类阅读 / 与 added_at 风格一致
    if len(trade_date_raw) == 8 and trade_date_raw.isdigit():
        date_iso = f"{trade_date_raw[:4]}-{trade_date_raw[4:6]}-{trade_date_raw[6:]}"
    else:
        date_iso = trade_date_raw or datetime.now().strftime("%Y-%m-%d")

    recommendations = report_payload.get("recommendations", []) or []
    rec_lookup: dict[str, dict] = {}
    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        ticker = str(rec.get("ticker", "")).strip()
        if ticker:
            rec_lookup[ticker] = rec

    scored_count = 0
    top_picks: list[dict] = []
    for ticker in wl.all_tickers():
        rec = rec_lookup.get(ticker)
        if rec is None:
            continue
        score = _safe_float(rec.get("score_b"), 0.0)
        signal = str(rec.get("decision", "neutral"))
        wl.update_score(ticker, score=score, signal=signal, date=date_iso)
        scored_count += 1
        entry = wl.get(ticker)
        top_picks.append(
            {
                "ticker": ticker,
                "name": entry.name if entry else "",
                "score_b": score,
                "decision": signal,
                "consecutive_days": int(rec.get("consecutive_days", 0) or 0),
            }
        )

    # 按 score 降序排列后取 Top 5
    top_picks.sort(key=lambda item: item.get("score_b", 0.0), reverse=True)
    return {"scored_count": scored_count, "top_picks": top_picks[:5]}


def run_winrate_dashboard(lookback_days: int = 30) -> int:
    """P2-4 历史推荐胜率看板 — CLI 入口。

    Args:
        lookback_days: 回溯天数 (默认 30)

    Returns:
        退出码 (0 = 成功, 1 = 无数据)
    """
    from colorama import Fore, Style

    from src.screening.consecutive_recommendation import resolve_report_dir
    from src.screening.winrate_dashboard import (
        compute_winrate_dashboard,
        render_winrate_dashboard,
    )

    report_dir = resolve_report_dir()
    history_path = report_dir / "tracking_history.json"

    if not history_path.exists():
        print(f"{Fore.YELLOW}暂无追踪历史 (请先运行 --auto 至少一次): {history_path}{Style.RESET_ALL}")
        return 1

    summary = compute_winrate_dashboard(history_path, lookback_days=lookback_days)

    if summary.total_days == 0:
        print(f"{Fore.YELLOW}近 {lookback_days} 天内无推荐记录: {history_path}{Style.RESET_ALL}")
        return 1

    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[WinRate Dashboard] 历史推荐胜率看板 (P2-4){Style.RESET_ALL}")
    print(f"  历史文件: {Fore.WHITE}{history_path}{Style.RESET_ALL}")
    print(f"  回溯天数: {lookback_days} 天")
    print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}\n")
    print(render_winrate_dashboard(summary), end="")
    return 0


def run_verify_recommendations(lookback_days: int = 30, include_detail: bool = False) -> int:
    """P3-1 推荐闭环验证 — CLI 入口。

    Args:
        lookback_days: 回溯天数 (默认 30)
        include_detail: 是否输出日度明细

    Returns:
        退出码 (0 = 成功, 1 = 无数据)
    """
    from colorama import Fore, Style

    from src.screening.consecutive_recommendation import resolve_report_dir
    from src.screening.verify_recommendations import (
        compute_verify_recommendations,
        render_verify_recommendations,
    )

    report_dir = resolve_report_dir()

    summary = compute_verify_recommendations(
        reports_dir=report_dir,
        lookback_days=lookback_days,
        include_detail=include_detail,
    )

    if summary.total_days == 0:
        print(f"{Fore.YELLOW}近 {lookback_days} 天内无推荐数据 — 请先运行 --auto{Style.RESET_ALL}")
        return 1

    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[Verify] 推荐闭环验证 (P3-1){Style.RESET_ALL}")
    print(f"  报告目录: {Fore.WHITE}{report_dir}{Style.RESET_ALL}")
    print(f"  回溯天数: {lookback_days} 天")
    print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}\n")
    print(render_verify_recommendations(summary), end="")
    return 0


def run_industry_cross_picks(trade_date: str | None = None, top_industries: int = 5, picks_per_industry: int = 3) -> int:
    """P3-3 行业 + 个股交叉选择 — CLI 入口。

    Args:
        trade_date: 报告日期 YYYYMMDD (None=最新)
        top_industries: 输出前 N 个强势行业
        picks_per_industry: 每个行业输出 Top N 个股

    Returns:
        退出码 (0=成功, 1=错误)
    """
    from colorama import Fore, Style
    import json

    from src.screening.consecutive_recommendation import resolve_report_dir
    from src.screening.industry_cross_picks import (
        compute_cross_picks,
        render_cross_picks,
    )

    report_dir = resolve_report_dir()
    if not report_dir.exists():
        print(f"{Fore.RED}未找到 reports 目录: {report_dir}{Style.RESET_ALL}")
        return 1

    # 加载最新或指定日期的报告
    if trade_date:
        date_str = trade_date.replace("-", "")
        report_path = report_dir / f"auto_screening_{date_str}.json"
    else:
        report_files = sorted(report_dir.glob("auto_screening_*.json"), reverse=True)
        if not report_files:
            print(f"{Fore.RED}没有 auto_screening_*.json 报告, 请先运行 --auto{Style.RESET_ALL}")
            return 1
        report_path = report_files[0]
        date_str = report_path.stem.replace("auto_screening_", "")

    if not report_path.exists():
        print(f"{Fore.RED}未找到报告: {report_path}{Style.RESET_ALL}")
        return 1

    try:
        with open(report_path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        print(f"{Fore.YELLOW}读取 {report_path.name} 失败: {exc}{Style.RESET_ALL}")
        return 1

    recommendations = payload.get("recommendations", [])
    if not recommendations:
        print(f"{Fore.YELLOW}报告 {date_str} 无推荐数据{Style.RESET_ALL}")
        return 0

    cross_picks = compute_cross_picks(
        recommendations,
        trade_date=date_str,
        top_industries=top_industries,
        picks_per_industry=picks_per_industry,
    )

    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[Cross Picks] 行业+个股交叉选择 (P3-3){Style.RESET_ALL}")
    print(f"  报告日期: {date_str}  |  推荐数: {len(recommendations)}")
    print(f"  行业数: {len(cross_picks)}  |  每行业 Top: {picks_per_industry}")
    print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}\n")
    print(render_cross_picks(cross_picks), end="")
    return 0


def run_portfolio_builder(trade_date: str | None = None, top_n: int = 10, position_cap: float = 0.20, industry_cap: float = 0.30) -> int:
    """P3-4 推荐组合构建器 — CLI 入口。

    Args:
        trade_date: 报告日期 YYYYMMDD (None=最新)
        top_n: 选 top N 个股进入组合
        position_cap: 单股权重上限
        industry_cap: 行业集中度上限

    Returns:
        退出码 (0=成功, 1=错误)
    """
    from colorama import Fore, Style
    import json

    from src.screening.consecutive_recommendation import resolve_report_dir
    from src.portfolio.builder import (
        compute_portfolio,
        render_portfolio,
    )

    report_dir = resolve_report_dir()
    if not report_dir.exists():
        print(f"{Fore.RED}未找到 reports 目录: {report_dir}{Style.RESET_ALL}")
        return 1

    if trade_date:
        date_str = trade_date.replace("-", "")
        report_path = report_dir / f"auto_screening_{date_str}.json"
    else:
        report_files = sorted(report_dir.glob("auto_screening_*.json"), reverse=True)
        if not report_files:
            print(f"{Fore.RED}没有 auto_screening_*.json 报告, 请先运行 --auto{Style.RESET_ALL}")
            return 1
        report_path = report_files[0]
        date_str = report_path.stem.replace("auto_screening_", "")

    if not report_path.exists():
        print(f"{Fore.RED}未找到报告: {report_path}{Style.RESET_ALL}")
        return 1

    try:
        with open(report_path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        print(f"{Fore.YELLOW}读取 {report_path.name} 失败: {exc}{Style.RESET_ALL}")
        return 1

    recommendations = payload.get("recommendations", [])
    if not recommendations:
        print(f"{Fore.YELLOW}报告 {date_str} 无推荐数据{Style.RESET_ALL}")
        return 0

    summary = compute_portfolio(
        recommendations,
        top_n=top_n,
        position_cap=position_cap,
        industry_cap=industry_cap,
    )

    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[Portfolio] 推荐组合构建器 (P3-4){Style.RESET_ALL}")
    print(f"  报告日期: {date_str}  |  Top N: {top_n}")
    print(f"  约束: 单股 ≤ {position_cap:.0%}  |  行业 ≤ {industry_cap:.0%}")
    print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}\n")
    print(render_portfolio(summary), end="")
    return 0


def run_weight_calibration(lookback_days: int = 30) -> int:
    """P3-2 策略动态权重校准 — CLI 入口。

    Args:
        lookback_days: 回溯天数 (默认 30, 实际观测期 = 报告数)

    Returns:
        退出码 (0=成功, 1=无数据)
    """
    from colorama import Fore, Style
    import json

    from src.screening.consecutive_recommendation import resolve_report_dir
    from src.research.weight_calibration import (
        compute_weight_calibration,
        render_weight_calibration,
    )
    from src.research.factor_ic_analysis import extract_factor_panel_from_history

    report_dir = resolve_report_dir()
    if not report_dir.exists():
        print(f"{Fore.RED}未找到 reports 目录: {report_dir}{Style.RESET_ALL}")
        return 1

    # 尝试从历史报告中提取因子面板
    try:
        from datetime import datetime
        end_date = datetime.now().strftime("%Y%m%d")
        factor_panel, return_history = extract_factor_panel_from_history(
            reports_dir=report_dir,
            lookback_days=lookback_days,
            end_date=end_date,
        )
    except Exception as exc:
        print(f"{Fore.YELLOW}无法提取因子面板: {exc}{Style.RESET_ALL}")
        return 1

    if not factor_panel:
        print(f"{Fore.YELLOW}近 {lookback_days} 天内无因子数据 — 需要 ≥3 期的 auto_screening 报告{Style.RESET_ALL}")
        return 1

    result = compute_weight_calibration(
        factor_history=factor_panel,
        return_history=return_history,
        lookback_days=lookback_days,
    )

    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[Weight Calibration] 策略权重校准 (P3-2){Style.RESET_ALL}")
    print(f"  报告目录: {Fore.WHITE}{report_dir}{Style.RESET_ALL}")
    print(f"  回溯天数: {lookback_days} 天")
    print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}\n")
    print(render_weight_calibration(result), end="")
    return 0


def run_performance_report_cli(period: str = "weekly", end_date: str | None = None) -> int:
    """P2-8 组合绩效周报/月报独立 CLI 入口。

    从 data/positions.json 读取持仓, 从 data/reports/ 读取追踪历史,
    生成指定周期的绩效报告并打印。

    Args:
        period: "weekly" / "monthly"
        end_date: 结束日期 YYYYMMDD; None = 今天

    Returns:
        退出码 (0 = 成功, 1 = 无数据)
    """
    from colorama import Fore, Style

    from src.portfolio.performance_report import (
        generate_performance_report,
        render_performance_report,
    )
    from src.screening.consecutive_recommendation import resolve_report_dir

    # 1. 加载持仓历史 — 从 data/positions.json 读取当前持仓作为单一快照
    positions_path = _resolve_positions_path()
    positions = _load_positions_for_attribution(positions_path)
    portfolio_value = 0.0
    if positions:
        portfolio_value = sum(float(p.get("current_value", 0.0) or 0.0) for p in positions if isinstance(p.get("current_value"), (int, float)))
    positions_history: list[dict] = []
    if positions and portfolio_value > 0:
        today_str = (end_date or datetime.now().strftime("%Y%m%d")).replace("-", "")
        positions_history.append({"date": today_str, "portfolio_value": portfolio_value, "positions": positions})

    # 2. 加载追踪历史 (P1-3)
    report_dir = resolve_report_dir()
    tracking_history: list[dict] = []
    tracking_path = report_dir / "tracking_history.json"
    if tracking_path.exists():
        try:
            with open(tracking_path, encoding="utf-8") as f:
                payload = json.load(f)
            records = payload.get("records") if isinstance(payload, dict) else payload
            if isinstance(records, list):
                tracking_history = records
        except (OSError, json.JSONDecodeError):
            pass

    # 3. 从追踪历史中构建交易记录 (每条有 next_day_return 的视为一笔已结算交易)
    trades: list[dict] = []
    for rec in tracking_history:
        t1 = rec.get("next_day_return")
        if t1 is not None:
            trades.append({
                "date": rec.get("recommended_date", ""),
                "ticker": rec.get("ticker", ""),
                "name": rec.get("name", ""),
                "pnl": _safe_float(t1) / 100.0 if _safe_float(t1) != 0 else 0.0,
                "return_pct": _safe_float(t1) / 100.0,
                "strategy": "unknown",
            })

    # 4. 生成报告
    report = generate_performance_report(
        positions_history=positions_history,
        trades=trades,
        recommendations=[],
        tracking_history=tracking_history,
        period=period,
        end_date=end_date,
        benchmark_return=0.0,
    )

    # 5. 打印
    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[Performance Report] 组合绩效周报/月报 (P2-8){Style.RESET_ALL}")
    print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(render_performance_report(report))

    # 6. 落盘 JSON
    payload = report.to_dict()
    try:
        output_path = _save_json_report(
            f"performance_{period}_{report.end_date}.json",
            payload,
        )
        print(f"{Fore.CYAN}已输出: {output_path}{Style.RESET_ALL}")
    except Exception as exc:  # pragma: no cover
        logger.debug("[PerformanceReport] 落盘失败: %s", exc)
    return 0


def run_explain(ticker: str) -> int:
    """Explain why a ticker was recommended by reading the latest auto-screening report.

    Loads the most recent auto_screening_*.json from data/reports/, finds the ticker,
    and prints a 10-line readable breakdown of each strategy's contribution.
    """
    import json as _json

    from colorama import Fore, Style

    # Find the most recent auto_screening report
    reports_dir = Path("data/reports")
    if not reports_dir.exists():
        print(f"{Fore.RED}未找到 reports 目录: {reports_dir}{Style.RESET_ALL}")
        return 1

    report_files = sorted(reports_dir.glob("auto_screening_*.json"), reverse=True)
    if not report_files:
        print(f"{Fore.RED}没有 auto_screening_*.json 报告, 请先运行 --auto{Style.RESET_ALL}")
        return 1

    latest = report_files[0]
    try:
        with open(latest, encoding="utf-8") as f:
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
        print(f"{Fore.CYAN}市场状态:{Style.RESET_ALL} {ms.get('state_type', '?')}  |  " f"仓位系数: {ms.get('position_scale', 1.0):.2f}  |  " f"regime: {ms.get('regime_gate_level', 'normal')}")

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

if __name__ == "__main__":
    # 早期分发: 集中处理 --preheat / --macro / --market-status / --pipeline /
    # --industry-rotation / --tracking-summary / --export-pdf / --attribution-daily
    # / --factor-ic / --rebalance / --conditional-orders / --push-test
    # / --winrate-dashboard / --stock-detail / --custom-weights / --compare
    # / --watchlist-* / --performance-report / --daily-gainers 等独立命令。
    # 这些命令在 ``parse_cli_inputs`` 之前执行, 避免与 argparse 的 required 校验冲突。
    # 详见 ``src/cli/dispatcher.py`` (Round 18 提取自此处的 340 行重复 ``if`` 模式)。
    from src.cli.dispatcher import dispatch

    _early_rc = dispatch()
    if _early_rc is not None:
        raise SystemExit(_early_rc)

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

    # --why-not mode (P0-8): 反事实解释, 为什么某只票**不在** Top 推荐中
    if inputs.why_not:
        from src.cli.why_not import run_why_not as _run_why_not

        raise SystemExit(_run_why_not(inputs.why_not))

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
