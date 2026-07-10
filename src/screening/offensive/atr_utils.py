"""ATR (Average True Range) 计算工具 — 用于动态止损.

Wilder ATR 的简化版 (SMA of True Range), 供 paper_tracker 的可选止损执行路径用.
当 DAILY_ACTION_EXECUTION_STOP=atr 时, close_matured 用 ATR 倍数止损替代 T+N 收盘回填.

⚠ 回测验证 (2026-07-10, 81 笔 BTST): ATR 止损在当前牛市样本上 E[r]/Sharpe 均
**不优于** no_stop (均值回归 setup 的波动反而赚钱). 故默认关闭, 仅作熊市/高波动期
的可选逃生口. 详见 scripts/backtest_exit_strategies.py.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

_DEFAULT_ATR_PERIOD = 20  # 与 btst_breakout._MAIN_FLOW_LOOKBACK_DAYS 对齐


def compute_atr(prices: pd.DataFrame, period: int = _DEFAULT_ATR_PERIOD, at_idx: int | None = None) -> float | None:
    """计算 Wilder 风格的 ATR (True Range 的 SMA).

    True Range = max(high - low, |high - prev_close|, |low - prev_close|).
    ATR = 最近 ``period`` 个交易日的 TR 均值.

    Args:
        prices: 单 ticker 价格 DataFrame, 须含 high/low/close 列, 按日期升序.
        period: ATR 计算窗口 (默认 20 交易日).
        at_idx: 截止行号 (不含); None → 用整个 df 尾部. 用于回测时避免未来函数
            (只用 entry 前的数据算 ATR).

    Returns:
        ATR 绝对值 (价格单位); high/low/close 列缺失或数据不足 → None.
    """
    if prices is None or len(prices) == 0:
        return None
    required = {"high", "low", "close"}
    if not required.issubset(prices.columns):
        return None
    end = at_idx if at_idx is not None else len(prices)
    if end < period + 1:
        return None  # 需要 period+1 行才能算首个 TR (含 prev_close)
    df = prices.iloc[:end]
    prev_close = df["close"].shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    window = tr.iloc[-(period):]
    if window.isna().all():
        return None
    return float(window.mean())


def atr_stop_price(entry_price: float, atr: float | None, k: float = 2.0) -> float | None:
    """计算 ATR 止损价 = entry_price - k × ATR.

    Args:
        entry_price: 入场价 (已含滑点).
        atr: ATR 绝对值 (None → 无法算止损, 返回 None).
        k: ATR 倍数 (默认 2.0; 越大止损越宽, 越少误杀但尾部风险越大).

    Returns:
        止损价 (绝对值); atr 为 None/<=0 时返回 None (调用方降级到时间退出).
    """
    if atr is None or atr <= 0 or entry_price <= 0:
        return None
    return entry_price - k * atr
