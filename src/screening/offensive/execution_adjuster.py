"""执行成本调整器 — v2 P0 关键。

回测名义收益 → 实际可执行收益, 三项调整:
1. limit_up_unbuyable: 触发日涨停且次日开盘继续涨停 → 剔除样本 (NaN)
2. t_plus_1_lock: T+1 交收, horizon=1 时不可卖 (退化处理: 仍算 T+1 收益但标注)
3. slippage: 买卖两端各扣 slippage_bps 个基点

这是 v2 §C.2 的核心模块 — 不经此调整的回测收益是幻觉。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

import numpy as np
import pandas as pd

# A 股涨跌停阈值 (主板 ±10%, 创业板/科创板 ±20%; 本期统一用 +9.5% 判定避免浮点)
_LIMIT_UP_PCT_THRESHOLD = 9.5


class ExecutionStatus(str, Enum):
    """Conservative daily-bar execution classification."""

    EXECUTABLE_PROXY = "executable_proxy"
    UNEXECUTABLE_PROXY = "unexecutable_proxy"
    UNKNOWN_QUEUE = "unknown_queue"


@dataclass(frozen=True)
class ExecutionCosts:
    """Versioned, injectable cost assumptions for one fill."""

    version: str = "v1"
    commission: float = 0.0
    tax_rate: float = 0.0
    slippage_bps: float = 0.0
    other_fee: float = 0.0


@dataclass(frozen=True)
class FillResult:
    """Auditable fill economics with the observed price left unchanged."""

    raw_fill_price: float
    quantity: int
    side: str
    gross_notional: float
    commission: float
    tax: float
    slippage_cost: float
    other_fee: float
    net_cash_flow: float
    cost_version: str


def classify_open_fill(
    open_price: float | None,
    limit_down: float | None,
    limit_up: float | None,
    suspended: bool | None,
    *,
    high: float | None = None,
    low: float | None = None,
) -> ExecutionStatus:
    """Classify an open-price paper-fill proxy without guessing queue fills."""
    if suspended is None or open_price is None or limit_down is None or limit_up is None:
        return ExecutionStatus.UNKNOWN_QUEUE
    if suspended:
        return ExecutionStatus.UNEXECUTABLE_PROXY
    if limit_down >= limit_up:
        return ExecutionStatus.UNKNOWN_QUEUE

    on_limit = open_price == limit_down or open_price == limit_up
    locked_at_open = high == open_price and low == open_price
    if on_limit and locked_at_open:
        return ExecutionStatus.UNEXECUTABLE_PROXY
    if on_limit:
        return ExecutionStatus.UNKNOWN_QUEUE
    if limit_down < open_price < limit_up:
        return ExecutionStatus.EXECUTABLE_PROXY
    return ExecutionStatus.UNEXECUTABLE_PROXY


def apply_execution_costs(
    raw_fill_price: float,
    quantity: int,
    side: str,
    costs: ExecutionCosts,
    *,
    entry_date: date | None = None,
    exit_date: date | None = None,
) -> FillResult:
    """Apply independently auditable costs while preserving the raw fill price."""
    side = side.lower()
    if side not in {"buy", "sell"}:
        raise ValueError("side must be 'buy' or 'sell'")
    if raw_fill_price <= 0 or quantity <= 0:
        raise ValueError("raw_fill_price and quantity must be positive")
    if min(costs.commission, costs.tax_rate, costs.slippage_bps, costs.other_fee) < 0:
        raise ValueError("execution costs must be non-negative")
    if side == "sell" and entry_date is not None:
        if exit_date is None or exit_date <= entry_date:
            raise ValueError("exit_date must be strictly after entry_date for T+1")

    gross_notional = raw_fill_price * quantity
    tax = gross_notional * costs.tax_rate
    slippage_cost = gross_notional * costs.slippage_bps / 10_000.0
    total_cost = costs.commission + tax + slippage_cost + costs.other_fee
    net_cash_flow = -(gross_notional + total_cost) if side == "buy" else gross_notional - total_cost
    return FillResult(
        raw_fill_price=raw_fill_price,
        quantity=quantity,
        side=side,
        gross_notional=gross_notional,
        commission=costs.commission,
        tax=tax,
        slippage_cost=slippage_cost,
        other_fee=costs.other_fee,
        net_cash_flow=net_cash_flow,
        cost_version=costs.version,
    )


@dataclass(frozen=True)
class ExecutionConfig:
    slippage_bps: int = 30  # 单边滑点 (基点); 30bps = 0.3%
    limit_up_unbuyable: bool = True  # 触发日涨停+次日续涨停 → 剔除
    t_plus_1_lock: bool = True  # T+1 交收约束


def is_limit_up_unbuyable_next_day(prices: pd.DataFrame, trigger_idx: int, ticker: str = "") -> bool:
    """判定: 触发日涨停 (pct_change ≥ 板块涨停阈值) 且 次日开盘相对触发日收盘继续涨停。

    板块自适应涨停阈值: 主板 9.5%, 科创板/创业板 19.5%, 北交所 29.0%.
    旧固定 9.5% 在 20% 板会把次日开盘涨 9.5-19.5% (非涨停, 实际可买) 的样本
    错误剔除 → 回测样本偏少. 按 ticker 前缀取正确阈值.

    Args:
        prices: 单 ticker 价格 DataFrame (date, close, open, pct_change)
        trigger_idx: 触发日在 prices 中的行号
        ticker: 6 位代码 (用于按板块判涨停阈值; 空则回退主板 9.5%)

    Returns:
        True = 次日开盘买不到 (继续涨停)
    """
    if trigger_idx + 1 >= len(prices):
        return False  # 没有次日数据
    # 板块自适应涨停阈值 (ticker 空时回退主板口径, 保持向后兼容)
    from src.tools.ashare_board_utils import limit_up_pct_for_ticker

    limit_up_pct = limit_up_pct_for_ticker(ticker) if ticker else _LIMIT_UP_PCT_THRESHOLD
    trigger_pct = float(prices.iloc[trigger_idx].get("pct_change", 0.0) or 0.0)
    if trigger_pct < limit_up_pct:
        return False  # 触发日没涨停
    trigger_close = float(prices.iloc[trigger_idx]["close"])
    next_open = float(prices.iloc[trigger_idx + 1]["open"])
    # 次日开盘继续涨停 (相对触发日收盘再涨 ≥涨停幅度) → 买不到.
    # limit_up_pct 是 pct 下限 (如 9.5/19.5), 转成倍数: 1 + 9.5/100 = 1.095.
    return next_open >= trigger_close * (1 + limit_up_pct / 100.0)


def _build_date_index(prices: pd.DataFrame) -> dict[str, int]:
    """构建 {YYYYMMDD: row_index} 索引 (一次构建, 多次查).

    性能修复: 此前 adjust_returns 在循环内对每个样本做 prices.copy() +
    pd.to_datetime 全表转换 (29k 样本 × 1575 行 = 4500 万次操作, ~分钟级).
    现在外部缓存索引, 定位触发日从 O(n) 全表扫降到 O(1) dict 查.
    """
    if hasattr(prices["date"].dt, "strftime"):
        date_strs = prices["date"].dt.strftime("%Y%m%d")
    else:
        date_strs = prices["date"].astype(str).str.replace("-", "", regex=False)
    return {d: i for i, d in enumerate(date_strs)}


def adjust_returns(
    trigger_dates: list[str],
    tickers: list[str],
    prices_by_ticker: dict[str, pd.DataFrame],
    horizon: int,
    config: ExecutionConfig,
) -> np.ndarray:
    """对一批触发样本计算 execution-adjusted T+horizon 收益。

    Args:
        trigger_dates: 触发日列表 (YYYYMMDD)
        tickers: 对应 ticker 列表 (同长度)
        prices_by_ticker: {ticker: 价格 DataFrame}, 至少含 date/close/open/pct_change
        horizon: 持有期 (交易日)
        config: 执行配置

    Returns:
        np.ndarray[float], 每个样本的调整后收益率; 不可买/数据不足 → NaN
    """
    assert len(trigger_dates) == len(tickers)
    out = np.full(len(trigger_dates), np.nan)
    costs = ExecutionCosts(slippage_bps=config.slippage_bps)

    # 预建每个 ticker 的 date→idx 索引 (per ticker 只算一次, 后续 O(1) 查)
    date_idx_cache: dict[str, dict[str, int]] = {}

    for i, (date_str, ticker) in enumerate(zip(trigger_dates, tickers)):
        prices = prices_by_ticker.get(ticker)
        if prices is None or len(prices) == 0:
            continue
        if ticker not in date_idx_cache:
            date_idx_cache[ticker] = _build_date_index(prices)
        trigger_idx = date_idx_cache[ticker].get(date_str)
        if trigger_idx is None:
            continue
        exit_idx = trigger_idx + horizon
        if exit_idx >= len(prices):
            continue  # 数据不足

        # 涨停不可买 (板块自适应: 主板 +10%, 科创/创业 +20%, 北交所 +30%)
        if config.limit_up_unbuyable and is_limit_up_unbuyable_next_day(prices, trigger_idx, ticker):
            continue  # NaN

        # 通过 v2 成本模型独立计算滑点，再还原 legacy 的每股有效价格。
        entry_idx = trigger_idx + 1  # 次日开盘买入 (T+1 settlement)
        if entry_idx >= len(prices):
            continue
        raw_entry_price = float(prices.iloc[entry_idx]["open"])
        raw_exit_price = float(prices.iloc[exit_idx]["close"])
        if raw_entry_price <= 0 or raw_exit_price <= 0:
            continue
        entry_fill = apply_execution_costs(raw_entry_price, 1, "buy", costs)
        exit_fill = apply_execution_costs(raw_exit_price, 1, "sell", costs)
        entry_price = -entry_fill.net_cash_flow
        exit_price = exit_fill.net_cash_flow
        if entry_price <= 0:
            continue
        out[i] = (exit_price / entry_price) - 1.0

    return out
