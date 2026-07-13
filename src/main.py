from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import sys
import tempfile
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv

# autodev-21 / loop 120: pipeline-only imports (langchain_core / langgraph /
# src.agents.* / src.graph.state / src.utils.analysts) are deferred into the
# functions that actually run the full ``--pipeline`` workflow. The front doors
# (--top / --custom-weights / --top-picks) never build an agent graph, so they
# must not pay the import cost of 39 agent/graph modules + langchain_core at
# module load time — previously a single missing langchain dep broke every
# front door. Annotations resolve via TYPE_CHECKING below.
if TYPE_CHECKING:
    from langchain_core.messages import HumanMessage
    from langgraph.graph import END, StateGraph

    from src.agents.portfolio_manager import portfolio_management_agent
    from src.agents.risk_manager import risk_management_agent
    from src.graph.state import AgentState

# Round 20.14: 从 main.py 抽取到独立模块的 UI 辅助函数 (纯重构, 行为不变)
from src.cli.explain_helpers import (
    _print_factor_detail_block,
    _print_industry_ranking_block,
    _print_recent_events_block,
    _print_strategy_breakdown,
)
from src.cli.input import (
    parse_cli_inputs,
)
from src.cli.market_status_helpers import (
    _extract_market_status,
    _format_market_status_table,
)
from src.execution.daily_pipeline import DailyPipeline
from src.llm.defaults import get_default_model_config
from src.screening.candidate_pool import build_candidate_pool
from src.screening.consecutive_recommendation import (
    DEFAULT_LOOKBACK_DAYS,
    enrich_recommendations_with_history,
)
from src.screening.consecutive_recommendation import (
    resolve_report_dir as _resolve_consecutive_report_dir,
)
from src.screening.custom_weights import STRATEGY_KEYS
from src.screening.industry_rotation import (
    calculate_industry_rotation,
    format_rotation_block,
    IndustrySignal,
)
from src.screening.investability import (
    compute_full_pool_shadow_ranking,
    rank_recommendations_by_investability,
)
from src.screening.market_state import detect_market_state
from src.screening.recommendation_tracker import (
    get_tracking_summary,
    render_tracking_summary,
)
from src.screening.signal_fusion import fuse_batch
from src.screening.strategy_scorer import score_batch
from src.tools.tushare_api import get_ashare_daily_gainers_with_tushare
from src.utils.llm import build_parallel_provider_execution_plan
from src.utils.logging import get_logger, setup_logging
from src.utils.numeric import is_finite_number as _is_finite_number
from src.utils.numeric import safe_float as _safe_float
from src.utils.numeric import safe_int as _safe_int
from src.utils.progress import progress

if TYPE_CHECKING:
    # 仅用于 _build_selected_strategy_weights 的字符串注解; 运行时由函数体内 import 提供。
    from src.screening.custom_weights import StrategyWeights

# Load environment variables from .env file and override stale inherited values.
load_dotenv(override=True)

# Setup logging
setup_logging()
logger = get_logger(__name__)


# score_b 决策阈值 — 用于表格颜色编码 (绿/黄/红) 与 high_pool 过滤。
# 同一阈值在多处使用, 集中定义避免分叉; 修改时仅需调整此处。
SCORE_B_GREEN_FLOOR = 0.35  # >= 此值 → 绿色 (看多) / high_pool 候选
SCORE_B_YELLOW_FLOOR = 0.0  # >= 此值 (但 < 绿色) → 黄色 (中性); 低于此值 → 红色 (看空)

# Composite scoring lookback — 动量/板块/成交量维度计算窗口。
# Bug fix: 原来误用 DEFAULT_LOOKBACK_DAYS=3 (连续推荐窗口), 但 signal_momentum/
# sector_strength 设计默认值是 5 天。3 天太短, 噪声大, 导致排名次级键不稳定。
COMPOSITE_SCORE_LOOKBACK_DAYS = 5


def _compute_model_version() -> str:
    """NS-2: 返回当前打分模型的版本标识 (git short sha)。

    ``model_version`` 让后续诊断模块 (state_type_calibration /
    regime_calibration / expected_return / conviction_ranking) 能按版本分组
    区分 owner 因子调优前后的老/新模型效果 — owner 改因子 = 改代码 = commit
    = git sha 变, 因此 git short sha 精确反映打分逻辑状态。

    Returns:
        7 位小写 hex (git short sha); git 不可用时回退 ``"unknown"``。
        绝不抛异常阻断主流程 (打分/落盘优先于版本标记)。
    """
    import re
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        sha = result.stdout.strip()
        # git short sha 默认 7 位; 验证是 hex 防止异常输出污染
        if sha and re.fullmatch(r"[0-9a-f]{7,40}", sha):
            return sha
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return "unknown"


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

    # Deferred imports — loop 120 import isolation: these are pipeline-only.
    from langchain_core.messages import HumanMessage
    from src.utils.analysts import get_analyst_nodes

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
    # Deferred imports — loop 120 import isolation: pipeline-only deps.
    from langgraph.graph import END, StateGraph
    from src.agents.portfolio_manager import portfolio_management_agent
    from src.agents.risk_manager import risk_management_agent
    from src.graph.state import AgentState
    from src.utils.analysts import get_analyst_nodes

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
    from src.utils.analysts import ANALYST_ORDER, get_analyst_nodes  # deferred — loop 120

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
    from src.utils.display import save_daily_gainers_report

    report_path = save_daily_gainers_report(results, report_date, args.pct_threshold, output_path=args.output_md)
    if report_path:
        print(f"已保存报告: {report_path}")
    else:
        print("报告保存失败")
    return 0


def _sanitize_nonfinite(value):
    """BH-012: replace NaN/Inf floats with None so persisted JSON is valid.

    ``json.dump`` defaults to ``allow_nan=True``, which writes the literal
    ``NaN``/``Infinity`` tokens (non-standard JSON). Python ``json.loads``
    accepts them on read-back, so a corrupt ``score_b`` silently survives a
    round-trip and re-poisons ranking (see ``composite_score.py`` BH-012).
    Recursively walking dicts/lists, this maps any non-finite float to ``None``
    so the on-disk report is always strict JSON and downstream readers coerce
    ``None`` to ``0.0`` via ``coerce_score_b``.
    """
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, dict):
        return {key: _sanitize_nonfinite(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_sanitize_nonfinite(item) for item in value]
    return value


def _save_json_report(filename: str, payload: dict) -> Path:
    report_dir = Path(__file__).resolve().parents[1] / "data" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    output_path = report_dir / filename
    # BH-012: sanitize before write + allow_nan=False as a hard guard so a
    # non-finite float can never be persisted as a literal NaN/Infinity token.
    sanitized = _sanitize_nonfinite(payload)
    # R93-style atomic write: serialize to a same-dir temp file then os.replace
    # onto the final path. A crash (Ctrl-C / OOM / kill) during json.dump leaves
    # the previous report intact instead of a truncated/corrupt half-file — the
    # R88 corrupt-report CRASH vector. Complements c292 (flock) which guards the
    # CONCURRENT-write vector. Together: full proactive guard for the R88 family.
    fd, tmp_name = tempfile.mkstemp(prefix="." + filename + ".", suffix=".tmp", dir=str(report_dir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(sanitized, file, ensure_ascii=False, indent=2, default=str, allow_nan=False)
        os.replace(tmp_name, output_path)
    except BaseException:
        # Never leave a half-written temp behind; the prior report stays intact.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
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
    high_pool = [item for item in fused if item.score_b >= SCORE_B_GREEN_FLOOR]
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


def _build_auto_screening_payload(
    *,
    trade_date: str,
    top_n: int,
    market_state,
    candidates,
    fused,
    top_results_serializable: list[dict],
    sector_warnings: list,
    consecutive_highlight: int,
    decay_summary: dict,
    industry_rotation_payload: list[dict],
    batch_fetcher_use_batch: bool,
    batch_fetcher_stats: dict,
    optional_feature_quality: dict | None = None,
    shadow_rank_status: str = "insufficient",
    shadow_rank: list[dict] | None = None,
) -> dict:
    """Build the canonical ``--auto`` screening payload.

    Single source of truth consumed by :mod:`src.screening.auto_pipeline` for
    canonical/attempt publication and by the in-memory caller.
    """
    data_quality = {"optional_features": {}}
    data_quality.update(optional_feature_quality or {})
    candidate_rows: list[dict] = []
    for candidate in candidates:
        if hasattr(candidate, "model_dump"):
            row = candidate.model_dump(mode="json")
        else:
            row = dict(vars(candidate))
        ticker = str(row.get("ticker", "") or "")[:6]
        if not ticker:
            raise ValueError("Layer-A candidate is missing ticker")
        row["ticker"] = ticker
        candidate_rows.append(row)
    candidate_rows.sort(key=lambda row: row["ticker"])
    return {
        "mode": "auto_screening",
        "date": trade_date,
        # NS-2: 模型版本标识 (git short sha), 让诊断模块按版本区分老/新模型效果。
        "model_version": _compute_model_version(),
        "market_state": market_state.model_dump(),
        "layer_a_count": len(candidates),
        # Direct output of this compute call. auto_pipeline verifies it against
        # the exact-date snapshot written by build_candidate_pool, then binds it
        # to the publication run before building the manifest.
        "candidate_pool_run": {
            "trade_date": trade_date,
            "tickers": [row["ticker"] for row in candidate_rows],
            "candidates": candidate_rows,
        },
        "total_scored": len(fused),
        "high_pool_count": sum(1 for item in fused if item.score_b >= SCORE_B_GREEN_FLOOR),
        "top_n": top_n,
        "recommendations": top_results_serializable,
        # Research-only full Layer-A challenger.  It is deliberately separate
        # from recommendations and contains no position/execution instruction.
        "shadow_rank_status": shadow_rank_status,
        "shadow_rank": list(shadow_rank or []),
        "sector_concentration_warnings": sector_warnings,
        "consecutive_recommendation": {
            "lookback_days": DEFAULT_LOOKBACK_DAYS,
            "high_streak_count": consecutive_highlight,
        },
        # P0-3: 信号衰减汇总
        "signal_decay_summary": decay_summary,
        # P0-1: 批量获取层统计
        "batch_data_fetcher": {
            "use_batch": batch_fetcher_use_batch,
            **batch_fetcher_stats,
        },
        # P1-2: 行业轮动信号
        "industry_rotation": industry_rotation_payload,
        "data_quality": data_quality,
        # P1-10: 条件单建议 (基于 ATR 波动率) — 默认注入空数组,
        # 真实价格 provider 由调用方在 Web 端 / CLI 端注入
        "conditional_orders": [],
    }


def _close_from_price_cache(ticker: str, trade_date: str) -> float | None:
    """C-TRACKING-PRICE-BACKFILL (20260710): price_cache fallback for recommended_price.

    当 batch fetcher 缺某 ticker 当日行情时 (实测 20260709 Top-N 10 只中 4 只:
    002049/300184/300308/600392 在 batch df 缺失但 price_cache 有), 回退到
    ``data/price_cache/{ticker}.csv`` 读当日 close。避免 recommended_price 落到 0
    → legacy report-driven tracking 可能永久残留 0 → 入场价诊断/展示错误。

    数据不可用 (文件缺失/无该日行/close<=0/解析异常) 返回 None, 绝不伪造价格。
    """
    cache_path = Path("data/price_cache") / f"{ticker}.csv"
    if not cache_path.exists():
        return None
    try:
        import pandas as pd

        df = pd.read_csv(cache_path, dtype={"date": str})
        df["date"] = pd.to_datetime(df["date"])
        row = df[df["date"] == pd.to_datetime(trade_date)]
        if len(row):
            close_val = float(row.iloc[0]["close"])
            return close_val if close_val > 0 else None
    except Exception:
        logger.debug("[Auto] price_cache fallback failed for %s %s", ticker, trade_date, exc_info=True)
        return None
    return None


def _inject_recommended_prices(
    recommendations: list[dict],
    trade_date: str,
    *,
    price_frame_fetcher=None,
    price_cache_loader=None,
) -> list[dict]:
    """NS-1: 注入推荐日收盘价作为 ``recommended_price``。

    ``_build_auto_screening_payload`` 产出的 recommendations 不含任何价格字段,
    ``recommendation_tracker._coerce_recommended_price`` 按序找
    ``recommended_price`` / ``entry_price`` / ``close`` 全部缺失 → 落到
    ``return 0.0``, 污染每条 tracking_history 记录的 recommended_price,
    进而污染下游诊断 / 校准 / 归因。

    Fix: 从全市场当日 daily 行情 (batch fetcher, 与评分共用同一缓存) 取 close,
    按 ts_code → 6 位代码映射后注入每条缺少价格的 rec。

    C-TRACKING-PRICE-BACKFILL: batch fetcher 缺某 ticker 时回退到 price_cache
    (实测 4/10 的 20260709 Top-N 靠此 fallback 才拿到价)。

    - ``price_frame_fetcher``: 可注入 ``(trade_date) -> pd.DataFrame | None``
      (测试用); 默认走 ``BatchDataFetcher.fetch_daily_prices_batch``。
    - ``price_cache_loader``: 可注入 ``(ticker, trade_date) -> float | None``
      (测试用); 默认走 :func:`_close_from_price_cache`。
    - 数据不可用 (None / 空 / 缺列) 时不注入, 绝不伪造价格。
    - 已有非零 ``recommended_price`` 的 rec 不覆盖。
    """
    close_by_ticker: dict[str, float] = {}
    if price_frame_fetcher is not None:
        df = price_frame_fetcher(trade_date)
    else:
        from src.screening.batch_data_fetcher import get_global_batch_data_fetcher

        df = get_global_batch_data_fetcher().fetch_daily_prices_batch(trade_date)

    # batch fetcher 数据可用时建 ticker→close 映射; 不可用时 close_by_ticker 空,
    # 下方仍走 price_cache fallback (此前 batch 不可用直接 return, 导致全量 price=0).
    if df is not None and hasattr(df, "columns") and not df.empty and "ts_code" in df.columns and "close" in df.columns:
        for ts_code, close in zip(df["ts_code"].tolist(), df["close"].tolist()):
            code6 = str(ts_code).split(".")[0]  # "000001.SZ" → "000001"
            try:
                close_val = float(close)
            except (TypeError, ValueError):
                continue
            if code6 and close_val > 0 and code6 not in close_by_ticker:
                close_by_ticker[code6] = close_val

    cache_loader = price_cache_loader if price_cache_loader is not None else _close_from_price_cache

    fallback_count = 0
    for rec in recommendations:
        existing = rec.get("recommended_price")
        try:
            if existing is not None and float(existing) > 0:
                continue  # 真实价格优先, 不覆盖
        except (TypeError, ValueError):
            pass
        ticker = str(rec.get("ticker", "")).split(".")[0]
        close_val = close_by_ticker.get(ticker)
        if not (close_val and close_val > 0):
            # C-TRACKING-PRICE-BACKFILL: batch fetcher 缺该 ticker → 回退 price_cache
            cached = cache_loader(ticker, trade_date)
            if cached and cached > 0:
                close_val = cached
                fallback_count += 1
        if close_val and close_val > 0:
            rec["recommended_price"] = round(close_val, 4)
    if fallback_count:
        logger.info("[Auto] recommended_price price_cache fallback 注入 %d 只 (batch fetcher 缺失)", fallback_count)
    return recommendations


def _attach_signal_decay(
    top_results_serializable: list[dict],
    consecutive_report_dir: Path | None,
    trade_date: str,
):
    """P0-3 信号衰减检测 — 对比当前与历史 score_b。

    返回 ``decay_summary`` 并给 ``top_results_serializable`` 每条 rec 注入 ``decay`` 字段
    (有衰减信息时取 ``decay_info.to_dict()``, 否则填充 level=none 的默认结构)。
    """
    from src.screening.signal_decay_detector import (
        build_decay_summary,
        detect_signal_decay,
    )

    decay_map = detect_signal_decay(
        current_recommendations=top_results_serializable,
        report_dir=consecutive_report_dir,
        lookback_days=DEFAULT_LOOKBACK_DAYS,
        end_date=trade_date,
    )
    decay_summary = build_decay_summary(decay_map)
    for rec in top_results_serializable:
        ticker = rec.get("ticker", "")
        decay_info = decay_map.get(ticker)
        if decay_info is not None:
            rec["decay"] = decay_info.to_dict()
        else:
            rec["decay"] = {"level": "none", "current_score": rec.get("score_b", 0), "previous_score": None, "change_pct": None, "days_since_peak": 0}
    return decay_summary


def _rank_pool_by_investability(ranking_pool: list[dict], trade_date: str) -> list[dict]:
    """Composite-score + expected-return 投资性排名; 任何异常时回退到原 ``ranking_pool``。

    Extracted from :func:`compute_auto_screening_results` — 将 composite / expected-return
    报告构建与 ``rank_recommendations_by_investability`` 调用集中在容错 helper 中。
    """
    try:
        from src.screening.consecutive_recommendation import (
            load_auto_screening_history,
            load_tracking_history,
        )
        from src.screening.composite_score import (
            compute_composite_scores_for_recommendations,
        )
        from src.screening.expected_return import compute_expected_returns

        reports_dir = _resolve_consecutive_report_dir()
        history_records = load_tracking_history(reports_dir)
        history_reports = load_auto_screening_history(
            lookback_days=max(60, COMPOSITE_SCORE_LOOKBACK_DAYS),
            report_dir=reports_dir,
            end_date=trade_date,
        )
        model_version = _compute_model_version()
        composite_report = compute_composite_scores_for_recommendations(
            recommendations=ranking_pool,
            trade_date=trade_date,
            as_of=trade_date,
            history_reports=history_reports,
            lookback_days=COMPOSITE_SCORE_LOOKBACK_DAYS,
        )
        expected_report = compute_expected_returns(
            recommendations=ranking_pool,
            as_of=trade_date,
            model_version=model_version,
            history_records=history_records,
            lookback_days=60,
        )
        return rank_recommendations_by_investability(ranking_pool, composite_report, expected_report)
    except Exception as exc:
        # BH-017: never crash auto-screening on ranking failure, but make the
        # silent fallback observable — the user otherwise sees an unranked pool
        # with no signal that investability ranking degraded.
        logger.warning("[AutoScreening] investability ranking failed, returning unranked pool: %s", exc)
        return ranking_pool


def _rank_full_pool_shadow(
    full_pool: list[dict], trade_date: str
) -> dict[str, object]:
    """Compute the explicit full-pool challenger without influencing Top-N."""
    insufficient: dict[str, object] = {
        "shadow_rank_status": "insufficient",
        "shadow_rank": [],
    }
    try:
        from src.screening.consecutive_recommendation import (
            load_auto_screening_history,
            load_tracking_history,
        )
        from src.screening.composite_score import (
            compute_composite_scores_for_recommendations,
        )
        from src.screening.expected_return import compute_expected_returns

        reports_dir = _resolve_consecutive_report_dir()
        history_records = load_tracking_history(reports_dir)
        history_reports = load_auto_screening_history(
            lookback_days=max(60, COMPOSITE_SCORE_LOOKBACK_DAYS),
            report_dir=reports_dir,
            end_date=trade_date,
        )
        composite_report = compute_composite_scores_for_recommendations(
            recommendations=full_pool,
            trade_date=trade_date,
            as_of=trade_date,
            history_reports=history_reports,
            lookback_days=COMPOSITE_SCORE_LOOKBACK_DAYS,
        )
        expected_report = compute_expected_returns(
            recommendations=full_pool,
            as_of=trade_date,
            model_version=_compute_model_version(),
            history_records=history_records,
            lookback_days=60,
        )
        return compute_full_pool_shadow_ranking(
            full_pool, composite_report, expected_report
        )
    except Exception as exc:
        logger.warning("[AutoScreening] full-pool shadow ranking insufficient: %s", exc)
        return insufficient


def _inject_score_decomposition(
    ranking_pool: list[dict],
    fused_by_ticker: dict[str, object],
) -> int:
    """NS-6 (c266 observable): inject ``score_decomposition`` into each ranking_pool rec.

    Reads ``stability_bonus`` from the rec dict itself (written by
    ``enrich_recommendations_with_history``) so the decomposition captures the
    real consecutive-day bonus. Must therefore be called AFTER enrichment.

    Best-effort: a failure for one rec logs a WARNING and continues (was a silent
    ``except Exception: pass`` before c266 — BH-017 silent-degradation family).
    Without this observability, a future ``signal_fusion`` refactor that breaks
    ``compute_score_decomposition`` would silently drop decomposition for every rec
    → ``factor_attribution`` returns "insufficient" with no log, and the owner
    cannot diagnose why the factor-feedback loop (which factor is inverted) broke
    mid-tuning-iteration. Only 12/8005 tracking_history records currently carry
    decomposition (feature is new); masking a regression here directly blocks the
    NS-4-flip evaluation the owner is waiting on.

    Returns:
        count of recs successfully injected (for an info-level coverage log).
    """
    from src.screening.signal_fusion import compute_score_decomposition

    injected = 0
    for rec in ranking_pool:
        fused_item = fused_by_ticker.get(str(rec.get("ticker", "")))
        if fused_item is None:
            continue
        try:
            # Build consecutive_info from the rec's own enrichment fields so the
            # saved decomposition matches what _print_score_waterfall computes
            # (which reads stability_bonus from the enriched rec). Without this,
            # the saved JSON's other_adjustments diverges from the printed one.
            consecutive_info = {
                "stability_bonus": rec.get("stability_bonus", 0.0),
                "consecutive_days": rec.get("consecutive_days", 0),
            }
            rec["score_decomposition"] = compute_score_decomposition(fused_item, consecutive_info)
            injected += 1
        except Exception as exc:  # best-effort: never block the pipeline, but DO log
            logger.warning(
                "[Auto] score_decomposition injection failed for ticker=%s: %s " "(factor_attribution will be insufficient for this rec)",
                rec.get("ticker", "?"),
                exc,
            )
    return injected


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

    batch_fetcher = get_global_batch_data_fetcher()
    batch_fetcher.reset_stats()
    logger.debug(
        "[Auto] P0-1 BatchDataFetcher: use_batch=%s, max_concurrency=%d",
        batch_fetcher.use_batch,
        batch_fetcher._max_concurrency,
    )

    # Step 1: Layer A 候选池快筛
    progress.update_status("auto_screening", None, "Step 1/4: 全市场快筛 (Layer A)")
    logger.debug("[Auto] Step 1/4: trade_date=%s", trade_date)
    candidates = build_candidate_pool(trade_date)
    logger.info("[Auto] 候选池: %d 只", len(candidates))
    if not candidates:
        raise ValueError(f"候选池为空 (trade_date={trade_date}), 请检查市场数据源是否可用")

    from src.screening.scoring_feature_refresh import refresh_scoring_features
    from src.screening.scoring_feature_store import ScoringFeatureStore

    candidate_tickers = [candidate.ticker for candidate in candidates]
    refresh_summary = refresh_scoring_features(
        trade_date,
        candidate_tickers,
        timeout_seconds=float(os.environ.get("AUTO_OPTIONAL_FEATURE_REFRESH_TIMEOUT_SECONDS", "180")),
    )
    optional_feature_quality = None
    # allow_stale: when today's snapshot is missing (e.g. tushare rate-limited),
    # fall back to the most recent snapshot within 7 days. Financial data is
    # quarterly and event inputs are relatively stable, so a few days of staleness
    # is far better than returning empty signals (F:—, E:—) for every ticker.
    _stale_days = int(os.environ.get("SCORING_FEATURE_MAX_STALE_DAYS", "7"))
    scoring_feature_store = ScoringFeatureStore(allow_stale=_stale_days > 0, max_stale_days=_stale_days)
    if isinstance(refresh_summary, dict):
        logger.debug(
            "[Auto] Scoring feature refresh status=%s; score_batch will consume local snapshots",
            refresh_summary.get("status", "unknown"),
        )

    # Step 2: 四策略评分
    progress.update_status("auto_screening", None, f"Step 2/4: 四策略评分 ({len(candidates)} 只)")

    scored = score_batch(candidates, trade_date, feature_store=scoring_feature_store)
    # Backward-compatible payload key: this summary now contains both
    # data_quality.scoring_features and data_quality.optional_features.
    optional_feature_quality = scoring_feature_store.build_quality_summary(
        trade_date,
        candidate_tickers,
    )

    # Step 3: 信号融合
    progress.update_status("auto_screening", None, "Step 3/4: 信号融合 + 冲突仲裁")
    market_state = detect_market_state(trade_date)
    fused = fuse_batch(scored, market_state, trade_date, candidates=candidates)

    # Step 4: 排序输出 Top N
    progress.update_status("auto_screening", None, f"Step 4/4: 输出 Top {top_n} 推荐")
    logger.debug("[Auto] Step 4/4: 排序 Top %d", top_n)
    ranking_pool_size = max(top_n * 3, top_n)
    # NS-6: fused_by_ticker 提前构建, 供 selected_strategies / default 两分支统一注入
    # score_decomposition (因子瀑布) — 避免 selected_strategies 分支漏注入导致
    # tracking_history 落盘的 rec 无 decomposition → factor_attribution insufficient.
    fused_by_ticker = {str(item.ticker): item for item in fused}
    if selected_strategies:
        from src.screening.custom_weights import reweight_recommendations

        selected_weights = _build_selected_strategy_weights(selected_strategies)
        reweighted_results = reweight_recommendations(
            [item.model_dump(mode="json") for item in fused],
            selected_weights,
        )
        full_shadow_pool = [dict(item) for item in reweighted_results]
        ranking_pool = reweighted_results[:ranking_pool_size]
    else:
        sorted_results = sorted(fused, key=lambda item: item.score_b, reverse=True)
        full_shadow_pool = [item.model_dump(mode="json") for item in sorted_results]
        ranking_pool = [item.model_dump(mode="json") for item in sorted_results[:ranking_pool_size]]

    # NS-6: 注入 score_decomposition 到 ranking_pool 每条 rec (per-strategy
    # T/MR/F/E 贡献 + attention + stability + consensus + other + total), 让
    # update_tracking_history 落盘后 factor_attribution 模块可按贡献分位检测
    # 高低 winrate 倒挂。注意: 此处 stability_bonus 尚未 enrichment, 所以这一步
    # 注入的 decomposition 里 stability_bonus=0 (历史报告的 factor_attribution
    # 只需要 base 贡献, 不依赖 stability_bonus)。对 Top-N 的最终存盘/打印, 我们在
    # enrichment 后会重新注入一次 (见下方 _inject_score_decomposition 对
    # top_results_serializable 的调用), 确保存盘 JSON 与打印瀑布用同一份数据。
    # best-effort: 异常时不阻塞主流程 (rec 无 decomposition → factor_attribution
    # 消费侧 isinstance 校验后返回 insufficient).
    # c266: 抽成 _inject_score_decomposition helper — 失败时 logger.warning (was
    # silent except:pass), 让 factor_attribution insufficient 可诊断 (BH-017 drain).
    _injected = _inject_score_decomposition(ranking_pool, fused_by_ticker)
    logger.debug("[Auto] score_decomposition injected for %d/%d ranking_pool recs", _injected, len(ranking_pool))

    ranked_pool = _rank_pool_by_investability(ranking_pool, trade_date)

    # Keep the Top-30 production preselection intact.  The full-pool result is
    # an independently computed research challenger and cannot feed selection,
    # sizing, ledger plans, or recommendation order.
    shadow_ranking = _rank_full_pool_shadow(full_shadow_pool, trade_date)

    top_results_serializable = _select_top_n_with_constraints(ranked_pool, top_n)
    top_results_for_sector = [fused_by_ticker.get(str(rec.get("ticker", "")), rec) for rec in top_results_serializable]

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
    # 重新注入 score_decomposition 到 Top-N (此时 stability_bonus 已被 enrichment
    # 写入), 确保存盘 JSON 的 decomposition 与 _print_score_waterfall 打印的
    # 一致 (此前存盘用 stability_bonus=0 而打印用真实值, 造成 other_adjustments
    # 在 JSON=0 但日志=-10 的不一致)。
    _inject_score_decomposition(top_results_serializable, fused_by_ticker)
    # NS-1: 注入推荐日收盘价 → tracking_history recommended_price 不再落到 0.0。
    top_results_serializable = _inject_recommended_prices(top_results_serializable, trade_date)
    # Candidate-pool admission is the explicit source for these control fields:
    # build_candidate_pool only returns currently listed, non-ST names. Persist
    # that decision plus the exact board-rule implementation version so the
    # run-bound manifest need not infer them later from ticker/name strings.
    for recommendation in top_results_serializable:
        recommendation["security_status"] = "listed"
        recommendation["st_status"] = False
        recommendation["board_rule_version"] = "ashare-board-prefix-v1"
    consecutive_highlight = sum(1 for rec in top_results_serializable if rec.get("consecutive_days", 0) >= 3)

    # P0-3 信号衰减检测 — 对比当前与历史 score_b
    decay_summary = _attach_signal_decay(top_results_serializable, consecutive_report_dir, trade_date)

    # P1-2 行业轮动信号 — 申万一级行业动量 + 强度排名。
    # 用全市场快筛 fused (~300 只) 而非仅 Top-10: 行业轮动的本质是全市场
    # 横截面动量比较, 只看 Top-10 会导致强势/弱势行业列表坍缩为同一批
    # (10 只集中在 1-2 个行业, min_candidates=2 过滤后无分化)。
    fused_serializable = [item.model_dump(mode="json") for item in fused]
    industry_signals = calculate_industry_rotation(
        recommendations=fused_serializable,
        trade_date=trade_date,
    )
    industry_rotation_payload = [sig.to_dict() for sig in industry_signals]

    # Compute is deliberately publication-free. ``auto_pipeline`` is the only
    # owner of canonical/attempt publication and tracking order.
    return _build_auto_screening_payload(
        trade_date=trade_date,
        top_n=top_n,
        market_state=market_state,
        candidates=candidates,
        fused=fused,
        top_results_serializable=top_results_serializable,
        sector_warnings=sector_warnings,
        consecutive_highlight=consecutive_highlight,
        decay_summary=decay_summary,
        industry_rotation_payload=industry_rotation_payload,
        batch_fetcher_use_batch=batch_fetcher.use_batch,
        batch_fetcher_stats=batch_fetcher.stats(),
        optional_feature_quality=optional_feature_quality,
        shadow_rank_status=str(
            shadow_ranking.get("shadow_rank_status", "insufficient")
        ),
        shadow_rank=list(shadow_ranking.get("shadow_rank", [])),
    )


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

    from src.data.cache_preheater import (
        format_preheat_report,
        get_preheat_tasks,
        preheat_cache,
    )

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


def _rebuild_cli_objects(report_payload: dict):
    """重建 CLI 展示所需的强类型对象。

    从 ``compute_auto_screening_results`` 返回的 JSON payload 反序列化为
    ``_print_table_block`` 所需的 ``FusedScore`` / ``MarketState`` /
    ``IndustrySignal`` / ``DecayInfo`` 映射，返回
    ``(top_results, market_state, industry_signals, decay_map, composite_by_ticker)``。
    """
    from src.screening.market_state import MarketState
    from src.screening.signal_decay_detector import DecayInfo
    from src.screening.signal_fusion import FusedScore

    top_results = [FusedScore.model_validate(item) for item in report_payload["recommendations"]]

    market_state = MarketState.model_validate(report_payload["market_state"])

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

    # composite_score 是主排序键 (investability 排序), 但不在 FusedScore 模型上
    # (它在 rec dict 上, 由 investability.py 注入)。构建 ticker→composite 映射
    # 供表格的 Composite 列显示, 让排序自解释 (避免 score_b 非降序的困惑)。
    composite_by_ticker: dict[str, float] = {}
    for rec in report_payload["recommendations"]:
        ticker = rec.get("ticker", "")
        if ticker and rec.get("composite_score") is not None:
            composite_by_ticker[ticker] = float(rec["composite_score"])

    decay_map: dict = {}
    for rec in report_payload["recommendations"]:
        decay_payload = rec.get("decay") or {}
        if decay_payload.get("level") and decay_payload.get("level") != "none":
            try:
                decay_map[rec["ticker"]] = DecayInfo.from_dict(decay_payload)
            except Exception as exc:
                # BH-017 drain: per-ticker decay enrichment is best-effort, but
                # make the skip observable at debug level for diagnosis.
                logger.debug("[AutoScreening] decay parse skipped for %s: %s", rec.get("ticker"), exc)

    return top_results, market_state, industry_signals, decay_map, composite_by_ticker


_AUTO_PIPELINE_LOCK_PATH = Path(__file__).resolve().parents[1] / "logs" / ".auto_pipeline.lock"


def _try_acquire_pipeline_lock(lock_path: Path) -> int | None:
    """Try to acquire an exclusive advisory lock on ``lock_path`` (non-blocking).

    Concurrency guard for the ``--auto`` pipeline. Overlapping invocations
    (cron launchd + manual + ``daily_accumulate`` subprocess + direct call)
    write the same ``auto_screening_{trade_date}.json`` (fixed-path → partial
    write / last-writer-wins — the R88/R104 corrupt-report root cause) and race
    on ``tracking_history.json`` read-modify-write. The codebase has reactive
    corrupt-report armor (R88 drain across composite_score /
    data_quality_audit / candidate_pool_persistence_helpers / signal_consistency)
    but this is the first PROACTIVE mutual exclusion — it treats the root cause,
    the reactive guards treat the symptom.

    ``fcntl.flock`` is advisory and auto-releases when the holding process exits
    (even on crash / ``kill -9``), so there is no stale-lock cleanup.

    Returns the lock fd on success (caller keeps it open for the critical
    section; released at fd close / process exit), or ``None`` if another
    ``--auto`` run currently holds the lock.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        os.close(fd)
        return None
    return fd


def _daily_action_cache_refresh_enabled() -> bool:
    raw = os.environ.get("DAILY_ACTION_CACHE_REFRESH")
    if raw is None or raw == "":
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def _refresh_daily_action_caches_for_auto(
    trade_date: str,
    report_payload: dict,
    *,
    refresh_fn=None,
) -> None:
    """Best-effort cache refresh for the next ``--daily-action`` run."""

    if not _daily_action_cache_refresh_enabled():
        logger.info("[Auto] daily-action cache refresh skipped by DAILY_ACTION_CACHE_REFRESH")
        return

    if refresh_fn is None:
        from src.screening.offensive.cache_refresh import refresh_daily_action_caches

        refresh_fn = refresh_daily_action_caches

    try:
        stats = refresh_fn(trade_date)
        summary = stats.to_dict() if hasattr(stats, "to_dict") else dict(stats)
        summary["status"] = "success"
        _log_cache_refresh_summary(summary)
    except Exception as exc:  # pragma: no cover - cache refresh must not fail --auto
        logger.warning("[Auto] daily-action cache refresh failed: %s", exc)
        summary = {"status": "failed", "error": str(exc)}

    report_payload["daily_action_cache_refresh"] = summary


def _log_cache_refresh_summary(s: dict) -> None:
    """缓存刷新摘要 — 多行 INFO, 每行一个主题, 带人话标注."""
    # 行业指数
    ind_rows = s.get("industry_index_total", 0)
    ind_failed = s.get("industry_index_failed", 0)
    if ind_rows > 0 or ind_failed > 0:
        status = "✓" if ind_failed == 0 else f"✗ ({ind_failed} 失败)"
        logger.info("[Auto] 缓存刷新 · 行业指数: %d 行 %s", ind_rows, status)

    # 涨停注入
    injected = s.get("limit_up_injected", 0)
    if injected > 0:
        logger.info("[Auto] 缓存刷新 · 涨停注入: %d 只 (不在候选池的涨停股, BTST 目标)", injected)

    # 资金流
    ff_total = s.get("fund_flow_total", 0)
    ff_saved = s.get("fund_flow_saved", 0)
    ff_skipped = s.get("fund_flow_skipped_fresh", 0)
    ff_suspended = s.get("fund_flow_suspended", 0)
    ff_bse = s.get("fund_flow_bse_unsupported", 0)
    ff_empty = s.get("fund_flow_empty", 0)
    ff_failed = s.get("fund_flow_failed", 0)
    empty_tickers = s.get("fund_flow_empty_tickers", [])
    if ff_total > 0:
        parts = [f"扫描 {ff_total} 只"]
        if ff_saved > 0:
            parts.append(f"新增 {ff_saved}")
        if ff_skipped > 0:
            parts.append(f"已是最新 {ff_skipped}")
        if ff_suspended > 0:
            parts.append(f"停牌 {ff_suspended}")
        if ff_bse > 0:
            parts.append(f"北交所不支持 {ff_bse}")
        if ff_empty > 0:
            parts.append(f"⚠异常 {ff_empty}")
        if ff_failed > 0:
            parts.append(f"报错 {ff_failed}")
        logger.info("[Auto] 缓存刷新 · 资金流: %s", " · ".join(parts))
        # 异常 ticker 逐只列出 (需排查的新上市/退市/源故障)
        if empty_tickers:
            logger.warning("[Auto] 缓存刷新 · 资金流异常 ticker: %s", ", ".join(empty_tickers))

    # 价格
    px_total = s.get("price_total", 0)
    px_updated = s.get("price_updated", 0)
    px_failed = s.get("price_failed", 0)
    if px_total > 0 and (px_updated > 0 or px_failed > 0):
        parts = [f"扫描 {px_total} 只"]
        if px_updated > 0:
            parts.append(f"更新 {px_updated}")
        if px_failed > 0:
            parts.append(f"失败 {px_failed}")
        logger.info("[Auto] 缓存刷新 · 价格: %s", " · ".join(parts))


def _attach_freshness_check(trade_date: str, report_payload: dict) -> None:
    """P6-1 + F5: 在 auto_screening 报告中附加数据源新鲜度信息.

    Best-effort: ``run_auto_screening`` 必须继续渲染, 即使缓存数据库不可达.
    这是对 ``_check_report_freshness`` (report 文件日期检查) 的补充 —
    它检查底层缓存数据 (价格/资金流/新闻) 的实际新鲜度.
    """
    # Import lazily: data_freshness_guard 的 SQLite 依赖只在 auto 路径按需加载
    from src.screening.data_freshness_guard import check_data_freshness

    try:
        freshness = check_data_freshness(trade_date=trade_date)
    except Exception as exc:  # noqa: BLE001 - 新鲜度检查不应阻塞 auto 主流程
        logger.warning("[Auto] data freshness check failed (非阻塞): %s", exc)
        return

    report_payload["data_freshness"] = freshness

    # 控制台: 数据源过期时输出单行摘要 (非打断, 不改变返回码)
    if freshness.get("fresh") is False:
        summary = freshness.get("summary", "")
        if summary:
            from colorama import Fore, Style

            print(f"  {Fore.YELLOW}⚠ 数据源新鲜度:{Style.RESET_ALL} {summary}")


AUTO_BUSY_EXIT_CODE = 75


def run_auto_screening(
    trade_date: str,
    top_n: int = 10,
    *,
    strict_quality: bool = False,
) -> int:
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
        退出码（0 = 完成，1 = fatal，3 = strict-quality degraded，
        75 = 临时失败/已有实例持锁）
    """
    from colorama import Fore, Style
    from src.utils.date_utils import latest_open_trade_date_on_or_before

    normalized_trade_date = latest_open_trade_date_on_or_before(trade_date)
    if normalized_trade_date != trade_date:
        logger.info("[Auto] %s 非交易日或未开市, 改用最近开市日 %s 运行筛选", trade_date, normalized_trade_date)
        trade_date = normalized_trade_date

    # Concurrency guard (R88/R104 corrupt-report root cause): serialize overlapping
    # --auto invocations (cron launchd + manual + daily_accumulate subprocess + direct
    # call) so they cannot corrupt auto_screening_{trade_date}.json or race on
    # tracking_history.json. flock auto-releases at process exit (crash-safe).
    _auto_lock_fd = _try_acquire_pipeline_lock(_AUTO_PIPELINE_LOCK_PATH)
    if _auto_lock_fd is None:
        print(f"\n{Fore.YELLOW}[Auto] 另一个 --auto 实例正在运行 (lock {_AUTO_PIPELINE_LOCK_PATH} 已占用)；" f"跳过本次以避免 auto_screening 报告 / tracking_history 并发写入损坏。{Style.RESET_ALL}\n")
        logger.warning(
            "--auto skipped: another instance holds the pipeline lock (%s) — " "concurrent run would corrupt auto_screening report / tracking_history",
            _AUTO_PIPELINE_LOCK_PATH,
        )
        return AUTO_BUSY_EXIT_CODE

    _lock_closed = False

    def _close_auto_lock() -> None:
        nonlocal _lock_closed
        if _lock_closed:
            return
        _lock_closed = True
        try:
            os.close(_auto_lock_fd)
        except OSError:
            logger.warning("[Auto] pipeline lock fd close failed", exc_info=True)

    try:
        progress.start()
        try:
            from src.screening.auto_pipeline import AutoRunStatus, run_auto_pipeline

            # run_auto_pipeline reconciles any durable pending state before its
            # default prepare_inputs performs preheat/cache work for a new run.
            result = run_auto_pipeline(
                trade_date,
                top_n,
                strict_quality=strict_quality,
                reports_dir=_resolve_consecutive_report_dir(),
            )
            for diagnostic in result.recovery_diagnostics:
                logger.warning("[Auto] recovery diagnostic: %s", diagnostic)
        finally:
            _close_auto_lock()

        if result.status is AutoRunStatus.FATAL or result.payload is None:
            print(
                f"{Fore.RED}[Auto] 运行失败；诊断已保存到 "
                f"{result.artifact_path or '不可用'}{Style.RESET_ALL}"
            )
            return result.exit_code

        report_payload = result.payload
        payload_trade_date = report_payload.get("date")
        effective_trade_date = result.effective_trade_date or payload_trade_date
        try:
            if type(effective_trade_date) is not str:
                raise ValueError("effective trade date must be a string")
            parsed_effective_date = datetime.strptime(effective_trade_date, "%Y%m%d")
            if parsed_effective_date.strftime("%Y%m%d") != effective_trade_date:
                raise ValueError("effective trade date must be exact YYYYMMDD")
            if payload_trade_date != effective_trade_date:
                raise ValueError("result and payload trade dates differ")
        except (TypeError, ValueError) as exc:
            logger.error("[Auto] 无效的 pipeline 有效日期: %s", exc)
            print(f"{Fore.RED}[Auto] pipeline 返回的有效交易日无效，停止下游处理。{Style.RESET_ALL}")
            return 1

        if result.recovered and effective_trade_date != trade_date:
            print(
                f"{Fore.YELLOW}[Auto] 已恢复 {effective_trade_date} 的未完成发布；"
                f"本次请求日期 {trade_date} 未执行。{Style.RESET_ALL}"
            )
            logger.warning(
                "[Auto] recovered effective_trade_date=%s; requested_trade_date=%s was not executed",
                effective_trade_date,
                trade_date,
            )
        trade_date = effective_trade_date

        # 重建 CLI 展示所需的强类型对象 (top_results / market_state / industry_signals / decay_map / composite_by_ticker)
        top_results, market_state, industry_signals, decay_map, composite_by_ticker = _rebuild_cli_objects(report_payload)

        report_path = result.artifact_path
        if report_path is None:  # defensive: successful publication always returns a path
            return 1

        if result.status is AutoRunStatus.HEALTHY:
            # Only canonical healthy output may feed watchlists, PDFs, rebalance,
            # or external push channels. A degraded attempt remains diagnostic.
            pdf_path = _enrich_recommendations_with_history(
                report_payload=report_payload,
                trade_date=trade_date,
                tracking_dir=report_path.parent,
            )
            _handle_post_screening_tasks(
                report_payload=report_payload,
                trade_date=trade_date,
                report_path=report_path,
                pdf_path=pdf_path,
            )
        else:
            logger.warning(
                "[Auto] degraded attempt %s is display-only; downstream side effects skipped",
                report_path,
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
            composite_by_ticker=composite_by_ticker,
        )

        return result.exit_code
    finally:
        try:
            progress.stop()
        finally:
            _close_auto_lock()


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

    # Tracking is performed exactly once by ``auto_pipeline`` immediately after
    # canonical publication, from this same in-memory payload.
    tracking_summary = get_tracking_summary(
        history_path=tracking_dir / "tracking_history.json",
        lookback_days=30,
    )
    if tracking_summary.get("total_recommendations", 0) > 0:
        report_payload["tracking_summary"] = tracking_summary

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

    # P1-7: 可选 — 自动导出 PDF 报告 (环境变量 AUTO_EXPORT_PDF=true)
    pdf_path: Path | None = None
    if os.environ.get("AUTO_EXPORT_PDF", "").strip().lower() in ("1", "true", "yes", "on"):
        try:
            from src.reporting.pdf_exporter import (
                generate_screening_pdf,
                PDFReportConfig,
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


def _attach_strategy_attribution(report_payload: dict, trade_date: str) -> None:
    """P1-11: 策略归因日报 — 若当前有持仓则附加归因摘要到 JSON 报告并二次落盘。

    所有失败容错 (归因计算 / 落盘异常均不影响主流程)。
    """
    # P1-11: 策略归因日报 — 若当前有持仓 (data/positions.json) 则附加归因摘要到 JSON 报告。
    try:
        from src.screening.strategy_attribution_daily import (
            compute_strategy_daily_attribution,
            render_attribution_report,
        )

        attr_positions_path = _resolve_positions_path()
        attr_positions = _load_positions_for_attribution(attr_positions_path)
        if attr_positions:
            attributions = compute_strategy_daily_attribution(attr_positions, today_date=trade_date)
            if attributions:
                attr_total_pnl = sum(a.daily_pnl for a in attributions.values())
                attr_base = sum(float(p.get("prev_value", 0.0) or 0.0) for p in attr_positions if isinstance(p.get("prev_value"), (int, float)))
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
    except Exception as exc:  # pragma: no cover - 归因失败不影响主流程
        logger.warning("[Auto] P1-11 策略归因日报附加失败: %s", exc)


def _handle_post_screening_tasks(
    report_payload: dict,
    trade_date: str,
    report_path: Path,
    pdf_path: Path | None,
) -> None:
    """P1-11 + P1-12 + P2-3: 筛选后处理 (归因、再平衡、推送)。所有失败容错。"""
    from colorama import Fore, Style

    # P1-11: 策略归因日报 — 若当前有持仓则附加归因摘要到 JSON 报告并二次落盘。
    _attach_strategy_attribution(report_payload, trade_date)

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
            print(f"{Fore.CYAN}[Auto] P2-3 推送完成: {success_count}/{len(push_results)} 通道成功{Style.RESET_ALL}")
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
    composite_by_ticker: dict[str, float] | None = None,
) -> None:
    """P0-1 + O-1: 输出 batch fetcher 统计 + CLI 表格。"""
    fetcher_stats = report_payload.get("batch_data_fetcher", {})
    logger.debug(
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
        composite_by_ticker=composite_by_ticker,
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


def _build_top_table_row(*, idx: int, rec: dict, market_regime: str = "normal") -> list:
    """Build one row of the ``--top`` recommendations table.

    Extracted from :func:`run_top` — per-row formatting (score/decision color,
    consecutive-day + re-entry signal, P0-3 decay tag) lives here; the caller
    only assembles headers and invokes ``tabulate``.
    """
    from colorama import Fore, Style

    score_b = _safe_float(rec.get("score_b"), 0.0)
    decision = rec.get("decision", "neutral")
    try:
        from src.screening.investability import build_front_door_verdict

        front_door_action = str(
            build_front_door_verdict(rec, market_regime=market_regime).get("action", "AVOID") or "AVOID"
        )
    except Exception as exc:  # noqa: BLE001 — keep legacy top table rendering
        logger.warning("[Top] build_front_door_verdict 失败, 前门判决显示为不可用: %s", exc, exc_info=True)
        front_door_action = "不可用"

    if score_b >= SCORE_B_GREEN_FLOOR:
        score_colored = f"{Fore.GREEN}{score_b:+.4f}{Style.RESET_ALL}"
        decision_colored = f"{Fore.GREEN}{decision}{Style.RESET_ALL}"
    elif score_b >= SCORE_B_YELLOW_FLOOR:
        score_colored = f"{Fore.YELLOW}{score_b:+.4f}{Style.RESET_ALL}"
        decision_colored = f"{Fore.YELLOW}{decision}{Style.RESET_ALL}"
    else:
        score_colored = f"{Fore.RED}{score_b:+.4f}{Style.RESET_ALL}"
        decision_colored = f"{Fore.RED}{decision}{Style.RESET_ALL}"
    if front_door_action == "BUY":
        front_door_colored = f"{Fore.GREEN}{front_door_action}{Style.RESET_ALL}"
    elif front_door_action == "HOLD":
        front_door_colored = f"{Fore.YELLOW}{front_door_action}{Style.RESET_ALL}"
    elif front_door_action == "AVOID":
        front_door_colored = f"{Fore.RED}{front_door_action}{Style.RESET_ALL}"
    else:
        front_door_colored = f"{Fore.YELLOW}{front_door_action}{Style.RESET_ALL}"

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
        # R53: surface days_since_peak (computed-but-hidden). Distinguishes early
        # decay (↓20% at 1d) from late decay (↓20% at 5d) — a trajectory signal
        # for the "is this BUY still valid?" decision. Omit when 0 (today=peak).
        days_since_peak = int(decay.get("days_since_peak", 0) or 0)
        days_tag = f"({days_since_peak}d)" if days_since_peak > 0 else ""
        decay_str = f"{Fore.YELLOW}↓{decay_pct:.0f}%{days_tag}{Style.RESET_ALL}"

    return [idx, ticker_label, industry, score_colored, decision_colored, front_door_colored, cons_str, decay_str]


def _print_top_score_enhancements(
    recs: list[dict],
    top_n: int,
    report_path,
    *,
    trade_date: str | None = None,
    model_version: str | None = None,
    history_records: list[dict] | None = None,
) -> None:
    """打印 Top N 的评分构成、因子瀑布和预期收益增强信息。

    Extracted from :func:`run_top` — 将 score decomposition / waterfall /
    expected-returns 增强块集中到独立 helper, 容错处理旧报告格式与预期收益计算失败。
    """
    from colorama import Fore, Style

    from src.screening.signal_fusion import FusedScore

    consecutive_lookup = {r.get("ticker", ""): r for r in recs}
    top_results: list = []
    for r in recs[:top_n]:
        try:
            top_results.append(FusedScore.model_validate(r))
        except Exception as exc:
            # Older report format — skip decomposition rather than crash.
            # BH-017 drain: log at debug so format drift is diagnosable.
            logger.debug("[AutoScreening] score decomposition skipped (old format?): %s", exc)
            continue
    if not top_results:
        return

    _print_score_decomposition(top_results, consecutive_lookup)
    # R20.5 P1-3 扩展: 因子瀑布显示完整调整项
    _print_score_waterfall(top_results, consecutive_lookup)

    # R20.36 P9-1: Show expected returns if tracking history exists
    try:
        from pathlib import Path as _Path

        from src.screening.expected_return import (
            compute_expected_returns,
            render_expected_returns_compact,
        )

        _reports_dir = _Path(report_path).parent if report_path else None
        if _reports_dir:
            if trade_date is not None or history_records is not None:
                er_report = compute_expected_returns(
                    recommendations=recs[:top_n],
                    as_of=trade_date,
                    model_version=model_version,
                    history_records=history_records or [],
                    lookback_days=60,
                )
            else:
                er_report = compute_expected_returns(
                    recommendations=recs[:top_n],
                    lookback_days=60,
                    reports_dir=_reports_dir,
                )
            if er_report.total_samples > 0:
                print(f"\n{Fore.WHITE}{Style.BRIGHT}{'━' * 22} 预期收益 (P9-1) {'━' * 22}{Style.RESET_ALL}")
                print(render_expected_returns_compact(er_report))
    except Exception as exc:
        # Non-critical enhancement — never crash auto output. BH-017 drain:
        # log at debug so display-enhancement failure is diagnosable.
        logger.debug("[AutoScreening] expected-returns display skipped: %s", exc)


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

    from src.reporting.pdf_exporter import find_latest_report, load_report
    from src.screening.consecutive_recommendation import resolve_report_dir

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
    if isinstance(market_state, dict):
        state_type = market_state.get("state_type", "mixed")
        market_regime = str(market_state.get("regime_gate_level", "normal") or "normal")
    else:
        state_type = "mixed"
        market_regime = "normal"
    pool_size = payload.get("layer_a_count", len(recs))

    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[Top] 最近推荐{Style.RESET_ALL}")
    print(f"  报告日期: {trade_date}  |  市场状态: {state_type}  |  候选池: {pool_size}")
    print(f"  报告路径: {Fore.CYAN}{report_path}{Style.RESET_ALL}")

    # autodev-29 loop 146: 报告时效性披露. 过时报 (≥2天) 提示操作者
    # 数据可能不反映最新行情. R-5.D (2026-06-24) 已验证 regime 依赖时效性.
    _stale_warn_threshold = 2
    try:
        _report_date = datetime.strptime(str(trade_date).replace("-", "")[:8], "%Y%m%d")
        _report_age = (datetime.now() - _report_date).days
        if _report_age >= _stale_warn_threshold:
            print(f"  {Fore.YELLOW}⚠ 报告已过 {_report_age} 天 ({trade_date}), 数据可能已过时{Style.RESET_ALL}")
    except (ValueError, IndexError):
        pass  # 无法解析日期时静默跳过, 不阻塞显示

    print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}\n")

    table_data = [_build_top_table_row(idx=idx, rec=rec, market_regime=market_regime) for idx, rec in enumerate(recs, 1)]

    headers = [f"{Fore.WHITE}#", "Ticker", "Industry", "Score B", "Decision", "Front Door", "Consec", "Decay"]
    print(tabulate(table_data, headers=headers, tablefmt="grid", colalign=("right", "left", "left", "right", "center", "center", "center", "center")))

    # Score decomposition + waterfall + expected returns for top 5 (skip on validation failure)
    from src.screening.consecutive_recommendation import load_tracking_history

    _print_top_score_enhancements(
        recs,
        top_n,
        report_path,
        trade_date=str(trade_date),
        model_version=str(payload.get("model_version") or ""),
        history_records=load_tracking_history(report_dir),
    )

    # Cache stats if available
    fetcher_stats = payload.get("batch_data_fetcher", {})
    if fetcher_stats:
        _print_cache_hit_summary(fetcher_stats)

    print(f"  完整报告: {Fore.CYAN}{report_path}{Style.RESET_ALL}")

    # autodev-30 loop 149: 数据质量摘要 (复用 top_picks 的数据质量审计).
    # 与 --top-picks 的 _print_data_quality_block 一致: 审计 Top N 策略完整度.
    try:
        from src.screening.data_quality_audit import (
            audit_recommendations,
            load_latest_recommendations,
            render_data_quality_summary,
            summarize_data_quality,
        )

        _date_str, dq_recs = load_latest_recommendations(report_dir=report_dir)
        if dq_recs:
            dq_audits = audit_recommendations(dq_recs)
            dq_summary = summarize_data_quality(dq_audits)
            dq_summary.latest_report_date = _date_str or None
            dq_line = render_data_quality_summary(dq_summary)
            if dq_line:
                print(dq_line)
    except Exception:  # noqa: BLE001 — best-effort display; never break the front door
        pass

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
        strategy_labels = ("T", "MR", "F", "E")
        for sname, slabel in zip(STRATEGY_KEYS, strategy_labels):
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
        if score_b >= SCORE_B_GREEN_FLOOR:
            score_color = Fore.GREEN
        elif score_b >= SCORE_B_YELLOW_FLOOR:
            score_color = Fore.YELLOW
        else:
            score_color = Fore.RED

        print(f"  {consensus} {Fore.CYAN}{ticker:<8s}{Style.RESET_ALL} " f"{score_color}{score_b:+.4f}{Style.RESET_ALL}  " f"{' | '.join(parts)}  " f"{att_str}  {stab_str}")

    print(f"{Fore.WHITE}{'━' * 72}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}T=趋势 MR=均值回归 F=基本面 E=事件情绪  att=注意力  stab=连续推荐加成  ★=共识加成{Style.RESET_ALL}\n")


def _print_score_waterfall(
    top_results: list,
    consecutive_lookup: dict[str, dict],
) -> None:
    """R20.5 P1-3 扩展: 因子级瀑布 (factor-level waterfall)。

    显示每个推荐的 score_b 构成:
      score_b = clamp(base 各策略贡献 + consensus_bonus, -1, +1)
      other = score_b - (base + consensus)  [仅 clamp 截断时有非零残差]

    ``att`` (attention_composite) 和 ``stab`` (stability_bonus) 是正交元数据,
    **不参与 score_b 求和** (非加性上下文), 仅作展示。这修正了此前把它们当
    加性分量导致 other 被迫用 -stab 抵消的伪分解。

    让用户精确理解"为什么 A 排在 B 前面"——不仅看 4 个策略贡献, 还能看
    共识加成等真实调整项 + 非加性的注意力/连续推荐上下文。
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

        # Attention — non-additive metadata (not part of score_b)
        if abs(decomp["attention_contribution"]) > 1e-6:
            color = Fore.GREEN if decomp["attention_contribution"] > 0 else Fore.RED
            print(f"    {Fore.WHITE}att   {Style.RESET_ALL} {color}{decomp['attention_contribution']:+.4f}{Style.RESET_ALL}  (non-additive: cross-sectional attention)")

        # Stability bonus — non-additive metadata (not part of score_b)
        if abs(decomp["stability_bonus"]) > 1e-6:
            consec_days = int(consecutive_info.get("consecutive_days", 0) or 0)
            print(f"    {Fore.WHITE}stab  {Style.RESET_ALL} {Fore.GREEN}+{decomp['stability_bonus']:.4f}{Style.RESET_ALL}  (non-additive: consecutive={consec_days}d)")

        # Consensus bonus — additive component of score_b (±0.05)
        if abs(decomp["consensus_bonus"]) > 1e-6:
            label = "★bull" if decomp["consensus_bonus"] > 0 else "★bear"
            color = Fore.GREEN if decomp["consensus_bonus"] > 0 else Fore.RED
            print(f"    {Fore.WHITE}{label:<6s}{Style.RESET_ALL} {color}{decomp['consensus_bonus']:+.4f}{Style.RESET_ALL}")

        # Other adjustments — residual = score_b - (base_sum + consensus_bonus).
        # Non-zero only when compute_score_b's [-1, +1] clamp truncates the raw score.
        if abs(decomp["other_adjustments"]) > 1e-6:
            color = Fore.YELLOW
            print(f"    {Fore.WHITE}other {Style.RESET_ALL} {color}{decomp['other_adjustments']:+.4f}{Style.RESET_ALL}  (clamp residual)")

        # Total
        total = decomp["total"]
        if total >= SCORE_B_GREEN_FLOOR:
            total_color = Fore.GREEN + Style.BRIGHT
        elif total >= SCORE_B_YELLOW_FLOOR:
            total_color = Fore.YELLOW
        else:
            total_color = Fore.RED
        print(f"    {Fore.WHITE}{'─' * 30}{Style.RESET_ALL}")
        print(f"    {Fore.WHITE}score_b{Style.RESET_ALL}  {total_color}{total:+.4f}{Style.RESET_ALL}\n")

    print(f"{Fore.WHITE}{'━' * 64}{Style.RESET_ALL}")
    print(f"  {Fore.WHITE}score_b = base(T+MR+F+E) + consensus ± other(clamp残差); att/stab 为非加性上下文{Style.RESET_ALL}\n")


def _print_cache_hit_summary(fetcher_stats: dict[str, int]) -> None:
    """O-1: 在 --auto 表格后打印一行缓存命中率摘要，让用户感知缓存提速效果。

    有效命中率 = single_ticker_cache_hits / (batch_calls + single_ticker_calls) * 100。
    batch_calls 是批量拉取（一次请求服务全部 ticker），计入分母 total_requests，
    但不计入命中分子；因此此比率为 single-ticker 缓存命中的保守下界。
    """
    from colorama import Fore, Style

    batch_calls = int(fetcher_stats.get("batch_calls", 0))
    batch_failures = int(fetcher_stats.get("batch_failures", 0))
    single_calls = int(fetcher_stats.get("single_ticker_calls", 0))
    cache_hits = int(fetcher_stats.get("single_ticker_cache_hits", 0))
    total_requests = batch_calls + single_calls
    total_served_from_cache = cache_hits  # batch_calls 批量拉取不计入命中分子（保守下界）
    if total_requests > 0:
        effective_hit_rate = total_served_from_cache / total_requests * 100
    else:
        effective_hit_rate = 0.0
    colour = Fore.GREEN if effective_hit_rate >= 50 else Fore.YELLOW if effective_hit_rate >= 20 else Fore.RED
    print(f"  {colour}Cache: {effective_hit_rate:.0f}% hit " f"({total_served_from_cache} cached / {total_requests} requests)" f" | Batch: {batch_calls} calls ({batch_failures} failures)" f"{Style.RESET_ALL}")


def _build_auto_screening_table_row(
    *,
    idx: int,
    item,
    consecutive_lookup: dict[str, dict],
    decay_map: dict | None,
    composite_score: float | None = None,
) -> list[str]:
    """Build one row of the ``--auto`` screening table.

    Extracted from :func:`_print_auto_screening_table` to keep the per-row
    formatting (decision/score color, signal summary, consecutive highlight,
    P0-3 decay tag) in one place — the caller only assembles the headers and
    invokes ``tabulate``.
    """
    from colorama import Fore, Style

    from src.screening.signal_decay_detector import DecayLevel

    decision = item.decision
    score_b = item.score_b

    # Color-code the decision
    if score_b >= SCORE_B_GREEN_FLOOR:
        decision_colored = f"{Fore.GREEN}{decision}{Style.RESET_ALL}"
        score_colored = f"{Fore.GREEN}{score_b:+.4f}{Style.RESET_ALL}"
    elif score_b >= SCORE_B_YELLOW_FLOOR:
        decision_colored = f"{Fore.YELLOW}{decision}{Style.RESET_ALL}"
        score_colored = f"{Fore.YELLOW}{score_b:+.4f}{Style.RESET_ALL}"
    else:
        decision_colored = f"{Fore.RED}{decision}{Style.RESET_ALL}"
        score_colored = f"{Fore.RED}{score_b:+.4f}{Style.RESET_ALL}"

    # Composite score (主排序键) — 用 score_b 同款色阶, 让排序自解释。
    # composite_score 是 investability 排序的第一级键, 而 score_b 只是第 5 级
    # tie-breaker; 不显示 composite 会让 score_b 非降序显得像 bug。
    if composite_score is not None:
        if composite_score >= SCORE_B_GREEN_FLOOR:
            composite_colored = f"{Fore.GREEN}{composite_score:+.4f}{Style.RESET_ALL}"
        elif composite_score >= SCORE_B_YELLOW_FLOOR:
            composite_colored = f"{Fore.YELLOW}{composite_score:+.4f}{Style.RESET_ALL}"
        else:
            composite_colored = f"{Fore.RED}{composite_score:+.4f}{Style.RESET_ALL}"
    else:
        composite_colored = f"{Fore.WHITE}—{Style.RESET_ALL}"

    # Signal summary: direction + confidence per strategy
    signals = item.strategy_signals
    signal_parts = []
    for strategy_name in STRATEGY_KEYS:
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

    # P0-3 信号衰减标记 + R53 days_since_peak surfacing
    decay_info = decay_map.get(item.ticker) if decay_map else None
    if decay_info is None or decay_info.level == DecayLevel.NONE:
        decay_str = f"{Fore.WHITE}—{Style.RESET_ALL}"
    else:
        # R53: append days_since_peak tag (computed-but-hidden) so the user
        # can distinguish early decay (↓20% 1d) from late decay (↓20% 5d).
        _dsp = int(getattr(decay_info, "days_since_peak", 0) or 0)
        _days_tag = f"({_dsp}d)" if _dsp > 0 else ""
        if decay_info.level == DecayLevel.MILD:
            decay_str = f"{Fore.YELLOW}↓{abs(decay_info.change_pct or 0):.0f}%{_days_tag}{Style.RESET_ALL}"
        elif decay_info.level == DecayLevel.MODERATE:
            decay_str = f"{Fore.YELLOW}{Style.BRIGHT}↓{abs(decay_info.change_pct or 0):.0f}%{_days_tag}{Style.RESET_ALL}"
        else:  # SEVERE
            decay_str = f"{Fore.RED}{Style.BRIGHT}↓{abs(decay_info.change_pct or 0):.0f}%{_days_tag}{Style.RESET_ALL}"

    return [
        f"{idx}",
        ticker_label,
        item.industry_sw or "—",
        score_colored,
        composite_colored,
        decision_colored,
        signal_summary,
        consecutive_str,
        decay_str,
        arbitration,
    ]


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
    composite_by_ticker: dict[str, float] | None = None,
) -> None:
    """打印格式化的自动筛选推荐表格。

    Args:
        consecutive_recommendations: 与 ``top_results`` 顺序对应的连续推荐元数据列表
            (每个 dict 包含 ``consecutive_days`` / ``stability_bonus`` 等字段)。
        decay_map: P0-3 信号衰减映射 ``{ticker: DecayInfo}``，用于显示 Decay 列。
        industry_signals: P1-2 行业轮动信号列表 (已按 momentum_score 降序)。
        composite_by_ticker: ticker→composite_score 映射 (主排序键), 用于显示
            Composite 列让排序自解释。FusedScore 模型无此字段, 故从 rec dict 透传。
    """
    from colorama import Fore, Style
    from tabulate import tabulate

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
    composite_by_ticker = composite_by_ticker or {}
    for idx, item in enumerate(top_results, 1):
        table_data.append(
            _build_auto_screening_table_row(
                idx=idx,
                item=item,
                consecutive_lookup=consecutive_lookup,
                decay_map=decay_map,
                composite_score=composite_by_ticker.get(item.ticker),
            )
        )

    headers = [
        f"{Fore.WHITE}#",
        "Ticker",
        "Industry",
        "Score B",
        "Composite",
        "Decision",
        "Signals (T MR F E)",
        "Consecutive",
        "Decay",
        "Arbitration",
    ]
    print(tabulate(table_data, headers=headers, tablefmt="grid", colalign=("right", "left", "left", "right", "right", "center", "center", "center", "center", "left")))

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


def _select_top_n_with_constraints(ranked_pool: list[dict], top_n: int) -> list[dict]:
    """Select Top N from ranked pool with two post-ranking constraints:

    1. **att exclusion**: Skip stocks whose ``attention_composite`` exceeds
       ``AUTO_ATT_EXCLUSION_THRESHOLD`` (default 0.7). Backtest data (42 records
       with decomposition) shows high-att stocks have *negative* predictive
       value at all horizons — high attention = market peak = short-term
       reversal. This is a soft filter: if the pool is too small after
       exclusion, the threshold is ignored.

    2. **Sector cap**: No more than ``AUTO_MAX_PER_SECTOR`` (default 3) stocks
       from the same industry. Reduces portfolio variance without sacrificing
       expected return. If the pool can't fill top_n with the cap, the cap is
       relaxed by 1 at a time until enough candidates are available.

    Both constraints are applied greedily on the already-ranked pool, so the
    highest-investability stock always gets priority. The ranked pool is
    typically top_n * 3, so there is ample depth for filtering.
    """
    att_threshold = float(os.environ.get("AUTO_ATT_EXCLUSION_THRESHOLD", "0.7"))
    max_per_sector = int(os.environ.get("AUTO_MAX_PER_SECTOR", "3"))

    def _get_att(rec: dict) -> float | None:
        d = rec.get("score_decomposition")
        if not isinstance(d, dict):
            return None
        v = d.get("attention_contribution", 0.0)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def _get_sector(rec: dict) -> str:
        return str(rec.get("industry_sw") or "其他")

    def _select(threshold: float, cap: int) -> list[dict]:
        selected: list[dict] = []
        sector_counts: dict[str, int] = {}
        for rec in ranked_pool:
            att = _get_att(rec)
            if att is not None and att > threshold:
                continue
            sector = _get_sector(rec)
            if sector_counts.get(sector, 0) >= cap:
                continue
            selected.append(rec)
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            if len(selected) >= top_n:
                break
        return selected

    # Try with full constraints first
    result = _select(att_threshold, max_per_sector)
    if len(result) >= top_n:
        return result

    # Relax sector cap progressively
    for relaxed_cap in range(max_per_sector + 1, top_n + 1):
        result = _select(att_threshold, relaxed_cap)
        if len(result) >= top_n:
            logger.debug("[Auto] sector cap relaxed to %d to fill %d slots", relaxed_cap, top_n)
            return result

    # Last resort: ignore att exclusion, keep sector cap at relaxed level
    result = _select(float("inf"), max_per_sector + 2)
    if len(result) >= top_n:
        logger.debug("[Auto] att exclusion relaxed to fill %d slots", top_n)
        return result

    # Final fallback: pure top_n (no constraints)
    logger.debug("[Auto] all constraints relaxed, returning top %d by rank", min(top_n, len(ranked_pool)))
    return ranked_pool[:top_n]


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
        find_latest_report,
        generate_screening_pdf,
        load_report,
        PDFReportConfig,
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
    logger.warning(
        "[Attribution] 持仓文件格式不识别 (期望 list 或 {'positions': [...]})",
    )
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
    portfolio_value_base = sum(float(p.get("prev_value", 0.0) or 0.0) for p in positions if isinstance(p.get("prev_value"), (int, float)))
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


def _build_push_test_payload() -> dict:
    """构造 P2-3 推送连通性测试用的最小 payload (含当日日期与单条示例推荐)。

    Extracted from :func:`run_push_test` — 纯数据构造, 无副作用, 便于后续复用与测试。
    """
    return {
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
        build_default_config,
        DEFAULT_PUSH_CONFIG_PATH,
        format_report_markdown,
        load_push_config,
        send_push,
    )

    resolved_path = Path(config_path) if config_path else DEFAULT_PUSH_CONFIG_PATH

    if init:
        template = build_default_config(enabled_channels=("wecom", "dingtalk", "email", "webhook"))
        if resolved_path.exists():
            print(f"{Fore.YELLOW}[PushTest] 配置文件已存在, 不会覆盖: {resolved_path}{Style.RESET_ALL}\n" f"  如需重新生成, 请先删除该文件。")
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
        print(f"{Fore.YELLOW}[PushTest] 未找到任何 enabled 通道 ({resolved_path}){Style.RESET_ALL}\n" f"  提示: 使用 --push-test --init 生成默认模板。")
        return 1

    if channel:
        target = channel.strip().lower()
        configs = [c for c in configs if c.channel.value == target]
        if not configs:
            print(f"{Fore.RED}[PushTest] 配置中无 channel={target!r} 的 enabled 通道{Style.RESET_ALL}")
            return 1

    test_payload = _build_push_test_payload()
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
        print(f"  [{marker}] {cfg.channel.value:<14} → {cfg.target}  " f"(attempts={result.attempts}, {result.duration_ms:.0f}ms, " f"truncated={result.truncated})")
        if result.error:
            print(f"    error: {result.error}")

    success_count = sum(1 for r in results if r.success)
    total = len(results)
    print(f"\n[PushTest] 完成: {success_count}/{total} 通道成功")
    return 0 if success_count == total else 1


def _print_custom_weights_results(top: list[dict], w: dict, *, market_regime: str = "normal") -> bool:
    """打印自定义权重推荐表头与 Top N 明细。

    Extracted from :func:`run_custom_weights` — 将表头渲染 (含权重摘要) 与
    Top N 逐条明细集中到独立 helper; 空列表时打印提示并返回 False。

    Returns:
        True 表示有结果已打印 (调用方继续落盘); False 表示无可用推荐 (调用方 return 0)。
    """
    from colorama import Fore, Style

    from src.screening.investability import build_front_door_verdict

    # 前门判决颜色: BUY=绿, HOLD=黄, AVOID=红, 不可用=黄
    _front_door_colors = {
        "BUY": Fore.GREEN,
        "HOLD": Fore.YELLOW,
        "AVOID": Fore.RED,
        "不可用": Fore.YELLOW,
    }

    today = datetime.now().strftime("%Y-%m-%d")
    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[CustomWeights] 自定义权重推荐 · {today}{Style.RESET_ALL}")
    print(f"权重: 趋势 {w['trend']:.2f} / 均值回归 {w['mean_reversion']:.2f} / " f"基本面 {w['fundamental']:.2f} / 事件情绪 {w['event_sentiment']:.2f}")
    print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    if not top:
        print(f"{Fore.YELLOW}无可用推荐{Style.RESET_ALL}")
        return False

    # autodev-25 loop 134: 预计算前门判决, 用于汇总行 + 行内着色 (避免双重计算).
    # 疾病类: autodev-23 loop-126 visual hierarchy — 每行 前门 {action} 为纯文本,
    # 且重权越界 ⚠ (黄色) 在同行可能淹没 AVOID 标注. 汇总行先于明细, 行内着色.
    front_door_actions: list[str] = []
    for rec in top:
        try:
            action = str(
                build_front_door_verdict(rec, market_regime=market_regime).get("action", "AVOID") or "AVOID"
            )
        except Exception as exc:  # noqa: BLE001 — keep custom-weights display rendering
            logger.warning(
                "[CustomWeights] build_front_door_verdict 失败, 前门判决显示为不可用: %s",
                exc,
                exc_info=True,
            )
            action = "不可用"
        front_door_actions.append(action)

    # 汇总行 (extending loop-126/132 pattern)
    buy_count = sum(1 for a in front_door_actions if a == "BUY")
    hold_count = sum(1 for a in front_door_actions if a == "HOLD")
    avoid_count = sum(1 for a in front_door_actions if a == "AVOID")
    total = len(front_door_actions)
    summary_parts = [f"{Fore.GREEN}前门 BUY {buy_count}/{total}{Style.RESET_ALL}"]
    if hold_count:
        summary_parts.append(f"{Fore.YELLOW}HOLD {hold_count}{Style.RESET_ALL}")
    if avoid_count:
        summary_parts.append(f"{Fore.RED}AVOID {avoid_count}{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}🎯 前门判决:{Style.RESET_ALL} " + "  |  ".join(summary_parts))
    if avoid_count:
        avoid_tickers = [str(top[i].get("ticker", "")) for i, a in enumerate(front_door_actions) if a == "AVOID"]
        print(f"  {Fore.RED}⚠ AVOID: {', '.join(avoid_tickers)} (前门门控拒绝, 谨慎对待){Style.RESET_ALL}")
    print()

    print(f"Top {len(top)}:")
    # c284 observability: reweight 越过桶边界的 pick 其 bucket 校准已被 reset
    # (见 reweight_recommendations 的 bucket_recalibration_needed 标记). CLI 必须
    # 让操作者看到 reset 发生 (否则只在 JSON 里, 人读不到) — 行内标记 + 末尾汇总,
    # 指引去 --top-picks 复核 (那里会重算校准).
    recalibration_needed_count = 0
    for idx, (rec, front_door_action) in enumerate(zip(top, front_door_actions), start=1):
        ticker = str(rec.get("ticker", ""))
        name = str(rec.get("name", "") or "")
        score_b = _safe_float(rec.get("score_b"), 0.0)
        original = _safe_float(rec.get("original_score_b"), 0.0)
        diff = score_b - original
        diff_str = f"{diff:+.3f}"
        label = f"{ticker} {name}".strip()
        verdict_color = _front_door_colors.get(front_door_action, Fore.YELLOW)
        verdict_display = f"{verdict_color}{front_door_action}{Style.RESET_ALL}"
        recalib_marker = ""
        if rec.get("bucket_recalibration_needed"):
            recalibration_needed_count += 1
            recalib_marker = f"  {Fore.YELLOW}⚠重权越界(校准已重置){Style.RESET_ALL}"
        print(
            f"  {idx:>2}. {label:<22}  score_b {score_b:+.3f}  "
            f"前门 {verdict_display}  (原 {original:+.3f}  Δ {diff_str}){recalib_marker}"
        )
    if recalibration_needed_count > 0:
        print(f"{Fore.YELLOW}⚠ {recalibration_needed_count} 只标的因重权越过桶边界, " f"bucket 校准已重置为未知 — 请 --top-picks 复核有效校准.{Style.RESET_ALL}")
    return True


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
        load_latest_recommendations,
        reweight_recommendations,
        StrategyWeights,
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
        print(f"{Fore.YELLOW}[CustomWeights] 未找到可用推荐报告 (trade_date={trade_date or 'latest'}), " f"请先运行 --auto{Style.RESET_ALL}")
        return 1

    # autodev-26 loop 138: 前门判决 regime 必须从报告 market_state 读取,
    # 不得默认 "normal" (同 loop-137 --stock-detail 修复). 否则 crisis 报告下
    # --custom-weights 显示 BUY 而 --top-picks 显示 HOLD, 跨 surface 矛盾.
    regime = "normal"
    try:
        import json

        from src.screening.consecutive_recommendation import resolve_report_dir
        from src.screening.data_quality_audit import _find_latest_report

        _latest = _find_latest_report(resolve_report_dir())
        if _latest is not None:
            _ms = json.loads(_latest.read_text(encoding="utf-8")).get("market_state") or {}
            regime = str(_ms.get("regime_gate_level", "normal") or "normal")
    except Exception as exc:  # noqa: BLE001 — best-effort; regime stays "normal"
        logger.debug("[CustomWeights] regime read failed (defaulting to normal): %s", exc)

    # 3. 重算
    reweighted = reweight_recommendations(recs, weights)
    top = reweighted[: max(1, top_n)]

    # 4. 渲染
    w = weights.to_dict()
    if not _print_custom_weights_results(top, w, market_regime=regime):
        return 0

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
        compute_consecutive_recommendations,
        DEFAULT_LOOKBACK_DAYS,
        resolve_report_dir,
    )
    from src.screening.watchlist import format_watchlist_status, Watchlist

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
    import json

    from colorama import Fore, Style

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
    market_state = payload.get("market_state") or {}
    market_regime = (
        str(market_state.get("regime_gate_level", "normal") or "normal")
        if isinstance(market_state, dict)
        else "normal"
    )

    cross_picks = compute_cross_picks(
        recommendations,
        trade_date=date_str,
        top_industries=top_industries,
        picks_per_industry=picks_per_industry,
        market_regime=market_regime,
    )

    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[Cross Picks] 行业+个股交叉选择 (P3-3){Style.RESET_ALL}")
    print(f"  报告日期: {date_str}  |  推荐数: {len(recommendations)}")
    print(f"  行业数: {len(cross_picks)}  |  每行业 Top: {picks_per_industry}")
    print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")

    # autodev-24 loop 2: 跨行业个票的前门判决汇总 (extending loop-126 pattern
    # from --daily-brief to --cross-picks). 每个行业的 Top 个票前门判决独立展示,
    # 但操作者扫读时可能只注意行业动量排名而忽略某只个票的 AVOID 标注.
    # 汇总行突出非 BUY 个票的数量, 减少视觉层级遗漏.
    from src.screening.industry_cross_picks import compute_cross_picks_verdict_summary

    buy_tickers, hold_tickers, avoid_tickers, all_count = compute_cross_picks_verdict_summary(cross_picks)
    if all_count:
        summary_parts = [f"{Fore.GREEN}前门 BUY {len(buy_tickers)}/{all_count}{Style.RESET_ALL}"]
        if hold_tickers:
            summary_parts.append(f"{Fore.YELLOW}HOLD {len(hold_tickers)}{Style.RESET_ALL}")
        if avoid_tickers:
            summary_parts.append(f"{Fore.RED}AVOID {len(avoid_tickers)}{Style.RESET_ALL}")
        print(f"  {Fore.CYAN}🎯 前门判决:{Style.RESET_ALL} " + "  |  ".join(summary_parts))
        if avoid_tickers:
            print(f"  {Fore.RED}⚠ AVOID: {', '.join(avoid_tickers)} (前门门控拒绝, 谨慎对待){Style.RESET_ALL}")
    print()

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
    import json

    from colorama import Fore, Style

    from src.portfolio.builder import (
        compute_portfolio,
        render_portfolio,
    )
    from src.screening.consecutive_recommendation import resolve_report_dir

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
    market_state = payload.get("market_state") or {}
    market_regime = (
        str(market_state.get("regime_gate_level", "normal") or "normal")
        if isinstance(market_state, dict)
        else "normal"
    )

    summary = compute_portfolio(
        recommendations,
        top_n=top_n,
        position_cap=position_cap,
        industry_cap=industry_cap,
        market_regime=market_regime,
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

    from src.research.factor_ic_analysis import extract_factor_panel_from_history
    from src.research.weight_calibration import (
        compute_weight_calibration,
        render_weight_calibration,
    )
    from src.screening.consecutive_recommendation import resolve_report_dir

    report_dir = resolve_report_dir()
    if not report_dir.exists():
        print(f"{Fore.RED}未找到 reports 目录: {report_dir}{Style.RESET_ALL}")
        return 1

    # 尝试从历史报告中提取因子面板
    # R90 family (autodev-34-op3): 用模块级 ``datetime`` (line 10), 不在此局部
    # re-import —— 局部 import 会遮蔽模块级 name 使测试 patch 失效 (Op2 在
    # daily_brief 已证同病致 staleness 测试随日历漂移变红).
    try:
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
            trades.append(
                {
                    "date": rec.get("recommended_date", ""),
                    "ticker": rec.get("ticker", ""),
                    "name": rec.get("name", ""),
                    "pnl": _safe_float(t1) / 100.0 if _safe_float(t1) != 0 else 0.0,
                    "return_pct": _safe_float(t1) / 100.0,
                    "strategy": "unknown",
                }
            )

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

    # R89/R54 third sibling: 复用 data_quality_audit._find_latest_report (优选开市日
    # 报告 + 跳过 malformed 文件名). 此前的内联 sorted(glob) 是第三 sibling, 漏网
    # 导致 --explain 看不到周五 Top 推荐 (2026-07-12: 300604/600206/688017/688630
    # 在周六报告 0711 中找不到, 误报 "未在 Top 推荐中"). shared helper 已由 Op1
    # 修复了周末 + malformed 双缺陷.
    from src.screening.data_quality_audit import _find_latest_report

    latest = _find_latest_report()
    if latest is None:
        print(f"{Fore.RED}没有 auto_screening_*.json 报告, 请先运行 --auto{Style.RESET_ALL}")
        return 1
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
    # Loop 95 (autodev): drain None score_b crash — sibling-disease sweep of
    # GAMMA-008 (_print_industry_ranking_block None score_b coerced via
    # _safe_float). dict.get("score_b", 0.0) returns 0.0 only when the KEY is
    # MISSING; when key is present but value=None (corrupt report / partial
    # pipeline / upstream None propagation), .get returns None, and
    # None:+.4f raises TypeError. Mirror GAMMA-008: coerce via safe_float.
    from src.utils.numeric import safe_float as _safe_float

    score_b = _safe_float(match.get("score_b"), 0.0)
    # Loop 95 (autodev): drain None/empty decision — sibling-disease sweep of
    # score_b above. dict.get("decision", "neutral") returns "neutral" only
    # when the KEY is MISSING; when key is present but value=None (corrupt
    # report / partial pipeline / upstream None propagation) or empty string,
    # .get returns the falsy value and the render shows misleading "决策: None"
    # or "决策:  " (operator sees a confusing label, not the missing-key
    # default "neutral"). Coerce falsy → "neutral" mirroring score_b.
    _raw_decision = match.get("decision")
    decision = _raw_decision if _raw_decision else "neutral"
    ms = data.get("market_state", {})
    regime = str(ms.get("regime_gate_level", "normal") or "normal") if isinstance(ms, dict) else "normal"
    try:
        from src.screening.investability import build_front_door_verdict

        front_door_action = str(build_front_door_verdict(match, market_regime=regime).get("action", "AVOID") or "AVOID")
    except Exception as exc:
        logger.warning("[Explain] build_front_door_verdict 失败, 前门判决显示为不可用: %s", exc, exc_info=True)
        front_door_action = "不可用"
    # Loop 96 (autodev): drain None signals/arbitration — sibling-disease
    # sweep of Loop 95. Same disease class: dict.get(key, default) returns
    # default only when the KEY is MISSING; when key is present but
    # value=None (corrupt report / partial pipeline / upstream None
    # propagation from to_recommendation_dict), .get returns None.
    # - signals=None crashes _print_strategy_breakdown at
    #   ``signals.get(strat_name)`` (explain_helpers.py:43) with
    #   AttributeError. Verified RED before fix.
    # - arbitration=None is currently absorbed by ``if arbitration:``
    #   truthiness (works by accident, not by design). Coercion makes the
    #   intent explicit and protects against future code that iterates
    #   arbitration outside the truthiness guard.
    signals = match.get("strategy_signals") or {}
    arbitration = match.get("arbitration_applied") or []

    print(f"\n{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{Style.BRIGHT}[Explain] {ticker} {name} ({industry}){Style.RESET_ALL}")
    print(f"  报告: {latest.name}")
    # autodev-27 loop 141: 前门判决着色, 与 --stock-detail/--why-not/--custom-weights
    # 等跨 surface 一致 (BUY=绿/HOLD=黄/AVOID=红). 原为纯文本, AVOID 不醒目.
    _explain_verdict_colors = {"BUY": Fore.GREEN, "HOLD": Fore.YELLOW, "AVOID": Fore.RED, "不可用": Fore.YELLOW}
    _verdict_color = _explain_verdict_colors.get(front_door_action, Fore.YELLOW)
    _verdict_display = f"{_verdict_color}{front_door_action}{Style.RESET_ALL}"
    print(f"  决策: {decision}  |  前门判决: {_verdict_display}  |  Score B: {score_b:+.4f}")
    print(f"{Fore.WHITE}{Style.BRIGHT}{'=' * 70}{Style.RESET_ALL}\n")

    # Market state at scoring time
    if ms:
        print(f"{Fore.CYAN}市场状态:{Style.RESET_ALL} {ms.get('state_type', '?')}  |  " f"仓位系数: {ms.get('position_scale', 1.0):.2f}  |  " f"regime: {ms.get('regime_gate_level', 'normal')}")

    # Per-strategy breakdown
    _print_strategy_breakdown(signals)

    # ── Block A: 因子贡献度明细 ──
    _print_factor_detail_block(signals)

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

    # R75 (R71/R72/R73 trust-calibration family): this surface emits a per-ticker
    # decision label plus a full strategy/factor breakdown. Carry the same
    # non-advice disclaimer as --top-picks / --daily-brief / --position-check /
    # PDF / backtest so users do not read "决策: buy" as a deterministic
    # instruction (serves product goal "更高确信" = confidence includes honest
    # boundary disclosure).
    print(f"\n  {Fore.WHITE}⚠ 以上解释由 AI 模型自动生成, 仅供研究 / 学习用途, 不构成任何投资建议。" f"实际投资需结合个人风险承受能力与最新市场情况。{Style.RESET_ALL}")
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
        raise SystemExit(
            run_auto_screening(
                trade_date,
                top_n=inputs.top_n,
                strict_quality=inputs.strict_quality,
            )
        )

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
    from src.utils.display import print_trading_output, save_trading_report

    print_trading_output(result)
    save_trading_report(
        result=result,
        tickers=tickers,
        model_name=inputs.model_name,
        model_provider=inputs.model_provider,
        start_date=inputs.start_date,
        end_date=inputs.end_date,
    )
