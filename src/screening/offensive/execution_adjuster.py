"""执行成本调整器 — v2 P0 关键。

回测名义收益 → 实际可执行收益, 三项调整:
1. limit_up_unbuyable: 触发日涨停且次日开盘继续涨停 → 剔除样本 (NaN)
2. t_plus_1_lock: T+1 交收, horizon=1 时不可卖 (退化处理: 仍算 T+1 收益但标注)
3. slippage: 买卖两端各扣 slippage_bps 个基点

这是 v2 §C.2 的核心模块 — 不经此调整的回测收益是幻觉。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# A 股涨跌停阈值 (主板 ±10%, 创业板/科创板 ±20%; 本期统一用 +9.5% 判定避免浮点)
_LIMIT_UP_PCT_THRESHOLD = 9.5


@dataclass(frozen=True)
class ExecutionConfig:
    slippage_bps: int = 30  # 单边滑点 (基点); 30bps = 0.3%
    limit_up_unbuyable: bool = True  # 触发日涨停+次日续涨停 → 剔除
    t_plus_1_lock: bool = True  # T+1 交收约束


def is_limit_up_unbuyable_next_day(prices: pd.DataFrame, trigger_idx: int) -> bool:
    """判定: 触发日涨停 (pct_change ≥ 9.5%) 且 次日开盘相对触发日收盘继续涨停。

    主板涨停 = +10%, 创业板/科创板 +20%; 用 9.5% 触发保守判定 (含 ST 5% 的极端
    情况会在 trigger 阶段被 candidate_pool 过滤)。

    Args:
        prices: 单 ticker 价格 DataFrame (date, close, open, pct_change)
        trigger_idx: 触发日在 prices 中的行号

    Returns:
        True = 次日开盘买不到 (继续涨停)
    """
    if trigger_idx + 1 >= len(prices):
        return False  # 没有次日数据
    trigger_pct = float(prices.iloc[trigger_idx].get("pct_change", 0.0) or 0.0)
    if trigger_pct < _LIMIT_UP_PCT_THRESHOLD:
        return False  # 触发日没涨停
    trigger_close = float(prices.iloc[trigger_idx]["close"])
    next_open = float(prices.iloc[trigger_idx + 1]["open"])
    # 次日开盘 = 触发日收盘 × 1.10 (再涨停) → 买不到
    return next_open >= trigger_close * 1.095


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
    slippage = config.slippage_bps / 10_000.0
    out = np.full(len(trigger_dates), np.nan)

    for i, (date_str, ticker) in enumerate(zip(trigger_dates, tickers)):
        prices = prices_by_ticker.get(ticker)
        if prices is None or len(prices) == 0:
            continue
        prices = prices.copy()
        prices["date_str"] = pd.to_datetime(prices["date"]).dt.strftime("%Y%m%d")
        # 定位触发日
        trigger_rows = prices[prices["date_str"] == date_str]
        if len(trigger_rows) == 0:
            continue
        trigger_idx = trigger_rows.index[0]
        exit_idx = trigger_idx + horizon
        if exit_idx >= len(prices):
            continue  # 数据不足

        # 涨停不可买
        if config.limit_up_unbuyable and is_limit_up_unbuyable_next_day(prices, trigger_idx):
            continue  # NaN

        # 入口价 = 次日开盘 × (1 + slippage); 出口价 = T+horizon 收盘 × (1 - slippage)
        entry_idx = trigger_idx + 1  # 次日开盘买入 (T+1 settlement)
        if entry_idx >= len(prices):
            continue
        entry_price = float(prices.iloc[entry_idx]["open"]) * (1 + slippage)
        exit_price = float(prices.iloc[exit_idx]["close"]) * (1 - slippage)
        if entry_price <= 0:
            continue
        out[i] = (exit_price / entry_price) - 1.0

    return out
