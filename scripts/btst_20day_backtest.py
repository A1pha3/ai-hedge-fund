#!/usr/bin/env python3
"""
BTST 20天真实回测：比较多个 short-trade profile 的实际选股表现。

核心逻辑：
1. 对每个交易日，构建候选池（模拟pipeline的过滤逻辑）
2. 用历史价格数据计算7+1个因子的近似值
3. 分别用各profile的在线权重计算score_target
4. 选出score_target超过阈值的股票
5. 对比次日以及T+2/T+3实际收益

注意：这是因子层面的近似回测，不包含LLM agent评分（score_c）。
score_c在实际pipeline中贡献~40%权重，因此回测结果会低估实际区分度。
"""

import argparse
import json
import math
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv

from src.targets import build_short_trade_target_profile, get_short_trade_target_profile

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


def _compact_trade_date_value(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%Y%m%d")
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10].replace("-", "")
    return text.replace("-", "")


def _extract_open_trade_dates_from_calendar_frame(cal: pd.DataFrame, start_date: str, end_date: str) -> list[str]:
    if cal is None or cal.empty:
        return []
    for column in ("cal_date", "trade_date"):
        if column in cal.columns:
            values = [_compact_trade_date_value(value) for value in cal[column].tolist()]
            return sorted({value for value in values if value and start_date <= value <= end_date})
    return []


def _load_open_trade_dates(pro, start_date: str, end_date: str) -> list[str]:
    try:
        cal = pro.trade_cal(exchange="SSE", start_date=start_date, end_date=end_date, is_open="1")
    except Exception:
        cal = None
    all_dates = _extract_open_trade_dates_from_calendar_frame(cal, start_date, end_date)
    if all_dates:
        return all_dates

    import akshare as ak

    fallback_cal = ak.tool_trade_date_hist_sina()
    all_dates = _extract_open_trade_dates_from_calendar_frame(fallback_cal, start_date, end_date)
    if all_dates:
        return all_dates
    raise ValueError(f"Unable to load open trade dates between {start_date} and {end_date}")


def spearman_ic(x, y):
    x, y = np.array(x, dtype=float), np.array(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if len(x) < 10:
        return np.nan
    rx = pd.Series(x).rank().values
    ry = pd.Series(y).rank().values
    n = len(rx)
    d = rx - ry
    return 1.0 - 6.0 * np.sum(d**2) / (n * (n**2 - 1))


def compute_factors(hist_group, trade_date_price):
    """从历史价格数据计算各因子近似值。"""
    g = hist_group.sort_values("trade_date")
    close = g["close"].values
    high = g["high"].values
    open_arr = g["open"].values
    vol_col = "vol" if "vol" in g.columns else "volume"
    volume = g[vol_col].values
    n = len(close)
    if n < 22:
        return None

    # --- 基础指标 ---
    last_close = close[-1]
    prev_close = close[-2] if n >= 2 else close[-1]
    open_price = open_arr[-1]

    # --- momentum_strength (trend agent momentum subfactor) ---
    mom_1m = (close[-1] / close[-22] - 1) if n >= 23 else 0
    mom_3m = (close[-1] / close[-min(66, n - 1)] - 1) if n >= 67 else mom_1m
    mom_1m_n = min(max(mom_1m / 0.3, 0), 1)
    mom_3m_n = min(max(mom_3m / 0.5, 0), 1)
    if n >= 133:
        mom_6m = close[-1] / close[-132] - 1
        mom_6m_n = min(max(mom_6m / 0.8, 0), 1)
        momentum_strength = min(max(0.4 * mom_1m_n + 0.3 * mom_3m_n + 0.3 * mom_6m_n, 0), 1)
    elif n >= 67:
        momentum_strength = min(max(0.6 * mom_1m_n + 0.4 * mom_3m_n, 0), 1)
    else:
        momentum_strength = mom_1m_n

    # --- volume_expansion_quality ---
    # 近5日成交量 vs 20日均量
    avg_vol_20 = np.mean(volume[-min(20, n) :]) if n >= 5 else 1
    avg_vol_5 = np.mean(volume[-5:]) if n >= 5 else 1
    vol_ratio = avg_vol_5 / avg_vol_20 if avg_vol_20 > 0 else 1.0
    volume_expansion = min(max((vol_ratio - 1.0) / 1.5, 0), 1)  # 0~2.5x volume → 0~1

    # --- close_strength (EMA alignment proxy) ---
    # 简化：用价格相对位置表示趋势强度
    high_20 = np.max(close[-min(20, n) :])
    low_20 = np.min(close[-min(20, n) :])
    price_range = high_20 - low_20 if high_20 > low_20 else 1
    close_strength = (last_close - low_20) / price_range  # 在区间中的位置

    # --- breakout_freshness (简化) ---
    # 近5日涨幅 + 当日涨幅
    ret_5d = (close[-1] / close[-min(6, n)] - 1) if n >= 6 else 0
    daily_return = (last_close / prev_close - 1) if prev_close > 0 else 0
    breakout_raw = 0.5 * min(max(ret_5d / 0.15, 0), 1) + 0.5 * min(max(daily_return / 0.05, 0), 1)
    breakout_freshness = min(max(breakout_raw, 0), 1)

    # --- trend_acceleration (简化) ---
    # 短期动量 vs 中期动量的加速度
    if n >= 44:
        mom_2w = close[-1] / close[-10] - 1
        mom_prev_2w = close[-11] / close[-21] - 1 if n >= 22 else 0
        accel = mom_2w - mom_prev_2w
        trend_acceleration = min(max(accel / 0.1, 0), 1)
    else:
        trend_acceleration = 0.5 * momentum_strength

    # --- sector_resonance (用行业beta近似) ---
    # 简化：当日涨幅vs市场涨幅
    sector_resonance = 0.5  # 无行业数据，取中性值

    # --- catalyst_freshness (用事件信号强度近似) ---
    # 简化：用换手率和涨幅组合
    amount = g["amount"].values[-1]
    avg_amount = np.mean(g["amount"].values[-min(20, n) :])
    amount_ratio = amount / avg_amount if avg_amount > 0 else 1.0
    catalyst_freshness = min(max(0.6 * min(amount_ratio / 3.0, 1) + 0.4 * breakout_freshness, 0), 1)

    # --- layer_c_alignment (简化) ---
    # 用阳线+涨跌幅组合
    is_bull = last_close > open_price
    layer_c_alignment = min(max(0.5 * float(is_bull) + 0.5 * min(max(daily_return / 0.03, 0), 1), 0), 1)

    # --- historical_continuation_score (same-ticker continuation proxy) ---
    continuation_hits_close = 0
    continuation_hits_high = 0
    continuation_return_sum = 0.0
    continuation_evaluable = 0
    for idx in range(20, n - 1):
        base_close = close[idx]
        prev_day_close = close[idx - 1]
        if prev_day_close <= 0 or base_close <= 0:
            continue
        base_return = (base_close / prev_day_close) - 1.0
        window = close[max(0, idx - 19) : idx + 1]
        window_high = np.max(window)
        window_low = np.min(window)
        window_range = window_high - window_low if window_high > window_low else 1.0
        close_position = (base_close - window_low) / window_range
        if base_return < 0.015 or close_position < 0.55:
            continue
        continuation_evaluable += 1
        next_close = close[idx + 1]
        next_high = high[idx + 1]
        next_open = open_arr[idx + 1]
        if next_close > base_close:
            continuation_hits_close += 1
        if next_high >= (base_close * 1.02):
            continuation_hits_high += 1
        if next_open > 0:
            continuation_return_sum += (next_close - next_open) / next_open
    if continuation_evaluable > 0:
        next_close_positive_rate = continuation_hits_close / continuation_evaluable
        next_high_hit_rate = continuation_hits_high / continuation_evaluable
        next_open_to_close_return_mean = continuation_return_sum / continuation_evaluable
    else:
        next_close_positive_rate = 0.50
        next_high_hit_rate = 0.60
        next_open_to_close_return_mean = 0.01
    continuation_evidence_weight = continuation_evaluable / (continuation_evaluable + 3.0) if continuation_evaluable > 0 else 0.0
    normalized_open_to_close_return = min(max((next_open_to_close_return_mean + 0.01) / 0.04, 0), 1)
    historical_continuation_score = min(
        max(
            (0.50 * next_close_positive_rate)
            + (0.25 * next_high_hit_rate)
            + (0.15 * normalized_open_to_close_return)
            + (0.10 * continuation_evidence_weight),
            0,
        ),
        1,
    )

    # --- 短期反转因子 (improved: RSI + price reversal + volume confirmation) ---
    if n >= 14:
        # RSI-based mean reversion (closer to real agent's mean reversion strategy)
        deltas = np.diff(close[-15:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))
        else:
            rsi = 100.0
        # RSI < 30 → strong oversold (reversal opportunity)
        rsi_reversal = min(max((30.0 - rsi) / 30.0, 0), 1) if rsi < 50 else 0.0
    else:
        rsi_reversal = 0.0

    if n >= 6:
        ret_5d_raw = close[-1] / close[-6] - 1
        price_reversal = min(max(-ret_5d_raw / 0.10, 0), 1)
    else:
        price_reversal = 0.0

    # Volume confirmation for reversal (declining volume on sell-off = healthy reversal setup)
    if n >= 10:
        vol_recent = np.mean(volume[-3:])
        vol_prior = np.mean(volume[-10:-3])
        vol_decline = vol_recent < vol_prior  # Volume declining = selling exhaustion
        vol_confirm = 0.15 if vol_decline else 0.0
    else:
        vol_confirm = 0.0

    reversal = min(max(0.40 * price_reversal + 0.45 * rsi_reversal + vol_confirm, 0), 1)

    # --- 2日反转因子 (improved: Bollinger Band position + 2d reversal) ---
    if n >= 20:
        # Bollinger Band position (closer to real agent's stat analysis)
        sma_20 = np.mean(close[-20:])
        std_20 = np.std(close[-20:])
        if std_20 > 0:
            bb_position = (last_close - sma_20) / (2.0 * std_20)  # -1 to +1 range
        else:
            bb_position = 0.0
        # Low BB position (below lower band) = oversold
        bb_oversold = min(max((-bb_position - 1.0) / 1.0, 0), 1) if bb_position < 0 else 0.0
    else:
        bb_oversold = 0.0

    if n >= 3:
        ret_2d_raw = close[-1] / close[-3] - 1
        price_2d_reversal = min(max(-ret_2d_raw / 0.06, 0), 1)
    else:
        price_2d_reversal = 0.0

    reversal_2d = min(max(0.45 * price_2d_reversal + 0.40 * bb_oversold + 0.15 * rsi_reversal, 0), 1)

    # --- 日内尾盘强度 ---
    if open_price > 0:
        intraday_change = (last_close - open_price) / open_price
        intraday_strength = min(max(intraday_change / 0.03, 0), 1)
    else:
        intraday_strength = 0.0

    return {
        "momentum_strength": momentum_strength,
        "volume_expansion_quality": volume_expansion,
        "close_strength": close_strength,
        "breakout_freshness": breakout_freshness,
        "trend_acceleration": trend_acceleration,
        "sector_resonance": sector_resonance,
        "catalyst_freshness": catalyst_freshness,
        "layer_c_alignment": layer_c_alignment,
        "historical_continuation_score": historical_continuation_score,
        "reversal": reversal,
        "reversal_2d": reversal_2d,
        "intraday_strength": intraday_strength,
        "daily_return": daily_return,
        "vol_ratio": vol_ratio,
    }


def summarize_return_stats(returns: pd.Series, *, big_win_threshold: float = 3.0) -> dict[str, float | None]:
    values = pd.Series(returns, dtype=float).dropna()
    if values.empty:
        return {
            "win_rate": 0.0,
            "avg_ret": 0.0,
            "big_win_rate": 0.0,
            "avg_win_ret": 0.0,
            "avg_loss_ret": 0.0,
            "payoff_ratio": None,
            "expectancy": 0.0,
            "downside_p10": 0.0,
        }

    wins = values[values > 0]
    losses = values[values <= 0]
    win_rate = float((values > 0).mean())
    avg_ret = float(values.mean())
    big_win_rate = float((values > big_win_threshold).mean())
    avg_win_ret = float(wins.mean()) if not wins.empty else 0.0
    avg_loss_ret = float(losses.mean()) if not losses.empty else 0.0
    payoff_ratio: float | None = None
    if avg_win_ret > 0 and avg_loss_ret < 0:
        payoff_ratio = float(avg_win_ret / abs(avg_loss_ret))
    expectancy = float((win_rate * avg_win_ret) + ((1.0 - win_rate) * avg_loss_ret))
    downside_p10 = float(values.quantile(0.10))
    return {
        "win_rate": win_rate,
        "avg_ret": avg_ret,
        "big_win_rate": big_win_rate,
        "avg_win_ret": avg_win_ret,
        "avg_loss_ret": avg_loss_ret,
        "payoff_ratio": payoff_ratio,
        "expectancy": expectancy,
        "downside_p10": downside_p10,
    }


def summarize_horizon_return_stats(returns: pd.Series, *, big_win_threshold: float = 3.0) -> dict[str, float | int | None]:
    values = pd.Series(returns, dtype=float).dropna()
    if values.empty:
        return {
            "available_count": 0,
            "win_rate": 0.0,
            "avg_ret": 0.0,
            "big_win_rate": 0.0,
            "avg_win_ret": 0.0,
            "avg_loss_ret": 0.0,
            "payoff_ratio": None,
            "expectancy": 0.0,
            "downside_p10": 0.0,
        }
    stats = summarize_return_stats(values, big_win_threshold=big_win_threshold)
    return {
        "available_count": int(len(values)),
        **stats,
    }


PROFILE_WEIGHT_FIELDS = {
    "breakout_freshness": "breakout_freshness_weight",
    "trend_acceleration": "trend_acceleration_weight",
    "volume_expansion_quality": "volume_expansion_quality_weight",
    "close_strength": "close_strength_weight",
    "sector_resonance": "sector_resonance_weight",
    "catalyst_freshness": "catalyst_freshness_weight",
    "layer_c_alignment": "layer_c_alignment_weight",
    "historical_continuation_score": "historical_continuation_score_weight",
    "momentum_strength": "momentum_strength_weight",
    "reversal": "short_term_reversal_weight",
    "intraday_strength": "intraday_strength_weight",
    "reversal_2d": "reversal_2d_weight",
}

SUPPORTED_PROFILE_OVERRIDE_FIELDS = {
    "select_threshold",
    "near_miss_threshold",
    "selected_rank_cap",
    "near_miss_rank_cap",
    "selected_rank_cap_ratio",
    "near_miss_rank_cap_ratio",
    "selected_rank_cap_relief_score_margin_min",
    "selected_rank_cap_relief_rank_buffer",
    "selected_rank_cap_relief_rank_buffer_ratio",
    "selected_rank_cap_relief_sector_resonance_min",
    "selected_rank_cap_relief_close_strength_max",
    "selected_rank_cap_relief_require_confirmed_breakout",
    "selected_rank_cap_relief_allow_risk_off",
    "selected_rank_cap_relief_allow_crisis",
    "selected_breakout_freshness_min",
    "selected_trend_acceleration_min",
    "selected_close_retention_min",
    "selected_close_retention_threshold_lift",
    "selected_breakout_close_gap_max",
    "selected_breakout_close_gap_threshold_lift",
    "selected_close_retention_penalty_weight",
    *PROFILE_WEIGHT_FIELDS.values(),
}
DEFAULT_PROFILE_NAMES = ("default", "ic_optimized", "momentum_optimized", "momentum_tuned", "btst_precision_v1", "btst_precision_v2", "btst_precision_v3", "ic_v3", "ic_v4", "ic_v5")


def _parse_profile_names(raw: str | None) -> tuple[str, ...]:
    if raw is None or not str(raw).strip():
        return DEFAULT_PROFILE_NAMES
    names: list[str] = []
    for token in str(raw).split(","):
        profile_name = str(token).strip()
        if not profile_name:
            continue
        get_short_trade_target_profile(profile_name)
        if profile_name not in names:
            names.append(profile_name)
    return tuple(names) if names else DEFAULT_PROFILE_NAMES


def _build_profiles(profile_names: tuple[str, ...] = DEFAULT_PROFILE_NAMES, profile_overrides: dict[str, object] | None = None) -> dict[str, dict[str, object]]:
    profiles: dict[str, dict[str, object]] = {}
    unsupported_override_fields = sorted(set((profile_overrides or {}).keys()) - SUPPORTED_PROFILE_OVERRIDE_FIELDS)
    if unsupported_override_fields:
        unsupported_fields_text = ", ".join(str(field) for field in unsupported_override_fields)
        raise ValueError(
            f"Profile overrides not modeled by btst_20day_backtest.py: {unsupported_fields_text}"
        )
    for profile_name in profile_names:
        profile = build_short_trade_target_profile(profile_name, overrides=profile_overrides)
        profiles[profile_name] = {
            "select_threshold": float(profile.select_threshold),
            "near_miss_threshold": float(profile.near_miss_threshold),
            "selected_rank_cap": int(profile.selected_rank_cap),
            "near_miss_rank_cap": int(profile.near_miss_rank_cap),
            "selected_rank_cap_ratio": float(profile.selected_rank_cap_ratio),
            "near_miss_rank_cap_ratio": float(profile.near_miss_rank_cap_ratio),
            "selected_rank_cap_relief_score_margin_min": float(getattr(profile, "selected_rank_cap_relief_score_margin_min", 0.0)),
            "selected_rank_cap_relief_rank_buffer": int(getattr(profile, "selected_rank_cap_relief_rank_buffer", 0)),
            "selected_rank_cap_relief_rank_buffer_ratio": float(getattr(profile, "selected_rank_cap_relief_rank_buffer_ratio", 0.0)),
            "selected_rank_cap_relief_sector_resonance_min": float(getattr(profile, "selected_rank_cap_relief_sector_resonance_min", 0.0)),
            "selected_rank_cap_relief_close_strength_max": float(getattr(profile, "selected_rank_cap_relief_close_strength_max", 1.0)),
            "selected_rank_cap_relief_require_confirmed_breakout": bool(getattr(profile, "selected_rank_cap_relief_require_confirmed_breakout", False)),
            "selected_rank_cap_relief_allow_risk_off": bool(getattr(profile, "selected_rank_cap_relief_allow_risk_off", True)),
            "selected_rank_cap_relief_allow_crisis": bool(getattr(profile, "selected_rank_cap_relief_allow_crisis", True)),
            "selected_breakout_freshness_min": float(profile.selected_breakout_freshness_min),
            "selected_trend_acceleration_min": float(profile.selected_trend_acceleration_min),
            "selected_close_retention_min": float(getattr(profile, "selected_close_retention_min", 0.0) or 0.0),
            "selected_close_retention_threshold_lift": float(getattr(profile, "selected_close_retention_threshold_lift", 0.0) or 0.0),
            "selected_breakout_close_gap_max": float(getattr(profile, "selected_breakout_close_gap_max", 1.0) or 1.0),
            "selected_breakout_close_gap_threshold_lift": float(getattr(profile, "selected_breakout_close_gap_threshold_lift", 0.0) or 0.0),
            "selected_close_retention_penalty_weight": float(getattr(profile, "selected_close_retention_penalty_weight", 0.0) or 0.0),
            "weights": {factor_name: float(getattr(profile, weight_field)) for factor_name, weight_field in PROFILE_WEIGHT_FIELDS.items()},
        }
    return profiles


def _summarize_group_entries(entries: list[dict[str, object]]) -> dict[str, float | int | None]:
    total_n = int(sum(int(e["n"]) for e in entries))
    avg_wr = float(np.mean([float(e["win_rate"]) for e in entries])) if entries else 0.0
    avg_ret = float(np.mean([float(e["avg_ret"]) for e in entries])) if entries else 0.0
    avg_big = float(np.mean([float(e["big_win_rate"]) for e in entries])) if entries else 0.0
    avg_expectancy = float(np.mean([float(e.get("expectancy", 0.0)) for e in entries])) if entries else 0.0
    avg_downside_p10 = float(np.mean([float(e.get("downside_p10", 0.0)) for e in entries])) if entries else 0.0
    payoff_values = [float(e["payoff_ratio"]) for e in entries if e.get("payoff_ratio") is not None]
    avg_payoff = float(np.mean(payoff_values)) if payoff_values else None
    n_days_positive = int(sum(1 for e in entries if float(e["avg_ret"]) > 0))
    return {
        "total_n": total_n,
        "avg_wr": avg_wr,
        "avg_ret": avg_ret,
        "avg_big": avg_big,
        "avg_expectancy": avg_expectancy,
        "avg_downside_p10": avg_downside_p10,
        "avg_payoff": avg_payoff,
        "n_days_positive": n_days_positive,
    }


def _build_profile_leaderboard(all_daily: dict[str, dict[str, list[dict[str, object]]]], *, group_name: str = "selected") -> list[dict[str, float | int | None | str]]:
    leaderboard: list[dict[str, float | int | None | str]] = []
    for profile_name, groups in all_daily.items():
        entries = list(groups.get(group_name) or [])
        if not entries:
            continue
        summary = _summarize_group_entries(entries)
        leaderboard.append(
            {
                "profile": profile_name,
                "days": len(entries),
                **summary,
            }
        )
    leaderboard.sort(
        key=lambda row: (
            float(row.get("avg_ret") or -999.0),
            float(row.get("avg_wr") or -999.0),
            float(row.get("avg_payoff") or -999.0),
            float(row.get("avg_downside_p10") or -999.0),
        ),
        reverse=True,
    )
    return leaderboard


PROFILES = _build_profiles(DEFAULT_PROFILE_NAMES)


def _resolve_effective_rank_cap(*, hard_cap: int, cap_ratio: float, rank_population: int) -> int | None:
    normalized_hard_cap = int(hard_cap or 0)
    normalized_ratio = float(cap_ratio or 0.0)
    dynamic_cap: int | None = None
    if normalized_ratio > 0 and rank_population > 0:
        dynamic_cap = max(1, int(math.ceil(rank_population * normalized_ratio)))
    if dynamic_cap is None:
        return normalized_hard_cap if normalized_hard_cap > 0 else None
    if normalized_hard_cap <= 0:
        return dynamic_cap
    return max(normalized_hard_cap, dynamic_cap)


def _resolve_selected_close_retention_adjustment_series(
    results: pd.DataFrame,
    *,
    select_threshold: float,
    selected_close_retention_min: float = 0.0,
    selected_close_retention_threshold_lift: float = 0.0,
    selected_breakout_close_gap_max: float = 1.0,
    selected_breakout_close_gap_threshold_lift: float = 0.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    close_strength_series = pd.to_numeric(results["close_strength"], errors="coerce").fillna(0.0) if "close_strength" in results else pd.Series(0.0, index=results.index, dtype=float)
    layer_c_alignment_series = pd.to_numeric(results["layer_c_alignment"], errors="coerce").fillna(0.0) if "layer_c_alignment" in results else pd.Series(0.0, index=results.index, dtype=float)
    breakout_freshness_series = pd.to_numeric(results["breakout_freshness"], errors="coerce").fillna(0.0) if "breakout_freshness" in results else pd.Series(0.0, index=results.index, dtype=float)
    trend_acceleration_series = pd.to_numeric(results["trend_acceleration"], errors="coerce").fillna(0.0) if "trend_acceleration" in results else pd.Series(0.0, index=results.index, dtype=float)
    volume_expansion_quality_series = pd.to_numeric(results["volume_expansion_quality"], errors="coerce").fillna(0.0) if "volume_expansion_quality" in results else pd.Series(0.0, index=results.index, dtype=float)

    close_retention_score = ((0.75 * close_strength_series) + (0.25 * layer_c_alignment_series)).clip(lower=0.0, upper=1.0)
    breakout_pressure = pd.concat(
        [breakout_freshness_series, trend_acceleration_series, volume_expansion_quality_series],
        axis=1,
    ).max(axis=1)
    breakout_close_gap = (breakout_pressure - close_retention_score).clip(lower=0.0, upper=1.0)

    threshold_lift = pd.Series(0.0, index=results.index, dtype=float)
    if float(selected_close_retention_threshold_lift) > 0.0:
        threshold_lift += np.where(close_retention_score < float(selected_close_retention_min), float(selected_close_retention_threshold_lift), 0.0)
    if float(selected_breakout_close_gap_threshold_lift) > 0.0:
        threshold_lift += np.where(breakout_close_gap > float(selected_breakout_close_gap_max), float(selected_breakout_close_gap_threshold_lift), 0.0)

    adjusted_select_threshold = (float(select_threshold) + threshold_lift).clip(lower=0.0, upper=0.95)
    return adjusted_select_threshold, close_retention_score, breakout_close_gap


def _apply_rank_caps_to_scored_results(
    results: pd.DataFrame,
    *,
    score_col: str,
    select_threshold: float,
    near_miss_threshold: float,
    selected_rank_cap: int,
    near_miss_rank_cap: int,
    selected_rank_cap_ratio: float = 0.0,
    near_miss_rank_cap_ratio: float = 0.0,
    selected_rank_cap_relief_score_margin_min: float = 0.0,
    selected_rank_cap_relief_rank_buffer: int = 0,
    selected_rank_cap_relief_rank_buffer_ratio: float = 0.0,
    selected_rank_cap_relief_sector_resonance_min: float = 0.0,
    selected_rank_cap_relief_close_strength_max: float = 1.0,
    selected_rank_cap_relief_require_confirmed_breakout: bool = False,
    selected_rank_cap_relief_allow_risk_off: bool = True,
    selected_rank_cap_relief_allow_crisis: bool = True,
    selected_breakout_freshness_min: float = 0.0,
    selected_trend_acceleration_min: float = 0.0,
    selected_close_retention_min: float = 0.0,
    selected_close_retention_threshold_lift: float = 0.0,
    selected_breakout_close_gap_max: float = 1.0,
    selected_breakout_close_gap_threshold_lift: float = 0.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ranked = results.sort_values(score_col, ascending=False).copy()
    ranked["rank_hint"] = np.arange(1, len(ranked) + 1, dtype=int)
    rank_population = len(ranked)
    effective_selected_rank_cap = _resolve_effective_rank_cap(
        hard_cap=selected_rank_cap,
        cap_ratio=selected_rank_cap_ratio,
        rank_population=rank_population,
    )
    effective_near_miss_rank_cap = _resolve_effective_rank_cap(
        hard_cap=near_miss_rank_cap,
        cap_ratio=near_miss_rank_cap_ratio,
        rank_population=rank_population,
    )
    effective_selected_rank_cap_relief_buffer = _resolve_effective_rank_cap(
        hard_cap=selected_rank_cap_relief_rank_buffer,
        cap_ratio=selected_rank_cap_relief_rank_buffer_ratio,
        rank_population=rank_population,
    )
    effective_selected_rank_relief_cap: int | None = None
    if effective_selected_rank_cap is not None and effective_selected_rank_cap_relief_buffer is not None:
        effective_selected_rank_relief_cap = int(effective_selected_rank_cap + effective_selected_rank_cap_relief_buffer)

    score_series = ranked[score_col]
    adjusted_select_threshold_series, _, _ = _resolve_selected_close_retention_adjustment_series(
        ranked,
        select_threshold=select_threshold,
        selected_close_retention_min=selected_close_retention_min,
        selected_close_retention_threshold_lift=selected_close_retention_threshold_lift,
        selected_breakout_close_gap_max=selected_breakout_close_gap_max,
        selected_breakout_close_gap_threshold_lift=selected_breakout_close_gap_threshold_lift,
    )
    selected_score_mask = score_series >= adjusted_select_threshold_series
    near_miss_score_mask = (score_series >= near_miss_threshold) & (score_series < adjusted_select_threshold_series)

    selected_rank_mask = pd.Series(True, index=ranked.index) if effective_selected_rank_cap is None else ranked["rank_hint"] <= int(effective_selected_rank_cap)
    near_miss_rank_mask = pd.Series(True, index=ranked.index) if effective_near_miss_rank_cap is None else ranked["rank_hint"] <= int(effective_near_miss_rank_cap)
    selected_over_cap_mask = selected_score_mask & ~selected_rank_mask

    selected_relief_rank_mask = pd.Series(False, index=ranked.index) if effective_selected_rank_relief_cap is None else ranked["rank_hint"] <= int(effective_selected_rank_relief_cap)
    selected_relief_score_mask = (score_series - adjusted_select_threshold_series) >= float(selected_rank_cap_relief_score_margin_min)
    if selected_rank_cap_relief_require_confirmed_breakout:
        breakout_series = pd.to_numeric(ranked.get("breakout_freshness"), errors="coerce").fillna(0.0)
        trend_series = pd.to_numeric(ranked.get("trend_acceleration"), errors="coerce").fillna(0.0)
        selected_relief_breakout_mask = (breakout_series >= float(selected_breakout_freshness_min)) & (trend_series >= float(selected_trend_acceleration_min))
    else:
        selected_relief_breakout_mask = pd.Series(True, index=ranked.index)
    if "sector_resonance" in ranked:
        sector_resonance_series = pd.to_numeric(ranked["sector_resonance"], errors="coerce").fillna(0.0)
    else:
        sector_resonance_series = pd.Series(0.0, index=ranked.index)
    selected_relief_sector_mask = sector_resonance_series >= float(selected_rank_cap_relief_sector_resonance_min)
    if "close_strength" in ranked:
        close_strength_series = pd.to_numeric(ranked["close_strength"], errors="coerce").fillna(0.0)
    else:
        close_strength_series = pd.Series(0.0, index=ranked.index)
    selected_relief_close_strength_mask = close_strength_series <= float(selected_rank_cap_relief_close_strength_max)

    if "market_risk_level" in ranked:
        market_risk_series = ranked["market_risk_level"].fillna("").astype(str).str.lower().str.strip()
    elif "market_state_risk_level" in ranked:
        market_risk_series = ranked["market_state_risk_level"].fillna("").astype(str).str.lower().str.strip()
    else:
        if "volatility_regime" in ranked:
            volatility_regime_series = pd.to_numeric(ranked["volatility_regime"], errors="coerce").fillna(0.0)
        else:
            volatility_regime_series = pd.Series(0.0, index=ranked.index)
        if "atr_ratio" in ranked:
            atr_ratio_series = pd.to_numeric(ranked["atr_ratio"], errors="coerce").fillna(0.0)
        else:
            atr_ratio_series = pd.Series(0.0, index=ranked.index)
        market_risk_series = pd.Series("normal", index=ranked.index)
        market_risk_series[(volatility_regime_series >= 1.35) | (atr_ratio_series >= 0.11)] = "crisis"
        market_risk_series[(market_risk_series != "crisis") & ((volatility_regime_series >= 1.15) | (atr_ratio_series >= 0.085))] = "risk_off"

    selected_relief_risk_mask = pd.Series(True, index=ranked.index)
    if not bool(selected_rank_cap_relief_allow_risk_off):
        selected_relief_risk_mask &= market_risk_series != "risk_off"
    if not bool(selected_rank_cap_relief_allow_crisis):
        selected_relief_risk_mask &= market_risk_series != "crisis"

    selected_relief_mask = selected_over_cap_mask & selected_relief_rank_mask & selected_relief_score_mask & selected_relief_breakout_mask & selected_relief_sector_mask & selected_relief_close_strength_mask & selected_relief_risk_mask

    selected_mask = selected_score_mask & (selected_rank_mask | selected_relief_mask)
    demoted_selected_mask = selected_score_mask & ~selected_mask & near_miss_rank_mask
    near_miss_mask = (near_miss_score_mask & near_miss_rank_mask) | demoted_selected_mask

    return ranked[selected_mask], ranked[near_miss_mask]


def normalize_weights(weights):
    total = sum(max(0.0, v) for v in weights.values())
    if total <= 0:
        return {k: 1.0 / len(weights) for k in weights}
    return {k: max(0.0, v) / total for k, v in weights.items()}


def _resolve_selected_close_retention_penalty_from_factors(
    factors,
    *,
    selected_close_retention_min: float = 0.0,
    selected_breakout_close_gap_max: float = 1.0,
    selected_close_retention_penalty_weight: float = 0.0,
):
    weight = max(0.0, float(selected_close_retention_penalty_weight or 0.0))
    if weight <= 0.0:
        return 0.0
    close_retention_score = min(max((0.75 * float(factors.get("close_strength", 0.0) or 0.0)) + (0.25 * float(factors.get("layer_c_alignment", 0.0) or 0.0)), 0.0), 1.0)
    breakout_pressure = max(
        float(factors.get("breakout_freshness", 0.0) or 0.0),
        float(factors.get("trend_acceleration", 0.0) or 0.0),
        float(factors.get("volume_expansion_quality", 0.0) or 0.0),
    )
    breakout_close_gap = min(max(breakout_pressure - close_retention_score, 0.0), 1.0)
    close_shortfall = max(0.0, float(selected_close_retention_min or 0.0) - close_retention_score)
    breakout_close_gap_excess = max(0.0, breakout_close_gap - float(selected_breakout_close_gap_max or 1.0))
    severity = min(1.0, (close_shortfall / 0.12) + (breakout_close_gap_excess / 0.10))
    return min(weight, weight * severity)


def compute_score(
    factors,
    weights,
    *,
    selected_close_retention_min: float = 0.0,
    selected_breakout_close_gap_max: float = 1.0,
    selected_close_retention_penalty_weight: float = 0.0,
):
    nw = normalize_weights(weights)
    score = sum(nw.get(k, 0) * factors.get(k, 0) for k in nw)
    score -= _resolve_selected_close_retention_penalty_from_factors(
        factors,
        selected_close_retention_min=selected_close_retention_min,
        selected_breakout_close_gap_max=selected_breakout_close_gap_max,
        selected_close_retention_penalty_weight=selected_close_retention_penalty_weight,
    )
    return min(max(score, 0), 1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BTST 20天近似回测，比较多个 short-trade profile 的选股表现。")
    parser.add_argument("--profiles", default=",".join(DEFAULT_PROFILE_NAMES), help="逗号分隔的profile列表，例如 default,ic_optimized,momentum_optimized")
    parser.add_argument("--output-json", default=None, help="结果输出JSON路径（默认 data/reports/btst_20day_backtest.json）")
    parser.add_argument("--profile-overrides-json", default=None, help="JSON对象，覆盖所有选中profile的字段，例如 '{\"short_term_reversal_weight\":0.5}'")
    return parser.parse_args()


def main():
    import tushare as ts

    args = parse_args()
    active_profile_names = _parse_profile_names(args.profiles)
    profile_overrides = json.loads(str(args.profile_overrides_json or "{}"))
    if not isinstance(profile_overrides, dict):
        raise ValueError("--profile-overrides-json must be a JSON object")
    profiles = _build_profiles(active_profile_names, profile_overrides=profile_overrides)

    ts.set_token(os.getenv("TUSHARE_TOKEN"))
    pro = ts.pro_api()

    # 获取交易日历
    cal_end = datetime.now().strftime("%Y%m%d")
    cal_start = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
    all_dates = _load_open_trade_dates(pro, cal_start, cal_end)
    # 构建 next_date 映射
    next_map = {d: all_dates[i + 1] for i, d in enumerate(all_dates) if i + 1 < len(all_dates)}
    next2_map = {d: all_dates[i + 2] for i, d in enumerate(all_dates) if i + 2 < len(all_dates)}
    next3_map = {d: all_dates[i + 3] for i, d in enumerate(all_dates) if i + 3 < len(all_dates)}

    test_end = cal_end
    test_dates = [d for d in all_dates if d <= test_end][-20:]

    print(f"回测日期: {test_dates[0]} ~ {test_dates[-1]} ({len(test_dates)}天)")
    print("=" * 90)

    sb = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name,industry")

    all_daily = {p: {"selected": [], "near_miss": [], "all_scores": []} for p in profiles}

    for di, test_date in enumerate(test_dates):
        next_date = next_map.get(test_date)
        next2_date = next2_map.get(test_date)
        next3_date = next3_map.get(test_date)
        if not next_date:
            continue

        # 获取当日数据
        try:
            df = pro.daily(trade_date=test_date)
        except:
            continue
        if df is None or df.empty:
            continue

        df = df.merge(sb, on="ts_code", how="left")
        # 候选池过滤
        df = df[df["amount"] >= 100000]
        df = df[~df["name"].str.contains("ST|退", na=False)]
        df = df[~df["ts_code"].str.startswith(("688", "8", "4"))]
        df = df[df["pct_chg"].between(-9.5, 9.5)]

        # 获取次日收益
        try:
            dfn = pro.daily(trade_date=next_date)[["ts_code", "pct_chg"]].rename(columns={"pct_chg": "next_ret"})
        except:
            continue
        df = df.merge(dfn, on="ts_code")
        if next2_date:
            try:
                dft2 = pro.daily(trade_date=next2_date)[["ts_code", "pct_chg"]].rename(columns={"pct_chg": "tplus2_ret"})
                df = df.merge(dft2, on="ts_code", how="left")
            except:
                df["tplus2_ret"] = np.nan
        else:
            df["tplus2_ret"] = np.nan
        if next3_date:
            try:
                dft3 = pro.daily(trade_date=next3_date)[["ts_code", "pct_chg"]].rename(columns={"pct_chg": "tplus3_ret"})
                df = df.merge(dft3, on="ts_code", how="left")
            except:
                df["tplus3_ret"] = np.nan
        else:
            df["tplus3_ret"] = np.nan
        if len(df) < 100:
            continue

        # 获取历史价格
        codes = df["ts_code"].tolist()
        history = []
        for i in range(0, len(codes), 80):
            batch = codes[i : i + 80]
            try:
                h = pro.daily(ts_code=",".join(batch), start_date="20250601", end_date=test_date)
                if h is not None and not h.empty:
                    history.append(h)
            except:
                continue
        if not history:
            continue

        hist = pd.concat(history, ignore_index=True)
        hist["trade_date"] = pd.to_datetime(hist["trade_date"], format="%Y%m%d")
        hist = hist.sort_values(["ts_code", "trade_date"])

        # 计算因子
        stock_factors = {}
        for code, g in hist.groupby("ts_code"):
            if len(g) < 22:
                continue
            f = compute_factors(g, None)
            if f is not None:
                stock_factors[code] = f

        if not stock_factors:
            continue

        # 为每只股票计算各profile的score
        results = df[df["ts_code"].isin(stock_factors.keys())].copy()
        if len(results) < 50:
            continue
        results["breakout_freshness"] = results["ts_code"].map(lambda code: float((stock_factors.get(code) or {}).get("breakout_freshness", 0.0)))
        results["trend_acceleration"] = results["ts_code"].map(lambda code: float((stock_factors.get(code) or {}).get("trend_acceleration", 0.0)))
        results["volume_expansion_quality"] = results["ts_code"].map(lambda code: float((stock_factors.get(code) or {}).get("volume_expansion_quality", 0.0)))
        results["sector_resonance"] = results["ts_code"].map(lambda code: float((stock_factors.get(code) or {}).get("sector_resonance", 0.0)))
        results["close_strength"] = results["ts_code"].map(lambda code: float((stock_factors.get(code) or {}).get("close_strength", 0.0)))
        results["layer_c_alignment"] = results["ts_code"].map(lambda code: float((stock_factors.get(code) or {}).get("layer_c_alignment", 0.0)))

        for pname, pconfig in profiles.items():
            scores = []
            for _, row in results.iterrows():
                f = stock_factors.get(row["ts_code"])
                if f is None:
                    scores.append(0)
                    continue
                s = compute_score(
                    f,
                    pconfig["weights"],
                    selected_close_retention_min=float(pconfig["selected_close_retention_min"]),
                    selected_breakout_close_gap_max=float(pconfig["selected_breakout_close_gap_max"]),
                    selected_close_retention_penalty_weight=float(pconfig["selected_close_retention_penalty_weight"]),
                )
                scores.append(s)
            results[f"score_{pname}"] = scores

        # 统计各profile表现
        date_summary = {"date": test_date, "next_date": next_date, "n_pool": len(results)}
        for pname, pconfig in profiles.items():
            col = f"score_{pname}"
            sel, nm = _apply_rank_caps_to_scored_results(
                results,
                score_col=col,
                select_threshold=float(pconfig["select_threshold"]),
                near_miss_threshold=float(pconfig["near_miss_threshold"]),
                selected_rank_cap=int(pconfig["selected_rank_cap"]),
                near_miss_rank_cap=int(pconfig["near_miss_rank_cap"]),
                selected_rank_cap_ratio=float(pconfig["selected_rank_cap_ratio"]),
                near_miss_rank_cap_ratio=float(pconfig["near_miss_rank_cap_ratio"]),
                selected_rank_cap_relief_score_margin_min=float(pconfig["selected_rank_cap_relief_score_margin_min"]),
                selected_rank_cap_relief_rank_buffer=int(pconfig["selected_rank_cap_relief_rank_buffer"]),
                selected_rank_cap_relief_rank_buffer_ratio=float(pconfig["selected_rank_cap_relief_rank_buffer_ratio"]),
                selected_rank_cap_relief_sector_resonance_min=float(pconfig["selected_rank_cap_relief_sector_resonance_min"]),
                selected_rank_cap_relief_close_strength_max=float(pconfig["selected_rank_cap_relief_close_strength_max"]),
                selected_rank_cap_relief_require_confirmed_breakout=bool(pconfig["selected_rank_cap_relief_require_confirmed_breakout"]),
                selected_rank_cap_relief_allow_risk_off=bool(pconfig["selected_rank_cap_relief_allow_risk_off"]),
                selected_rank_cap_relief_allow_crisis=bool(pconfig["selected_rank_cap_relief_allow_crisis"]),
                selected_breakout_freshness_min=float(pconfig["selected_breakout_freshness_min"]),
                selected_trend_acceleration_min=float(pconfig["selected_trend_acceleration_min"]),
                selected_close_retention_min=float(pconfig["selected_close_retention_min"]),
                selected_close_retention_threshold_lift=float(pconfig["selected_close_retention_threshold_lift"]),
                selected_breakout_close_gap_max=float(pconfig["selected_breakout_close_gap_max"]),
                selected_breakout_close_gap_threshold_lift=float(pconfig["selected_breakout_close_gap_threshold_lift"]),
            )

            for group_name, group_df in [("selected", sel), ("near_miss", nm)]:
                if len(group_df) < 1:
                    continue
                return_stats = summarize_return_stats(group_df["next_ret"])
                tplus2_stats = summarize_horizon_return_stats(group_df["tplus2_ret"])
                tplus3_stats = summarize_horizon_return_stats(group_df["tplus3_ret"])
                all_daily[pname][group_name].append(
                    {
                        "date": test_date,
                        "next_date": next_date,
                        "n": len(group_df),
                        "win_rate": return_stats["win_rate"],
                        "avg_ret": return_stats["avg_ret"],
                        "big_win_rate": return_stats["big_win_rate"],
                        "avg_win_ret": return_stats["avg_win_ret"],
                        "avg_loss_ret": return_stats["avg_loss_ret"],
                        "payoff_ratio": return_stats["payoff_ratio"],
                        "expectancy": return_stats["expectancy"],
                        "downside_p10": return_stats["downside_p10"],
                        "tplus2_available_count": tplus2_stats["available_count"],
                        "tplus2_win_rate": tplus2_stats["win_rate"],
                        "tplus2_avg_ret": tplus2_stats["avg_ret"],
                        "tplus2_payoff_ratio": tplus2_stats["payoff_ratio"],
                        "tplus2_expectancy": tplus2_stats["expectancy"],
                        "tplus2_downside_p10": tplus2_stats["downside_p10"],
                        "tplus3_available_count": tplus3_stats["available_count"],
                        "tplus3_win_rate": tplus3_stats["win_rate"],
                        "tplus3_avg_ret": tplus3_stats["avg_ret"],
                        "tplus3_payoff_ratio": tplus3_stats["payoff_ratio"],
                        "tplus3_expectancy": tplus3_stats["expectancy"],
                        "tplus3_downside_p10": tplus3_stats["downside_p10"],
                        "tickers": group_df["ts_code"].tolist()[:10],
                    }
                )

            # IC of score vs next_ret
            ic = spearman_ic(results[col].values, results["next_ret"].values)
            date_summary[f"{pname}_ic"] = ic
            date_summary[f"{pname}_selected"] = len(sel)
            date_summary[f"{pname}_near_miss"] = len(nm)

        print(f"[{di + 1}/{len(test_dates)}] {test_date}→{next_date}: pool={len(results)}", end="")
        for pname in profiles:
            s = date_summary.get(f"{pname}_selected", 0)
            ic = date_summary.get(f"{pname}_ic", 0)
            print(f"  {pname}: sel={s} IC={ic:+.3f}", end="")
        print()

    # ====== 汇总 ======
    print(f"\n{'=' * 90}")
    print("回测汇总")
    print(f"{'=' * 90}")

    for pname in profiles:
        print(f"\n--- {pname} profile ---")
        for group in ["selected", "near_miss"]:
            entries = all_daily[pname][group]
            if not entries:
                print(f"  {group}: 无数据")
                continue
            summary = _summarize_group_entries(entries)
            total_n = int(summary["total_n"])
            avg_wr = float(summary["avg_wr"])
            avg_ret = float(summary["avg_ret"])
            avg_big = float(summary["avg_big"])
            avg_expectancy = float(summary["avg_expectancy"])
            avg_downside_p10 = float(summary["avg_downside_p10"])
            avg_payoff = summary["avg_payoff"]
            n_days_positive = int(summary["n_days_positive"])
            print(f"  {group}: {len(entries)}天有数据, 总计{total_n}只")
            payoff_text = f"{float(avg_payoff):.2f}" if avg_payoff is not None and np.isfinite(float(avg_payoff)) else "N/A"
            print(f"    日均胜率={avg_wr:.0%} 日均收益={avg_ret:+.2f}% 大涨率={avg_big:.0%} " f"赔率={payoff_text} 期望={avg_expectancy:+.2f}% 下行P10={avg_downside_p10:+.2f}% " f"正收益天数={n_days_positive}/{len(entries)}")
            tplus2_entries = [e for e in entries if int(e.get("tplus2_available_count", 0)) > 0]
            if tplus2_entries:
                tplus2_avg_ret = float(np.mean([float(e.get("tplus2_avg_ret", 0.0)) for e in tplus2_entries]))
                tplus2_avg_wr = float(np.mean([float(e.get("tplus2_win_rate", 0.0)) for e in tplus2_entries]))
                tplus2_payoff_values = [float(e["tplus2_payoff_ratio"]) for e in tplus2_entries if e.get("tplus2_payoff_ratio") is not None]
                tplus2_avg_payoff = float(np.mean(tplus2_payoff_values)) if tplus2_payoff_values else np.nan
                tplus2_pos_days = int(sum(1 for e in tplus2_entries if float(e.get("tplus2_avg_ret", 0.0)) > 0))
                tplus2_payoff_text = f"{tplus2_avg_payoff:.2f}" if np.isfinite(tplus2_avg_payoff) else "N/A"
                print(f"    T+2日均胜率={tplus2_avg_wr:.0%} 日均收益={tplus2_avg_ret:+.2f}% 赔率={tplus2_payoff_text} 正收益天数={tplus2_pos_days}/{len(tplus2_entries)}")
            tplus3_entries = [e for e in entries if int(e.get("tplus3_available_count", 0)) > 0]
            if tplus3_entries:
                tplus3_avg_ret = float(np.mean([float(e.get("tplus3_avg_ret", 0.0)) for e in tplus3_entries]))
                tplus3_avg_wr = float(np.mean([float(e.get("tplus3_win_rate", 0.0)) for e in tplus3_entries]))
                tplus3_payoff_values = [float(e["tplus3_payoff_ratio"]) for e in tplus3_entries if e.get("tplus3_payoff_ratio") is not None]
                tplus3_avg_payoff = float(np.mean(tplus3_payoff_values)) if tplus3_payoff_values else np.nan
                tplus3_pos_days = int(sum(1 for e in tplus3_entries if float(e.get("tplus3_avg_ret", 0.0)) > 0))
                tplus3_payoff_text = f"{tplus3_avg_payoff:.2f}" if np.isfinite(tplus3_avg_payoff) else "N/A"
                print(f"    T+3日均胜率={tplus3_avg_wr:.0%} 日均收益={tplus3_avg_ret:+.2f}% 赔率={tplus3_payoff_text} 正收益天数={tplus3_pos_days}/{len(tplus3_entries)}")
            # 逐日明细
            for e in entries:
                day_payoff = "N/A" if e.get("payoff_ratio") is None else f"{float(e['payoff_ratio']):.2f}"
                print(f"    {e['date']}: {e['n']}只 胜率={e['win_rate']:.0%} 收益={e['avg_ret']:+.2f}% " f"赔率={day_payoff} 期望={e.get('expectancy', 0.0):+.2f}% 下行P10={e.get('downside_p10', 0.0):+.2f}% " f"{e['tickers'][:5]}")

    selected_leaderboard = _build_profile_leaderboard(all_daily, group_name="selected")
    if selected_leaderboard:
        print("\n--- selected profile leaderboard (按日均收益排序) ---")
        for idx, row in enumerate(selected_leaderboard, start=1):
            payoff_text = "N/A" if row["avg_payoff"] is None else f"{float(row['avg_payoff']):.2f}"
            print(f"  {idx}. {row['profile']}: 日均收益={float(row['avg_ret']):+.2f}% " f"胜率={float(row['avg_wr']):.0%} 赔率={payoff_text} " f"下行P10={float(row['avg_downside_p10']):+.2f}% " f"正收益天数={int(row['n_days_positive'])}/{int(row['days'])} 样本={int(row['total_n'])}")

    # 保存结果
    out = {}
    for pname in profiles:
        out[pname] = {}
        for group in ["selected", "near_miss"]:
            out[pname][group] = [
                {
                    "date": e["date"],
                    "next_date": e["next_date"],
                    "n": e["n"],
                    "win_rate": round(float(e["win_rate"]), 4),
                    "avg_ret": round(float(e["avg_ret"]), 4),
                    "big_win_rate": round(float(e["big_win_rate"]), 4),
                    "avg_win_ret": round(float(e.get("avg_win_ret", 0.0)), 4),
                    "avg_loss_ret": round(float(e.get("avg_loss_ret", 0.0)), 4),
                    "payoff_ratio": (round(float(e["payoff_ratio"]), 4) if e.get("payoff_ratio") is not None else None),
                    "expectancy": round(float(e.get("expectancy", 0.0)), 4),
                    "downside_p10": round(float(e.get("downside_p10", 0.0)), 4),
                    "tplus2_available_count": int(e.get("tplus2_available_count", 0)),
                    "tplus2_win_rate": round(float(e.get("tplus2_win_rate", 0.0)), 4),
                    "tplus2_avg_ret": round(float(e.get("tplus2_avg_ret", 0.0)), 4),
                    "tplus2_payoff_ratio": (round(float(e["tplus2_payoff_ratio"]), 4) if e.get("tplus2_payoff_ratio") is not None else None),
                    "tplus2_expectancy": round(float(e.get("tplus2_expectancy", 0.0)), 4),
                    "tplus2_downside_p10": round(float(e.get("tplus2_downside_p10", 0.0)), 4),
                    "tplus3_available_count": int(e.get("tplus3_available_count", 0)),
                    "tplus3_win_rate": round(float(e.get("tplus3_win_rate", 0.0)), 4),
                    "tplus3_avg_ret": round(float(e.get("tplus3_avg_ret", 0.0)), 4),
                    "tplus3_payoff_ratio": (round(float(e["tplus3_payoff_ratio"]), 4) if e.get("tplus3_payoff_ratio") is not None else None),
                    "tplus3_expectancy": round(float(e.get("tplus3_expectancy", 0.0)), 4),
                    "tplus3_downside_p10": round(float(e.get("tplus3_downside_p10", 0.0)), 4),
                    "tickers": e["tickers"],
                }
                for e in all_daily[pname][group]
            ]

    out_path = Path(args.output_json).expanduser().resolve() if args.output_json else Path(__file__).resolve().parent.parent / "data" / "reports" / "btst_20day_backtest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存到 {out_path}")


if __name__ == "__main__":
    main()
