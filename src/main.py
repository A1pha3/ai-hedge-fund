import argparse
import json
import math
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
    bottom_weak_industries,
    calculate_industry_rotation,
    format_rotation_block,
    top_strong_industries,
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


def _is_finite_number(value: object) -> bool:
    """检查 value 是否为有限数 (非 NaN / Inf / None)。"""
    if value is None:
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _adx_level(value: float) -> tuple[str, str]:
    """ADX -> 强度等级 + 颜色码（colorama 颜色常量字符串）。

    Thresholds (matches market_state_helpers regime logic):
        >= 25 : 偏强 (green)
        >= 20 : 正常 (yellow)
        >= 15 : 偏弱 (yellow)
        else  : 弱势 (red)
        NaN   : 无数据 (white)
    """
    from colorama import Fore

    if not _is_finite_number(value):
        return ("无数据", Fore.WHITE)
    if value >= 25:
        return ("偏强", Fore.GREEN)
    if value >= 20:
        return ("正常", Fore.YELLOW)
    if value >= 15:
        return ("偏弱", Fore.YELLOW)
    return ("弱势", Fore.RED)


def _atr_level(value: float) -> tuple[str, str]:
    """ATR 比率 -> 波动等级 + 颜色码。

    Thresholds:
        >= 3.0% : 高波动 (red)
        >= 1.8% : 偏大   (yellow)
        >= 1.0% : 正常   (green)
        else    : 低波   (cyan)
        NaN     : 无数据 (white)
    """
    from colorama import Fore

    if not _is_finite_number(value):
        return ("无数据", Fore.WHITE)
    if value >= 0.030:
        return ("高波动", Fore.RED)
    if value >= 0.018:
        return ("偏大", Fore.YELLOW)
    if value >= 0.010:
        return ("正常", Fore.GREEN)
    return ("低波", Fore.CYAN)


def _breadth_level(value: float) -> tuple[str, str]:
    """市场宽度 (0-1 涨跌比) -> 等级 + 颜色码。

    Thresholds:
        >= 0.60 : 强势 (green)
        >= 0.50 : 均衡 (yellow)
        >= 0.40 : 偏弱 (yellow)
        else    : 弱势 (red)
        NaN     : 无数据 (white)
    """
    from colorama import Fore

    if not _is_finite_number(value):
        return ("无数据", Fore.WHITE)
    if value >= 0.60:
        return ("强势", Fore.GREEN)
    if value >= 0.50:
        return ("均衡", Fore.YELLOW)
    if value >= 0.40:
        return ("偏弱", Fore.YELLOW)
    return ("弱势", Fore.RED)


def _northbound_label(days: int) -> tuple[str, str]:
    """北向资金连续天数 -> 文本 + 颜色码。"""
    from colorama import Fore

    if days > 0:
        return (f"+{days}日 净流入", Fore.GREEN)
    if days < 0:
        return (f"{days}日 净流出", Fore.RED)
    return ("无连续方向", Fore.YELLOW)


def _regime_gate_color(level: str) -> str:
    """Regime Gate 级别 -> 颜色码。"""
    from colorama import Fore

    return {
        "normal": Fore.GREEN,
        "risk_off": Fore.YELLOW,
        "crisis": Fore.RED,
    }.get(str(level or "").lower(), Fore.WHITE)


def _state_type_cn(state_type: str) -> str:
    """state_type 英文枚举 -> 中文标签。"""
    return {
        "trend": "趋势型",
        "range": "震荡型",
        "mixed": "混合型",
        "crisis": "危机型",
    }.get(str(state_type or "").lower(), str(state_type or "—"))


def _safe_float(value: object, default: float) -> float:
    """将 value 安全转为 float, 处理 None / NaN / Inf / 异常类型。

    不能使用 ``float(value or default)`` — 当 value 是 NaN 时,
    ``NaN or default`` 仍为 NaN (NaN 是 truthy), 会污染下游。
    """
    if value is None:
        return default
    try:
        fv = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(fv) or math.isinf(fv):
        return default
    return fv


def _safe_int(value: object, default: int) -> int:
    """将 value 安全转为 int, 处理 None / NaN / 异常类型。"""
    if value is None:
        return default
    try:
        fv = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(fv) or math.isinf(fv):
        return default
    try:
        return int(fv)
    except (TypeError, ValueError):
        return default


def _extract_market_status(market_state: object) -> dict:
    """从 MarketState 对象提取温度计所需的字段，含 NaN/None 兜底。

    所有数值字段均经过 ``_safe_float`` / ``_safe_int`` 处理, 杜绝 NaN 污染。
    """
    return {
        "adx": _safe_float(getattr(market_state, "adx", 0.0), 0.0),
        "atr_ratio": _safe_float(getattr(market_state, "atr_price_ratio", 0.0), 0.0),
        "breadth_ratio": _safe_float(getattr(market_state, "breadth_ratio", 0.5), 0.5),
        "daily_return": _safe_float(getattr(market_state, "daily_return", 0.0), 0.0),
        "limit_up": _safe_int(getattr(market_state, "limit_up_count", 0), 0),
        "limit_down": _safe_int(getattr(market_state, "limit_down_count", 0), 0),
        "northbound_days": _safe_int(getattr(market_state, "northbound_flow_days", 0), 0),
        "state_type": str(getattr(market_state, "state_type", None) or "mixed"),
        "position_scale": _safe_float(getattr(market_state, "position_scale", 1.0), 1.0),
        "regime_gate_level": str(getattr(market_state, "regime_gate_level", None) or "normal"),
    }


def _format_market_status_table(data: dict) -> str:
    """根据提取的字段生成温度计文本 (彩色 ANSI 序列)。"""
    from colorama import Fore, Style

    adx = data["adx"]
    atr = data["atr_ratio"]
    breadth = data["breadth_ratio"]
    daily_return = data["daily_return"]
    limit_up = data["limit_up"]
    limit_down = data["limit_down"]
    north_days = data["northbound_days"]
    state_type = data["state_type"]
    position_scale = data["position_scale"]
    regime_gate = data["regime_gate_level"]

    has_index_data = _is_finite_number(adx) and adx > 0
    has_price_data = _is_finite_number(atr) and atr > 0

    adx_label, adx_color = _adx_level(adx)
    atr_label, atr_color = _atr_level(atr)
    breadth_label, breadth_color = _breadth_level(breadth)

    if not has_index_data:
        northbound_segment = f"{Fore.WHITE}数据暂不可用{Style.RESET_ALL}"
    else:
        nb_text, nb_color = _northbound_label(north_days)
        northbound_segment = nb_color + nb_text + Style.RESET_ALL

    regime_color = _regime_gate_color(regime_gate)
    state_type_cn = _state_type_cn(state_type)

    if _is_finite_number(breadth) and 0.0 <= breadth <= 1.0:
        total_est = 5000
        advancers = int(round(breadth * total_est))
        decliners = total_est - advancers
        breadth_detail = f"  ↓{decliners}/↑{advancers}"
    else:
        breadth_detail = ""

    def _bar(value: float, full_scale: float, width: int = 10) -> str:
        if not _is_finite_number(value) or value <= 0:
            return "░" * width
        ratio = max(0.0, min(1.0, value / full_scale))
        filled = int(round(ratio * width))
        return "█" * filled + "░" * (width - filled)

    adx_bar = _bar(adx, 50.0)
    atr_bar = _bar(atr, 0.030)

    border = "═" * 54
    lines: list[str] = []
    lines.append(Fore.CYAN + Style.BRIGHT + f"╔{border}╗" + Style.RESET_ALL)
    lines.append(Fore.CYAN + Style.BRIGHT + f"║{'市场温度计 · ' + str(data.get('date', '')):^54}║" + Style.RESET_ALL)
    lines.append(Fore.CYAN + Style.BRIGHT + f"╠{border}╣" + Style.RESET_ALL)
    lines.append(Fore.CYAN + "║" + " " * 54 + "║" + Style.RESET_ALL)

    if has_index_data:
        adx_value_str = f"{adx:.1f}"
    else:
        adx_value_str = "数据暂不可用"
    lines.append(Fore.CYAN + "║  " + Style.RESET_ALL + f"趋势强度 (ADX)    {adx_bar}  {adx_value_str:>10}  " + adx_color + adx_label + Style.RESET_ALL)

    if has_price_data:
        atr_value_str = f"{atr * 100:.2f}%"
    else:
        atr_value_str = "数据暂不可用"
    lines.append(Fore.CYAN + "║  " + Style.RESET_ALL + f"波动率 (ATR)      {atr_bar}  {atr_value_str:>10}  " + atr_color + atr_label + Style.RESET_ALL)

    breadth_value_str = f"{breadth:.2f}{breadth_detail}" if _is_finite_number(breadth) else "数据暂不可用"
    lines.append(Fore.CYAN + "║  " + Style.RESET_ALL + f"市场宽度 (涨跌比)  {breadth_value_str:<20}  " + breadth_color + breadth_label + Style.RESET_ALL)

    lines.append(Fore.CYAN + "║  " + Style.RESET_ALL + f"北向资金          {northbound_segment}")

    limit_str = f"涨停{Fore.GREEN}{limit_up}{Style.RESET_ALL} / 跌停{Fore.RED}{limit_down}{Style.RESET_ALL}"
    lines.append(Fore.CYAN + "║  " + Style.RESET_ALL + f"涨跌停            {limit_str:<40}  ")

    lines.append(Fore.CYAN + "║" + " " * 54 + "║" + Style.RESET_ALL)

    summary_line = f"综合状态: {state_type_cn}  |  仓位系数: {position_scale:.2f}"
    lines.append(Fore.CYAN + "║  " + Style.RESET_ALL + Fore.WHITE + Style.BRIGHT + summary_line + Style.RESET_ALL)

    regime_line = f"Regime Gate: {regime_gate}"
    lines.append(Fore.CYAN + "║  " + Style.RESET_ALL + regime_color + Style.BRIGHT + regime_line + Style.RESET_ALL)

    if _is_finite_number(daily_return):
        return_pct = daily_return * 100
        if return_pct > 0:
            return_color = Fore.RED if return_pct > 1 else Fore.WHITE
        else:
            return_color = Fore.GREEN if return_pct < -1 else Fore.WHITE
        return_line = f"指数日收益: {return_pct:+.2f}%"
        lines.append(Fore.CYAN + "║  " + Style.RESET_ALL + return_color + return_line + Style.RESET_ALL)

    lines.append(Fore.CYAN + "║" + " " * 54 + "║" + Style.RESET_ALL)
    lines.append(Fore.CYAN + Style.BRIGHT + f"╚{border}╝" + Style.RESET_ALL)

    return "\n".join(lines)


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


def compute_auto_screening_results(trade_date: str, top_n: int = 10) -> dict:
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

        # P1-3 推荐标的自动追踪 — 记录本次 Top N, 并补全历史 T+1/T+3/T+5 收益
        tracking_dir = report_path.parent
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

        # P0-1: 输出 batch fetcher 统计
        fetcher_stats = report_payload.get("batch_data_fetcher", {})
        logger.info(
            "[Auto] P0-1 BatchDataFetcher stats: batch_calls=%d, batch_failures=%d, " "single_ticker_calls=%d, cache_hits=%d",
            fetcher_stats.get("batch_calls", 0),
            fetcher_stats.get("batch_failures", 0),
            fetcher_stats.get("single_ticker_calls", 0),
            fetcher_stats.get("cache_hits", 0),
        )

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

        # P1-7: 可选 — 自动导出 PDF 报告 (环境变量 AUTO_EXPORT_PDF=true)
        if os.environ.get("AUTO_EXPORT_PDF", "").strip().lower() in ("1", "true", "yes", "on"):
            try:
                from src.reporting.pdf_exporter import (
                    PDFReportConfig,
                    generate_screening_pdf,
                )

                pdf_dir = report_path.parent
                pdf_path = pdf_dir / f"auto_screening_{trade_date}.pdf"
                generate_screening_pdf(report_payload, pdf_path, PDFReportConfig())
                print(f"{Fore.CYAN}[Auto] P1-7 PDF 报告已生成: {pdf_path}{Style.RESET_ALL}")
                logger.info("[Auto] P1-7 PDF 报告已生成: %s", pdf_path)
            except Exception as exc:  # pragma: no cover - PDF 失败不影响主流程
                logger.warning("[Auto] P1-7 PDF 导出失败: %s", exc)

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
                push_pdf = pdf_path if "pdf_path" in locals() and pdf_path.exists() else None
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

        return 0
    except ValueError as exc:
        # 候选池为空 — 纯函数明确抛出的 ValueError
        print(f"{Fore.YELLOW}[Auto] {exc}{Style.RESET_ALL}")
        return 1
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
    print(f"\n[PushTest] 测试 payload Markdown 预览 (前 10 行):")
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
                        print(f'  {day_label}  新闻: "{title}"')
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

    peers = [(r.get("ticker", ""), _safe_score(r.get("score_b"))) for r in recs if r.get("industry_sw") == industry]
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

    # P1-9: --market-status 一键查看市场温度计
    if "--market-status" in sys.argv:
        _market_status_trade_date = datetime.now().strftime("%Y%m%d")
        for arg in sys.argv:
            if arg.startswith("--market-date="):
                _market_status_trade_date = arg.split("=", 1)[1]
        if len(_market_status_trade_date) == 10 and _market_status_trade_date[4] == "-":
            _market_status_trade_date = _market_status_trade_date.replace("-", "")
        raise SystemExit(run_market_status(_market_status_trade_date))

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

    # P1-2: --industry-rotation 独立 CLI 入口
    if "--industry-rotation" in sys.argv:
        _ir_trade_date: str | None = None
        _ir_top_n = 5
        _ir_bottom_n = 3
        for arg in sys.argv:
            if arg.startswith("--ir-date="):
                _ir_trade_date = arg.split("=", 1)[1]
            elif arg.startswith("--ir-top="):
                try:
                    _ir_top_n = int(arg.split("=", 1)[1])
                except ValueError:
                    pass
            elif arg.startswith("--ir-bottom="):
                try:
                    _ir_bottom_n = int(arg.split("=", 1)[1])
                except ValueError:
                    pass
        raise SystemExit(run_industry_rotation(_ir_trade_date, top_n=_ir_top_n, bottom_n=_ir_bottom_n))

    # P1-3: --tracking-summary 独立 CLI 入口
    if "--tracking-summary" in sys.argv:
        _ts_lookback = 30
        for arg in sys.argv:
            if arg.startswith("--tracking-lookback="):
                try:
                    _ts_lookback = int(arg.split("=", 1)[1])
                except ValueError:
                    pass
        raise SystemExit(run_tracking_summary(lookback_days=_ts_lookback))

    # P1-7: --export-pdf 独立 CLI 入口 — 从已有 auto_screening_*.json 报告生成 PDF
    if "--export-pdf" in sys.argv:
        _ep_trade_date: str | None = None
        _ep_output: str | None = None
        for arg in sys.argv:
            if arg.startswith("--pdf-date="):
                _ep_trade_date = arg.split("=", 1)[1].strip().replace("-", "")
            elif arg.startswith("--pdf-output="):
                _ep_output = arg.split("=", 1)[1].strip()
        raise SystemExit(run_export_pdf(trade_date=_ep_trade_date, output_path=_ep_output))

    # P1-11: --attribution-daily 独立 CLI 入口
    if "--attribution-daily" in sys.argv:
        _attr_trade_date: str | None = None
        _attr_positions_path: Path | None = None
        for arg in sys.argv:
            if arg.startswith("--date="):
                _attr_trade_date = arg.split("=", 1)[1]
            elif arg.startswith("--positions="):
                _attr_positions_path = Path(arg.split("=", 1)[1]).expanduser()
        if not _attr_trade_date:
            _attr_trade_date = datetime.now().strftime("%Y%m%d")
        # 标准化日期 YYYY-MM-DD -> YYYYMMDD
        if len(_attr_trade_date) == 10 and _attr_trade_date[4] == "-":
            _attr_trade_date = _attr_trade_date.replace("-", "")
        raise SystemExit(run_attribution_daily(_attr_trade_date, positions_path=_attr_positions_path))

    # P1-4: --factor-ic 独立 CLI 入口 — 因子重要性 IC 分析
    if "--factor-ic" in sys.argv:
        _ic_lookback = 30
        _ic_method = "spearman"
        for arg in sys.argv:
            if arg.startswith("--ic-lookback="):
                try:
                    _ic_lookback = int(arg.split("=", 1)[1])
                except ValueError:
                    pass
            elif arg.startswith("--ic-method="):
                _ic_method = arg.split("=", 1)[1].strip().lower()
        from src.research.factor_ic_analysis import run_factor_ic

        raise SystemExit(run_factor_ic(lookback_days=_ic_lookback, method=_ic_method))

    # P1-12: --rebalance 组合再平衡建议独立 CLI 入口
    if "--rebalance" in sys.argv:
        _reb_positions_path: Path | None = None
        _reb_drift = 0.05
        for arg in sys.argv:
            if arg.startswith("--positions-path="):
                _reb_positions_path = Path(arg.split("=", 1)[1]).expanduser()
            elif arg.startswith("--positions="):
                _reb_positions_path = Path(arg.split("=", 1)[1]).expanduser()
            elif arg.startswith("--drift-threshold="):
                try:
                    _reb_drift = float(arg.split("=", 1)[1])
                except ValueError:
                    pass
        raise SystemExit(run_rebalance(positions_path=_reb_positions_path, drift_threshold=_reb_drift))

    # P1-10: --conditional-orders 条件单建议独立 CLI 入口
    if "--conditional-orders" in sys.argv:
        _co_top_n = 20
        _co_atr_period = 14
        _co_lookback = 60
        for arg in sys.argv:
            if arg.startswith("--top-n="):
                try:
                    _co_top_n = int(arg.split("=", 1)[1])
                except ValueError:
                    pass
            elif arg.startswith("--atr-period="):
                try:
                    _co_atr_period = int(arg.split("=", 1)[1])
                except ValueError:
                    pass
            elif arg.startswith("--co-lookback="):
                try:
                    _co_lookback = int(arg.split("=", 1)[1])
                except ValueError:
                    pass
        from src.screening.conditional_order_advisor import run_conditional_orders_cli

        raise SystemExit(
            run_conditional_orders_cli(
                top_n=_co_top_n,
                atr_period=_co_atr_period,
                lookback_sessions=_co_lookback,
            )
        )

    # P2-3: --push-test 推送通道连通性测试 CLI 入口
    if "--push-test" in sys.argv:
        _pt_channel: str | None = None
        _pt_config: str | None = None
        _pt_init = "--init" in sys.argv
        for arg in sys.argv:
            if arg.startswith("--channel="):
                _pt_channel = arg.split("=", 1)[1].strip()
            elif arg.startswith("--push-config="):
                _pt_config = arg.split("=", 1)[1].strip()
        if _pt_channel is None and not _pt_init:
            for arg in sys.argv:
                if arg == "--channel":
                    idx = sys.argv.index(arg)
                    if idx + 1 < len(sys.argv):
                        _pt_channel = sys.argv[idx + 1]
        _pt_config_path = Path(_pt_config).expanduser() if _pt_config else None
        raise SystemExit(
            run_push_test(channel=_pt_channel, config_path=_pt_config_path, init=_pt_init)
        )

    # P2-5: --custom-weights 自定义策略权重独立 CLI 入口
    if "--custom-weights" in sys.argv:
        _cw_trend = 0.25
        _cw_mr = 0.25
        _cw_fund = 0.25
        _cw_es = 0.25
        _cw_top_n = 10
        _cw_trade_date: str | None = None
        for arg in sys.argv:
            if arg.startswith("--trend="):
                try:
                    _cw_trend = float(arg.split("=", 1)[1])
                except ValueError:
                    pass
            elif arg.startswith("--mean-reversion="):
                try:
                    _cw_mr = float(arg.split("=", 1)[1])
                except ValueError:
                    pass
            elif arg.startswith("--fundamental="):
                try:
                    _cw_fund = float(arg.split("=", 1)[1])
                except ValueError:
                    pass
            elif arg.startswith("--event-sentiment="):
                try:
                    _cw_es = float(arg.split("=", 1)[1])
                except ValueError:
                    pass
            elif arg.startswith("--top-n="):
                try:
                    _cw_top_n = int(arg.split("=", 1)[1])
                except ValueError:
                    pass
            elif arg.startswith("--trade-date="):
                _cw_trade_date = arg.split("=", 1)[1].strip() or None
        raise SystemExit(
            run_custom_weights(
                trend=_cw_trend,
                mean_reversion=_cw_mr,
                fundamental=_cw_fund,
                event_sentiment=_cw_es,
                top_n=_cw_top_n,
                trade_date=_cw_trade_date,
            )
        )

    # P1-8: 标的对比工具独立 CLI 入口 — 早期分发避免与 parse_cli_inputs 冲突
    # 支持 --compare=300750,600519 和 --compare 300750,600519 两种形式
    if any(arg == "--compare" or arg.startswith("--compare=") for arg in sys.argv):
        from colorama import Fore, Style

        _compare_tickers_arg: str | None = None
        _compare_metrics_arg: str | None = None
        _compare_no_radar = False
        for arg in sys.argv:
            if arg.startswith("--compare="):
                _compare_tickers_arg = arg.split("=", 1)[1]
            elif arg == "--compare":
                # 支持 --compare 300750,600519,000001 的下个 argv 形式
                idx = sys.argv.index(arg)
                if idx + 1 < len(sys.argv):
                    _compare_tickers_arg = sys.argv[idx + 1]
            elif arg.startswith("--metrics="):
                _compare_metrics_arg = arg.split("=", 1)[1]
            elif arg == "--no-radar":
                _compare_no_radar = True
        if not _compare_tickers_arg:
            print(
                f"{Fore.RED}[Compare] 用法: --compare 300750,600519,000001 "
                f"[--metrics trend_score,score_b] [--no-radar]{Style.RESET_ALL}"
            )
            raise SystemExit(1)
        from src.screening.compare_tool import run_compare_cli

        raise SystemExit(
            run_compare_cli(
                tickers_arg=_compare_tickers_arg,
                metrics_arg=_compare_metrics_arg,
                show_radar=not _compare_no_radar,
            )
        )

    # P0-5: Watchlist 独立 CLI 入口 — 早期分发, 避免与 parse_cli_inputs 的 required 校验冲突
    if any(arg in sys.argv for arg in ("--watchlist-add", "--watchlist-remove", "--watchlist-list", "--watchlist-status")):
        _wl_parser = argparse.ArgumentParser(description="Watchlist management (P0-5)")
        _wl_parser.add_argument("--watchlist-add", type=str, default=None, metavar="TICKER", help="添加标的到自选池")
        _wl_parser.add_argument("--watchlist-remove", type=str, default=None, metavar="TICKER", help="从自选池移除标的")
        _wl_parser.add_argument("--watchlist-list", action="store_true", help="列出自选池所有标的")
        _wl_parser.add_argument("--watchlist-status", action="store_true", help="展示自选池最新评分 + 信号")
        _wl_parser.add_argument("--name", type=str, default="", help="标的名称 (与 --watchlist-add 配合)")
        _wl_parser.add_argument("--tags", type=str, nargs="*", default=None, help="标签列表 (空格分隔)")
        _wl_parser.add_argument("--note", type=str, default="", help="备注 (可选)")
        _wl_parser.add_argument("--filter-tag", type=str, default=None, help="--watchlist-list 时按标签过滤")
        _wl_args, _ = _wl_parser.parse_known_args()

        if _wl_args.watchlist_add:
            raise SystemExit(
                run_watchlist_add(
                    ticker=_wl_args.watchlist_add,
                    name=_wl_args.name,
                    tags=list(_wl_args.tags) if _wl_args.tags else None,
                    note=_wl_args.note,
                )
            )
        if _wl_args.watchlist_remove:
            raise SystemExit(run_watchlist_remove(_wl_args.watchlist_remove))
        if _wl_args.watchlist_list:
            raise SystemExit(run_watchlist_list(tag=_wl_args.filter_tag))
        if _wl_args.watchlist_status:
            raise SystemExit(run_watchlist_status())

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
