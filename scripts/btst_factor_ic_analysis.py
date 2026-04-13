#!/usr/bin/env python3
"""BTST因子IC分析：测量每个因子对次日收益的预测能力。

计算：
- IC (Information Coefficient): 因子值与次日收益的rank相关性
- Hit Rate: 因子方向与次日收益方向一致的比例
- 分位数收益: 因子分位数组合的日均收益
- 胜率: 各分位数的正收益比例
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


def _spearmanr(x: np.ndarray, y: np.ndarray) -> float:
    """纯numpy实现Spearman rank相关系数，无需scipy依赖。"""
    n = len(x)
    if n < 3:
        return np.nan
    rank_x = pd.Series(x).rank().values
    rank_y = pd.Series(y).rank().values
    d = rank_x - rank_y
    return 1.0 - 6.0 * np.sum(d ** 2) / (n * (n ** 2 - 1))

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tushare as ts

TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "ab9ec94882de89ccf50a06744281e9f6bdeef378b509b30f8eaef7aa")
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()


# ─────────────────────────────────────────────
# 1. 获取股票池和数据
# ─────────────────────────────────────────────

def get_liquid_stock_pool(date: str, min_amount: float = 100000) -> pd.DataFrame:
    """获取某日流动性足够的股票池（剔除ST、退市、涨跌停）。

    min_amount 单位：千元（tushare amount单位）。100000千元 = 1亿元。
    """
    # 获取当日全部行情
    df = pro.daily(trade_date=date)
    if df is None or df.empty:
        return pd.DataFrame()

    # 获取股票基本信息
    stock_basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name,industry,list_date")
    if stock_basic is None or stock_basic.empty:
        return pd.DataFrame()

    df = df.merge(stock_basic[["ts_code", "name", "industry", "list_date"]], on="ts_code", how="left")

    # 过滤条件
    df = df[df["amount"] >= min_amount]  # 成交额 > 1亿（千元单位）
    df = df[~df["name"].str.contains("ST|退", na=False)]  # 剔除ST和退市
    df = df[~df["ts_code"].str.startswith(("688", "8", "4"))]  # 剔除科创板和北交所（流动性差）
    df = df[df["pct_chg"].between(-9.5, 9.5)]  # 剔除涨跌停
    df = df.sort_values("amount", ascending=False).head(500)  # 取成交额前500

    return df


def get_multi_day_data(ts_codes: list[str], start_date: str, end_date: str) -> pd.DataFrame:
    """批量获取多只股票的历史行情数据。"""
    all_data = []
    batch_size = 50

    for i in range(0, len(ts_codes), batch_size):
        batch = ts_codes[i : i + batch_size]
        for code in batch:
            try:
                df = pro.daily(ts_code=code, start_date=start_date, end_date=end_date)
                if df is not None and not df.empty:
                    all_data.append(df)
            except Exception:
                continue

    if not all_data:
        return pd.DataFrame()

    result = pd.concat(all_data, ignore_index=True)
    result["trade_date"] = pd.to_datetime(result["trade_date"], format="%Y%m%d")
    result = result.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    return result


# ─────────────────────────────────────────────
# 2. 因子计算
# ─────────────────────────────────────────────

def compute_factors(df: pd.DataFrame) -> pd.DataFrame:
    """计算BTST相关的所有因子。df必须按ts_code和trade_date排序。"""
    grouped = df.groupby("ts_code")

    # ── 趋势因子 ──
    # EMA对齐度：EMA5 > EMA10 > EMA20 的程度
    df["ema5"] = grouped["close"].transform(lambda x: x.ewm(span=5, adjust=False).mean())
    df["ema10"] = grouped["close"].transform(lambda x: x.ewm(span=10, adjust=False).mean())
    df["ema20"] = grouped["close"].transform(lambda x: x.ewm(span=20, adjust=False).mean())
    df["ema60"] = grouped["close"].transform(lambda x: x.ewm(span=60, adjust=False).mean())

    # EMA对齐度：短期均线在长期均线之上的程度
    df["ema_alignment"] = (
        0.4 * (df["ema5"] > df["ema10"]).astype(float)
        + 0.35 * (df["ema10"] > df["ema20"]).astype(float)
        + 0.25 * (df["ema20"] > df["ema60"]).astype(float)
    )
    # 加权距离
    ema5_gap = (df["ema5"] / df["ema20"] - 1).clip(-0.1, 0.1)
    df["ema_alignment"] = df["ema_alignment"] * 0.6 + ema5_gap.clip(lower=0) * 10 * 0.4

    # ADX强度
    df["adx"] = grouped["close"].transform(_calc_adx)

    # 动量：5日、10日、20日收益率
    df["mom5"] = grouped["close"].transform(lambda x: x.pct_change(5))
    df["mom10"] = grouped["close"].transform(lambda x: x.pct_change(10))
    df["mom20"] = grouped["close"].transform(lambda x: x.pct_change(20))
    df["momentum"] = 0.5 * df["mom5"].clip(-0.15, 0.15) / 0.15 + 0.3 * df["mom10"].clip(-0.2, 0.2) / 0.2 + 0.2 * df["mom20"].clip(-0.3, 0.3) / 0.3

    # ── 波动率因子 ──
    df["volatility_5d"] = grouped["pct_chg"].transform(lambda x: x.rolling(5).std())
    df["volatility_20d"] = grouped["pct_chg"].transform(lambda x: x.rolling(20).std())
    df["vol_ratio"] = (df["volatility_5d"] / df["volatility_20d"]).clip(0.3, 3.0)

    # ── 成交量因子 ──
    df["vol_ma5"] = grouped["vol"].transform(lambda x: x.rolling(5).mean())
    df["vol_ma20"] = grouped["vol"].transform(lambda x: x.rolling(20).mean())
    df["volume_expansion"] = (df["vol"] / df["vol_ma5"]).clip(0.3, 5.0)
    df["volume_expansion_quality"] = (
        0.5 * (df["volume_expansion"] > 1.2).astype(float)
        + 0.3 * (df["volume_expansion"] - 1.0).clip(0, 2) / 2
        + 0.2 * (df["pct_chg"] > 0).astype(float) * (df["volume_expansion"] > 1.0).astype(float)
    )

    # ── 收盘强度因子 ──
    day_range = (df["high"] - df["low"]).clip(lower=0.01)
    df["close_strength"] = ((df["close"] - df["low"]) / day_range).clip(0, 1)

    # ── 突破新鲜度 ──
    df["high_20d"] = grouped["high"].transform(lambda x: x.rolling(20).max())
    df["low_20d"] = grouped["low"].transform(lambda x: x.rolling(20).min())
    df["breakout_freshness"] = ((df["close"] - df["high_20d"].shift(1)) / df["high_20d"].shift(1)).clip(-0.1, 0.1)
    df.loc[df["breakout_freshness"] <= 0, "breakout_freshness"] = (
        (df["close"] - df["low_20d"].shift(1))
        / (df["high_20d"].shift(1) - df["low_20d"].shift(1)).clip(lower=0.01)
    ).clip(0, 1) * 0.3  # 没有突破的给予部分分

    # ── 趋势加速度 ──
    df["ema5_prev"] = grouped["ema5"].shift(1)
    df["ema5_slope"] = ((df["ema5"] / df["ema5_prev"] - 1) * 100).fillna(0)
    df["ema5_slope_prev"] = grouped["ema5_slope"].shift(1)
    df["trend_acceleration"] = (df["ema5_slope"] - df["ema5_slope_prev"]).clip(-2, 2) / 2
    df["trend_acceleration"] = df["trend_acceleration"].fillna(0)

    # ── RSI ──
    df["rsi_14"] = grouped["close"].transform(_calc_rsi)

    # ── 均值回归因子 ──
    df["zscore_20"] = grouped["close"].transform(
        lambda x: ((x - x.rolling(20).mean()) / x.rolling(20).std()).clip(-3, 3)
    )

    # ── 次日收益标签 ──
    df["next_open"] = grouped["open"].shift(-1)
    df["next_close"] = grouped["close"].shift(-1)
    df["next_high"] = grouped["high"].shift(-1)
    df["next_low"] = grouped["low"].shift(-1)
    df["next_pct_chg"] = grouped["pct_chg"].shift(-1)
    df["next2_pct_chg"] = grouped["pct_chg"].shift(-2)

    # 次日收益（T日收盘 → T+1收盘）
    df["ret_t1"] = ((df["next_close"] / df["close"]) - 1) * 100
    # 次日高点收益（T日收盘 → T+1最高）
    df["ret_t1_high"] = ((df["next_high"] / df["close"]) - 1) * 100
    # T+2收益
    df["ret_t2"] = ((df["next2_pct_chg"]))
    # 次日开盘收益（T日收盘 → T+1开盘）
    df["gap_return"] = ((df["next_open"] / df["close"]) - 1) * 100
    # 日内收益（T+1开盘 → T+1收盘）
    df["intraday_return"] = ((df["next_close"] / df["next_open"]) - 1) * 100

    return df


def _calc_adx(series: pd.Series, period: int = 14) -> pd.Series:
    """计算ADX指标。"""
    if len(series) < period + 1:
        return pd.Series([np.nan] * len(series), index=series.index)

    high = series.rolling(2).max()
    low = series.rolling(2).min()
    plus_dm = (high - high.shift(1)).clip(lower=0)
    minus_dm = (low.shift(1) - low).clip(lower=0)
    tr = (series.rolling(2).max() - series.rolling(2).min()).clip(lower=0.01)

    plus_di = 100 * (plus_dm.ewm(span=period, adjust=False).mean() / tr.ewm(span=period, adjust=False).mean())
    minus_di = 100 * (minus_dm.ewm(span=period, adjust=False).mean() / tr.ewm(span=period, adjust=False).mean())
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).clip(lower=1))
    adx = dx.ewm(span=period, adjust=False).mean()

    # Normalize to 0-1
    return (adx / 50).clip(0, 2)


def _calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """计算RSI指标。"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()
    rs = avg_gain / avg_loss.clip(lower=0.001)
    return 100 - (100 / (1 + rs))


# ─────────────────────────────────────────────
# 3. IC分析
# ─────────────────────────────────────────────

FACTOR_NAMES = [
    "ema_alignment",
    "adx",
    "momentum",
    "vol_ratio",
    "volume_expansion",
    "volume_expansion_quality",
    "close_strength",
    "breakout_freshness",
    "trend_acceleration",
    "rsi_14",
    "zscore_20",
]

RETURN_NAMES = {
    "ret_t1": "次日收益(T→T+1收盘)",
    "ret_t1_high": "次日高点收益(T→T+1最高)",
    "ret_t2": "T+2收益",
    "gap_return": "次日跳空收益",
    "intraday_return": "次日日内收益",
}


def compute_daily_ic(df: pd.DataFrame, factor_name: str, return_name: str) -> pd.Series:
    """计算每日IC（Spearman rank correlation）。"""
    def _spearman(group):
        if len(group) < 10:
            return np.nan
        valid = group[[factor_name, return_name]].dropna()
        if len(valid) < 10:
            return np.nan
        corr = _spearmanr(valid[factor_name].values, valid[return_name].values)
        return corr

    ic_series = df.groupby("trade_date").apply(_spearman)
    return ic_series


def compute_hit_rate(df: pd.DataFrame, factor_name: str, return_name: str) -> float:
    """计算因子方向预测正确的比例。"""
    valid = df[[factor_name, return_name]].dropna()
    if valid.empty:
        return np.nan

    # 因子值大于中位数时，收益为正的比例
    median_val = valid[factor_name].median()
    high_factor = valid[valid[factor_name] > median_val]
    low_factor = valid[valid[factor_name] <= median_val]

    hit_high = (high_factor[return_name] > 0).mean() if len(high_factor) > 0 else np.nan
    hit_low = (low_factor[return_name] > 0).mean() if len(low_factor) > 0 else np.nan

    return hit_high, hit_low


def compute_quantile_returns(df: pd.DataFrame, factor_name: str, return_name: str, n_quantiles: int = 5) -> pd.DataFrame:
    """计算因子分位数组合的收益统计。"""
    valid = df[[factor_name, return_name, "trade_date"]].dropna()
    if valid.empty:
        return pd.DataFrame()

    def _quantile_stats(group):
        group = group.copy()
        group["quantile"] = pd.qcut(group[factor_name], n_quantiles, labels=False, duplicates="drop") + 1
        stats_df = group.groupby("quantile")[return_name].agg(["mean", "median", "count"])
        stats_df["win_rate"] = group.groupby("quantile")[return_name].apply(lambda x: (x > 0).mean())
        return stats_df

    daily_stats = valid.groupby("trade_date").apply(_quantile_stats)
    if daily_stats.empty:
        return pd.DataFrame()

    # Average across days
    result = daily_stats.groupby(level=1).agg({
        "mean": "mean",
        "median": "mean",
        "count": "sum",
        "win_rate": "mean",
    })
    return result


def run_analysis(start_date: str = "20260101", end_date: str = "20260413", sample_dates: int = 30):
    """运行完整的因子IC分析。"""
    print("=" * 80)
    print("BTST 因子IC分析")
    print(f"分析期间: {start_date} ~ {end_date}")
    print("=" * 80)

    # 获取交易日历（扩展到end_date之后几天，确保能拿到最近交易日）
    trade_cal = pro.trade_cal(exchange="SSE", start_date=start_date, end_date=end_date, is_open="1")
    if trade_cal is None or trade_cal.empty:
        print("无法获取交易日历")
        return

    all_dates = sorted(trade_cal["cal_date"].tolist())
    print(f"总交易日数: {len(all_dates)}")

    # 采样一些日期来构建股票池和因子
    # 取最近的交易日来获取股票池（从后往前尝试）
    sample_date = None
    for d in reversed(all_dates):
        pool_test = get_liquid_stock_pool(d)
        if pool_test is not None and not pool_test.empty:
            sample_date = d
            break
    if sample_date is None:
        print("无法获取任何交易日的股票池")
        return
    end_date_clean = sample_date  # 使用实际有数据的最后一天

    print(f"\n获取 {sample_date} 的流动性股票池...")
    pool = get_liquid_stock_pool(sample_date)
    if pool.empty:
        print("股票池为空")
        return

    ts_codes = pool["ts_code"].tolist()
    print(f"股票池大小: {len(ts_codes)}")

    # 需要至少60个交易日的数据来计算因子
    data_start = (pd.to_datetime(start_date) - timedelta(days=150)).strftime("%Y%m%d")
    print(f"\n获取历史数据: {data_start} ~ {end_date_clean}...")
    print(f"下载 {len(ts_codes)} 只股票数据...")

    # 分批下载
    all_data = []
    batch_size = 80
    for i in range(0, len(ts_codes), batch_size):
        batch = ts_codes[i : i + batch_size]
        batch_str = ",".join(batch)
        try:
            df = pro.daily(ts_code=batch_str, start_date=data_start, end_date=end_date_clean)
            if df is not None and not df.empty:
                all_data.append(df)
                print(f"  批次 {i // batch_size + 1}: 获取 {len(df)} 条记录", flush=True)
        except Exception as e:
            print(f"  批次 {i // batch_size + 1}: 错误 {e}", flush=True)
            continue

    if not all_data:
        print("无法获取数据")
        return

    df = pd.concat(all_data, ignore_index=True)
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    print(f"\n原始数据: {len(df)} 条, {df['ts_code'].nunique()} 只股票")

    # 计算因子
    print("\n计算因子...")
    df = compute_factors(df)

    # 过滤到分析期间
    analysis_start = pd.to_datetime(start_date)
    df_analysis = df[df["trade_date"] >= analysis_start].copy()
    print(f"分析数据: {len(df_analysis)} 条, {df_analysis['ts_code'].nunique()} 只股票")

    # ── IC分析 ──
    print("\n" + "=" * 80)
    print("因子IC分析结果")
    print("=" * 80)

    results = {}
    for ret_name, ret_label in RETURN_NAMES.items():
        print(f"\n{'─' * 60}")
        print(f"目标收益: {ret_label} ({ret_name})")
        print(f"{'─' * 60}")
        print(f"{'因子':<30} {'IC均值':>8} {'IC_std':>8} {'ICIR':>8} {'IC>0%':>8} {'高组胜率':>8} {'低组胜率':>8} {'多空差':>8}")
        print("-" * 96)

        factor_results = {}
        for factor_name in FACTOR_NAMES:
            # 计算IC
            ic_series = compute_daily_ic(df_analysis, factor_name, ret_name)
            if ic_series.empty or ic_series.isna().all():
                continue

            ic_mean = ic_series.mean()
            ic_std = ic_series.std()
            icir = ic_mean / ic_std if ic_std > 0 else 0
            ic_positive_rate = (ic_series > 0).mean()

            # 计算胜率
            try:
                hit_high, hit_low = compute_hit_rate(df_analysis, factor_name, ret_name)
            except Exception:
                hit_high, hit_low = np.nan, np.nan

            long_short_diff = (hit_high or 0) - (hit_low or 0)

            print(
                f"{factor_name:<30} {ic_mean:>8.4f} {ic_std:>8.4f} {icir:>8.4f} {ic_positive_rate:>7.1%} "
                f"{hit_high:>7.1%} {hit_low:>7.1%} {long_short_diff:>7.1%}"
            )

            factor_results[factor_name] = {
                "ic_mean": ic_mean,
                "ic_std": ic_std,
                "icir": icir,
                "ic_positive_rate": ic_positive_rate,
                "hit_high": hit_high,
                "hit_low": hit_low,
                "long_short_diff": long_short_diff,
            }

        results[ret_name] = factor_results

    # ── 分位数分析 ──
    print("\n" + "=" * 80)
    print("关键因子分位数分析（目标: 次日收益 ret_t1）")
    print("=" * 80)

    for factor_name in FACTOR_NAMES:
        qr = compute_quantile_returns(df_analysis, factor_name, "ret_t1", n_quantiles=5)
        if qr.empty:
            continue

        # 只显示有显著单调性的因子
        q5_mean = qr.loc[5, "mean"] if 5 in qr.index else None
        q1_mean = qr.loc[1, "mean"] if 1 in qr.index else None
        if q5_mean is not None and q1_mean is not None:
            spread = q5_mean - q1_mean
            if abs(spread) < 0.05:
                continue  # 跳过区分度太小的因子

        print(f"\n  因子: {factor_name}")
        print(f"  {'分位':>6} {'平均收益%':>10} {'中位收益%':>10} {'胜率':>8} {'样本数':>8}")
        for q in sorted(qr.index):
            row = qr.loc[q]
            print(f"  Q{int(q):>5} {row['mean']:>9.3f}% {row['median']:>9.3f}% {row['win_rate']:>7.1%} {int(row['count']):>8}")

        if 5 in qr.index and 1 in qr.index:
            spread = qr.loc[5, "mean"] - qr.loc[1, "mean"]
            print(f"  Q5-Q1 spread: {spread:.3f}%")

    # ── 最优因子组合分析 ──
    print("\n" + "=" * 80)
    print("多因子组合胜率分析")
    print("=" * 80)

    # 取IC最高的几个因子组合
    t1_results = results.get("ret_t1", {})
    if t1_results:
        sorted_factors = sorted(t1_results.items(), key=lambda x: abs(x[1]["ic_mean"]), reverse=True)
        top_factors = [f[0] for f in sorted_factors[:5]]
        print(f"\nIC最高的5个因子: {top_factors}")

        # 计算综合得分
        valid = df_analysis[["ts_code", "trade_date"] + top_factors + ["ret_t1", "ret_t1_high", "ret_t2"]].dropna()
        if len(valid) > 100:
            # 等权综合得分
            valid = valid.copy()
            valid["composite_score"] = valid[top_factors].rank(pct=True).mean(axis=1)

            # 分5组看收益
            valid["score_group"] = pd.qcut(valid["composite_score"], 5, labels=False, duplicates="drop") + 1

            print(f"\n  综合因子分位收益:")
            print(f"  {'分位':>6} {'平均T+1%':>10} {'平均T+1高%':>12} {'T+1胜率':>8} {'T+2胜率':>8} {'样本数':>8}")
            for g in sorted(valid["score_group"].unique()):
                group = valid[valid["score_group"] == g]
                t1_mean = group["ret_t1"].mean()
                t1_high_mean = group["ret_t1_high"].mean()
                t1_win = (group["ret_t1"] > 0).mean()
                t2_win = (group["ret_t2"] > 0).mean()
                print(f"  G{int(g):>5} {t1_mean:>9.3f}% {t1_high_mean:>11.3f}% {t1_win:>7.1%} {t2_win:>7.1%} {len(group):>8}")

            # Top组详细分析
            top_group = valid[valid["score_group"] == valid["score_group"].max()]
            print(f"\n  === Top组 (G{int(valid['score_group'].max())}) 详细分析 ===")
            print(f"  样本数: {len(top_group)}")
            print(f"  T+1平均收益: {top_group['ret_t1'].mean():.3f}%")
            print(f"  T+1中位收益: {top_group['ret_t1'].median():.3f}%")
            print(f"  T+1胜率: {(top_group['ret_t1'] > 0).mean():.1%}")
            print(f"  T+1高开率: {(top_group['gap_return'] > 0).mean():.1%}")
            print(f"  T+1平均高开: {top_group['gap_return'].mean():.3f}%")
            print(f"  T+1高点收益: {top_group['ret_t1_high'].mean():.3f}%")
            print(f"  T+1收益>2%比例: {(top_group['ret_t1'] > 2).mean():.1%}")
            print(f"  T+1收益>3%比例: {(top_group['ret_t1'] > 3).mean():.1%}")
            print(f"  T+1收益<-2%比例: {(top_group['ret_t1'] < -2).mean():.1%}")

    # ── 最优阈值分析 ──
    print("\n" + "=" * 80)
    print("因子阈值优化（寻找最优选股条件）")
    print("=" * 80)

    if t1_results and top_factors:
        for factor_name in top_factors[:3]:
            valid_f = df_analysis[["ts_code", "trade_date", factor_name, "ret_t1", "ret_t1_high"]].dropna()
            if len(valid_f) < 100:
                continue

            print(f"\n  因子: {factor_name}")
            print(f"  {'阈值':>12} {'选股数':>8} {'T+1均值%':>10} {'T+1胜率':>8} {'T+1高>2%':>10}")

            thresholds = [0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95]
            for t in thresholds:
                selected = valid_f[valid_f[factor_name] >= valid_f[factor_name].quantile(t)]
                if len(selected) < 5:
                    continue
                mean_ret = selected["ret_t1"].mean()
                win_rate = (selected["ret_t1"] > 0).mean()
                high_hit = (selected["ret_t1_high"] > 2).mean()
                print(f"  {f'>={t:.0%}':>12} {len(selected):>8} {mean_ret:>9.3f}% {win_rate:>7.1%} {high_hit:>9.1%}")

    print("\n" + "=" * 80)
    print("分析完成!")
    print("=" * 80)

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="BTST因子IC分析")
    parser.add_argument("--start-date", default="20260101", help="分析开始日期")
    parser.add_argument("--end-date", default="20260413", help="分析结束日期")
    args = parser.parse_args()

    run_analysis(start_date=args.start_date, end_date=args.end_date)
