"""ATR (Average True Range) 计算工具 — 用于动态止损.

使用标准 Wilder RMA（首周期算术均值 seed，之后递推），供 paper_tracker 的可选
止损执行路径和固定参数 exit-shadow 研究共用.
当 DAILY_ACTION_EXECUTION_STOP=atr 时, close_matured 用 ATR 倍数止损替代 T+N 收盘回填.

⚠ 回测验证 (2026-07-10, 81 笔 BTST): ATR 止损在当前牛市样本上 E[r]/Sharpe 均
**不优于** no_stop (均值回归 setup 的波动反而赚钱). 故默认关闭, 仅作熊市/高波动期
的可选逃生口. 详见 scripts/backtest_exit_strategies.py.
"""

from __future__ import annotations

import math
from numbers import Integral

import numpy as np
import pandas as pd

_DEFAULT_ATR_PERIOD = 14


def compute_atr(
    prices: pd.DataFrame,
    period: int = _DEFAULT_ATR_PERIOD,
    at_idx: int | None = None,
) -> float | None:
    """计算因果 Wilder ATR（首个周期算术均值 seed，之后 RMA）.

    True Range = max(high - low, |high - prev_close|, |low - prev_close|).
    首个 ATR = 前 ``period`` 个 TR 的算术均值；之后
    ``ATR[t] = (ATR[t-1] * (period-1) + TR[t]) / period``。seed 之前保持
    NaN，对外返回 ``None``。只验证并使用 ``at_idx`` 之前的因果前缀。

    Args:
        prices: 单 ticker 价格 DataFrame, 须含 high/low/close 列, 按日期升序.
        period: ATR 计算窗口 (默认 14 交易日).
        at_idx: 截止行号 (不含); None → 用整个 df 尾部. 用于回测时避免未来函数
            (只用 entry 前的数据算 ATR).

    Returns:
        ATR 绝对值 (价格单位); high/low/close 列缺失或数据不足 → None.
    """
    if prices is None or not isinstance(prices, pd.DataFrame) or prices.empty:
        return None
    if isinstance(period, bool) or not isinstance(period, Integral) or period < 1:
        return None
    required = {"high", "low", "close"}
    if not required.issubset(prices.columns):
        return None
    if at_idx is None:
        end = len(prices)
    elif (
        isinstance(at_idx, bool)
        or not isinstance(at_idx, Integral)
        or at_idx < 0
        or at_idx > len(prices)
    ):
        return None
    else:
        end = int(at_idx)
    if end < period:
        return None

    df = prices.iloc[:end].copy()
    if "date" in df.columns:
        dates = pd.to_datetime(df["date"], errors="coerce")
        if dates.isna().any():
            return None
        civil_dates = dates.dt.normalize()
        if civil_dates.duplicated().any() or not civil_dates.is_monotonic_increasing:
            return None

    for column in required:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    values = df[["high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        return None
    if (df["high"] < df["low"]).any():
        return None

    prev_close = df["close"].shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    if tr.isna().any() or not tr.map(math.isfinite).all():
        return None

    atr = pd.Series(np.nan, index=df.index, dtype=float)
    seed = float(tr.iloc[:period].mean())
    atr.iloc[period - 1] = seed
    previous_atr = seed
    for position in range(period, len(tr)):
        previous_atr = (
            previous_atr * (int(period) - 1) + float(tr.iloc[position])
        ) / int(period)
        atr.iloc[position] = previous_atr
    current = float(atr.iloc[-1])
    return current if math.isfinite(current) else None


def atr_stop_price(
    entry_price: float, atr: float | None, k: float = 2.0
) -> float | None:
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
